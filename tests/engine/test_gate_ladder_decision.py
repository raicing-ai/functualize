"""The walk records each ladder rung and its accepted decision through its store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from functualize_substrate_sqlite import SqliteRuntimeStoreFactory
from pydantic import BaseModel

from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._events.run_log import pop_run, push_run
from functualize._gate import GateRegistry
from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.gate_resolution import EvaluationOutcome
from functualize._types.workflow import WorkflowDeclaration
from functualize.plugin import OutboxStore, RuntimeStoreConfig
from functualize.workflow import END, Edge, Gate

if TYPE_CHECKING:
    from functualize._gate._context import GateContext
    from functualize.plugin import RuntimeStore


class Approval(BaseModel):
    approved: bool


class _Fails:
    def resolve(self, context: GateContext) -> Approval:
        raise RuntimeError("resolver failed")


class _Accepts:
    def resolve(self, context: GateContext) -> Approval:
        return Approval(approved=True)


def _store(backend: str, root: Path) -> RuntimeStore:
    if backend == "documents":
        return DocumentRuntimeStore(JsonFileSubstrate(root))
    return (
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=f"sqlite://{root / 'state.db'}", scheme="sqlite", project_root=root
            )
        )
        .store
    )


def _run(store: RuntimeStore, *, accepts: bool) -> WalkOutcome:
    registry = GateRegistry()
    registry.register_strategy("prompt", _Fails())
    if accepts:
        registry.register_strategy("resolve", _Accepts())
    declaration = WorkflowDeclaration(
        nodes=(Gate("approval", Approval, strategy="ai_inbound"),),
        edges=(Edge("approval", END),),
    )
    walker = WorkflowWalker(
        declaration,
        "wf_ladder",
        run_step=lambda name: name,
        runtime_store=store,
        gate_registry=registry,
    )
    push_run("run_ladder")
    try:
        return walker.run().outcome
    finally:
        pop_run("run_ladder")


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
def test_accepted_ladder_records_observed_rungs_decision_and_intent(
    backend: str, tmp_path: Path
) -> None:
    store = _store(backend, tmp_path)
    try:
        assert _run(store, accepts=True) is WalkOutcome.COMPLETED
        request = store.inputs.for_gate("wf_ladder", "approval")
        assert request is not None
        assert request.run_id == "run_ladder"
        assert request.status == "consumed"

        candidates = store.inputs.candidates_for(request.request_id)
        assert [candidate.evaluation.outcome for candidate in candidates] == [
            EvaluationOutcome.UNAVAILABLE,
            EvaluationOutcome.FAILED,
            EvaluationOutcome.ACCEPTED,
        ]
        decision = store.inputs.decision(request.request_id)
        assert decision is not None
        assert decision.accepted_id == candidates[-1].candidate_id
        assert decision.observed_candidate_ids == tuple(
            candidate.candidate_id for candidate in candidates
        )
        assert decision.policy_id and decision.policy_version

        if backend == "sqlite":
            assert isinstance(store, OutboxStore)
            effects = store.effects.claim(
                ("gate.accepted",),
                now=datetime.now(UTC) + timedelta(seconds=1),
                lease_seconds=30,
                limit=10,
            )
            assert len(effects) == 1
            assert effects[0].idempotency_key == (f"gate.accepted:{request.request_id}")
            assert effects[0].payload["accepted_id"] == decision.accepted_id
    finally:
        store.close()


@pytest.mark.parametrize("backend", ["documents", "sqlite"])
def test_unaccepted_ladder_records_rungs_without_a_decision_or_intent(
    backend: str, tmp_path: Path
) -> None:
    store = _store(backend, tmp_path)
    try:
        assert _run(store, accepts=False) is WalkOutcome.BLOCKED
        request = store.inputs.for_gate("wf_ladder", "approval")
        assert request is not None
        assert request.run_id == "run_ladder"
        assert request.status == "open"
        assert [
            candidate.evaluation.outcome
            for candidate in store.inputs.candidates_for(request.request_id)
        ] == [
            EvaluationOutcome.UNAVAILABLE,
            EvaluationOutcome.FAILED,
            EvaluationOutcome.UNAVAILABLE,
        ]
        assert store.inputs.decision(request.request_id) is None
        if backend == "sqlite":
            assert isinstance(store, OutboxStore)
            assert (
                store.effects.claim(
                    ("gate.accepted",), now=datetime.now(UTC), lease_seconds=30, limit=1
                )
                == ()
            )
    finally:
        store.close()
