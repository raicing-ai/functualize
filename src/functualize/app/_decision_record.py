"""One routed run, read back as a single record.

A projection of the candidates a gate request collected — nothing is
re-evaluated and nothing is re-decided; outcomes are read exactly as they
were recorded at submission. The reader asks the question an operator asks
of a routed gate: who took it, on which route, and when the declared
fallback took it, why the decision did not.

``source`` is read as the ``GateCandidate`` docstring documents it —
recorded for attribution, never parsed for control — and the one
distinction this reader draws is between the ``strategy:decision`` rung
and the ``strategy:resolve`` rung that accepted, which is what separates a
decision from a fallback.

TRANSITIONAL(FUN-21): storage is read through ``gate_requests``, as
``_resolution_view`` reads it — the document gate record, not the durable
table this projection eventually deserves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._primitives import gate_requests
from functualize._types.gate_resolution import EvaluationOutcome

if TYPE_CHECKING:
    from functualize._types.gate_resolution import GateCandidate

__all__ = ["decision_record"]

#: The rung sources this reader distinguishes, as the ladder records them.
_DECISION_SOURCE = "strategy:decision"
_RESOLVE_SOURCE = "strategy:resolve"


def decision_record(store: Any, scope_id: str, gate: str) -> dict[str, Any] | None:
    """Read one gate's routing decision as a single record. **Provisional.**

    Returns ``None`` when the gate has no record. Otherwise one mapping:
    ``gate`` and ``request_id`` name what was read; ``decided_by`` says who
    took it (``"decision"``, ``"fallback"``, ``"person"``, or ``None`` while
    unanswered); ``route`` is the accepted payload's value for the decided
    field when the evidence names one, else the payload's single value;
    ``reason`` carries the decision rung's detail when the fallback took
    over; ``evidence`` is the decision rung's recorded evidence, or ``None``.
    """
    record = store.get_gate(scope_id, gate)
    if record is None:
        return None
    lease = store.get_lease(scope_id)
    request = gate_requests.request_for(
        scope_id, gate, record, lease.generation if lease else 0
    )
    candidates = gate_requests.candidates_for(record)

    decision = next(
        (
            candidate
            for candidate in reversed(candidates)
            if candidate.source == _DECISION_SOURCE
        ),
        None,
    )
    accepted: GateCandidate | None = next(
        (
            candidate
            for candidate in candidates
            if candidate.evaluation.outcome is EvaluationOutcome.ACCEPTED
        ),
        None,
    )

    decided_by: str | None = None
    if accepted is not None:
        if accepted.source == _DECISION_SOURCE:
            decided_by = "decision"
        elif accepted.source == _RESOLVE_SOURCE:
            decided_by = "fallback"
        else:
            decided_by = "person"

    evidence = decision.evaluation.evidence if decision is not None else None

    route: Any = None
    if accepted is not None:
        if evidence is not None and "field" in evidence:
            payload = accepted.payload
            route = (
                payload.get(evidence["field"]) if isinstance(payload, dict) else None
            )
        elif isinstance(accepted.payload, dict) and len(accepted.payload) == 1:
            route = next(iter(accepted.payload.values()))

    reason: str | None = None
    if decided_by == "fallback" and decision is not None:
        reason = f"decision: {decision.evaluation.detail}"

    return {
        "gate": gate,
        "request_id": request.request_id,
        "route": route,
        "decided_by": decided_by,
        "fallback_used": decided_by == "fallback",
        "reason": reason,
        "evidence": dict(evidence) if evidence is not None else None,
    }
