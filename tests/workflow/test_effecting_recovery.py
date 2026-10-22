"""An effecting attempt is durable before its callback and needs a verdict after death."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import pytest
from tests._support.engine_storage import port_for
from tests.conformance.sqlite_hooks import _prepared_store

from functualize._app.state import AppState
from functualize._engine.frontier import FrontierWalk, StepStatus, step_key
from functualize._engine.recording import InputRecorder
from functualize._engine.workflow_walker import (
    StepBlocked,
    WalkOutcome,
    WorkflowWalker,
    graph_model_of,
)
from functualize._primitives.scope_store import ScopeStore as RawScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import ScopeCancelledError
from functualize._types.gate_resolution import CandidateEvaluation, EvaluationOutcome
from functualize._types.workflow import Loop, OnFailure, WorkflowDeclaration
from functualize.app import FunctualizeApp
from functualize.app.utils import ScopeStore, answer_gate
from functualize.job import FromJob, RunStatus
from functualize.types import RunRequest
from functualize.workflow import END, Edge, Step, workflow


class Crash(BaseException):
    """Stand in for a process that did not run its cleanup handlers."""


@pytest.fixture(autouse=True)
def isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield project
    AppState.reset()


def _app(
    calls: list[str],
    *,
    crash: bool = False,
    crash_once: bool = False,
    error: Exception | None = None,
    dependent: bool = False,
) -> FunctualizeApp:
    app = FunctualizeApp(name="effect-recovery")

    def charge() -> str:
        calls.append("charge")
        if crash and (not crash_once or calls.count("charge") == 1):
            raise Crash()
        if error is not None:
            raise error
        return "receipt"

    def after(receipt: Annotated[str, FromJob("charge")] = "invented") -> str:
        calls.append("after")
        return receipt if dependent else "done"

    @workflow(
        steps=[Step("charge", effecting=True), Step("after")],
        edges=[Edge("charge", "after"), Edge("after", END)],
    )
    def release() -> str:
        return "released"

    app.register_dynamic_job("charge", charge)
    app.register_dynamic_job("after", after)
    app.register_dynamic_job("release", release)
    return app


def _run(app: FunctualizeApp, scope: str = "s1") -> Any:
    return app.execute(
        RunRequest(job_name="release", surface="app.execute", workflow_scope_id=scope)
    )


def test_crash_leaves_attempt_and_resume_asks_before_reentry(
    isolated_project: Path,
) -> None:
    calls: list[str] = []
    app = _app(calls, crash=True)
    with pytest.raises(Crash):
        _run(app)
    store = ScopeStore.for_project(isolated_project)
    first = store.get_step("s1", step_key("charge", ""))
    assert first["status"] == StepStatus.ATTEMPTING
    assert first["attempt"] == 1
    assert first["started_at"]
    assert not first.get("completed_at")
    assert _run(app).status is RunStatus.BLOCKED
    assert calls == ["charge"]
    doubt = store.get_step("s1", step_key("charge", ""))
    assert doubt["status"] == StepStatus.IN_DOUBT
    assert doubt["attempt"] == 1
    assert store.get_scope("s1")["position"] == "charge"
    gate = store.get_gate("s1", "charge-in-doubt")
    assert gate["prompt"]["attempt"] == 1


def test_effect_is_not_repeated_after_crash(isolated_project: Path) -> None:
    calls: list[str] = []
    app = _app(calls, crash=True, crash_once=True)
    with pytest.raises(Crash):
        _run(app)
    report = _run(app)
    assert calls.count("charge") == 1, f"effect marker count: {calls.count('charge')}"
    assert report.status is RunStatus.BLOCKED


@pytest.mark.parametrize("outcome, count", [("ran", 1), ("did_not_run", 2)])
def test_answer_decides_reentry(
    isolated_project: Path, outcome: str, count: int
) -> None:
    calls: list[str] = []
    app = _app(calls, crash=True)
    with pytest.raises(Crash):
        _run(app)
    assert _run(app).status is RunStatus.BLOCKED
    store = ScopeStore.for_project(isolated_project)
    answer = answer_gate(
        app, store, "s1", "charge-in-doubt", {"outcome": outcome, "value": "receipt"}
    )
    assert answer["status"] == "answered", answer
    app = _app(calls)
    assert _run(app).status is RunStatus.SUCCESS
    assert calls.count("charge") == count
    final = store.get_step("s1", step_key("charge", ""))
    assert final["status"] == StepStatus.SUCCESS
    assert final["attempt"] == count


def test_normal_return_replaces_attempt(isolated_project: Path) -> None:
    calls: list[str] = []
    app = _app(calls)
    assert _run(app).status is RunStatus.SUCCESS
    step = ScopeStore.for_project(isolated_project).get_step(
        "s1", step_key("charge", "")
    )
    assert step["status"] == StepStatus.SUCCESS
    assert step["attempt"] == 1
    assert step["started_at"]
    assert step["completed_at"]


def test_ran_without_value_is_not_reusable_or_invented(isolated_project: Path) -> None:
    calls: list[str] = []
    app = _app(calls, crash=True, dependent=True)
    with pytest.raises(Crash):
        _run(app)
    assert _run(app).status is RunStatus.BLOCKED
    store = ScopeStore.for_project(isolated_project)
    assert (
        answer_gate(app, store, "s1", "charge-in-doubt", {"outcome": "ran"})["status"]
        == "answered"
    )
    app = _app(calls, dependent=True)
    assert _run(app).status is not RunStatus.SUCCESS
    step = store.get_step("s1", step_key("charge", ""))
    assert step["status"] == StepStatus.SUCCESS
    assert step["return_value_reusable"] is False
    assert step["return_value_kind"] == "missing_recovery_value"
    assert calls == ["charge"]
    assert _run(app).status is not RunStatus.SUCCESS
    assert calls == ["charge"]


def test_second_attempt_asks_a_new_question(isolated_project: Path) -> None:
    calls: list[str] = []
    app = _app(calls, crash=True)
    with pytest.raises(Crash):
        _run(app)
    assert _run(app).status is RunStatus.BLOCKED
    store = ScopeStore.for_project(isolated_project)
    first = store.get_gate("s1", "charge-in-doubt")
    assert (
        answer_gate(app, store, "s1", "charge-in-doubt", {"outcome": "did_not_run"})[
            "status"
        ]
        == "answered"
    )
    with pytest.raises(Crash):
        _run(app)
    assert _run(app).status is RunStatus.BLOCKED
    second = store.get_gate("s1", "charge-in-doubt")
    assert second["request_id"] != first["request_id"]
    assert second["prompt"]["attempt"] == 2
    assert calls == ["charge", "charge"]


def test_raise_replaces_attempt_with_failed(isolated_project: Path) -> None:
    app = _app([], error=RuntimeError("failed after effect"))
    assert _run(app).status is not RunStatus.SUCCESS
    step = ScopeStore.for_project(isolated_project).get_step(
        "s1", step_key("charge", "")
    )
    assert step["status"] == StepStatus.FAILED
    assert step["attempt"] == 1
    assert step["completed_at"]


@pytest.mark.parametrize(
    "error,status",
    [
        (StepBlocked("child", "approval"), StepStatus.BLOCKED),
        (ScopeCancelledError("child", workflow="nested"), StepStatus.CANCELLED),
    ],
)
def test_block_and_cancel_are_endings(
    isolated_project: Path, error: Exception, status: str
) -> None:
    store = RawScopeStore(JsonFileSubstrate(isolated_project / "raw"))
    declaration = WorkflowDeclaration(
        nodes=(Step("charge", effecting=True),), edges=(Edge("charge", END),)
    )
    events: list[tuple[str, str]] = []

    def run(_: str) -> None:
        raise error

    walker = WorkflowWalker(
        declaration,
        "s1",
        run_step=run,
        runtime_store=port_for(store),
        emit=lambda action, **data: events.append((action, data.get("outcome", ""))),
    )
    report = walker.run()
    assert report.outcome in (WalkOutcome.BLOCKED, WalkOutcome.FAILED)
    assert store.get_step("s1", step_key("charge", ""))["status"] == status
    assert ("workflow.step.end", report.outcome.value) in events
    if status == StepStatus.BLOCKED:
        assert walker.run().outcome is WalkOutcome.BLOCKED
        assert store.get_step("s1", step_key("charge", ""))["attempt"] == 2


def test_routed_failure_replaces_attempt(isolated_project: Path) -> None:
    store = RawScopeStore(JsonFileSubstrate(isolated_project / "raw"))
    declaration = WorkflowDeclaration(
        nodes=(Step("charge", effecting=True), Step("cleanup")),
        edges=(OnFailure(source="charge", target="cleanup"), Edge("cleanup", END)),
    )

    def run(name: str) -> str:
        if name == "charge":
            raise RuntimeError("failed after effect")
        return "cleaned"

    report = WorkflowWalker(
        declaration, "s1", run_step=run, runtime_store=port_for(store)
    ).run()
    assert report.outcome is WalkOutcome.COMPLETED
    step = store.get_step("s1", step_key("charge", ""))
    assert step["status"] == StepStatus.FAILED
    assert step["attempt"] == 1
    assert step["completed_at"]


def test_reclaim_keeps_attempt_until_resumed_walk_reaches_it(
    isolated_project: Path,
) -> None:
    store = RawScopeStore(JsonFileSubstrate(isolated_project / "raw"))
    port = port_for(store)
    declaration = WorkflowDeclaration(
        nodes=(Step("charge", effecting=True),), edges=(Edge("charge", END),)
    )

    def crash(_: str) -> None:
        raise Crash()

    with pytest.raises(Crash):
        WorkflowWalker(declaration, "s1", run_step=crash, runtime_store=port).run()
    reclaim = FrontierWalk(graph_model_of(declaration), "s1", runtime_store=port)
    reclaim.claim()
    assert (
        store.get_step("s1", step_key("charge", ""))["status"] == StepStatus.ATTEMPTING
    )
    reclaim.release()
    report = WorkflowWalker(declaration, "s1", run_step=crash, runtime_store=port).run()
    assert report.outcome is WalkOutcome.BLOCKED
    assert report.blocked_on == "charge-in-doubt"
    assert report.blocked_reason.startswith(
        "in_doubt: step charge, attempt 1, started_at"
    )


def test_no_strategy_decides_recovery_without_prompt_gates(
    isolated_project: Path,
) -> None:
    store = RawScopeStore(JsonFileSubstrate(isolated_project / "raw"))
    port = port_for(store)
    declaration = WorkflowDeclaration(
        nodes=(Step("charge", effecting=True),), edges=(Edge("charge", END),)
    )

    def crash(_: str) -> None:
        raise Crash()

    class TrapRegistry:
        def evaluate(self, *_: Any, **__: Any) -> None:
            raise AssertionError("a strategy tried to decide the doubt")

    with pytest.raises(Crash):
        WorkflowWalker(declaration, "s1", run_step=crash, runtime_store=port).run()
    report = WorkflowWalker(
        declaration,
        "s1",
        run_step=crash,
        runtime_store=port,
        gate_registry=TrapRegistry(),
        prompt_gates=False,
    ).run()
    assert report.outcome is WalkOutcome.BLOCKED
    assert report.blocked_on == "charge-in-doubt"


@pytest.mark.parametrize("backend", ["document", "sqlite"])
def test_loop_doubt_is_specific_to_its_pass(
    isolated_project: Path, backend: str
) -> None:
    port = (
        port_for(RawScopeStore(JsonFileSubstrate(isolated_project / "raw")))
        if backend == "document"
        else _prepared_store(isolated_project)
    )
    declaration = WorkflowDeclaration(
        nodes=(Step("charge", effecting=True),),
        edges=(Loop("charge", "charge", max_iterations=2), Edge("charge", END)),
    )
    calls = 0

    def run(_: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Crash()
        return "receipt"

    with pytest.raises(Crash):
        WorkflowWalker(declaration, "s1", run_step=run, runtime_store=port).run()
    report = WorkflowWalker(declaration, "s1", run_step=run, runtime_store=port).run()
    assert report.outcome is WalkOutcome.BLOCKED
    assert calls == 2
    steps = {step.step_key: step for step in port.workflows.steps("s1")}
    assert steps[step_key("charge", "")].status == StepStatus.SUCCESS
    assert any(step.status == StepStatus.IN_DOUBT for step in steps.values())
    request = port.inputs.for_gate("s1", "charge-in-doubt")
    assert request is not None
    assert request.prompt["iteration"] == 1


@pytest.mark.parametrize("backend", ["document", "sqlite"])
def test_a_consumed_verdict_never_answers_a_second_attempt(
    isolated_project: Path, backend: str
) -> None:
    port = (
        port_for(RawScopeStore(JsonFileSubstrate(isolated_project / "raw")))
        if backend == "document"
        else _prepared_store(isolated_project)
    )
    declaration = WorkflowDeclaration(
        nodes=(Step("charge", effecting=True),), edges=(Edge("charge", END),)
    )
    calls = 0

    def crash(_: str) -> None:
        nonlocal calls
        calls += 1
        raise Crash()

    def walk() -> Any:
        return WorkflowWalker(
            declaration, "s1", run_step=crash, runtime_store=port
        ).run()

    with pytest.raises(Crash):
        walk()
    assert walk().outcome is WalkOutcome.BLOCKED
    first = port.inputs.for_gate("s1", "charge-in-doubt")
    assert first is not None
    candidate = InputRecorder().submitted(
        first.request_id,
        "test",
        CandidateEvaluation(EvaluationOutcome.ACCEPTED),
        {"outcome": "did_not_run"},
        ordinal=0,
        now=datetime.now(UTC),
    )
    with port.transaction() as tx:
        tx.inputs.append(candidate)
    with pytest.raises(Crash):
        walk()
    assert walk().outcome is WalkOutcome.BLOCKED
    second = port.inputs.for_gate("s1", "charge-in-doubt")
    assert second is not None
    assert second.request_id != first.request_id
    assert second.prompt["attempt"] == 2
    assert calls == 2
