"""`engine.run(request)` and `engine.execute(...)` must agree.

This equality is what makes wave 3 of `run-request-entry` safe. Seven doors
migrate to building a `RunRequest` one at a time, each landing on its own with
the suite green — which is only true if the two entries are the same execution
by construction.

The test is written against observable `JobResult` fields rather than against
`execute`'s internals: it must keep meaning at T11, when `execute()` is deleted
and `run()` stops delegating.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from functualize._app.state import AppState
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


def test_run_and_execute_produce_equal_results(app: FunctualizeApp) -> None:
    engine = app.execution_engine
    job = engine.get_job("greet")

    via_execute = engine.execute("greet", job.function, kwargs={"name": "a"})
    via_run = engine.run(
        RunRequest(job_name="greet", surface="app.execute", kwargs={"name": "a"})
    )

    assert via_run.status == via_execute.status
    assert via_run.return_value == via_execute.return_value
    assert via_run.job_name == via_execute.job_name
    assert via_run.exception is None and via_execute.exception is None


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
