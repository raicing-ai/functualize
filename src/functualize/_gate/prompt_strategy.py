"""PROMPT gate strategy resolver — collects gate inputs via a Surface.

Uses the active Surface to interactively collect values for unresolved fields
in a gate context. When force_gate=True, all fields are presented with
resolved values as editable pre-filled defaults.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from functualize._types.interactivity import (
    InputNotAvailable,
    PromptIntent,
    PromptRequest,
    PromptResponse,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._gate._context import GateContext
    from functualize._types.interactivity import PromptCollector

__all__ = [
    "PROMPT_STRATEGY_NAME",
    "PromptGateResolver",
    "register_prompt_gate_strategy",
]

#: Strategy name used for registration with the gate registry.
PROMPT_STRATEGY_NAME = "prompt"


class PromptGateResolver:
    """Gate resolver that collects field values via interactive prompts.

    Uses the active Surface to prompt the user for each unresolved field.
    When force_gate=True, all fields (including already-resolved ones) are
    presented, with resolved values shown as editable defaults.

    The collector is resolved dynamically at call time through the app's
    surface stack, rather than being fixed at construction time — this
    allows the strategy to be registered at boot, before any surface is
    available, and resolve correctly when a surface is later pushed.
    """

    def __init__(
        self,
        app: Any = None,
        collector_factory: Callable[[Any], PromptCollector | None] | None = None,
    ) -> None:
        self._app = app
        # Injected rather than imported: "which surface answers a prompt right
        # now" is `_engine`'s knowledge, and `_gate` is its peer — importing it
        # here broke the peer-layer independence contract. The composition root
        # (`_app.boot`) is the one place allowed to know both, so it supplies
        # `_engine.surface_routing.active_collector`.
        self._collector_factory = collector_factory

    def _collector(self) -> PromptCollector | None:
        if self._collector_factory is None:
            return None
        return self._collector_factory(self._app)

    def resolve(self, ctx: GateContext) -> BaseModel:
        """Resolve gate fields by prompting the user via the Surface.

        Args:
            ctx: The gate context containing model info and field state.

        Returns:
            A fully populated BaseModel instance with user-provided values.

        Raises:
            InputNotAvailable: If no Surface is available.
            ValueError: If the model cannot be constructed from collected values.
        """
        provider = self._collector()
        if provider is None:
            raise InputNotAvailable(
                "No Surface is available to collect input. The 'prompt' gate "
                "strategy needs an interactive terminal or a registered "
                "surface."
            )

        # Determine which fields to prompt for
        # Present ALL fields when forced (resolved ones get pre-filled defaults),
        # otherwise only prompt for unresolved fields.
        fields_to_prompt = ctx.all_fields if ctx.force_gate else ctx.unresolved_fields

        # Collect values for each field
        collected_values: dict[str, Any] = dict(ctx.resolved_fields)

        for field_name in fields_to_prompt:
            field_info = ctx.model_class.model_fields[field_name]

            # Determine the default value for the prompt
            default: Any = None
            if field_name in ctx.resolved_fields:
                # Already-resolved value serves as the editable default
                default = ctx.resolved_fields[field_name]
            elif not field_info.is_required():
                # Use model field default
                if field_info.default_factory is not None:
                    default = field_info.default_factory()  # type: ignore[call-arg]
                else:
                    default = field_info.default

            # Build the question text from field metadata
            description = field_info.description or ""
            question = _build_question(field_name, description)

            # Determine if the field is required
            required = field_info.is_required() and default is None

            request = PromptRequest(
                question=question,
                intent=PromptIntent.TEXT_INPUT,
                default=default,
                required=required,
                help_text=description if description else None,
            )

            response: PromptResponse = provider.collect(request)
            collected_values[field_name] = response.value

        # Construct the model from collected values
        from pydantic import ValidationError

        try:
            return ctx.model_class(**collected_values)
        except (ValidationError, TypeError) as exc:
            raise ValueError(
                f"Failed to construct {ctx.model_class.__name__} from "
                f"prompted values: {exc}"
            ) from exc


def register_prompt_gate_strategy(
    app: Any,
    collector_factory: Callable[[Any], PromptCollector | None] | None = None,
) -> None:
    """Register the prompt gate strategy on ``app``.

    ``collector_factory`` resolves the surface that should answer a prompt;
    the composition root passes ``_engine.surface_routing.active_collector``.
    Omitting it leaves the resolver with no collector, which is the same
    "no surface available" path as an unanswerable prompt.
    """
    resolver = PromptGateResolver(app=app, collector_factory=collector_factory)
    app.register_gate_strategy(PROMPT_STRATEGY_NAME, resolver)


def _build_question(field_name: str, description: str) -> str:
    """Build a human-readable question from field name and description.

    Args:
        field_name: The model field name (snake_case).
        description: Optional field description from Pydantic metadata.

    Returns:
        A formatted question string for the prompt.
    """
    # Convert snake_case to a readable label
    label = field_name.replace("_", " ").capitalize()
    if description:
        return f"{label} ({description})"
    return f"{label}"
