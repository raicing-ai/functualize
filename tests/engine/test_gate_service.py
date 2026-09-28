"""The gate service records what it resolved — the rungs, not just the win.

This file is the sabotage anchor for the recording call: drop
``record_candidates`` from the service and the public-entry-point test fails.
The candidates it reads are the ones the walk wrote through the port.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel
from tests._support.engine_storage import port_for

from functualize._engine.recording import InputRecorder
from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._gate import GateRegistry
from functualize._primitives.gate_requests import candidates_for
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
)
from functualize._types.workflow import END, Edge, Gate, WorkflowDeclaration
from functualize.app import FunctualizeApp
from functualize.types import RunRequest
from functualize.workflow import Step, workflow

if TYPE_CHECKING:
    from pathlib import Path

    from functualize._gate._context import GateContext


class Approval(BaseModel):
    approved: bool


class _Boom:
    """A registered resolver that raises — the failed rung."""

    def resolve(self, ctx: GateContext) -> BaseModel:
        raise RuntimeError("resolver exploded")


class _Yes:
    """A registered resolver that answers — the accepted rung."""

    def resolve(self, ctx: GateContext) -> BaseModel:
        return Approval(approved=True)


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _walk(store: ScopeStore, registry: GateRegistry) -> WorkflowWalker:
    declaration = WorkflowDeclaration(
        nodes=(Gate(name="triage", awaits=Approval, strategy="ai_inbound"),),
        edges=(Edge(source="triage", target=END),),
    )
    return WorkflowWalker(
        declaration,
        store,
        "wf-gate",
        run_step=lambda name: f"{name}-result",
        runtime_store=port_for(store),
        gate_registry=registry,
    )


def _runged_registry(resolve_with: Any = None) -> GateRegistry:
    """`ai_inbound`'s ladder with `prompt` broken; `resolve` optional."""
    registry = GateRegistry()
    registry.register_strategy("prompt", _Boom())
    if resolve_with is not None:
        registry.register_strategy("resolve", resolve_with)
    return registry


class TestTheLadderIsRecorded:
    def test_ladder_rungs_are_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        (project / ".functualize").mkdir(parents=True)
        monkeypatch.chdir(project)
        app = FunctualizeApp(name="gate-recording")

        def prepare() -> str:
            return "ready"

        @workflow(
            steps=[Step("prepare"), Gate("triage", Approval, strategy="ai_inbound")],
            edges=[Edge("prepare", "triage"), Edge("triage", END)],
        )
        def review() -> str:
            return "reviewed"

        app.register_dynamic_job("prepare", prepare)
        app.register_dynamic_job("review", review)
        app.gates.register_gate_strategy("prompt", _Boom())
        app.gates.register_gate_strategy("resolve", _Yes())

        result = app.execute(
            RunRequest(
                job_name="review", surface="app.execute", workflow_scope_id="wf-gate"
            )
        )
        assert result.status.value == "Success"
        record = ScopeStore.for_project(project).get_gate("wf-gate", "triage")
        assert record is not None
        assert [
            candidate.evaluation.outcome for candidate in candidates_for(record)
        ] == [
            EvaluationOutcome.UNAVAILABLE,
            EvaluationOutcome.FAILED,
            EvaluationOutcome.ACCEPTED,
        ]
        assert record["status"] == "consumed"

    def test_a_resolved_ladder_leaves_one_candidate_per_rung(
        self, store: ScopeStore
    ) -> None:
        report = _walk(store, _runged_registry(_Yes())).run()
        assert report.outcome is WalkOutcome.COMPLETED

        record = store.get_gate("wf-gate", "triage") or {}
        recorded = candidates_for(record)
        assert [c.evaluation.outcome for c in recorded] == [
            EvaluationOutcome.UNAVAILABLE,
            EvaluationOutcome.FAILED,
            EvaluationOutcome.ACCEPTED,
        ]
        assert [c.source for c in recorded] == [
            "strategy:ai_inbound",
            "strategy:prompt",
            "strategy:resolve",
        ]
        assert record["status"] == "consumed"
        assert record["payload"] == {"approved": True}

    def test_a_blocked_ladder_records_its_failed_rungs(self, store: ScopeStore) -> None:
        report = _walk(store, _runged_registry()).run()
        assert report.outcome is WalkOutcome.BLOCKED
        assert "resolver exploded" in report.blocked_reason
        assert "ai_inbound" in report.blocked_reason

        record = store.get_gate("wf-gate", "triage") or {}
        recorded = candidates_for(record)
        assert [c.evaluation.outcome for c in recorded] == [
            EvaluationOutcome.UNAVAILABLE,
            EvaluationOutcome.FAILED,
            EvaluationOutcome.UNAVAILABLE,
        ]
        assert record["status"] == "open"
        assert record["payload"] is None


class TestTheRequestIdentity:
    def test_a_blocked_gate_then_resume_keeps_one_request(
        self, store: ScopeStore
    ) -> None:
        first = _walk(store, _runged_registry()).run()
        assert first.outcome is WalkOutcome.BLOCKED
        request_id = (store.get_gate("wf-gate", "triage") or {})["request_id"]

        # Answered out-of-band, then walked again: same request, consumed.
        recorder = InputRecorder()
        candidate = recorder.submitted(
            request_id,
            "api",
            CandidateEvaluation(EvaluationOutcome.ACCEPTED),
            {"approved": True},
            ordinal=3,
            now=datetime.now(UTC),
        )
        walker = _walk(store, _runged_registry(_Yes()))
        walker._walk.record_candidates((candidate,))
        resumed = _walk(store, _runged_registry(_Yes())).run()
        assert resumed.outcome is WalkOutcome.COMPLETED

        record = store.get_gate("wf-gate", "triage") or {}
        assert record["request_id"] == request_id, "the id is stable across resumes"
        assert record["status"] == "consumed"
        outcomes = [c.evaluation.outcome for c in candidates_for(record)]
        assert outcomes.count(EvaluationOutcome.ACCEPTED) == 1
        assert outcomes[-1] is EvaluationOutcome.ACCEPTED
        assert candidates_for(record)[-1].ordinal == 3
