"""The Jev wire mapping, pinned against measured bodies.

Every body below is copied verbatim from
``contributor/reference/jev-system-one-capability-matrix.md`` and each test
names the row it copies, so a change of shape on the service shows up as a
disagreement between this file and that record, not as a guess. Two rows
record a *field set* rather than a body — A4 (a ``choice`` answer) and D (the
usage block) — and the values filled into those fields here are illustrative;
the field names are the row's.

Nothing here touches a network: the three functions are pure.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from functualize_decision_jev._wire import (
    QUESTION_ID,
    build_request,
    failure_for,
    parse_choice,
)

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionResult,
    DecisionUnavailableError,
)

_OPTIONS = {
    "billing": "a question about an invoice or a charge",
    "returns": "the customer wants to send something back",
    "shipping": "where a parcel is, or when it arrives",
}
_REQUEST = ChoiceRequest(
    state="Where is my parcel? It was due on Monday.",
    instructions="Route the ticket to the team that owns it.",
    options=_OPTIONS,
)

#: Row A3 — a `noul` answer, verbatim.
_A3_NOUL_ANSWER: dict[str, Any] = {"noul": 0.02, "type": "noul"}


def _a4_choice_answer(**overrides: Any) -> dict[str, Any]:
    """Row A4's field set, `{"choice", "confidence", "probabilities", "type"}`."""
    answer: dict[str, Any] = {
        "choice": "shipping",
        "confidence": 0.83,
        "probabilities": {"billing": 0.05, "returns": 0.07, "shipping": 0.88},
        "type": "choice",
    }
    answer.update(overrides)
    return answer


def _body(answer: object, **envelope: Any) -> dict[str, Any]:
    """Row A2's envelope, `["answers", "model", "usage"]`.

    The usage block is row D's `choice, 3 criteria` point, 332 / 38.
    """
    body: dict[str, Any] = {
        "answers": {QUESTION_ID: answer},
        "model": "jev-1.13-free",
        "usage": {"input_tokens": 332, "output_tokens": 38},
    }
    body.update(envelope)
    return body


def _parse(body: object) -> DecisionResult[str]:
    return parse_choice(
        body,  # type: ignore[arg-type]
        _REQUEST,
        requested_model="jev-1.13-free",
        latency_seconds=1.25,
    )


def _malformed(body: object) -> DecisionUnavailableError:
    with pytest.raises(DecisionUnavailableError) as raised:
        _parse(body)
    error = raised.value
    assert error.kind is DecisionFailure.MALFORMED
    assert error.provider == "jev"
    assert error.status == 200
    return error


@pytest.fixture(autouse=True)
def _never_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-5: no case waits, whatever the status."""

    def refuse(seconds: float) -> None:
        raise AssertionError(f"the wire mapping slept for {seconds} s")

    monkeypatch.setattr(time, "sleep", refuse)


class TestBuildRequest:
    def test_the_request_for_three_options(self) -> None:
        """AC-3, row A1: `{model, state, questions}`, `criteria` an object."""
        assert build_request(_REQUEST, model="jev-1.13-free") == {
            "model": "jev-1.13-free",
            "state": "Where is my parcel? It was due on Monday.",
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": "Route the ticket to the team that owns it.",
                    "criteria": {
                        "billing": "a question about an invoice or a charge",
                        "returns": "the customer wants to send something back",
                        "shipping": "where a parcel is, or when it arrives",
                    },
                }
            },
        }

    def test_a_model_named_on_the_request_wins(self) -> None:
        request = ChoiceRequest(
            state="s", instructions="i", options=_OPTIONS, model="jev-1.13"
        )

        assert build_request(request, model="jev-1.13-free")["model"] == "jev-1.13"

    def test_criteria_is_a_copy_not_the_callers_mapping(self) -> None:
        body = build_request(_REQUEST, model="m")

        criteria = body["questions"]["decision"]["criteria"]
        assert type(criteria) is dict
        assert criteria is not _REQUEST.options


class TestParseChoice:
    def test_a4_choice_answer_becomes_a_result(self) -> None:
        """Row A4: the four fields map onto the result; row A2's envelope too."""
        result = _parse(_body(_a4_choice_answer()))

        assert result.value == "shipping"
        assert result.provider == "jev"
        assert result.model == "jev-1.13-free"
        assert result.distribution == {
            "billing": 0.05,
            "returns": 0.07,
            "shipping": 0.88,
        }
        assert result.confidence == 0.83
        assert result.provenance.requested_model == "jev-1.13-free"
        assert result.provenance.latency_seconds == 1.25
        assert (result.provenance.input_tokens, result.provenance.output_tokens) == (
            332,
            38,
        )

    def test_probabilities_in_two_key_orders_give_equal_results(self) -> None:
        """B3: `probabilities` order is not the request's and is not stable."""
        forward = _parse(
            _body(
                _a4_choice_answer(
                    probabilities={"billing": 0.05, "returns": 0.07, "shipping": 0.88}
                )
            )
        )
        backward = _parse(
            _body(
                _a4_choice_answer(
                    probabilities={"shipping": 0.88, "returns": 0.07, "billing": 0.05}
                )
            )
        )

        assert forward == backward

    def test_absent_confidence_is_none_not_invented(self) -> None:
        answer = _a4_choice_answer()
        del answer["confidence"]

        assert _parse(_body(answer)).confidence is None

    def test_absent_usage_leaves_the_token_counts_none(self) -> None:
        body = _body(_a4_choice_answer())
        del body["usage"]

        provenance = _parse(body).provenance
        assert (provenance.input_tokens, provenance.output_tokens) == (None, None)

    def test_a3_noul_answer_is_malformed(self) -> None:
        """AC-4, row A3: a `200` answering with the wrong type."""
        error = _malformed(_body(_A3_NOUL_ANSWER))

        assert error.detail == "answer type is 'noul', expected 'choice'"

    def test_a_choice_outside_the_options_is_malformed(self) -> None:
        """AC-4: the service may not answer with an option nobody offered."""
        error = _malformed(_body(_a4_choice_answer(choice="refund")))

        assert "'refund' is not one of the options" in error.detail

    def test_missing_probabilities_is_malformed(self) -> None:
        """AC-4: the distribution is what the gate decides on; it is required."""
        answer = _a4_choice_answer()
        del answer["probabilities"]

        error = _malformed(_body(answer))

        assert "'probabilities' is missing" in error.detail

    @pytest.mark.parametrize(
        ("body", "rule"),
        [
            pytest.param({"model": "m", "usage": {}}, "'answers'", id="no-answers"),
            pytest.param(
                {"answers": {}, "model": "m"}, "'answers.decision'", id="no-decision"
            ),
            pytest.param(
                {"answers": {"decision": _a4_choice_answer()}},
                "'model'",
                id="no-model",
            ),
            pytest.param(["not", "an", "object"], "expected an object", id="list"),
            pytest.param(
                _body(_a4_choice_answer(probabilities={"shipping": "0.88"})),
                "'probabilities.shipping'",
                id="string-probability",
            ),
            pytest.param(
                _body(_a4_choice_answer(confidence=True)),
                "'confidence'",
                id="boolean-confidence",
            ),
            pytest.param(
                _body(_a4_choice_answer(), usage={"input_tokens": "332"}),
                "'usage.input_tokens'",
                id="string-tokens",
            ),
            pytest.param(
                _body(_a4_choice_answer(), usage=[332, 38]),
                "'usage'",
                id="usage-not-an-object",
            ),
        ],
    )
    def test_a_shape_violation_is_malformed(self, body: object, rule: str) -> None:
        """B-9: a `200` that is not the asked-for shape is MALFORMED."""
        assert rule in _malformed(body).detail

    def test_a_probability_out_of_range_is_malformed_not_value_error(self) -> None:
        """The result's range check is converted, never raised as ValueError."""
        error = _malformed(
            _body(
                _a4_choice_answer(
                    probabilities={"billing": 0.0, "returns": 0.0, "shipping": 1.2}
                )
            )
        )

        assert "out of range" in error.detail


class TestFailureFor:
    @pytest.mark.parametrize(
        ("status", "body"),
        [
            pytest.param(
                422,
                '{"detail":[{"type":"missing","loc":["body","questions"],"msg":"Field required", …}]}',
                id="E1",
            ),
            pytest.param(
                400,
                '{"detail":{"error_type":"api_usage_error","message":"Invalid request."}}',
                id="E4",
            ),
            pytest.param(
                401,
                '{"type":"error","error":{"type":"ModelError","message":"Model  is not supported"}}',
                id="E8",
            ),
            pytest.param(
                402,
                '{"error":{"type":"server_error","message":"Upstream request failed: Insufficient account funds"}}',
                id="E10",
            ),
            pytest.param(
                401,
                '{"type":"error","error":{"type":"AuthError","message":"Invalid API key."}}',
                id="E11",
            ),
            pytest.param(403, "error code: 1010", id="E12-plain-text"),
        ],
    )
    def test_each_e_row_is_refused(self, status: int, body: str) -> None:
        """AC-5, row E: every measured refusal status maps to REFUSED."""
        error = failure_for(status, body, {})

        assert error.kind is DecisionFailure.REFUSED
        assert error.provider == "jev"
        assert error.status == status
        assert error.retry_after is None
        assert error.detail == body

    def test_the_429_carries_retry_after(self) -> None:
        """AC-5, row F4: `429 FreeUsageLimitError` with `Retry-After: 19014`."""
        error = failure_for(
            429,
            '{"type":"error","error":{"type":"FreeUsageLimitError",'
            '"message":"Rate limit exceeded. Please try again later."}}',
            {"Retry-After": "19014"},
        )

        assert error.kind is DecisionFailure.RATE_LIMITED
        assert error.status == 429
        assert error.retry_after == 19014.0
        assert str(error).startswith("jev rate_limited HTTP 429 retry after 19014 s: ")

    def test_retry_after_is_found_whatever_its_case(self) -> None:
        assert failure_for(429, "", {"retry-after": "7"}).retry_after == 7.0

    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param({}, id="absent"),
            pytest.param({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, id="date"),
            pytest.param({"Retry-After": "nan"}, id="nan"),
        ],
    )
    def test_retry_after_that_is_not_a_number_is_none(
        self, headers: dict[str, str]
    ) -> None:
        error = failure_for(429, "Rate limit exceeded", headers)

        assert error.kind is DecisionFailure.RATE_LIMITED
        assert error.retry_after is None

    def test_an_unlisted_status_is_refused(self) -> None:
        error = failure_for(503, "upstream unavailable", {})

        assert (error.kind, error.status) == (DecisionFailure.REFUSED, 503)

    def test_the_body_is_clipped_to_300(self) -> None:
        assert failure_for(400, "x" * 1000, {}).detail == "x" * 300
