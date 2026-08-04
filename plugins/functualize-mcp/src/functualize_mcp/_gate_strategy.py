"""AI_OUTBOUND gate strategy resolver — pauses for external AI input via MCP.

Serializes workflow checkpoint and pauses execution, allowing an external
AI agent (via MCP) to provide input. Validates input against the gate's
awaits_input model on resume.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize_mcp._state import gate_checkpoints, pending_gate_input

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._gate._context import GateContext

__all__ = [
    "AIOutboundGateResolver",
    "AI_OUTBOUND_STRATEGY_NAME",
    "AI_OUTBOUND_PRESET_NAME",
    "AI_OUTBOUND_PRESET_STRATEGIES",
    "register_ai_outbound_gate_strategy",
]

logger = logging.getLogger(__name__)

#: Strategy name used for registration with the gate registry.
AI_OUTBOUND_STRATEGY_NAME = "ai_outbound"

#: Gate preset registered at boot time.
#: "ai_outbound" → ["ai_outbound", "prompt", "resolve"]
AI_OUTBOUND_PRESET_NAME = "ai_outbound"
AI_OUTBOUND_PRESET_STRATEGIES = ["ai_outbound", "prompt", "resolve"]


class AIOutboundGateResolver:
    """Gate resolver that pauses execution for external AI input via MCP.

    When a workflow step reaches a gate with the ai_outbound strategy,
    execution pauses and the workflow state is serialized. An external AI
    agent can then provide input through MCP workflow tools
    (resume_workflow). The input is validated against the gate's input model.

    The resolve flow:
    1. Check if there's pending input from resume_workflow (stored in
       ``app.extension_state["mcp"]["pending_gate_input"]``).
    2. If pending input exists, validate against gate's model_class and return.
    3. If no pending input, raise ValueError signaling the gate awaits
       external input — this causes the gate registry's fallback chain to
       pause execution.

    Args:
        app: The FunctualizeApp instance for accessing workflow state.
    """

    def __init__(self, app: Any = None) -> None:
        self._app = app

    def resolve(self, ctx: GateContext) -> BaseModel:
        """Pause execution and wait for external AI input via MCP.

        Serializes the current workflow state and raises a pause signal
        that the MCP workflow tools can intercept. When the external AI
        provides input via resume_workflow, the input is validated against
        the gate's model and execution continues.

        Args:
            ctx: The gate context containing model info and field state.

        Returns:
            A fully populated BaseModel instance from external AI input.

        Raises:
            ValueError: If the gate cannot be resolved (no pending input or
                invalid input provided).
        """
        # The AI_OUTBOUND strategy works by signaling that this gate
        # requires external input. The MCP workflow tools handle the
        # actual pause/resume lifecycle. If we reach here without
        # pre-filled external input, we raise to signal the gate needs
        # external resolution.
        #
        # Check if there's pending external input stored for this gate
        pending_input = self._get_pending_input(ctx)
        if pending_input is not None:
            # Validate and construct the model from pending input
            return self._validate_and_construct(ctx, pending_input)

        # Serialize workflow checkpoint info for the MCP tools to expose
        self._serialize_checkpoint(ctx)

        # No pending input — signal that this gate awaits external AI input
        raise ValueError(
            f"ai_outbound: Gate '{ctx.model_class.__name__}' awaits external "
            f"AI input via MCP. Use the resume_workflow tool to provide input."
        )

    def _validate_and_construct(
        self, ctx: GateContext, pending_input: dict[str, Any]
    ) -> BaseModel:
        """Validate pending input against the gate's model and construct it.

        Args:
            ctx: The gate context.
            pending_input: Dict of field values from resume_workflow.

        Returns:
            A validated BaseModel instance.

        Raises:
            ValueError: If the input fails validation against the gate's model.
        """
        from pydantic import ValidationError

        try:
            return ctx.model_class(**pending_input)
        except ValidationError as e:
            raise ValueError(
                f"ai_outbound: Invalid input for gate model "
                f"'{ctx.model_class.__name__}': {e}"
            ) from e
        except (TypeError, Exception) as e:
            raise ValueError(
                f"ai_outbound: Failed to construct gate model "
                f"'{ctx.model_class.__name__}': {e}"
            ) from e

    def _serialize_checkpoint(self, ctx: GateContext) -> None:
        """Serialize workflow checkpoint state for MCP exposure.

        Stores the gate's pending state so that MCP workflow tools
        (get_workflow_state, list_active_workflows) can expose it to
        external AI agents.

        Args:
            ctx: The gate context.
        """
        if self._app is None:
            return

        # Store checkpoint info for the workflow tools to expose
        checkpoint_store = gate_checkpoints(self._app)

        model_key = ctx.model_class.__name__
        checkpoint_store[model_key] = {
            "model_name": model_key,
            "unresolved_fields": ctx.unresolved_fields,
            "resolved_fields": ctx.resolved_fields,
            "all_fields": ctx.all_fields,
            "awaits_input_schema": ctx.model_class.model_json_schema(),
            "workflow_context": ctx.workflow_context,
        }

        logger.debug(
            "AIOutboundGateResolver: Serialized checkpoint for gate '%s'.",
            model_key,
        )

    def _get_pending_input(self, ctx: GateContext) -> dict[str, Any] | None:
        """Check for pending external input stored for this gate.

        The MCP workflow tools store pending input when resume_workflow
        is called. This checks if such input exists and returns it.

        Args:
            ctx: The gate context.

        Returns:
            A dict of field values if pending input exists, None otherwise.
        """
        if self._app is None:
            return None

        # Pending input is set by MCP workflow tools (resume_workflow).
        pending_store = pending_gate_input(self._app)

        # Use the model class name as the key for pending input
        model_key = ctx.model_class.__name__
        return pending_store.pop(model_key, None)


def register_ai_outbound_gate_strategy(app: Any) -> None:
    """Register the 'ai_outbound' gate strategy and preset with the app.

    This should be called during the MCP plugin boot phase to enable
    AI-outbound gate resolution (pausing for external AI input via MCP).

    Registers:
    - Strategy: "ai_outbound"
    - Preset: "ai_outbound" → ["ai_outbound", "prompt", "resolve"]

    Args:
        app: The FunctualizeApp instance.
    """
    resolver = AIOutboundGateResolver(app=app)
    app.register_gate_strategy(AI_OUTBOUND_STRATEGY_NAME, resolver)

    # Register gate preset
    # "ai_outbound" → ["ai_outbound", "prompt", "resolve"]
    app.register_gate_preset(AI_OUTBOUND_PRESET_NAME, AI_OUTBOUND_PRESET_STRATEGIES)

    logger.debug(
        "Registered '%s' gate strategy and preset.",
        AI_OUTBOUND_STRATEGY_NAME,
    )
