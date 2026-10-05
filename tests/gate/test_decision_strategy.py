"""The decision strategy, read off the rungs a ``GateRegistry.evaluate`` records.

Every test drives the registry's ladder with a fake ``DecisionProvider`` and a
``ChoiceDecision`` declaring ``accept_at=0.70, min_margin=0.10``, then reads the
recorded rung: what was accepted, and — when nothing was — the exact detail a
person answering the gate is shown. The resolver is never called directly, so
the ``decision`` keyword's path from ``evaluate`` into ``GateContext`` is part of
what every case exercises.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from functualize._gate._registry import GateRegistry
from functualize._gate.decision_strategy import (
    DecisionBelowThresholdError,
    DecisionGateResolver,
)
from functualize._types.decision import (
    ChoiceDecision,
    ChoiceRequest,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
)
from functualize._types.errors import DecisionFailure, DecisionUnavailableError
from functualize._types.from_job import FromStep
from functualize._types.gate_resolution import EvaluationOutcome, LadderOutcome

_OPTIONS = {
    "billing": "a question about an invoice or a charge",
    "returns": "the customer wants to send something back",
    "shipping": "where a parcel is, or when it arrives",
}
_TICKET = "Where is my parcel? It was due on Monday."


class Route(BaseModel):
    route: Literal["billing", "returns", "shipping"]
    priority: str


_DECISION = ChoiceDecision(
    field="route",
    instructions="Route the ticket to the team that owns it.",
    options=_OPTIONS,
    state=FromStep("intake"),
    accept_at=0.70,
    min_margin=0.10,
)


@dataclass
class FakeProvider:
    """A ``DecisionProvider`` that proposes one fixed result, or raises."""

    value: str = "shipping"
    distribution: Mapping[str, float] | None = None
    confidence: float | None = None
    error: Exception | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    asked: list[ChoiceRequest] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        self.asked.append(request)
        if self.error is not None:
            raise self.error
        return DecisionResult(
            value=self.value,
            provider="fake",
            model="fake-1",
            provenance=DecisionProvenance(
                requested_model="fake-1",
                latency_seconds=0.0,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
            ),
            distribution=self.distribution,
            confidence=self.confidence,
        )


def _evaluate(
    provider: FakeProvider,
    *,
    workflow_context: dict[str, Any] | None = None,
    decision: ChoiceDecision | None = _DECISION,
) -> LadderOutcome:
    registry = GateRegistry()
    registry.register_strategy("decision", DecisionGateResolver(provider))
    return registry.evaluate(
        Route,
        gate_strategy="decision",
        gate_name="route",
        resolved_fields={"priority": "normal"},
        workflow_context=(
            {"intake": _TICKET} if workflow_context is None else workflow_context
        ),
        decision=decision,
    )


def _only_rung(outcome: LadderOutcome) -> tuple[EvaluationOutcome, str]:
    ((name, evaluation, _),) = outcome.rungs
    assert name == "decision"
    return evaluation.outcome, evaluation.detail


class TestAcceptance:
    def test_a_clear_proposal_is_accepted(self) -> None:
        """AC-9: 0.80, margin 0.40 → accepted, the model built with that option."""
        provider = FakeProvider(
            "shipping", {"shipping": 0.80, "returns": 0.40, "billing": 0.10}
        )

        outcome = _evaluate(provider)

        assert _only_rung(outcome) == (EvaluationOutcome.ACCEPTED, "")
        assert outcome.model == Route(route="shipping", priority="normal")
        assert outcome.blocked_reason == ""

    def test_a_proposal_below_threshold_is_refused_with_the_exact_detail(
        self,
    ) -> None:
        """AC-10: 0.54, margin 0.08 → the detail a person is shown, verbatim."""
        provider = FakeProvider(
            "returns", {"returns": 0.54, "shipping": 0.46, "billing": 0.00}
        )

        outcome = _evaluate(provider)

        detail = (
            "fake/fake-1 proposed 'returns' at 0.54 (margin 0.08); "
            "workflow requires >= 0.70, margin >= 0.10"
        )
        assert _only_rung(outcome) == (EvaluationOutcome.FAILED, detail)
        assert outcome.model is None
        assert outcome.blocked_reason == f"decision: {detail}"

    def test_a_high_probability_with_too_small_a_lead_is_refused(self) -> None:
        provider = FakeProvider("returns", {"returns": 0.75, "shipping": 0.70})

        outcome, detail = _only_rung(_evaluate(provider))

        assert outcome is EvaluationOutcome.FAILED
        assert "at 0.75 (margin 0.05)" in detail

    def test_accept_at_is_inclusive(self) -> None:
        provider = FakeProvider("returns", {"returns": 0.70, "shipping": 0.55})

        assert _only_rung(_evaluate(provider))[0] is EvaluationOutcome.ACCEPTED

    def test_a_single_option_distribution_leads_by_its_whole_probability(
        self,
    ) -> None:
        """No runner-up means a runner-up of 0.0."""
        provider = FakeProvider("billing", {"billing": 0.72})

        assert _only_rung(_evaluate(provider))[0] is EvaluationOutcome.ACCEPTED


class TestTheSelfAssessmentIsNeverRead:
    """AC-11: the provider's own scalar cannot move the decision either way."""

    def test_full_self_assurance_does_not_lift_a_weak_proposal(self) -> None:
        provider = FakeProvider(
            "returns", {"returns": 0.54, "shipping": 0.46}, confidence=1.0
        )

        assert _only_rung(_evaluate(provider))[0] is EvaluationOutcome.FAILED

    def test_no_self_assurance_does_not_sink_a_clear_proposal(self) -> None:
        provider = FakeProvider(
            "shipping", {"shipping": 0.80, "returns": 0.40}, confidence=0.0
        )

        assert _only_rung(_evaluate(provider))[0] is EvaluationOutcome.ACCEPTED


class TestWhatTheProviderIsAsked:
    def test_the_request_carries_the_declared_decision_and_the_state(self) -> None:
        provider = FakeProvider("shipping", {"shipping": 0.9})
        decision = ChoiceDecision(
            field="route",
            instructions="Route it.",
            options=_OPTIONS,
            state=FromStep("intake"),
            accept_at=0.7,
            model="m-2",
        )

        _evaluate(provider, decision=decision)

        (request,) = provider.asked
        assert request == ChoiceRequest(
            state=_TICKET, instructions="Route it.", options=_OPTIONS, model="m-2"
        )

    def test_a_structured_state_is_sent_as_sorted_json(self) -> None:
        provider = FakeProvider("shipping", {"shipping": 0.9})

        _evaluate(
            provider,
            workflow_context={"intake": {"subject": "parcel", "body": _TICKET}},
        )

        assert provider.asked[0].state == (
            '{"body": "Where is my parcel? It was due on Monday.", "subject": "parcel"}'
        )


class TestFailuresAreFailedRungs:
    @pytest.mark.parametrize("kind", list(DecisionFailure), ids=lambda k: k.value)
    def test_each_provider_failure_kind(self, kind: DecisionFailure) -> None:
        error = DecisionUnavailableError(kind=kind, provider="fake", detail="nope")

        outcome = _evaluate(FakeProvider(error=error))

        rung, detail = _only_rung(outcome)
        assert rung is EvaluationOutcome.FAILED
        assert kind.value in detail
        assert detail == str(error)
        assert outcome.blocked_reason == f"decision: {error}"

    def test_a_missing_state_step(self) -> None:
        provider = FakeProvider("shipping", {"shipping": 0.9})

        rung, detail = _only_rung(_evaluate(provider, workflow_context={"other": 1}))

        assert rung is EvaluationOutcome.FAILED
        assert "'intake'" in detail
        assert provider.asked == []

    def test_no_distribution(self) -> None:
        rung, detail = _only_rung(_evaluate(FakeProvider("shipping", None)))

        assert rung is EvaluationOutcome.FAILED
        assert "no distribution" in detail

    def test_a_proposal_its_distribution_does_not_cover(self) -> None:
        provider = FakeProvider("returns", {"shipping": 0.9, "billing": 0.1})

        rung, detail = _only_rung(_evaluate(provider))

        assert rung is EvaluationOutcome.FAILED
        assert "'returns', which its distribution does not cover" in detail

    def test_a_gate_with_no_decision_declared(self) -> None:
        rung, detail = _only_rung(
            _evaluate(FakeProvider("shipping", {"shipping": 0.9}), decision=None)
        )

        assert (rung, detail) == (
            EvaluationOutcome.FAILED,
            "gate has no decision declared",
        )


class TestTheRungEvidence:
    """What the decision rung records beside its verdict, read off the rung."""

    def _evidence(self, provider: FakeProvider) -> Mapping[str, Any] | None:
        outcome = _evaluate(provider)
        return outcome.rungs[0][1].evidence

    def test_an_accepted_proposal_records_an_accepted_verdict(self) -> None:
        provider = FakeProvider(
            "shipping", {"shipping": 0.80, "returns": 0.40, "billing": 0.10}
        )

        evidence = self._evidence(provider)

        assert evidence is not None
        assert evidence["verdict"] == "accepted"
        assert evidence["proposal"] == "shipping"
        assert evidence["distribution"] == {
            "shipping": 0.80,
            "returns": 0.40,
            "billing": 0.10,
        }
        assert evidence["field"] == "route"
        assert evidence["failure"] is None

    def test_tokens_are_recorded_as_the_provenance_reported_them(self) -> None:
        provider = FakeProvider(
            "shipping", {"shipping": 0.9}, input_tokens=120, output_tokens=8
        )

        evidence = self._evidence(provider)

        assert evidence is not None
        assert evidence["input_tokens"] == 120
        assert evidence["output_tokens"] == 8

    def test_a_below_threshold_proposal_records_its_numbers(self) -> None:
        provider = FakeProvider(
            "returns", {"returns": 0.54, "shipping": 0.46, "billing": 0.00}
        )

        evidence = self._evidence(provider)

        assert evidence is not None
        assert evidence["verdict"] == "below_threshold"
        assert evidence["probability"] == pytest.approx(0.54)
        assert evidence["margin"] == pytest.approx(0.08)

    def test_a_self_assessment_never_moves_the_verdict(self) -> None:
        """AC-7: the provider's own scalar is recorded, never read."""
        below = self._evidence(
            FakeProvider("returns", {"returns": 0.54, "shipping": 0.46}, confidence=1.0)
        )
        above = self._evidence(
            FakeProvider(
                "shipping", {"shipping": 0.80, "returns": 0.40}, confidence=0.0
            )
        )

        assert below is not None and above is not None
        assert below["verdict"] == "below_threshold"
        assert below["confidence"] == 1.0
        assert above["verdict"] == "accepted"
        assert above["confidence"] == 0.0

    def test_a_rate_limited_provider_records_its_failure(self) -> None:
        provider = FakeProvider(
            error=DecisionUnavailableError(
                kind=DecisionFailure.RATE_LIMITED,
                provider="fake",
                status=429,
                retry_after=19014.0,
                detail="Rate limit exceeded",
            )
        )

        evidence = self._evidence(provider)

        assert evidence is not None
        assert evidence["verdict"] == "provider_failed"
        assert evidence["failure"] == {
            "kind": "rate_limited",
            "status": 429,
            "retry_after": 19014.0,
        }
        assert evidence["latency_seconds"] >= 0

    def test_a_missing_distribution_records_no_distribution(self) -> None:
        evidence = self._evidence(FakeProvider("shipping", None))

        assert evidence is not None
        assert evidence["verdict"] == "no_distribution"
        assert evidence["distribution"] is None

    def test_an_uncovered_proposal_records_its_evidence(self) -> None:
        """C-3: the provider was called, so the rung is auditable whatever it
        returned — a proposal its own distribution does not cover included."""
        outcome = _evaluate(FakeProvider("returns", {"shipping": 0.9, "billing": 0.1}))

        ((name, evaluation, _),) = outcome.rungs
        assert name == "decision"
        assert evaluation.outcome is EvaluationOutcome.FAILED
        assert "does not cover" in evaluation.detail
        evidence = evaluation.evidence
        assert evidence is not None
        assert evidence["verdict"] == "uncovered_proposal"
        assert evidence["proposal"] == "returns"
        assert evidence["distribution"] == {"shipping": 0.9, "billing": 0.1}
        assert evidence["probability"] is None
        assert evidence["margin"] is None
        assert evidence["failure"] is None

    def test_a_missing_state_step_records_nothing(self) -> None:
        """The state check raises before any evidence can exist."""
        outcome = _evaluate(
            FakeProvider("shipping", {"shipping": 0.9}), workflow_context={"other": 1}
        )

        assert outcome.rungs[0][1].evidence is None


class TestShape:
    def test_the_fake_is_a_decision_provider(self) -> None:
        assert isinstance(FakeProvider(), DecisionProvider)

    def test_below_threshold_is_a_value_error(self) -> None:
        assert issubclass(DecisionBelowThresholdError, ValueError)
