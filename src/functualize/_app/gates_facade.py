"""Gate strategies, presets, and the resolution algorithm — `app.gates`.

Extracted from :class:`~functualize.app.core.FunctualizeApp`
(engine-sealed-construction/T9). Three members, one subject: who answers a gate,
what a named preset stands for, and the ladder that tries them in order.

`resolve_gate` is the only one a *surface* calls; the two registrations are what
a host or a plugin does at wiring time. They group because a preset is
meaningless without the strategies it names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._gate import GateResolver
    from functualize.app.core import FunctualizeApp

__all__ = ["GatesFacade"]


class GatesFacade:
    """`app.gates` — who answers a gate, and in what order."""

    __slots__ = ("_app",)

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def register_gate_strategy(self, name: str, resolver: GateResolver) -> None:
        """Register a gate resolution strategy by name.

        Args:
            name: Strategy identifier (1-64 characters).
            resolver: A GateResolver implementation instance.

        Raises:
            ValueError: If name length is outside [1, 64].
        """
        self._app._gate_registry.register_strategy(name, resolver)

    def register_gate_preset(self, name: str, strategies: list[str]) -> None:
        """Register an ordered fallback list of strategies under a preset name.

        Args:
            name: Preset identifier.
            strategies: Ordered list of strategy names (1-10 entries).

        Raises:
            ValueError: If strategies list length is outside [1, 10].
        """
        self._app._gate_registry.register_preset(name, strategies)

    def resolve_gate(
        self,
        model_class: type,
        *,
        force_gate: bool = False,
        gate_strategy: Any = None,
        resolved_fields: dict[str, Any] | None = None,
        workflow_context: dict[str, Any] | None = None,
        gate_name: str = "unnamed",
    ) -> Any:
        """Resolve a gate by applying the resolution algorithm."""
        from functualize._app.impl import resolve_gate

        return resolve_gate(
            self._app,
            model_class,
            force_gate=force_gate,
            gate_strategy=gate_strategy,
            resolved_fields=resolved_fields,
            workflow_context=workflow_context,
            gate_name=gate_name,
        )
