"""Gate resolver protocol definition.

Defines the interface that gate strategy implementations must satisfy,
and provides the default ResolveResolver that constructs a model from
the config chain's resolved fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._gate._context import GateContext


@runtime_checkable
class GateResolver(Protocol):
    """Protocol for gate strategy implementations.

    Any class implementing this protocol can be registered as a gate
    strategy via ``app.register_gate_strategy()``.
    """

    def resolve(self, ctx: GateContext) -> BaseModel:
        """Attempt to resolve a gate's input model.

        Args:
            ctx: The gate context with model info and resolved fields.

        Returns:
            A fully populated BaseModel instance.

        Raises:
            Any exception to signal failure and advance to next strategy.
        """
        ...


class ResolveResolver:
    """Default gate resolver that constructs a model from resolved fields.

    This resolver attempts to build the target model using only the
    fields already resolved from the config chain. If the model cannot
    be constructed (e.g., required fields are missing), it raises a
    ValueError to signal failure.
    """

    def resolve(self, ctx: GateContext) -> BaseModel:
        """Resolve the gate model from the config chain's resolved fields.

        Args:
            ctx: The gate context with model info and resolved fields.

        Returns:
            A fully populated BaseModel instance built from resolved fields.

        Raises:
            ValueError: If the model cannot be constructed from resolved fields
                (e.g., required fields are still unresolved).
        """
        from pydantic import ValidationError

        if ctx.unresolved_fields:
            raise ValueError(
                f"Cannot resolve model {ctx.model_class.__name__} from config chain: "
                f"unresolved fields: {ctx.unresolved_fields}"
            )

        try:
            return ctx.model_class(**ctx.resolved_fields)
        except (ValidationError, TypeError) as exc:
            raise ValueError(
                f"Failed to construct {ctx.model_class.__name__} from "
                f"resolved fields: {exc}"
            ) from exc
