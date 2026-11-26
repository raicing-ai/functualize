"""Cached resolution instructions read from admitted parameter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from functualize._types.parameter_contract import Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._types.parameter_contract import ParameterContract


@dataclass(frozen=True)
class ParamBinding:
    """The source declared for one parameter, without another kind decision."""

    name: str
    annotation: str | None
    qualifier: str | None
    source: str
    has_default: bool
    is_optional: bool
    from_job: str | None = None


@dataclass(frozen=True)
class ResolutionPlan:
    """Resolution instructions cached by callable reference at the engine."""

    params: tuple[ParamBinding, ...]


def build_resolution_plan(contracts: Sequence[ParameterContract]) -> ResolutionPlan:
    """Project the contract's injection source into resolution instructions."""
    bindings: list[ParamBinding] = []
    for contract in contracts:
        injection = contract.injection
        source = "skip"
        annotation = None
        if contract.verdict is Verdict.INJECTED and injection is not None:
            if injection.from_job is not None:
                source = "from_job"
            elif injection.capability is not None:
                source = (
                    "runcontext"
                    if injection.capability == "RunContext"
                    else "capability"
                )
                annotation = injection.capability
            elif injection.provider_type is not None:
                source = "di"
                annotation = injection.provider_type
        bindings.append(
            ParamBinding(
                name=contract.name,
                annotation=annotation,
                qualifier=injection.qualifier if injection else None,
                source=source,
                has_default=not contract.required,
                is_optional=bool(contract.shape and contract.shape.optional),
                from_job=injection.from_job if injection else None,
            )
        )
    return ResolutionPlan(params=tuple(bindings))
