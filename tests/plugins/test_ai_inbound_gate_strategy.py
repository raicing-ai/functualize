"""Unit tests for the AI_INBOUND gate strategy resolver.

Tests that the AIInboundGateResolver correctly:
- Uses AI.complete() with the gate's input model as response_model
- Includes resolved_fields as context in the LLM prompt
- Asks the LLM to decide values for unresolved_fields
- Raises AINotAvailableError when no AI capability is available
- Registers strategy and presets at boot
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from functualize_ai._ai import AI
from functualize_ai._errors import AINotAvailableError
from functualize_ai._gate_strategy import (
    AI_INBOUND_PRESET_NAME,
    AI_INBOUND_PRESET_STRATEGIES,
    AI_INBOUND_STRATEGY_NAME,
    AI_PRESET_NAME,
    AI_PRESET_STRATEGIES,
    AIInboundGateResolver,
    _build_prompt,
    register_ai_inbound_gate_strategy,
)
from pydantic import BaseModel, Field

from functualize._gate._context import GateContext

if TYPE_CHECKING:
    from functualize_ai._types import AILimits, AIResult

# ─── Test Models ───────────────────────────────────────────────────────


class DeployConfig(BaseModel):
    """Sample gate model for testing."""

    region: str = Field(description="Cloud region to deploy to")
    replicas: int = Field(description="Number of replicas")


class PartialConfig(BaseModel):
    """Model with some optional fields."""

    name: str = Field(description="Service name")
    port: int = Field(default=8080, description="Port number")
    debug: bool = Field(default=False, description="Enable debug mode")


# ─── Fake AI Provider ──────────────────────────────────────────────────


class FakeAIProvider:
    """A fake AI provider that returns predefined responses."""

    def __init__(self, response: Any = None) -> None:
        self._response = response
        self.last_prompt: str | None = None
        self.last_response_model: type | None = None

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        self.last_prompt = prompt
        self.last_response_model = response_model
        return self._response

    def run(
        self,
        prompt: str,
        *,
        tools: Any = None,
        response_model: type | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        raise NotImplementedError

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError

    def extract(self, text: str, *, model: type) -> Any:
        raise NotImplementedError


# ─── Tests: AIInboundGateResolver ──────────────────────────────────────


class TestAIInboundGateResolver:
    """Tests for the AIInboundGateResolver class."""

    def test_raises_when_no_ai_available(self) -> None:
        """Resolver raises AINotAvailableError when no AI is configured."""
        resolver = AIInboundGateResolver(ai=None)
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(AINotAvailableError, match="No AI capability"):
            resolver.resolve(ctx)

    def test_calls_ai_complete_with_response_model(self) -> None:
        """Resolver uses AI.complete() with the gate's model as response_model."""
        expected = DeployConfig(region="us-east-1", replicas=3)
        provider = FakeAIProvider(response=expected)
        ai = AI(_provider=provider)
        resolver = AIInboundGateResolver(ai=ai)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert result == expected
        assert provider.last_response_model is DeployConfig

    def test_includes_resolved_fields_as_context(self) -> None:
        """Resolver includes resolved_fields in the prompt to the LLM."""
        expected = DeployConfig(region="eu-west-1", replicas=5)
        provider = FakeAIProvider(response=expected)
        ai = AI(_provider=provider)
        resolver = AIInboundGateResolver(ai=ai)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "eu-west-1"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        resolver.resolve(ctx)

        # Verify the prompt contains the resolved field context
        assert provider.last_prompt is not None
        assert "eu-west-1" in provider.last_prompt
        assert "region" in provider.last_prompt
        assert "already resolved" in provider.last_prompt

    def test_asks_for_unresolved_fields(self) -> None:
        """Resolver asks the LLM to decide values for unresolved_fields."""
        expected = DeployConfig(region="us-west-2", replicas=2)
        provider = FakeAIProvider(response=expected)
        ai = AI(_provider=provider)
        resolver = AIInboundGateResolver(ai=ai)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "us-west-2"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        resolver.resolve(ctx)

        # Verify the prompt mentions the unresolved fields
        assert provider.last_prompt is not None
        assert "replicas" in provider.last_prompt
        assert "unresolved" in provider.last_prompt

    def test_all_fields_unresolved(self) -> None:
        """Resolver works when all fields are unresolved."""
        expected = DeployConfig(region="ap-south-1", replicas=1)
        provider = FakeAIProvider(response=expected)
        ai = AI(_provider=provider)
        resolver = AIInboundGateResolver(ai=ai)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert result.region == "ap-south-1"
        assert result.replicas == 1

    def test_propagates_ai_not_available_from_provider(self) -> None:
        """Resolver propagates AINotAvailableError from the AI provider."""

        class FailingProvider:
            def complete(self, prompt: str, **kwargs: Any) -> Any:
                raise AINotAvailableError("LLM service unavailable")

            def run(self, *a: Any, **kw: Any) -> Any:
                raise NotImplementedError

            def stream(self, *a: Any, **kw: Any) -> Any:
                raise NotImplementedError

            def extract(self, *a: Any, **kw: Any) -> Any:
                raise NotImplementedError

        ai = AI(_provider=FailingProvider())
        resolver = AIInboundGateResolver(ai=ai)

        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        with pytest.raises(AINotAvailableError):
            resolver.resolve(ctx)


# ─── Tests: _build_prompt ──────────────────────────────────────────────


class TestBuildPrompt:
    """Tests for the _build_prompt helper function."""

    def test_includes_model_name(self) -> None:
        """Prompt includes the model class name."""
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        assert "DeployConfig" in prompt

    def test_includes_resolved_fields_section(self) -> None:
        """Prompt includes a section listing resolved fields."""
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "us-east-1"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        assert "already resolved" in prompt
        assert "region" in prompt
        assert "us-east-1" in prompt

    def test_includes_unresolved_fields_section(self) -> None:
        """Prompt includes a section listing unresolved fields."""
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        assert "unresolved" in prompt
        assert "region" in prompt
        assert "replicas" in prompt

    def test_includes_field_descriptions(self) -> None:
        """Prompt includes field descriptions from the model."""
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        assert "Cloud region to deploy to" in prompt
        assert "Number of replicas" in prompt

    def test_empty_resolved_fields_omits_section(self) -> None:
        """Prompt omits the resolved fields section when empty."""
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas"],
            force_gate=False,
        )

        prompt = _build_prompt(ctx)

        assert "already resolved" not in prompt


# ─── Tests: Registration ───────────────────────────────────────────────


class TestAIInboundRegistration:
    """Tests for strategy and preset registration helpers."""

    def test_strategy_name_constant(self) -> None:
        """AI_INBOUND_STRATEGY_NAME is 'ai_inbound'."""
        assert AI_INBOUND_STRATEGY_NAME == "ai_inbound"

    def test_preset_constants(self) -> None:
        """Preset constants have correct values."""
        assert AI_INBOUND_PRESET_NAME == "ai_inbound"
        assert AI_INBOUND_PRESET_STRATEGIES == ["ai_inbound", "prompt", "resolve"]
        assert AI_PRESET_NAME == "ai"
        assert AI_PRESET_STRATEGIES == [
            "ai_outbound",
            "ai_inbound",
            "prompt",
            "resolve",
        ]

    def test_register_ai_inbound_gate_strategy_calls_app(self) -> None:
        """register_ai_inbound_gate_strategy registers strategy and presets."""
        app = MagicMock()
        provider = FakeAIProvider(response=None)
        ai = AI(_provider=provider)

        register_ai_inbound_gate_strategy(app, ai)

        # Should register the strategy
        app.register_gate_strategy.assert_called_once()
        call_args = app.register_gate_strategy.call_args
        assert call_args[0][0] == "ai_inbound"
        assert isinstance(call_args[0][1], AIInboundGateResolver)

        # Should register both presets
        assert app.register_gate_preset.call_count == 2
        preset_calls = app.register_gate_preset.call_args_list

        # First call: "ai_inbound" preset
        assert preset_calls[0][0][0] == "ai_inbound"
        assert preset_calls[0][0][1] == ["ai_inbound", "prompt", "resolve"]

        # Second call: "ai" preset
        assert preset_calls[1][0][0] == "ai"
        assert preset_calls[1][0][1] == [
            "ai_outbound",
            "ai_inbound",
            "prompt",
            "resolve",
        ]
