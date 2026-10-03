"""Gate context dataclass for gate resolution.

Carries all information a gate resolver needs to produce a resolved
model instance, and the write-once evidence sink a ladder rung fills
while it runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._types.decision import ChoiceDecision


class RungEvidence:
    """Write-once collector one ladder rung fills while it runs.

    The registry hands each rung its own sink through
    ``GateContext.evidence``; the rung records what it saw, at most once —
    a second ``record`` raises rather than overwriting, because a rung that
    changed its story after the fact would make the recorded ladder a
    narrative instead of a record. The registry reads ``value`` when the
    rung returns or raises, and the evidence becomes part of that rung's
    ``CandidateEvaluation``.
    """

    def __init__(self) -> None:
        self._value: Mapping[str, Any] | None = None

    def record(self, evidence: Mapping[str, Any]) -> None:
        if self._value is not None:
            raise RuntimeError("a rung records its evidence once")
        self._value = dict(evidence)

    @property
    def value(self) -> Mapping[str, Any] | None:
        return self._value


@dataclass(frozen=True)
class GateContext:
    """Information provided to a gate resolver strategy.

    Attributes:
        model_class: The Pydantic BaseModel subclass to resolve.
        resolved_fields: Fields already resolved from the config chain.
        unresolved_fields: Field names with no resolved value.
        all_fields: Complete list of all field names in the model.
        force_gate: Whether strategy dispatch was forced.
        workflow_context: Current workflow execution state.
        decision: The decision the gate declares (``Gate.decide``), for the
            ``decision`` strategy; ``None`` for every other gate.
        evidence: This rung's write-once evidence sink. ``None`` only where
            no rung is running — a reader projecting a context, or a caller
            building one by hand; the registry always hands a rung a live
            sink, and what the rung records there lands on its candidate.
    """

    model_class: type[BaseModel]
    resolved_fields: dict[str, Any]
    unresolved_fields: list[str]
    all_fields: list[str]
    force_gate: bool
    workflow_context: dict[str, Any] = field(default_factory=dict)
    decision: ChoiceDecision | None = None
    evidence: RungEvidence | None = None
