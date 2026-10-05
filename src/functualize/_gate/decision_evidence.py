"""The evidence a decision rung records beside its verdict.

This module exists separately from ``decision_strategy`` because the rule
module must never name the provider's own scalar (ADR-030 point 3): an
acceptance that module could raise by asserting certainty would not be the
workflow's rule. The evidence is the opposite contract — a faithful record
of everything the provider reported, that scalar included — so the builder
lives here, where the word can be written, and the rule module cannot even
spell it.

The mapping is flat and JSON-safe, tagged with ``SCHEMA``, and carries the
declared rule's digest so a reader can tell which rule produced the verdict
without loading the declaration.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from functualize._types.decision import decision_digest

if TYPE_CHECKING:
    from functualize._types.decision import ChoiceDecision, DecisionResult
    from functualize._types.errors import DecisionUnavailableError

__all__ = ["SCHEMA", "build_decision_evidence"]

#: The evidence's own version tag — the first key a reader checks.
SCHEMA = "decision-evidence/1"


def build_decision_evidence(
    decide: ChoiceDecision,
    *,
    state: str,
    latency_seconds: float,
    result: DecisionResult[str] | None = None,
    error: DecisionUnavailableError | None = None,
    probability: float | None = None,
    margin: float | None = None,
    verdict: str,
) -> dict[str, Any]:
    """One decision rung's evidence, as its ``CandidateEvaluation`` carries it.

    Exactly the keys the schema names, in one flat mapping: what was decided
    (``field``), what it was decided on (``state``), under which rule
    (``rule``), by whom (``provider``/``model``), what they proposed and
    reported (``proposal``/``distribution`` and the provider's own scalar),
    the numbers the rule read (``probability``/``margin``), how it ended
    (``verdict``/``failure``), and what it cost (``latency_seconds``, tokens).
    A provider failure carries the error's facts with no model, proposal or
    distribution to invent.
    """
    if result is not None:
        provider = result.provider
    elif error is not None:
        provider = error.provider
    else:
        raise ValueError(
            "decision evidence carries a result or a failure; build it with one"
        )
    return {
        "schema": SCHEMA,
        "field": decide.field,
        "state": {
            "step": decide.state.name,
            "sha256": hashlib.sha256(state.encode("utf-8")).hexdigest(),
            "chars": len(state),
        },
        "rule": {
            "digest": decision_digest(decide),
            "accept_at": float(decide.accept_at),
            "min_margin": float(decide.min_margin),
            "fallback": decide.fallback,
        },
        "provider": provider,
        "model": result.model if result is not None else None,
        "requested_model": (
            result.provenance.requested_model if result is not None else decide.model
        ),
        "proposal": result.value if result is not None else None,
        "distribution": (
            dict(result.distribution)
            if result is not None and result.distribution is not None
            else None
        ),
        "confidence": result.confidence if result is not None else None,
        "probability": probability,
        "margin": margin,
        "verdict": verdict,
        "failure": (
            None
            if error is None
            else {
                "kind": error.kind.value,
                "status": error.status,
                "retry_after": error.retry_after,
            }
        ),
        "latency_seconds": latency_seconds,
        "input_tokens": (
            result.provenance.input_tokens if result is not None else None
        ),
        "output_tokens": (
            result.provenance.output_tokens if result is not None else None
        ),
    }
