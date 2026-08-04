"""Unit tests for the AI_OUTBOUND gate strategy resolver.

Tests that the AIOutboundGateResolver correctly:
- Pauses execution (raises ValueError) when no pending input exists
- Serializes workflow checkpoint for MCP tools to expose
- Validates and constructs model from pending input on resume
- Raises ValueError for invalid input against the gate's model
- Registers strategy and preset at boot
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from functualize_mcp._gate_strategy import (
    AI_OUTBOUND_PRESET_NAME,
    AI_OUTBOUND_PRESET_STRATEGIES,
    AI_OUTBOUND_STRATEGY_NAME,
    AIOutboundGateResolver,
    register_ai_outbound_gate_strategy,
)
from functualize_mcp._state import gate_checkpoints, pending_gate_input
from pydantic import BaseModel, Field

from functualize._gate._context import GateContext

# ─── Helpers ───────────────────────────────────────────────────────────


def _app_double() -> MagicMock:
    """An app double exposing the kernel's ``extension_state`` slot.

    ``spec=["extension_state"]`` keeps the double honest: MCP must reach its
    state through the sanctioned namespace, so a reversion to monkey-patched
    private ``_mcp_*`` attributes fails here instead of passing silently.
    """
    app = MagicMock(spec=["extension_state"])
    app.extension_state = {}
    return app


# ─── Test Models ───────────────────────────────────────────────────────


class DeployConfig(BaseModel):
    """Sample gate model for testing."""

    region: str = Field(description="Cloud region to deploy to")
    replicas: int = Field(description="Number of replicas")


class ReviewDecision(BaseModel):
    """Model with required and optional fields."""

    approved: bool = Field(description="Whether the review is approved")
    comment: str = Field(default="", description="Optional reviewer comment")


# ─── Tests: AIOutboundGateResolver — Pause Behavior ───────────────────


class TestAIOutboundGateResolverPause:
    """Tests for the pause behavior when no pending input exists."""

    def test_raises_value_error_when_no_pending_input(self) -> None:
        """Resolver raises ValueError when no pending input exists."""
        app = MagicMock(spec=[])
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="awaits external"):
            resolver.resolve(ctx)

    def test_raises_when_app_has_no_pending_store(self) -> None:
        """Resolver raises when the app has no extension_state at all."""
        app = MagicMock(spec=[])
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "us-east-1"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="awaits external"):
            resolver.resolve(ctx)

    def test_raises_when_app_is_none(self) -> None:
        """Resolver raises when no app is provided."""
        resolver = AIOutboundGateResolver(app=None)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="awaits external"):
            resolver.resolve(ctx)

    def test_error_message_includes_model_name(self) -> None:
        """Raise message includes the gate model class name."""
        resolver = AIOutboundGateResolver(app=None)

        ctx = GateContext(
            model_class=ReviewDecision,
            resolved_fields={},
            unresolved_fields=["approved"],
            all_fields=["approved", "comment"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="ReviewDecision"):
            resolver.resolve(ctx)

    def test_raises_when_pending_store_empty(self) -> None:
        """Resolver raises when pending store exists but has no entry for this gate."""
        app = _app_double()
        pending_gate_input(app).clear()
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="awaits external"):
            resolver.resolve(ctx)


# ─── Tests: AIOutboundGateResolver — Resume Behavior ──────────────────


class TestAIOutboundGateResolverResume:
    """Tests for resume behavior when pending input is available."""

    def test_returns_model_from_valid_pending_input(self) -> None:
        """Resolver constructs model from valid pending input."""
        app = _app_double()
        pending_gate_input(app)["DeployConfig"] = {
            "region": "eu-west-1",
            "replicas": 3,
        }
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert isinstance(result, DeployConfig)
        assert result.region == "eu-west-1"
        assert result.replicas == 3

    def test_pending_input_is_consumed_after_resolve(self) -> None:
        """Pending input is removed from the store after successful resolve."""
        app = _app_double()
        pending_gate_input(app)["DeployConfig"] = {
            "region": "ap-south-1",
            "replicas": 1,
        }
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        resolver.resolve(ctx)

        # Input should be consumed (popped from the dict)
        assert "DeployConfig" not in pending_gate_input(app)

    def test_raises_value_error_for_invalid_input(self) -> None:
        """Resolver raises ValueError when pending input fails validation."""
        app = _app_double()
        # "replicas" should be int, not string
        pending_gate_input(app)["DeployConfig"] = {
            "region": "us-west-2",
            "replicas": "not-a-number",
        }
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="Invalid input for gate model"):
            resolver.resolve(ctx)

    def test_raises_value_error_for_missing_required_fields(self) -> None:
        """Resolver raises ValueError when required fields are missing."""
        app = _app_double()
        # Missing "region" which is required
        pending_gate_input(app)["DeployConfig"] = {"replicas": 5}
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="Invalid input for gate model"):
            resolver.resolve(ctx)

    def test_handles_optional_fields_with_defaults(self) -> None:
        """Resolver handles models where optional fields use defaults."""
        app = _app_double()
        pending_gate_input(app)["ReviewDecision"] = {"approved": True}
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=ReviewDecision,
            resolved_fields={},
            unresolved_fields=["approved", "comment"],
            all_fields=["approved", "comment"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert isinstance(result, ReviewDecision)
        assert result.approved is True
        assert result.comment == ""  # default value


# ─── Tests: Checkpoint Serialization ──────────────────────────────────


class TestAIOutboundCheckpoint:
    """Tests for workflow checkpoint serialization."""

    def test_serializes_checkpoint_on_pause(self) -> None:
        """Resolver serializes checkpoint info when pausing."""
        app = _app_double()
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "us-east-1"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
            workflow_context={"workflow_id": "wf-123", "step": "deploy"},
        )

        with pytest.raises(ValueError):
            resolver.resolve(ctx)

        # Checkpoint should be stored
        checkpoint = gate_checkpoints(app)["DeployConfig"]
        assert checkpoint["model_name"] == "DeployConfig"
        assert checkpoint["unresolved_fields"] == ["replicas"]
        assert checkpoint["resolved_fields"] == {"region": "us-east-1"}
        assert checkpoint["workflow_context"] == {
            "workflow_id": "wf-123",
            "step": "deploy",
        }

    def test_checkpoint_includes_json_schema(self) -> None:
        """Checkpoint includes the model's JSON schema for MCP exposure."""
        app = _app_double()
        resolver = AIOutboundGateResolver(app=app)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(ValueError):
            resolver.resolve(ctx)

        checkpoint = gate_checkpoints(app)["DeployConfig"]
        schema = checkpoint["awaits_input_schema"]
        assert "properties" in schema
        assert "region" in schema["properties"]
        assert "replicas" in schema["properties"]

    def test_no_checkpoint_when_app_is_none(self) -> None:
        """No checkpoint is stored when app is None."""
        resolver = AIOutboundGateResolver(app=None)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        # Should still raise (pause), but not crash on checkpoint serialization
        with pytest.raises(ValueError, match="awaits external"):
            resolver.resolve(ctx)


# ─── Tests: Registration ───────────────────────────────────────────────


class TestAIOutboundRegistration:
    """Tests for strategy and preset registration."""

    def test_strategy_name_constant(self) -> None:
        """AI_OUTBOUND_STRATEGY_NAME is 'ai_outbound'."""
        assert AI_OUTBOUND_STRATEGY_NAME == "ai_outbound"

    def test_preset_constants(self) -> None:
        """Preset constants have correct values."""
        assert AI_OUTBOUND_PRESET_NAME == "ai_outbound"
        assert AI_OUTBOUND_PRESET_STRATEGIES == ["ai_outbound", "prompt", "resolve"]

    def test_register_ai_outbound_gate_strategy_calls_app(self) -> None:
        """register_ai_outbound_gate_strategy registers strategy and preset."""
        app = MagicMock()

        register_ai_outbound_gate_strategy(app)

        # Should register the strategy
        app.register_gate_strategy.assert_called_once()
        call_args = app.register_gate_strategy.call_args
        assert call_args[0][0] == "ai_outbound"
        assert isinstance(call_args[0][1], AIOutboundGateResolver)

        # Should register the preset
        app.register_gate_preset.assert_called_once()
        preset_args = app.register_gate_preset.call_args
        assert preset_args[0][0] == "ai_outbound"
        assert preset_args[0][1] == ["ai_outbound", "prompt", "resolve"]

    def test_resolver_conforms_to_gate_resolver_protocol(self) -> None:
        """AIOutboundGateResolver satisfies the GateResolver protocol."""
        from functualize._gate._resolver import GateResolver

        resolver = AIOutboundGateResolver(app=None)
        assert isinstance(resolver, GateResolver)
