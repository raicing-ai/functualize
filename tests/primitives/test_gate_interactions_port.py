"""Gate interaction records through the port, on both shipped stores.

Gates for tasks 1.2 and 1.3 of `gate-interactions-outbox`: whichever store is
selected, a request carries its causal identity, a candidate its provenance
and evidence references, an acceptance one decision naming exactly what it
observed, and reopen cancels the accepted request (D-4) and opens a new one —
read back through ``InputReader`` alone.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from functualize._engine.recording import InputRecorder
from functualize._engine.recording.input_recorder import content_digest
from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    EvidenceRef,
    GateCandidate,
)
from functualize._types.persistence import (
    Claimed,
    ClaimWorkflow,
    RuntimeStore,
    RuntimeStoreConfig,
)

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
ACCEPTED = CandidateEvaluation(EvaluationOutcome.ACCEPTED)
INVALID = CandidateEvaluation(EvaluationOutcome.INVALID, errors=(("approved", "bad"),))
EVIDENCE = EvidenceRef("artifact://ev_5", content_digest(b"png"), "image/png", 3)


def _documents(root: Path) -> RuntimeStore:
    return DocumentRuntimeStore(JsonFileSubstrate(root))


def _sqlite(root: Path) -> RuntimeStore:
    sqlite = pytest.importorskip("functualize_substrate_sqlite._factory")
    config = RuntimeStoreConfig(
        url=f"sqlite://{root / 'state.db'}", scheme="sqlite", project_root=root
    )
    store: RuntimeStore = sqlite.SqliteRuntimeStoreFactory().prepare(config).store
    return store


@pytest.fixture(params=[_documents, _sqlite], ids=["documents", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> RuntimeStore:
    make: Callable[[Path], RuntimeStore] = request.param
    return make(tmp_path)


def _open_gate(store: RuntimeStore, *, run_id: str | None = "run_4") -> str:
    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow("wf_42", "walker", T0, 60.0))
    assert isinstance(claimed, Claimed)
    command = InputRecorder().opened(
        scope_id="wf_42",
        generation=claimed.generation,
        gate_name="approval",
        position="approval",
        now=T0,
        schema={"title": "Approval"},
        run_id=run_id,
    )
    with store.transaction() as tx:
        tx.workflows.suspend(command)
    return command.request_id


def _submit(
    request_id: str,
    evaluation: CandidateEvaluation,
    *,
    ordinal: int,
    supersedes: str | None = None,
    evidence: tuple[EvidenceRef, ...] = (),
) -> GateCandidate:
    return InputRecorder().submitted(
        request_id,
        "cli",
        evaluation,
        {"approved": evaluation.outcome is EvaluationOutcome.ACCEPTED},
        ordinal=ordinal,
        now=T0,
        schema_id="pkg.Approval",
        schema_version="sha256:v2",
        supersedes=supersedes,
        evidence=evidence,
    )


def _accept(
    store: RuntimeStore, request_id: str
) -> tuple[GateCandidate, GateCandidate]:
    invalid = _submit(request_id, INVALID, ordinal=0)
    with store.transaction() as tx:
        tx.inputs.append(invalid)
    accepted = _submit(
        request_id,
        ACCEPTED,
        ordinal=1,
        supersedes=invalid.candidate_id,
        evidence=(EVIDENCE,),
    )
    decision = InputRecorder().decided(
        request_id,
        [invalid, accepted],
        accepted.candidate_id,
        policy_id="gate.validate",
        policy_version="sha256:v2",
        now=T0,
    )
    with store.transaction() as tx:
        tx.inputs.append(accepted)
        tx.inputs.decide(decision)
    return invalid, accepted


def test_the_request_carries_its_causal_identity(store: RuntimeStore) -> None:
    request_id = _open_gate(store)

    request = store.inputs.request(request_id)

    assert request is not None
    assert (request.run_id, request.scope_id, request.position, request.generation) == (
        "run_4",
        "wf_42",
        "approval",
        1,
    )


def test_candidates_read_back_with_provenance_and_evidence(store: RuntimeStore) -> None:
    request_id = _open_gate(store)
    invalid, accepted = _accept(store, request_id)

    read = store.inputs.candidates_for(request_id)

    assert [c.candidate_id for c in read] == [
        invalid.candidate_id,
        accepted.candidate_id,
    ]
    last = read[1]
    assert (last.resolver_class, last.channel) == ("human", "cli")
    assert (last.schema_id, last.schema_version) == ("pkg.Approval", "sha256:v2")
    assert last.payload_hash == accepted.payload_hash
    assert last.supersedes_candidate_id == invalid.candidate_id
    assert last.evidence_refs == (EVIDENCE,)
    assert read[0].evaluation.outcome is EvaluationOutcome.INVALID


def test_the_decision_names_its_policy_and_what_it_observed(
    store: RuntimeStore,
) -> None:
    request_id = _open_gate(store)
    invalid, accepted = _accept(store, request_id)

    decision = store.inputs.decision(request_id)

    assert decision is not None
    assert decision.accepted_id == accepted.candidate_id
    assert (decision.policy_id, decision.policy_version) == (
        "gate.validate",
        "sha256:v2",
    )
    assert decision.observed_candidate_ids == (
        invalid.candidate_id,
        accepted.candidate_id,
    )


def test_a_second_decision_is_refused(store: RuntimeStore) -> None:
    request_id = _open_gate(store)
    _invalid, accepted = _accept(store, request_id)
    again = InputRecorder().decided(
        request_id,
        [accepted],
        accepted.candidate_id,
        policy_id="other",
        policy_version="2",
        now=T0,
    )

    with pytest.raises(ValueError, match="already decided"), store.transaction() as tx:
        tx.inputs.decide(again)

    decision = store.inputs.decision(request_id)
    assert decision is not None and decision.policy_id == "gate.validate"


def test_an_undecided_request_reads_no_decision(store: RuntimeStore) -> None:
    request_id = _open_gate(store)
    assert store.inputs.decision(request_id) is None


def test_reopen_cancels_the_accepted_request_and_opens_a_new_one(
    store: RuntimeStore,
) -> None:
    request_id = _open_gate(store)
    _accept(store, request_id)
    command = InputRecorder().superseding(
        scope_id="wf_42", gate_name="approval", request_id=request_id, now=T0
    )

    with store.transaction() as tx:
        tx.inputs.supersede(command)

    fresh = store.inputs.for_gate("wf_42", "approval")
    assert fresh is not None
    assert fresh.request_id == command.new_request_id
    assert (fresh.status, fresh.run_id, fresh.position) == ("open", "run_4", "approval")
    assert store.inputs.candidates_for(command.new_request_id) == ()
    # The withdrawn answer is history, not a hole: on the relational store
    # the request row is still there, cancelled, with its decision.
    withdrawn = store.inputs.request(request_id)
    if withdrawn is not None:
        assert withdrawn.status == "cancelled"
        assert store.inputs.decision(request_id) is not None


def test_reopen_of_an_unanswered_request_is_refused(store: RuntimeStore) -> None:
    request_id = _open_gate(store)
    command = InputRecorder().superseding(
        scope_id="wf_42", gate_name="approval", request_id=request_id, now=T0
    )

    with pytest.raises(ValueError, match="not accepted"), store.transaction() as tx:
        tx.inputs.supersede(command)

    request = store.inputs.request(request_id)
    assert request is not None and request.status == "open"


def test_a_candidate_after_acceptance_is_still_refused(store: RuntimeStore) -> None:
    request_id = _open_gate(store)
    _accept(store, request_id)

    with pytest.raises(InputRequestNotOpenError), store.transaction() as tx:
        tx.inputs.append(_submit(request_id, ACCEPTED, ordinal=2))
