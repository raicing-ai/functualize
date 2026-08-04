"""Gate strategy and preset registry.

Provides storage and lookup for registered gate strategies and
preset configurations, along with the gate resolution algorithm.
Intended to be composed into FunctualizeApp.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._gate._context import GateContext
from functualize._gate._strategy import GateStrategy
from functualize._types.errors import GateResolutionError

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._gate._resolver import GateResolver


class GateRegistry:
    """Registry for gate resolution strategies and presets.

    Manages the mapping of strategy names to resolver instances and
    preset names to ordered lists of strategy names. Also implements
    the gate resolution algorithm.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, GateResolver] = {}
        self._presets: dict[str, list[str]] = {}

    def register_strategy(self, name: str, resolver: GateResolver) -> None:
        """Register a gate resolution strategy by name.

        Args:
            name: Strategy identifier (1-64 characters).
            resolver: A GateResolver implementation instance.

        Raises:
            ValueError: If name length is outside [1, 64].
        """
        if not (1 <= len(name) <= 64):
            raise ValueError(f"Strategy name must be 1-64 chars, got {len(name)}")
        self._strategies[name] = resolver

    def register_preset(self, name: str, strategies: list[str]) -> None:
        """Register an ordered fallback list of strategies under a preset name.

        Args:
            name: Preset identifier.
            strategies: Ordered list of strategy names (1-10 entries).

        Raises:
            ValueError: If strategies list length is outside [1, 10].
        """
        if not (1 <= len(strategies) <= 10):
            raise ValueError(
                f"Preset must reference 1-10 strategies, got {len(strategies)}"
            )
        self._presets[name] = strategies

    def get_strategy(self, name: str) -> GateResolver | None:
        """Retrieve a registered strategy by name.

        Returns:
            The GateResolver instance, or None if not registered.
        """
        return self._strategies.get(name)

    def get_preset(self, name: str) -> list[str] | None:
        """Retrieve a registered preset by name.

        Returns:
            The ordered list of strategy names, or None if not registered.
        """
        return self._presets.get(name)

    def resolve_gate(
        self,
        model_class: type[BaseModel],
        *,
        force_gate: bool = False,
        gate_strategy: GateStrategy | str | list[GateStrategy | str] | None = None,
        resolved_fields: dict[str, Any] | None = None,
        workflow_context: dict[str, Any] | None = None,
        gate_name: str = "unnamed",
    ) -> BaseModel:
        """Resolve a gate by applying the resolution algorithm.

        Steps:
            1. Determine resolved/unresolved fields from the provided
               resolved_fields or by inspecting model defaults.
            2. Short-circuit if fully resolved and force_gate=False.
            3. Build GateContext and dispatch to strategies in order.
            4. Return model from first successful strategy.
            5. Raise GateResolutionError if all strategies fail.

        Args:
            model_class: The Pydantic BaseModel subclass to resolve.
            force_gate: If True, dispatch to strategy even when fully resolved.
            gate_strategy: Override strategy — a single strategy name/enum,
                or list of strategies, or a preset name.
            resolved_fields: Dict of field names to already-resolved values
                from the config chain. If None, resolution uses model defaults.
            workflow_context: Arbitrary context from the current workflow state.
            gate_name: Identifier for the gate (used in error messages).

        Returns:
            A fully populated BaseModel instance.

        Raises:
            GateResolutionError: If all strategies fail to resolve.
            ValueError: If a preset references an unregistered strategy.
        """
        if resolved_fields is None:
            resolved_fields = {}
        if workflow_context is None:
            workflow_context = {}

        # Step 1: Determine all fields and classify resolved/unresolved
        all_fields = list(model_class.model_fields.keys())
        actual_resolved: dict[str, Any] = {}
        unresolved_fields: list[str] = []

        for field_name in all_fields:
            if field_name in resolved_fields:
                actual_resolved[field_name] = resolved_fields[field_name]
            else:
                # Check if the field has a default value in the model
                field_info = model_class.model_fields[field_name]
                if not field_info.is_required():
                    # Field has a default or default_factory
                    if field_info.default_factory is not None:
                        actual_resolved[field_name] = field_info.default_factory()  # type: ignore[call-arg]
                    else:
                        actual_resolved[field_name] = field_info.default
                else:
                    unresolved_fields.append(field_name)

        # Step 2: Short-circuit if fully resolved and not forced
        if not unresolved_fields and not force_gate:
            return model_class(**actual_resolved)

        # Step 3: Build GateContext
        ctx = GateContext(
            model_class=model_class,
            resolved_fields=actual_resolved,
            unresolved_fields=unresolved_fields,
            all_fields=all_fields,
            force_gate=force_gate,
            workflow_context=workflow_context,
        )

        # Step 4: Determine strategy list
        strategy_entries = self._resolve_strategy_list(gate_strategy)

        # Step 5: Try each strategy in order
        last_exc: BaseException | None = None
        for strategy_name, preset_source in strategy_entries:
            resolver = self._strategies.get(strategy_name)
            if resolver is None:
                if preset_source is not None:
                    raise ValueError(
                        f"Unregistered gate strategy '{strategy_name}' "
                        f"referenced in preset '{preset_source}'. "
                        f"Register the strategy before using the preset."
                    )
                raise ValueError(
                    f"Unregistered gate strategy '{strategy_name}' "
                    f"referenced during resolution of gate '{gate_name}'"
                )
            try:
                return resolver.resolve(ctx)
            except Exception as exc:
                last_exc = exc
                continue

        # All strategies failed
        last_error_msg = str(last_exc) if last_exc else "no strategies attempted"
        raise GateResolutionError(
            gate_name=gate_name,
            strategies_attempted=len(strategy_entries),
            last_error=last_error_msg,
        )

    def _resolve_strategy_list(
        self,
        gate_strategy: GateStrategy | str | list[GateStrategy | str] | None,
    ) -> list[tuple[str, str | None]]:
        """Convert the gate_strategy parameter into an ordered list of (name, preset_source).

        Resolution rules:
            - None → default to [GateStrategy.RESOLVE]
            - Single GateStrategy/str → check if it's a preset name first,
              then treat as single-strategy list
            - List → expand each entry (checking for presets)

        Args:
            gate_strategy: The strategy specification to resolve.

        Returns:
            Ordered list of (strategy_name, preset_name_or_None) tuples.
            The second element identifies which preset the strategy came from,
            or None if it was specified directly.
        """
        if gate_strategy is None:
            return [(GateStrategy.RESOLVE.value, None)]

        if isinstance(gate_strategy, list):
            result: list[tuple[str, str | None]] = []
            for item in gate_strategy:
                name = item.value if isinstance(item, GateStrategy) else item
                # Check if it's a preset
                preset = self._presets.get(name)
                if preset is not None:
                    result.extend((s, name) for s in preset)
                else:
                    result.append((name, None))
            return result

        # Single strategy or preset name
        name = (
            gate_strategy.value
            if isinstance(gate_strategy, GateStrategy)
            else gate_strategy
        )
        # Check if it references a preset
        preset = self._presets.get(name)
        if preset is not None:
            return [(s, name) for s in preset]
        return [(name, None)]
