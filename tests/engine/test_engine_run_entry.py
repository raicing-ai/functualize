"""`engine.run(request)` is the single entry to job execution.

This is what makes wave 3 of `run-request-entry` safe. Seven doors
migrate to building a `RunRequest` one at a time, each landing on its own with
the suite green — which is only true if every surface arrives the same way by
construction.

The test is written against observable `JobResult` fields: it must keep meaning
at T11, when `execute()` is deleted and `run()` is the only entry.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from functualize._app.state import AppState
from functualize._types.enums import RunStatus
from functualize.app.core import FunctualizeApp
from functualize.types import RunRequest


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    application = FunctualizeApp(name="testapp")
    application.register_dynamic_job("greet", _greet)
    return application


def _greet(name: str = "world") -> str:
    return f"hello {name}"


def test_run_produces_expected_result(app: FunctualizeApp) -> None:
    engine = app.execution_engine

    result = engine.run(
        RunRequest(job_name="greet", surface="app.execute", kwargs={"name": "a"})
    )

    assert result.status == RunStatus.SUCCESS
    assert result.return_value == "hello a"
    assert result.job_name == "greet"
    assert result.exception is None


def test_run_resolves_the_name_the_caller_did_not(app: FunctualizeApp) -> None:
    """The point of the entry: the caller passes a name, never a function."""
    result = app.execution_engine.run(
        RunRequest(job_name="greet", surface="app.execute")
    )
    assert result.return_value == "hello world"


def test_run_carries_the_execution_inputs(app: FunctualizeApp) -> None:
    """A request's fields must reach the lifecycle, not be silently dropped."""
    result = app.execution_engine.run(
        RunRequest(
            job_name="greet",
            surface="engine.dependency",
            kwargs={"name": "b"},
            invoke_depth=1,
            run_dependencies=False,
        )
    )
    assert result.return_value == "hello b"


def test_unknown_job_name_raises(app: FunctualizeApp) -> None:
    with pytest.raises(KeyError):
        app.execution_engine.run(RunRequest(job_name="nope", surface="app.execute"))
