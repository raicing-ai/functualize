"""Gate context dataclass for gate resolution.

Carries all information a gate resolver needs to produce a resolved
model instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel


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
    """

    model_class: type[BaseModel]
    resolved_fields: dict[str, Any]
    unresolved_fields: list[str]
    all_fields: list[str]
    force_gate: bool
    workflow_context: dict[str, Any] = field(default_factory=dict)
