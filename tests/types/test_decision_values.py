"""The provider-neutral decision vocabulary: values, the port, and its failure.

What is pinned here is shape, not behaviour — ``_types/decision.py`` holds no
logic beyond range checks — so each test names the rule it holds: a result is a
candidate with no verdict on it, its distribution compares as a mapping, a
request offers a real choice, and a failure renders one exact string, because
that string is what a blocked gate later shows a person.
"""

from __future__ import annotations

import copy
import dataclasses
import pickle
from types import MappingProxyType

import pytest

from functualize._types.decision import (
    ChoiceDecision,
    ChoiceRequest,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
    decision_digest,
    decision_shape,
)
from functualize._types.errors import DecisionFailure, DecisionUnavailableError
from functualize._types.from_job import FromStep

_OPTIONS = {"billing": "an invoice question", "returns": "send it back"}


def _provenance() -> DecisionProvenance:
    return DecisionProvenance(requested_model="m-1", latency_seconds=0.25)


def _decision(**overrides: object) -> ChoiceDecision:
    arguments: dict[str, object] = {
        "field": "route",
        "instructions": "Route the ticket.",
        "options": _OPTIONS,
        "state": FromStep("intake"),
        "accept_at": 0.70,
    }
    arguments.update(overrides)
    return ChoiceDecision(**arguments)  # type: ignore[arg-type]


class TestDecisionResult:
    def test_a_result_with_a_distribution_and_a_confidence(self) -> None:
        """AC-1, first shape: both uncertainty fields reported."""
        result = DecisionResult(
            value="billing",
            provider="p",
            model="m-1",
            provenance=DecisionProvenance(
                requested_model="m-1",
                latency_seconds=0.25,
                input_tokens=120,
                output_tokens=8,
            ),
            distribution={"billing": 0.8, "returns": 0.2},
            confidence=0.9,
        )

        assert result.value == "billing"
        assert result.distribution == {"billing": 0.8, "returns": 0.2}
        assert result.confidence == 0.9
        assert result.provenance.input_tokens == 120

    def test_a_result_with_neither_distribution_nor_confidence(self) -> None:
        """AC-1, second shape: a provider that reports no uncertainty."""
        result = DecisionResult(
            value="returns", provider="p", model="m-1", provenance=_provenance()
        )

        assert result.distribution is None
        assert result.confidence is None
        assert result.provenance.input_tokens is None
        assert result.provenance.output_tokens is None

    def test_key_order_of_the_distribution_does_not_affect_equality(self) -> None:
        """AC-2: the distribution is a mapping, and its order means nothing."""
        forward = DecisionResult(
            value="billing",
            provider="p",
            model="m-1",
            provenance=_provenance(),
            distribution={"billing": 0.7, "returns": 0.3},
        )
        backward = DecisionResult(
            value="billing",
            provider="p",
            model="m-1",
            provenance=_provenance(),
            distribution={"returns": 0.3, "billing": 0.7},
        )

        assert forward == backward

    def test_the_distribution_is_a_read_only_copy(self) -> None:
        given = {"billing": 0.7, "returns": 0.3}
        result = DecisionResult(
            value="billing",
            provider="p",
            model="m-1",
            provenance=_provenance(),
            distribution=given,
        )

        given["billing"] = 0.0

        assert isinstance(result.distribution, MappingProxyType)
        assert result.distribution == {"billing": 0.7, "returns": 0.3}

    def test_a_probability_above_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            DecisionResult(
                value="billing",
                provider="p",
                model="m-1",
                provenance=_provenance(),
                distribution={"billing": 1.2, "returns": 0.0},
            )

    def test_a_negative_confidence_is_refused(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            DecisionResult(
                value="billing",
                provider="p",
                model="m-1",
                provenance=_provenance(),
                confidence=-0.1,
            )

    def test_a_distribution_need_not_sum_to_one(self) -> None:
        """The wire reports two decimals, so 0.33 x 3 is a faithful record."""
        result = DecisionResult(
            value="a",
            provider="p",
            model="m-1",
            provenance=_provenance(),
            distribution={"a": 0.33, "b": 0.33, "c": 0.33},
        )

        assert sum(result.distribution.values()) == pytest.approx(0.99)  # type: ignore[union-attr]

    def test_a_result_states_no_verdict(self) -> None:
        """Acceptance is the gate's to state, never the result's."""
        names = [field.name for field in dataclasses.fields(DecisionResult)]

        assert names == [
            "value",
            "provider",
            "model",
            "provenance",
            "distribution",
            "confidence",
        ]
        assert "accepted" not in names

    def test_a_result_is_frozen(self) -> None:
        result = DecisionResult(
            value="billing", provider="p", model="m-1", provenance=_provenance()
        )

        with pytest.raises(dataclasses.FrozenInstanceError):
            result.value = "returns"  # type: ignore[misc]


class TestChoiceRequest:
    def test_a_request_with_two_options(self) -> None:
        request = ChoiceRequest(state="s", instructions="i", options=_OPTIONS)

        assert request.options is _OPTIONS
        assert request.model is None

    def test_one_option_is_not_a_choice(self) -> None:
        with pytest.raises(ValueError, match="got 1"):
            ChoiceRequest(state="s", instructions="i", options={"only": "one"})

    def test_thirty_three_options_are_refused(self) -> None:
        options = {f"o{i}": f"meaning {i}" for i in range(33)}

        with pytest.raises(ValueError, match="got 33"):
            ChoiceRequest(state="s", instructions="i", options=options)

    def test_thirty_two_options_are_accepted(self) -> None:
        options = {f"o{i}": f"meaning {i}" for i in range(32)}

        assert (
            len(ChoiceRequest(state="s", instructions="i", options=options).options)
            == 32
        )

    def test_an_empty_option_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="empty string"):
            ChoiceRequest(
                state="s", instructions="i", options={"": "blank", "b": "bee"}
            )


class TestDecisionUnavailableError:
    def test_rate_limited_with_status_and_retry_after(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.RATE_LIMITED,
            provider="jev",
            status=429,
            retry_after=19014.0,
            detail="Rate limit exceeded",
        )

        assert (
            str(error)
            == "jev rate_limited HTTP 429 retry after 19014 s: Rate limit exceeded"
        )

    def test_rate_limited_without_retry_after(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.RATE_LIMITED,
            provider="jev",
            status=429,
            detail="Rate limit exceeded",
        )

        assert str(error) == "jev rate_limited HTTP 429: Rate limit exceeded"

    def test_not_configured_without_status(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.NOT_CONFIGURED,
            provider="jev",
            detail="OPENCODE_API_KEY is not set",
        )

        assert str(error) == "jev not_configured: OPENCODE_API_KEY is not set"

    def test_a_fractional_retry_after_is_rendered_as_given(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.RATE_LIMITED,
            provider="p",
            retry_after=1.5,
            detail="slow down",
        )

        assert str(error) == "p rate_limited retry after 1.5 s: slow down"

    def test_a_long_detail_is_stored_clipped_to_300(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.MALFORMED, provider="p", detail="x" * 400
        )

        assert error.detail == "x" * 300
        assert str(error) == "p malformed: " + "x" * 300

    def test_the_constructor_is_keyword_only(self) -> None:
        with pytest.raises(TypeError):
            DecisionUnavailableError(DecisionFailure.REFUSED, "p", "no")  # type: ignore[misc]

    def test_the_attributes_are_the_five_facts(self) -> None:
        error = DecisionUnavailableError(
            kind=DecisionFailure.UNREACHABLE,
            provider="p",
            status=503,
            detail="down",
        )

        assert (
            error.kind,
            error.provider,
            error.status,
            error.retry_after,
            error.detail,
        ) == (
            DecisionFailure.UNREACHABLE,
            "p",
            503,
            None,
            "down",
        )

    def test_the_failure_kinds_are_exactly_five(self) -> None:
        assert [kind.value for kind in DecisionFailure] == [
            "not_configured",
            "rate_limited",
            "refused",
            "unreachable",
            "malformed",
        ]

    @pytest.mark.parametrize(
        "round_trip",
        [copy.copy, lambda error: pickle.loads(pickle.dumps(error))],
        ids=["copy", "pickle"],
    )
    def test_it_survives_a_round_trip(self, round_trip: object) -> None:
        """A keyword-only constructor breaks the default exception reduce."""
        error = DecisionUnavailableError(
            kind=DecisionFailure.RATE_LIMITED,
            provider="p",
            status=429,
            retry_after=5.0,
            detail="wait",
        )

        rebuilt = round_trip(error)  # type: ignore[operator]

        assert str(rebuilt) == str(error)
        assert rebuilt.kind is DecisionFailure.RATE_LIMITED
        assert rebuilt.retry_after == 5.0


class TestChoiceDecisionFallback:
    def test_a_fallback_outside_the_options_is_refused(self) -> None:
        with pytest.raises(ValueError) as raised:
            _decision(fallback="shipping")

        message = str(raised.value)
        assert "not one of the options" in message
        assert "'billing'" in message and "'returns'" in message

    def test_no_fallback_is_the_default(self) -> None:
        assert _decision().fallback is None

    def test_two_decisions_differing_only_in_fallback_digest_differently(self) -> None:
        assert decision_digest(_decision(fallback="billing")) != decision_digest(
            _decision(fallback="returns")
        )

    def test_a_digest_is_a_sha256_prefix_and_64_hex_digits(self) -> None:
        digest = decision_digest(_decision(fallback="billing"))

        assert digest.startswith("sha256:")
        assert len(digest) == 71


class TestDecisionShape:
    def test_a_decision_without_a_fallback_projects_no_fallback_key(self) -> None:
        shape = decision_shape(_decision())

        assert "fallback" not in shape
        assert shape["field"] == "route"
        assert shape["state"] == "intake"

    def test_a_declared_fallback_joins_the_shape(self) -> None:
        assert decision_shape(_decision(fallback="billing"))["fallback"] == "billing"


class TestDecisionProvider:
    def test_a_two_member_fake_is_a_provider(self) -> None:
        class FakeProvider:
            @property
            def name(self) -> str:
                return "fake"

            def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
                return DecisionResult(
                    value=next(iter(request.options)),
                    provider=self.name,
                    model="m-1",
                    provenance=_provenance(),
                )

        provider = FakeProvider()

        assert isinstance(provider, DecisionProvider)
        assert (
            provider.choose(
                ChoiceRequest(state="s", instructions="i", options=_OPTIONS)
            ).value
            == "billing"
        )

    def test_an_object_without_choose_is_not_a_provider(self) -> None:
        class NameOnly:
            name = "half"

        assert not isinstance(NameOnly(), DecisionProvider)
