"""The engine marks a failure as the job's own only when the job call raised it.

A process boundary renders the job's own exception as one line and keeps the
traceback for everything else, so the line between the two has to be drawn
somewhere that *knows*. The exception object cannot say where it came from;
the engine can, because it makes the call. These tests pin the mark at its
source: by identity, at the one call that runs the job body, and never
inherited from metadata someone else wrote.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests._support.engine_run import run_job
from tests._support.engine_storage import engine_storage

from functualize._app.state import AppState
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.hooks import HookRegistry
from functualize._types.enums import RunStatus
from functualize._types.outcome import RAISED_BY_JOB, raised_by_job


class _JobError(Exception):
    """What a job body raises."""


class _MiddlewareError(Exception):
    """What a middleware raises on its own account."""


@pytest.fixture(autouse=True)
def _app_state() -> None:
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


def _engine(*middleware: Any) -> JobExecutionEngine:
    chain = ExecutionMiddlewareChain()
    for mw in middleware:
        chain.register(mw)
    return JobExecutionEngine(
        di_registry=MagicMock(),
        event_bus=MagicMock(),
        hook_registry=HookRegistry(),
        middleware_chain=chain,
        **engine_storage(),
    )


def _raising_job() -> None:
    raise _JobError("bad input: row 3 has no id")


def test_an_exception_the_job_raised_is_marked() -> None:
    result = run_job(_engine(), "boom", _raising_job, kwargs={})

    assert result.status is RunStatus.FAILURE
    assert isinstance(result.exception, _JobError)
    assert result.metadata.get(RAISED_BY_JOB) is True
    assert raised_by_job(result)


def test_a_middleware_that_re_raises_the_jobs_exception_keeps_the_mark() -> None:
    """Observing middleware is the normal case: it sees the error and lets it go."""
    seen: list[BaseException] = []

    def observing(_rc: Any) -> Generator[None]:
        try:
            yield
        except Exception as exc:
            seen.append(exc)
            raise

    result = run_job(_engine(observing), "boom", _raising_job, kwargs={})

    assert seen and seen[0] is result.exception
    assert raised_by_job(result)


def test_a_middleware_raising_after_a_clean_job_is_not_the_job() -> None:
    """The job returned; the failure is the middleware's own."""

    def failing_after(_rc: Any) -> Generator[None]:
        yield
        raise _MiddlewareError("middleware bug after the body")

    result = run_job(_engine(failing_after), "j", lambda: "value", kwargs={})

    assert isinstance(result.exception, _MiddlewareError)
    assert RAISED_BY_JOB not in result.metadata
    assert not raised_by_job(result)


def test_a_middleware_failing_before_the_job_runs_is_not_the_job() -> None:
    ran: list[bool] = []

    def broken(_rc: Any) -> Generator[None]:
        yield from ()  # a generator that fails on its first step
        raise _MiddlewareError("middleware bug")

    def job() -> None:
        ran.append(True)

    result = run_job(_engine(broken), "j", job, kwargs={})

    assert ran == []
    assert isinstance(result.exception, _MiddlewareError)
    assert not raised_by_job(result)


def test_a_planted_key_cannot_claim_a_failure_the_job_did_not_raise() -> None:
    """The mark is decided at the call, then written — never inherited."""

    def planting(rc: Any) -> Generator[None]:
        # Whatever the middleware receives, reach the execution context's
        # metadata, which the result's metadata is built from.
        context = getattr(rc, "_context", rc)
        getattr(context, "metadata", {})[RAISED_BY_JOB] = True
        yield
        raise _MiddlewareError("after a clean job")

    result = run_job(_engine(planting), "j", lambda: None, kwargs={})

    assert isinstance(result.exception, _MiddlewareError)
    assert not raised_by_job(result)


def test_a_successful_run_is_not_marked() -> None:
    result = run_job(_engine(), "ok", lambda: "value", kwargs={})

    assert result.status is RunStatus.SUCCESS
    assert not raised_by_job(result)
