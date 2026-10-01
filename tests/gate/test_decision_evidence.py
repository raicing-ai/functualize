"""The evidence builder's contract: exactly the keys, exactly the facts.

``build_decision_evidence`` is a pure projection — the declaration, the
state text, the provider's result or failure, and the verdict — so what is
pinned here is shape: the key set a reader may rely on, the state digest a
reader recomputes, and the failure facts a provider outage leaves behind.
The builder lives apart from the rule module, which never names the
provider's own scalar; the evidence records it faithfully all the same.
"""

from __future__ import annotations

import hashlib

from functualize._gate.decision_evidence import SCHEMA, build_decision_evidence
from functualize._types.decision import (
    ChoiceDecision,
    DecisionProvenance,
    DecisionResult,
)
from functualize._types.errors import DecisionFailure, DecisionUnavailableError
from functualize._types.from_job import FromStep

_TEXT = "Where is my parcel? It was due on Monday."

_KEYS = {
    "schema",
    "field",
    "state",
    "rule",
    "provider",
    "model",
    "requested_model",
    "proposal",
    "distribution",
    "confidence",
    "probability",
    "margin",
    "verdict",
    "failure",
    "latency_seconds",
    "input_tokens",
    "output_tokens",
}


def _decision(**overrides: object) -> ChoiceDecision:
    arguments: dict[str, object] = {
        "field": "route",
        "instructions": "Route the ticket to the team that owns it.",
        "options": {
            "billing": "an invoice question",
            "returns": "send it back",
            "shipping": "where a parcel is",
        },
        "state": FromStep("intake"),
        "accept_at": 0.70,
        "min_margin": 0.10,
    }
    arguments.update(overrides)
    return ChoiceDecision(**arguments)  # type: ignore[arg-type]


def _result(**overrides: object) -> DecisionResult[str]:
    arguments: dict[str, object] = {
        "value": "shipping",
        "provider": "fake",
        "model": "fake-1",
        "provenance": DecisionProvenance(
            requested_model="fake-1", latency_seconds=0.25
        ),
        "distribution": {"shipping": 0.8, "returns": 0.2},
    }
    arguments.update(overrides)
    return DecisionResult(**arguments)  # type: ignore[arg-type]


class TestTheKeySet:
    def test_an_accepted_rung_carries_exactly_the_contracted_keys(self) -> None:
        evidence = build_decision_evidence(
            _decision(),
            state=_TEXT,
            latency_seconds=0.25,
            result=_result(),
            probability=0.8,
            margin=0.6,
            verdict="accepted",
        )

        assert set(evidence) == _KEYS
        assert len(_KEYS) == 17
        assert evidence["schema"] == SCHEMA == "decision-evidence/1"

    def test_a_provider_failure_carries_the_same_keys(self) -> None:
        evidence = build_decision_evidence(
            _decision(),
            state=_TEXT,
            latency_seconds=0.5,
            error=DecisionUnavailableError(
                kind=DecisionFailure.RATE_LIMITED,
                provider="fake",
                detail="slow down",
            ),
            verdict="provider_failed",
        )

        assert set(evidence) == _KEYS


class TestTheStateDigest:
    def test_the_digest_is_the_sha256_of_the_state_text(self) -> None:
        evidence = build_decision_evidence(
            _decision(),
            state=_TEXT,
            latency_seconds=0.25,
            result=_result(),
            verdict="accepted",
        )

        assert evidence["state"] == {
            "step": "intake",
            "sha256": hashlib.sha256(_TEXT.encode()).hexdigest(),
            "chars": len(_TEXT),
        }

    def test_the_rule_carries_its_digest_and_declared_fallback(self) -> None:
        evidence = build_decision_evidence(
            _decision(fallback="returns"),
            state=_TEXT,
            latency_seconds=0.25,
            result=_result(),
            verdict="below_threshold",
        )

        rule = evidence["rule"]
        assert rule["digest"].startswith("sha256:")
        assert rule["accept_at"] == 0.70
        assert rule["min_margin"] == 0.10
        assert rule["fallback"] == "returns"


class TestAProviderFailure:
    def test_the_failure_facts_are_the_error_s_own(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.RATE_LIMITED,
            provider="fake",
            status=429,
            retry_after=19014.0,
            detail="Rate limit exceeded",
        )

        evidence = build_decision_evidence(
            _decision(),
            state=_TEXT,
            latency_seconds=0.5,
            error=error,
            verdict="provider_failed",
        )

        assert evidence["failure"] == {
            "kind": "rate_limited",
            "status": 429,
            "retry_after": 19014.0,
        }
        assert evidence["provider"] == "fake"
        assert evidence["verdict"] == "provider_failed"

    def test_nothing_is_invented_beside_a_failure(self) -> None:
        evidence = build_decision_evidence(
            _decision(),
            state=_TEXT,
            latency_seconds=0.5,
            error=DecisionUnavailableError(
                kind=DecisionFailure.NOT_CONFIGURED,
                provider="fake",
                detail="no key",
            ),
            verdict="provider_failed",
        )

        assert evidence["model"] is None
        assert evidence["requested_model"] is None
        assert evidence["proposal"] is None
        assert evidence["distribution"] is None
        assert evidence["confidence"] is None
        assert evidence["input_tokens"] is None
        assert evidence["output_tokens"] is None


class TestAReportedResult:
    def test_the_reported_facts_pass_through_unchanged(self) -> None:
        evidence = build_decision_evidence(
            _decision(),
            state=_TEXT,
            latency_seconds=0.25,
            result=_result(
                provenance=DecisionProvenance(
                    requested_model="fake-1",
                    latency_seconds=0.25,
                    input_tokens=120,
                    output_tokens=8,
                ),
                confidence=0.9,
            ),
            probability=0.8,
            margin=0.6,
            verdict="accepted",
        )

        assert evidence["provider"] == "fake"
        assert evidence["model"] == "fake-1"
        assert evidence["requested_model"] == "fake-1"
        assert evidence["proposal"] == "shipping"
        assert evidence["distribution"] == {"shipping": 0.8, "returns": 0.2}
        assert evidence["confidence"] == 0.9
        assert evidence["input_tokens"] == 120
        assert evidence["output_tokens"] == 8

    def test_a_requested_model_is_the_declared_one_without_a_result(self) -> None:
        evidence = build_decision_evidence(
            _decision(model="jev-1.13"),
            state=_TEXT,
            latency_seconds=0.5,
            error=DecisionUnavailableError(
                kind=DecisionFailure.NOT_CONFIGURED,
                provider="fake",
                detail="no key",
            ),
            verdict="provider_failed",
        )

        assert evidence["requested_model"] == "jev-1.13"
