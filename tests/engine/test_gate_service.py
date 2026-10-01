"""The gate service records what it resolved — the rungs, not just the win.

This file is the sabotage anchor for the recording call: drop
``record_candidates`` from the service and the public-entry-point test fails.
The candidates it reads are the ones the walk wrote through the port.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import pytest
from pydantic import BaseModel
from tests._support.engine_storage import port_for

from functualize._engine.gate_service import _gate_strategy_list
from functualize._engine.recording import InputRecorder
from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._gate import GateRegistry
from functualize._gate.decision_strategy import DecisionGateResolver
from functualize._primitives.gate_requests import candidates_for
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.decision import (
    ChoiceDecision,
    ChoiceRequest,
    DecisionProvenance,
    DecisionResult,
)
from functualize._types.from_job import FromStep
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    LadderOutcome,
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


class Route(BaseModel):
    route: Literal["billing", "returns", "shipping"]


_DECISION = ChoiceDecision(
    field="route",
    instructions="Route the ticket to the team that owns it.",
    options={
        "billing": "money",
        "returns": "the customer wants a refund",
        "shipping": "the parcel's journey",
    },
    state=FromStep("intake"),
    accept_at=0.70,
    min_margin=0.10,
)


class _RecordingRegistry:
    """A registry stub: records what ``evaluate`` received, accepts one rung."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []

    def evaluate(self, model_class: type[BaseModel], **kwargs: Any) -> LadderOutcome:
        self.received.append({"model_class": model_class, **kwargs})
        model = Route(route="billing")
        return LadderOutcome(
            rungs=(
                (
                    "decision",
                    CandidateEvaluation(EvaluationOutcome.ACCEPTED),
                    model.model_dump(),
                ),
            ),
            model=model,
        )


class _Proposes:
    """A ``DecisionProvider`` proposing ``shipping`` clearly, recording its asks."""

    def __init__(self) -> None:
        self.asked: list[ChoiceRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        self.asked.append(request)
        return DecisionResult(
            value="shipping",
            provider="fake",
            model="fake-1",
            provenance=DecisionProvenance(
                requested_model="fake-1", latency_seconds=0.0
            ),
            distribution={"shipping": 0.85, "returns": 0.10, "billing": 0.05},
        )


def _decision_walk(store: ScopeStore, registry: Any) -> WorkflowWalker:
    declaration = WorkflowDeclaration(
        nodes=(Step("intake"), Gate(name="route", awaits=Route, decide=_DECISION)),
        edges=(Edge(source="intake", target="route"), Edge(source="route", target=END)),
    )
    return WorkflowWalker(
        declaration,
        store,
        "wf-decision",
        run_step=lambda name: f"{name}-result",
        runtime_store=port_for(store),
        gate_registry=registry,
    )


class TestTheWalkHandsTheGateItsResultsAndItsDecision:
    """C-7: a strategy can only read this walk if the walk hands it over."""

    def test_evaluate_receives_the_results_and_the_decision(
        self, store: ScopeStore
    ) -> None:
        registry = _RecordingRegistry()

        report = _decision_walk(store, registry).run()

        assert report.outcome is WalkOutcome.COMPLETED
        (received,) = registry.received
        assert received["workflow_context"] == {"intake": "intake-result"}
        assert received["decision"] is _DECISION
        assert received["gate_strategy"] == ["decision", "prompt", "resolve"]

    def test_the_results_are_a_copy_not_the_ledger(self, store: ScopeStore) -> None:
        registry = _RecordingRegistry()

        report = _decision_walk(store, registry).run()

        assert registry.received[0]["workflow_context"] is not report.results

    def test_a_gate_without_a_decision_hands_over_none(self, store: ScopeStore) -> None:
        registry = _RecordingRegistry()
        declaration = WorkflowDeclaration(
            nodes=(Gate(name="triage", awaits=Approval, strategy="ai_inbound"),),
            edges=(Edge(source="triage", target=END),),
        )

        WorkflowWalker(
            declaration,
            store,
            "wf-plain",
            run_step=lambda name: name,
            runtime_store=port_for(store),
            gate_registry=registry,
        ).run()

        assert registry.received[0]["decision"] is None
        assert registry.received[0]["workflow_context"] == {}

    @pytest.mark.parametrize("prompt_gates", [True, False])
    def test_a_decision_gates_ladder_is_the_three_names(
        self, prompt_gates: bool
    ) -> None:
        gate = Gate(name="route", awaits=Route, decide=_DECISION)

        assert _gate_strategy_list(gate, prompt_gates) == [
            "decision",
            "prompt",
            "resolve",
        ]

    def test_a_real_registry_decides_from_the_step_the_decision_names(
        self, store: ScopeStore
    ) -> None:
        """The whole chain short of the plugin: walk → service → registry →
        resolver → provider, reading the ``intake`` step's recorded result."""
        provider = _Proposes()
        registry = GateRegistry()
        registry.register_strategy("decision", DecisionGateResolver(provider))

        report = _decision_walk(store, registry).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert provider.asked[0].state == "intake-result"
        record = store.get_gate("wf-decision", "route") or {}
        assert record["payload"] == {"route": "shipping"}
        assert [c.source for c in candidates_for(record)] == [
            "strategy:decision",
            "strategy:prompt",
            "strategy:resolve",
        ]
