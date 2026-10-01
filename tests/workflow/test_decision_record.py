"""`decision_record` — one routed run, read back as a single record.

The record is a projection of recorded candidates, so every case here is
built the way the ladder builds them: a request opened on a real store,
candidates appended through the same wire, and the reader asked the
operator's question — who took the gate, on which route, and when the
fallback took it, why the decision did not. Nothing is re-evaluated; the
assertions read exactly what was recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from functualize._primitives import gate_requests
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.app.utils import decision_record

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

_BELOW_THRESHOLD = (
    "fake/fake-1 proposed 'returns' at 0.54 (margin 0.08); "
    "workflow requires >= 0.70, margin >= 0.10"
)
_INSTALL_HINT = "install functualize-decision-jev to register it"


def _store(tmp_path: Path) -> ScopeStore:
    store = ScopeStore(JsonFileSubstrate(tmp_path))
    store.ensure_scope("wf-1")
    gate_requests.open_request(
        store,
        "wf-1",
        "route",
        request_id="req_1",
        schema={"type": "object"},
        prompt="Route it.",
        model="RouteChoice",
        tools=(),
        now=NOW,
    )
    return store


def _candidate(
    ordinal: int,
    source: str,
    outcome: EvaluationOutcome,
    *,
    detail: str = "",
    evidence: dict[str, Any] | None = None,
    payload: Any = None,
) -> GateCandidate:
    return GateCandidate(
        candidate_id=f"cand_{ordinal}",
        request_id="req_1",
        ordinal=ordinal,
        source=source,
        submitted_at=NOW,
        evaluation=CandidateEvaluation(outcome, detail=detail, evidence=evidence),
        payload=payload,
    )


_EVIDENCE = {
    "schema": "decision-evidence/1",
    "field": "route",
    "verdict": "accepted",
    "probability": 0.82,
    "margin": 0.72,
}


class TestAcceptedByDecision:
    def test_the_decision_rung_took_the_gate(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        gate_requests.append_candidate(
            store,
            "wf-1",
            "route",
            _candidate(
                0,
                "strategy:decision",
                EvaluationOutcome.ACCEPTED,
                evidence=_EVIDENCE,
                payload={"route": "cheap_model"},
            ),
        )

        record = decision_record(store, "wf-1", "route")

        assert record is not None
        assert record["gate"] == "route"
        assert record["request_id"] == "req_1"
        assert record["decided_by"] == "decision"
        assert record["route"] == "cheap_model"
        assert record["fallback_used"] is False
        assert record["reason"] is None
        assert record["evidence"] == _EVIDENCE


class TestTheFallbackTookIt:
    def test_after_a_below_threshold_proposal(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        gate_requests.append_candidate(
            store,
            "wf-1",
            "route",
            _candidate(
                0,
                "strategy:decision",
                EvaluationOutcome.FAILED,
                detail=_BELOW_THRESHOLD,
                evidence={**_EVIDENCE, "verdict": "below_threshold"},
            ),
        )
        gate_requests.append_candidate(
            store,
            "wf-1",
            "route",
            _candidate(
                1,
                "strategy:resolve",
                EvaluationOutcome.ACCEPTED,
                payload={"route": "human_review"},
            ),
        )

        record = decision_record(store, "wf-1", "route")

        assert record is not None
        assert record["decided_by"] == "fallback"
        assert record["fallback_used"] is True
        assert record["route"] == "human_review"
        assert record["reason"] is not None
        assert record["reason"].startswith("decision: ")
        assert "proposed 'returns' at 0.54" in record["reason"]
        assert record["evidence"] is not None
        assert record["evidence"]["verdict"] == "below_threshold"

    def test_after_an_unavailable_provider(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        gate_requests.append_candidate(
            store,
            "wf-1",
            "route",
            _candidate(
                0,
                "strategy:decision",
                EvaluationOutcome.UNAVAILABLE,
                detail=_INSTALL_HINT,
            ),
        )
        gate_requests.append_candidate(
            store,
            "wf-1",
            "route",
            _candidate(
                1,
                "strategy:resolve",
                EvaluationOutcome.ACCEPTED,
                payload={"route": "human_review"},
            ),
        )

        record = decision_record(store, "wf-1", "route")

        assert record is not None
        assert record["decided_by"] == "fallback"
        assert record["reason"] is not None
        assert "install functualize-decision-jev" in record["reason"]
        assert record["evidence"] is None


class TestAPersonTookIt:
    def test_a_surface_submission_is_a_person(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        gate_requests.append_candidate(
            store,
            "wf-1",
            "route",
            _candidate(
                0,
                "cli",
                EvaluationOutcome.ACCEPTED,
                payload={"route": "human_review", "handled": True},
            ),
        )

        record = decision_record(store, "wf-1", "route")

        assert record is not None
        assert record["decided_by"] == "person"
        assert record["fallback_used"] is False
        assert record["evidence"] is None
        assert record["reason"] is None
        # A two-key payload names no single route, and none is invented.
        assert record["route"] is None


class TestUnanswered:
    def test_an_open_request_has_no_taker(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        record = decision_record(store, "wf-1", "route")

        assert record is not None
        assert record["request_id"] == "req_1"
        assert record["decided_by"] is None
        assert record["route"] is None
        assert record["fallback_used"] is False
        assert record["reason"] is None
        assert record["evidence"] is None


class TestNoRecord:
    def test_a_gate_the_scope_never_reached_reads_none(self, tmp_path: Path) -> None:
        store = _store(tmp_path)

        assert decision_record(store, "wf-1", "absent") is None
