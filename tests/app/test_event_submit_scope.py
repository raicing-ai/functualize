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


class TestAWorkflowSubmittedByEventCanBeAnsweredAndResumed:
    """AC-14, end to end — the criterion the tests above do not reach.

    Every test in this file runs a plain `def greet()`. AC-14 is about a
    **`@workflow`** that **blocks on a gate**: it must report a scope id, and
    *that* scope must be answerable and resumable to completion. None of those
    three words is exercised by a job with no graph, no gate and nothing to
    resume.

    The distinction matters because the halves are guarded separately and the
    join is not. `test_submitted_job_runs_in_an_addressable_scope` proves the
    façade minted a scope and the registry knows its id;
    `tests/test_auto_scope.py` proves the id is well-formed. What nothing
    asserted is that the id the registry hands back **is the scope the walk
    actually persisted its gate into** — a change that kept the façade call and
    dropped the id at the engine seam would satisfy both and still leave the
    original defect exactly as the audit described it: *the scope existed and
    was unaddressable*.

    This walks the whole way: submit, read the id off the registry, answer the
    gate through that id, resume, and require completion.
    """

    @staticmethod
    def _gated_app(tmp_path: Any) -> tuple[FunctualizeApp, list[str]]:
        from pydantic import BaseModel, Field

        from functualize.workflow import END, Edge, Gate, Step, workflow

        calls: list[str] = []

        class Approval(BaseModel):
            approved: bool = Field(description="Ship it?")

        def survey() -> str:
            calls.append("survey")
            return "surveyed"

        @workflow(
            steps=[Step(survey), Gate(name="approve", awaits=Approval)],
            edges=[
                Edge(source="survey", target="approve"),
                Edge(source="approve", target=END),
            ],
        )
        def release() -> str:
            calls.append("body")
            return "released"

        application = FunctualizeApp(name="submitted")
        application.register_dynamic_job("survey", survey)
        application.register_dynamic_job("release", release)
        return application, calls

    def test_the_reported_scope_is_the_one_that_can_be_resumed(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from functualize._primitives.state_store import StateStore
        from functualize.app._workflow_answer import answer_gate
        from functualize.app._workflow_control import resume_scope

        app, calls = self._gated_app(tmp_path)

        before = set(app._scope_registry)
        on_job_submit_event(app, _Event(job_name="release", kwargs={}))
        created = set(app._scope_registry) - before

        assert len(created) == 1, "the submit door minted no addressable scope"
        scope_id = next(iter(created))
        assert calls == ["survey"], (
            f"the walk should have stopped at the gate, ran: {calls}"
        )

        store = StateStore.for_project(tmp_path)
        answer_gate(app, store, scope_id, "approve", {"approved": True})
        result = resume_scope(app, store, scope_id)

        assert result["status"] == "success", (
            f"the scope the submit door reported could not be resumed: {result}"
        )
        assert calls == ["survey", "body"], (
            "resuming ran the wrong steps — the gate's own scope was not the "
            f"one that advanced: {calls}"
        )

    def test_an_unanswered_scope_does_not_resume(self, tmp_path, monkeypatch) -> None:
        """The falsifier.

        Without it, a `resume_scope` that ignored the gate entirely and simply
        ran the body would satisfy the test above.
        """
        monkeypatch.chdir(tmp_path)
        from functualize._primitives.state_store import StateStore
        from functualize.app._workflow_control import resume_scope

        app, calls = self._gated_app(tmp_path)

        on_job_submit_event(app, _Event(job_name="release", kwargs={}))
        scope_id = next(iter(app._scope_registry))

        result = resume_scope(app, StateStore.for_project(tmp_path), scope_id)

        assert result["status"] != "success", (
            f"an unanswered gate resumed to completion: {result}"
        )
        assert calls == ["survey"], f"the body ran with the gate open: {calls}"
