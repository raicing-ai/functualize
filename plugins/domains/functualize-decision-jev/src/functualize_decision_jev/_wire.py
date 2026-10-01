"""The Jev wire mapping — pure functions between the port's values and JSON.

Three functions and no I/O: ``build_request`` turns a ``ChoiceRequest`` into the
request body, ``parse_choice`` turns a ``200`` body into a ``DecisionResult``,
and ``failure_for`` turns any other status into a ``DecisionUnavailableError``.
Sending the body, the headers and the credential are the provider's business,
not this module's, so every rule here can be tested against measured bodies
without a network.

The service's response shape is a discriminated union keyed by ``type`` (a
``choice`` answer carries ``choice``, ``confidence`` and ``probabilities``; a
``noul`` answer carries none of them), so a ``200`` is never trusted to be the
shape that was asked for: every field is checked, and any mismatch is
``MALFORMED`` rather than a ``KeyError`` or a ``TypeError`` escaping into the
gate that asked.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionProvenance,
    DecisionResult,
    DecisionUnavailableError,
)

__all__ = ["QUESTION_ID", "build_request", "failure_for", "parse_choice"]

#: The one question id this adapter sends. ``answers`` is keyed by it.
QUESTION_ID = "decision"

_PROVIDER = "jev"
#: The longest body a failure quotes. The error clips again; this keeps the
#: rule visible where the body is read.
_DETAIL_LIMIT = 300


class _MalformedError(Exception):
    """A shape rule a ``200`` body broke; carries the rule, for ``detail``."""


def build_request(request: ChoiceRequest, *, model: str) -> dict[str, Any]:
    """The request body for one ``choice`` question.

    ``model`` is the provider's configured default; a model named on the
    request wins over it.
    """
    return {
        "model": request.model if request.model is not None else model,
        "state": request.state,
        "questions": {
            QUESTION_ID: {
                "type": "choice",
                "instructions": request.instructions,
                "criteria": dict(request.options),
            }
        },
    }


def parse_choice(
    payload: Mapping[str, Any],
    request: ChoiceRequest,
    *,
    requested_model: str,
    latency_seconds: float,
) -> DecisionResult[str]:
    """A ``200`` body as a ``DecisionResult``, or ``MALFORMED``.

    Raises nothing but ``DecisionUnavailableError``: a body that breaks any
    shape rule, or carries a probability outside ``[0, 1]``, is reported with
    ``status=200`` and the rule it broke as ``detail``.
    """
    try:
        return _parse_choice(
            payload,
            request,
            requested_model=requested_model,
            latency_seconds=latency_seconds,
        )
    except _MalformedError as broken:
        detail = str(broken)
    except ValueError as out_of_range:
        detail = f"answer is out of range: {out_of_range}"
    raise DecisionUnavailableError(
        kind=DecisionFailure.MALFORMED,
        provider=_PROVIDER,
        status=200,
        detail=detail,
    )


def failure_for(
    status: int, body: str, headers: Mapping[str, str]
) -> DecisionUnavailableError:
    """The failure a non-``200`` response stands for.

    ``429`` is ``RATE_LIMITED`` and carries the service's ``Retry-After`` as
    sent; every other status is ``REFUSED``. The body is quoted, clipped, as
    the detail — refusal bodies come in several JSON shapes and one plain-text
    one, and a person reading a blocked gate needs whichever it was.
    """
    detail = body[:_DETAIL_LIMIT]
    if status == 429:
        return DecisionUnavailableError(
            kind=DecisionFailure.RATE_LIMITED,
            provider=_PROVIDER,
            status=status,
            retry_after=_retry_after(headers),
            detail=detail,
        )
    return DecisionUnavailableError(
        kind=DecisionFailure.REFUSED,
        provider=_PROVIDER,
        status=status,
        detail=detail,
    )


def _parse_choice(
    payload: Mapping[str, Any],
    request: ChoiceRequest,
    *,
    requested_model: str,
    latency_seconds: float,
) -> DecisionResult[str]:
    if not isinstance(payload, Mapping):
        raise _MalformedError(f"body is {type(payload).__name__}, expected an object")
    answered_by = payload.get("model")
    if not isinstance(answered_by, str):
        raise _MalformedError("body has no string 'model'")
    answers = _mapping(payload.get("answers"), "'answers'")
    answer = _mapping(answers.get(QUESTION_ID), f"'answers.{QUESTION_ID}'")

    kind = answer.get("type")
    if kind != "choice":
        raise _MalformedError(f"answer type is {kind!r}, expected 'choice'")
    value = answer.get("choice")
    if not isinstance(value, str) or value not in request.options:
        raise _MalformedError(
            f"answer choice {value!r} is not one of the options "
            f"{sorted(request.options)}"
        )

    raw_distribution = _mapping(answer.get("probabilities"), "'probabilities'")
    distribution: dict[str, float] = {}
    for option, probability in raw_distribution.items():
        if not isinstance(option, str):
            raise _MalformedError(f"'probabilities' key {option!r} is not a string")
        distribution[option] = _number(probability, f"'probabilities.{option}'")
    raw_confidence = answer.get("confidence")
    confidence = (
        None if raw_confidence is None else _number(raw_confidence, "'confidence'")
    )

    usage = payload.get("usage")
    if usage is None:
        usage = {}
    usage = _mapping(usage, "'usage'")

    return DecisionResult(
        value=value,
        provider=_PROVIDER,
        model=answered_by,
        provenance=DecisionProvenance(
            requested_model=requested_model,
            latency_seconds=latency_seconds,
            input_tokens=_tokens(usage, "input_tokens"),
            output_tokens=_tokens(usage, "output_tokens"),
        ),
        distribution=distribution,
        confidence=confidence,
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _MalformedError(f"{name} is missing or not an object")
    return value


def _number(value: object, name: str) -> float:
    # `bool` is an `int` subclass, and `true` is not a probability.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _MalformedError(f"{name} is {value!r}, expected a number")
    return float(value)


def _tokens(usage: Mapping[str, Any], key: str) -> int | None:
    count = usage.get(key)
    if count is None:
        return None
    if isinstance(count, bool) or not isinstance(count, int):
        raise _MalformedError(f"'usage.{key}' is {count!r}, expected an integer")
    return count


def _retry_after(headers: Mapping[str, str]) -> float | None:
    # Header names are case-insensitive on the wire; the transport may or may
    # not have normalised them, so this does not rely on it.
    raw = next(
        (value for name, value in headers.items() if name.lower() == "retry-after"),
        None,
    )
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) else None
