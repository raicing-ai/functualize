"""Gate strategy and preset registry.

Provides storage and lookup for registered gate strategies and
preset configurations, along with the gate resolution algorithm.
Intended to be composed into FunctualizeApp.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from functualize._gate._context import GateContext
from functualize._gate._evaluation import blocked_reason_from
from functualize._gate._strategy import GateStrategy, missing_strategy_hint
from functualize._types.errors import GateResolutionError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    LadderOutcome,
)

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

    def evaluate(
        self,
        model_class: type[BaseModel],
        *,
        gate_strategy: GateStrategy | str | list[GateStrategy | str] | None = None,
        gate_name: str = "unnamed",
        resolved_fields: dict[str, Any] | None = None,
        workflow_context: dict[str, Any] | None = None,
        force_gate: bool = False,
    ) -> LadderOutcome:
        """Run the resolution ladder, recording one rung per strategy.

        Pure: no store, no clock, no ids — the caller records the rungs as
        candidates, which is what makes the evaluation a fact about this run
        rather than something recomputed on read. The algorithm is the one
        ``resolve_gate`` has always run (field classification, the
        short-circuit when fully resolved and not forced, strategy-list
        expansion); what changes is that every expanded entry leaves a rung
        behind:

        - ``failed`` — the resolver raised; the detail is ``str(exc)``;
        - ``unavailable`` — the strategy is unregistered; the detail is the
          install hint;
        - ``accepted`` — the first success; the rung carries the model's dump;
        - ``not_reached`` — every rung after the accepted one, recorded
          rather than omitted so a ladder that stopped early reads as one.

        The two loud ``ValueError`` paths raise from here exactly as they
        always have — an unregistered strategy inside a preset, and a single
        explicitly-named unregistered strategy — with nothing returned.

        Args:
            model_class: The Pydantic BaseModel subclass to resolve.
            gate_strategy: Override strategy — a single strategy name/enum,
                or list of strategies, or a preset name.
            gate_name: Identifier for the gate (used in error messages).
            resolved_fields: Dict of field names to already-resolved values
                from the config chain. If None, resolution uses model defaults.
            workflow_context: Arbitrary context from the current workflow state.
            force_gate: If True, dispatch to strategy even when fully resolved.

        Returns:
            The ladder's outcome: rungs in order, the accepted model when a
            rung succeeded, and the blocked text when none did.
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

        # Step 2: Short-circuit if fully resolved and not forced. One rung,
        # credited to `resolve`, because the config chain is what answered.
        if not unresolved_fields and not force_gate:
            model = model_class(**actual_resolved)
            return LadderOutcome(
                rungs=(
                    (
                        "resolve",
                        CandidateEvaluation(EvaluationOutcome.ACCEPTED),
                        model.model_dump(),
                    ),
                ),
                model=model,
            )

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

        # Step 5: One rung per expanded entry, in ladder order. A rung after
        # the accepted one is `not_reached` rather than absent, and every
        # failure keeps its own label — the ladder used to fold all of them
        # into one string, which is how a broken *earlier* strategy stayed
        # invisible while the operator was shown the *next* one's complaint
        # (a `prompt` resolver raising `TypeError` reported a config-chain
        # error, and the config chain was fine).
        rungs: list[tuple[str, CandidateEvaluation, Any]] = []
        accepted: BaseModel | None = None
        for strategy_name, preset_source in strategy_entries:
            if accepted is not None:
                rungs.append(
                    (
                        strategy_name,
                        CandidateEvaluation(EvaluationOutcome.NOT_REACHED),
                        None,
                    )
                )
                continue
            resolver = self._strategies.get(strategy_name)
            if resolver is None:
                if preset_source is not None:
                    # A preset is a *registry* entry, so a name it references
                    # that nobody registered is a wiring mistake in the app,
                    # not a missing capability at this gate. Keep it loud.
                    raise ValueError(
                        f"Unregistered gate strategy '{strategy_name}' "
                        f"referenced in preset '{preset_source}'. "
                        f"Register the strategy before using the preset."
                    )
                if len(strategy_entries) == 1:
                    # One strategy, named explicitly, and it does not exist:
                    # there is no ladder to fall down, and a typo in
                    # `gate_strategy="ai_inbund"` must not be swallowed.
                    raise ValueError(
                        f"Unregistered gate strategy '{strategy_name}' "
                        f"referenced during resolution of gate '{gate_name}'"
                    )
                # A ladder should behave like a ladder. An unregistered rung
                # is a *failed* rung: record it and try the next one.
                #
                # This is what made a forgotten `pip install functualize-ai`
                # harsher than a broken API key. A registered resolver that
                # raised fell through to `prompt` and then `resolve`, and the
                # walk ended BLOCKED and resumable; an unregistered name raised
                # a bare ValueError out of `resolve_gate`, past the walker's
                # `except GateResolutionError`, and out of `app.execute()`.
                rungs.append(
                    (
                        strategy_name,
                        CandidateEvaluation(
                            EvaluationOutcome.UNAVAILABLE,
                            detail=missing_strategy_hint(strategy_name),
                        ),
                        None,
                    )
                )
                continue
            try:
                model = resolver.resolve(ctx)
            except Exception as exc:
                # **Every** rung's failure, each labelled with the rung it
                # came from — not just the last one.
                rungs.append(
                    (
                        strategy_name,
                        CandidateEvaluation(EvaluationOutcome.FAILED, detail=str(exc)),
                        None,
                    )
                )
                continue
            rungs.append(
                (
                    strategy_name,
                    CandidateEvaluation(EvaluationOutcome.ACCEPTED),
                    model.model_dump(),
                )
            )
            accepted = model

        return LadderOutcome(
            rungs=tuple(rungs),
            model=accepted,
            blocked_reason="" if accepted is not None else blocked_reason_from(rungs),
        )

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
        """Resolve a gate: :meth:`evaluate`, plus the raise when nothing did.

        The model when a rung was accepted, otherwise the
        :class:`GateResolutionError` the walker catches — same type, same
        message, same ``strategies_attempted`` count as before the ladder
        learned to enumerate itself. What is new is ``evaluations``: one per
        rung, so a caller that wants the recorded ladder does not have to
        re-derive it from the text.
        """
        outcome = self.evaluate(
            model_class,
            gate_strategy=gate_strategy,
            gate_name=gate_name,
            resolved_fields=resolved_fields,
            workflow_context=workflow_context,
            force_gate=force_gate,
        )
        if outcome.model is not None:
            # The value is the accepted rung's model instance; `LadderOutcome`
            # types it `Any` because a payload and a model share one field.
            return cast("BaseModel", outcome.model)
        raise GateResolutionError(
            gate_name=gate_name,
            strategies_attempted=len(outcome.rungs),
            last_error=outcome.blocked_reason,
            evaluations=tuple(evaluation for _, evaluation, _ in outcome.rungs),
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
