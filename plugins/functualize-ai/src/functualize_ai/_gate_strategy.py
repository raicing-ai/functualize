"""AI_INBOUND gate strategy resolver — uses AI to resolve gate inputs.

Uses the AI capability to generate a typed response matching the gate's input
model. Includes resolved_fields as context and asks the LLM to decide values
for unresolved_fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize_ai._errors import AINotAvailableError

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._gate._context import GateContext
    from functualize_ai._ai import AI


#: Strategy name used for registration with the gate registry.
AI_INBOUND_STRATEGY_NAME = "ai_inbound"

#: Gate presets registered at boot time.
AI_INBOUND_PRESET_NAME = "ai_inbound"
AI_INBOUND_PRESET_STRATEGIES = ["ai_inbound", "prompt", "resolve"]

AI_PRESET_NAME = "ai"
AI_PRESET_STRATEGIES = ["ai_outbound", "ai_inbound", "prompt", "resolve"]


def _build_prompt(ctx: GateContext) -> str:
    """Build an LLM prompt from the gate context.

    Includes resolved fields as context and asks the LLM to decide
    values for unresolved fields.

    Args:
        ctx: The gate context with model info and field state.

    Returns:
        A formatted prompt string for the LLM.
    """
    model_name = ctx.model_class.__name__
    lines: list[str] = []

    lines.append(f"You are resolving inputs for a gate with model '{model_name}'.")
    lines.append("")

    # Include resolved fields as context
    if ctx.resolved_fields:
        lines.append("The following fields are already resolved (context):")
        for field_name, value in ctx.resolved_fields.items():
            lines.append(f"  - {field_name}: {value!r}")
        lines.append("")

    # Ask LLM to decide unresolved fields
    if ctx.unresolved_fields:
        lines.append("Please decide values for the following unresolved fields:")
        for field_name in ctx.unresolved_fields:
            field_info = ctx.model_class.model_fields[field_name]
            description = field_info.description or ""
            annotation = field_info.annotation
            type_hint = getattr(annotation, "__name__", str(annotation))
            if description:
                lines.append(f"  - {field_name} ({type_hint}): {description}")
            else:
                lines.append(f"  - {field_name} ({type_hint})")
        lines.append("")

    lines.append(
        "Respond with appropriate values that make sense given the context above."
    )

    return "\n".join(lines)


class AIInboundGateResolver:
    """Gate resolver that uses AI to generate values for unresolved fields.

    Uses the AI capability's ``complete()`` method with the gate's input model
    as the ``response_model`` to generate a typed response. Resolved fields are
    included as context in the prompt, and the LLM is asked to decide the
    unresolved field values.

    Args:
        ai: The AI capability instance to use for generation, or None.
    """

    def __init__(self, ai: AI | None = None) -> None:
        self._ai = ai

    def resolve(self, ctx: GateContext) -> BaseModel:
        """Resolve gate fields by asking the AI to generate values.

        Args:
            ctx: The gate context containing model info and field state.

        Returns:
            A fully populated BaseModel instance with AI-generated values.

        Raises:
            AINotAvailableError: If no AI capability is registered.
            ValueError: If the model cannot be constructed from AI response.
        """
        if self._ai is None:
            raise AINotAvailableError(
                "No AI capability is available. "
                "Install an AI plugin (e.g., pip install functualize-ai-pydantic) "
                "to use the 'ai_inbound' gate strategy."
            )

        # Build prompt with resolved fields as context
        prompt = _build_prompt(ctx)

        # Use AI.complete() with the gate's input model as response_model
        # This returns a fully typed instance of the model
        result = self._ai.complete(prompt, response_model=ctx.model_class)

        return result


def register_ai_inbound_gate_strategy(app: Any, ai: AI) -> None:
    """Register the 'ai_inbound' gate strategy and gate presets with the app.

    This should be called during the AI domain boot phase to enable
    AI-driven gate resolution and register the preset fallback chains.

    Args:
        app: The FunctualizeApp instance.
        ai: The AI capability instance.
    """
    resolver = AIInboundGateResolver(ai=ai)
    app.register_gate_strategy(AI_INBOUND_STRATEGY_NAME, resolver)

    # Register gate presets
    # "ai_inbound" → ["ai_inbound", "prompt", "resolve"]
    app.register_gate_preset(AI_INBOUND_PRESET_NAME, AI_INBOUND_PRESET_STRATEGIES)

    # "ai" → ["ai_outbound", "ai_inbound", "prompt", "resolve"]
    app.register_gate_preset(AI_PRESET_NAME, AI_PRESET_STRATEGIES)
