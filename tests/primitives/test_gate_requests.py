"""The gate request document representation and its guard rules.

Everything here goes through ``ScopeStore``'s public surface — no method is
added to it, which is the point: the request model is a *shape* of the gate
record, not new store machinery. The five behaviours under test are the ones
the model exists for:

- **reuse** — one live request per (scope, gate), however often the walk
  re-enters;
- **projection** — a legacy record is read as an answered gate with zero
  candidates, never rewritten into a request it never was;
- **exclusivity** — two writers, two store instances, one substrate: exactly
  one accepted candidate lands and the other is refused with nothing
  written;
- **archive** — superseding keeps the answered request's candidates under
  ``superseded`` rather than discarding them;
- **idempotence** — consuming twice is a no-op, because a replayed resume
  is a legitimate second caller.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from functualize._primitives.gate_requests import (
    append_candidate,
    candidates_for,
    consume_request,
    open_request,
    request_for,
    supersede_request,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _fresh(tmp_path: Path) -> ScopeStore:
    """A second store over the same documents, sharing no memory with the
    first — the honest spelling of "another process" in one test."""
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _accepted(candidate_id: str, ordinal: int = 0) -> GateCandidate:
    return GateCandidate(
        candidate_id=candidate_id,
        request_id="req_1",
        ordinal=ordinal,
        source="api",
        submitted_at=NOW,
        evaluation=CandidateEvaluation(EvaluationOutcome.ACCEPTED),
        payload={"approved": True},
    )


def _open(store: ScopeStore, request_id: str = "req_1") -> str:
    return open_request(
        store,
        "wf-1",
        "approve",
        request_id=request_id,
        schema={"type": "object"},
        prompt="Approve?",
        model="Approval",
        tools=(),
        now=NOW,
    )


class TestOpenReusesALiveRequest:
    def test_a_second_open_returns_the_same_id_untouched(
        self, store: ScopeStore
    ) -> None:
        first = _open(store)
        later = NOW.replace(hour=13)
        second = open_request(
            store,
            "wf-1",
            "approve",
            request_id="req_2",
            schema={"type": "object"},
            prompt="Approve?",
            model="Approval",
            tools=(),
            now=later,
        )
        assert second == first == "req_1"
        record = store.get_gate("wf-1", "approve") or {}
        assert record["blocked_at"] == NOW.isoformat(), "blocked_at is not reset"
        assert record["request_id"] == "req_1"

    def test_a_consumed_request_is_still_reused(self, store: ScopeStore) -> None:
        _open(store)
        append_candidate(store, "wf-1", "approve", _accepted("cand_1"))
        consume_request(store, "wf-1", "approve", "req_1", NOW)
        assert _open(store, request_id="req_other") == "req_1"


class TestALegacyRecordIsProjected:
    def test_it_reads_under_the_derived_id_with_zero_candidates(
        self, store: ScopeStore
    ) -> None:
        store.ensure_scope("wf-1")
        store.put_gate(
            "wf-1",
            "approve",
            {
                "model": "Approval",
                "input_schema": {"type": "object"},
                "payload": {"approved": True},
                "blocked_at": NOW.isoformat(),
            },
        )
        request = request_for("wf-1", "approve", store.get_gate("wf-1", "approve"), 3)
        assert request.request_id == "wf-1::approve"
        assert request.status == "accepted"
        assert request.generation == 3
        assert candidates_for(store.get_gate("wf-1", "approve")) == ()
        # And the record itself is untouched — no request was synthesised.
        assert "request_id" not in (store.get_gate("wf-1", "approve") or {})

    def test_a_legacy_consumed_record_reads_consumed(self, store: ScopeStore) -> None:
        store.ensure_scope("wf-1")
        store.put_gate(
            "wf-1",
            "approve",
            {
                "payload": {"approved": True},
                "blocked_at": NOW.isoformat(),
                "consumed_at": NOW.isoformat(),
            },
        )
        request = request_for("wf-1", "approve", store.get_gate("wf-1", "approve"), 0)
        assert request.status == "consumed"
        assert request.resolved_at == NOW


class TestTwoWritersOneAnswer:
    def test_exactly_one_accepted_lands_and_the_other_is_refused(
        self, store: ScopeStore, tmp_path: Path
    ) -> None:
        _open(store)
        other = _fresh(tmp_path)
        append_candidate(store, "wf-1", "approve", _accepted("cand_a"))
        with pytest.raises(InputRequestNotOpenError) as refused:
            append_candidate(other, "wf-1", "approve", _accepted("cand_b"))
        assert refused.value.status == "accepted"

        record = _fresh(tmp_path).get_gate("wf-1", "approve") or {}
        recorded = candidates_for(record)
        assert [c.candidate_id for c in recorded] == ["cand_a"]
        assert record["payload"] == {"approved": True}


class TestSupersedeKeepsTheCandidates:
    def test_the_answered_history_survives_a_reopen(self, store: ScopeStore) -> None:
        _open(store)
        append_candidate(store, "wf-1", "approve", _accepted("cand_1", ordinal=2))
        supersede_request(store, "wf-1", "approve", new_request_id="req_2", now=NOW)
        record = store.get_gate("wf-1", "approve") or {}
        assert record["request_id"] == "req_2"
        assert record["status"] == "open"
        assert record["payload"] is None
        assert record["draft"] == {
            "values": {"approved": True},
            "updated_at": NOW.isoformat(),
        }
        archived = record["superseded"]
        assert len(archived) == 1
        assert archived[0]["status"] == "cancelled"
        assert archived[0]["cancel_reason"] == "reopened"
        assert [c.candidate_id for c in candidates_for(archived[0])] == ["cand_1"]
        # The new request is live and answerable.
        append_candidate(store, "wf-1", "approve", _accepted("cand_9"))
        consume_request(store, "wf-1", "approve", "req_2", NOW)


class TestConsumingTwiceIsANoOp:
    def test_the_second_consume_leaves_the_record_alone(
        self, store: ScopeStore
    ) -> None:
        _open(store)
        append_candidate(store, "wf-1", "approve", _accepted("cand_1"))
        consume_request(store, "wf-1", "approve", "req_1", NOW)
        first_state = dict(store.get_gate("wf-1", "approve") or {})
        consume_request(store, "wf-1", "approve", "req_1", NOW.replace(hour=14))
        assert store.get_gate("wf-1", "approve") == first_state

    def test_consuming_an_open_request_refuses(self, store: ScopeStore) -> None:
        _open(store)
        with pytest.raises(ValueError, match="not accepted"):
            consume_request(store, "wf-1", "approve", "req_1", NOW)

    def test_appending_after_consumption_refuses(self, store: ScopeStore) -> None:
        _open(store)
        append_candidate(store, "wf-1", "approve", _accepted("cand_1"))
        consume_request(store, "wf-1", "approve", "req_1", NOW)
        with pytest.raises(InputRequestNotOpenError) as refused:
            append_candidate(store, "wf-1", "approve", _accepted("cand_2"))
        assert refused.value.status == "consumed"
