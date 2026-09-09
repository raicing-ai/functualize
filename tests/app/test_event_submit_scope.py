"""D-13: a job submitted by event must land in a scope you can name.

`interactivity.job.submit` used to reach past the facade straight into the
engine (`_app/impl.py:861`, four arguments, no scope). The audit called this
"runs with no WorkflowScope", which is not quite what happens: for a
`@workflow` the engine still mints a *persisted* scope at
`_engine/workflow_runner.py:97`. The defect is narrower and worse — the scope
existed and was **unaddressable**. Nothing on this path ever learned its id, so
a workflow that blocked on a gate could never be answered or resumed.

The fix is therefore not "mint a scope here" but "stop bypassing the facade",
because the facade is what creates the scope *and* hands the id back.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from functualize._app.impl import on_job_submit_event
from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp


class _Event:
    def __init__(self, **payload: Any) -> None:
        self.payload = payload


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


def test_submitted_job_runs_in_an_addressable_scope(app: FunctualizeApp) -> None:
    """The D-13 property. Sabotage: restore the direct engine call and this fails."""
    before = set(app._scope_registry)
    on_job_submit_event(app, _Event(job_name="greet", kwargs={"name": "a"}))
    created = set(app._scope_registry) - before

    assert len(created) == 1, (
        "the event door must go through the facade, which is what creates the "
        "scope; reaching the engine directly leaves the run unaddressable"
    )
    assert next(iter(created)).startswith("greet-")


def test_submitted_job_actually_runs(app: FunctualizeApp) -> None:
    seen: list[str] = []
    app.register_dynamic_job("record", lambda value="x": seen.append(value))
    on_job_submit_event(app, _Event(job_name="record", kwargs={"value": "ran"}))
    assert seen == ["ran"]


def test_unregistered_job_is_a_warning_not_a_crash(
    app: FunctualizeApp, caplog: pytest.LogCaptureFixture
) -> None:
    """ADR-018: a discovery failure is reported, not fatal."""
    before = set(app._scope_registry)
    on_job_submit_event(app, _Event(job_name="nope", kwargs={}))
    assert set(app._scope_registry) == before
    assert "not registered" in caplog.text


def test_the_door_names_itself(app: FunctualizeApp) -> None:
    """The request must carry `event.job-submit`, not a guess or a default."""
    captured: list[Any] = []
    original = app.execute

    def _spy(request: Any, **kwargs: Any) -> Any:
        captured.append(request)
        return original(request, **kwargs)

    app.execute = _spy  # type: ignore[method-assign]
    on_job_submit_event(app, _Event(job_name="greet", kwargs={}))
    assert captured and captured[0].surface == "event.job-submit"
