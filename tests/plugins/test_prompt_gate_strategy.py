"""Unit tests for the PROMPT gate strategy resolver.

Tests that the PromptGateResolver correctly:
- Prompts for unresolved fields only (when force_gate=False)
- Prompts for ALL fields with defaults when force_gate=True
- Raises InputNotAvailable when no provider is available
- Correctly constructs the model from collected values
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from functualize._gate._context import GateContext
from functualize._gate.prompt_strategy import (
    PROMPT_STRATEGY_NAME,
    PromptGateResolver,
    _build_question,
    register_prompt_gate_strategy,
)
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptRequest,
    PromptResponse,
)

# ─── Test Models ──────────────────────────────────────────────────────────


class DeployConfig(BaseModel):
    """A test model with required and optional fields."""

    region: str = Field(description="AWS region to deploy to")
    replicas: int = Field(description="Number of replicas")
    environment: str = Field(default="staging", description="Target environment")


class SimpleModel(BaseModel):
    """A simple model with only required fields."""

    name: str
    value: int


# ─── Mock InputProvider ───────────────────────────────────────────────────


class RecordingInputProvider:
    """InputProvider that records requests and returns predefined responses."""

    def __init__(self, responses: dict[str, Any]) -> None:
        """Initialize with a mapping of field names to response values.

        The provider matches the request's question to determine which
        field is being prompted and returns the corresponding value.
        """
        self._responses = responses
        self.requests: list[PromptRequest] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Record the request and return a predefined response."""
        self.requests.append(request)
        # Find the matching response by checking if any key is in the question
        for field_name, value in self._responses.items():
            label = field_name.replace("_", " ").capitalize()
            if label.lower() in request.question.lower():
                return PromptResponse(value=value, source="user")
        # Default: return the default if available
        if request.default is not None:
            return PromptResponse(value=request.default, source="default")
        return PromptResponse(value=None, source="user")


# ─── Tests: InputNotAvailable ─────────────────────────────────────────────


class TestPromptGateResolverNoProvider:
    """Tests for PromptGateResolver when no InputProvider is available."""

    def test_raises_input_not_available_when_no_provider(self) -> None:
        """Resolver raises InputNotAvailable with helpful message."""
        resolver = PromptGateResolver(app=None)
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas", "environment"],
            force_gate=False,
        )

        with pytest.raises(InputNotAvailable, match="No Surface is available"):
            resolver.resolve(ctx)

    def test_error_message_mentions_how_to_enable(self) -> None:
        """Error message explains what's needed to collect input."""
        resolver = PromptGateResolver(app=None)
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"environment": "prod"},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas", "environment"],
            force_gate=False,
        )

        with pytest.raises(InputNotAvailable, match="interactive terminal"):
            resolver.resolve(ctx)


# ─── Tests: Unresolved Fields (force_gate=False) ──────────────────────────


class TestPromptGateResolverUnresolved:
    """Tests for prompting only unresolved fields."""

    def test_prompts_only_unresolved_fields(self) -> None:
        """When force_gate=False, only unresolved fields are prompted."""
        provider = RecordingInputProvider({"region": "us-east-1", "replicas": 3})
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"environment": "production"},
            unresolved_fields=["region", "replicas"],
            all_fields=["region", "replicas", "environment"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert result.region == "us-east-1"
        assert result.replicas == 3
        assert result.environment == "production"
        # Only 2 prompts for the unresolved fields
        assert len(provider.requests) == 2

    def test_prompted_fields_match_unresolved_exactly(self) -> None:
        """Prompts are made for exactly the unresolved fields, no more."""
        provider = RecordingInputProvider({"name": "test", "value": 42})
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=SimpleModel,
            resolved_fields={"name": "existing"},
            unresolved_fields=["value"],
            all_fields=["name", "value"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert result.name == "existing"
        assert result.value == 42
        # Only 1 prompt for the single unresolved field
        assert len(provider.requests) == 1

    def test_no_prompts_when_all_resolved_but_strategy_still_called(self) -> None:
        """If no unresolved fields and force_gate=False, no prompts are shown."""
        provider = RecordingInputProvider({})
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={
                "region": "eu-west-1",
                "replicas": 2,
                "environment": "dev",
            },
            unresolved_fields=[],
            all_fields=["region", "replicas", "environment"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert result.region == "eu-west-1"
        assert result.replicas == 2
        assert result.environment == "dev"
        assert len(provider.requests) == 0


# ─── Tests: Force Gate (force_gate=True) ──────────────────────────────────


class TestPromptGateResolverForceGate:
    """Tests for force_gate=True behavior."""

    def test_force_gate_prompts_all_fields(self) -> None:
        """When force_gate=True, all fields are presented to the user."""
        provider = RecordingInputProvider(
            {"region": "ap-south-1", "replicas": 5, "environment": "prod"}
        )
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "us-east-1", "environment": "staging"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas", "environment"],
            force_gate=True,
        )

        resolver.resolve(ctx)

        # All 3 fields were prompted
        assert len(provider.requests) == 3

    def test_force_gate_uses_resolved_values_as_defaults(self) -> None:
        """Already-resolved values are shown as defaults in prompts."""
        provider = RecordingInputProvider(
            {"region": "us-east-1", "replicas": 5, "environment": "staging"}
        )
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=DeployConfig,
            resolved_fields={"region": "us-east-1", "environment": "staging"},
            unresolved_fields=["replicas"],
            all_fields=["region", "replicas", "environment"],
            force_gate=True,
        )

        resolver.resolve(ctx)

        # Check that the region prompt has the resolved value as default
        region_request = next(
            r for r in provider.requests if "region" in r.question.lower()
        )
        assert region_request.default == "us-east-1"

        # Check environment uses resolved value as default
        env_request = next(
            r for r in provider.requests if "environment" in r.question.lower()
        )
        assert env_request.default == "staging"


# ─── Tests: Model Construction ────────────────────────────────────────────


class TestPromptGateResolverModelConstruction:
    """Tests for model construction from collected values."""

    def test_constructs_valid_model(self) -> None:
        """Resolver returns a properly constructed BaseModel instance."""
        provider = RecordingInputProvider({"name": "hello", "value": 99})
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=SimpleModel,
            resolved_fields={},
            unresolved_fields=["name", "value"],
            all_fields=["name", "value"],
            force_gate=False,
        )

        result = resolver.resolve(ctx)

        assert isinstance(result, SimpleModel)
        assert result.name == "hello"
        assert result.value == 99

    def test_raises_value_error_on_validation_failure(self) -> None:
        """Resolver raises ValueError if model validation fails."""
        # Return a string where int is expected
        provider = RecordingInputProvider({"name": "test", "value": "not_an_int"})
        resolver = PromptGateResolver(app=None)
        resolver._collector = lambda: provider  # type: ignore[method-assign]
        ctx = GateContext(
            model_class=SimpleModel,
            resolved_fields={},
            unresolved_fields=["name", "value"],
            all_fields=["name", "value"],
            force_gate=False,
        )

        with pytest.raises(ValueError, match="Failed to construct SimpleModel"):
            resolver.resolve(ctx)


# ─── Tests: Strategy Name and Registration ────────────────────────────────


class TestPromptGateStrategyRegistration:
    """Tests for strategy registration helpers."""

    def test_strategy_name_is_prompt(self) -> None:
        """The strategy name constant is 'prompt'."""
        assert PROMPT_STRATEGY_NAME == "prompt"

    def test_register_prompt_gate_strategy_calls_app(self) -> None:
        """register_prompt_gate_strategy registers with the app."""
        app = MagicMock()

        register_prompt_gate_strategy(app)

        app.register_gate_strategy.assert_called_once()
        call_args = app.register_gate_strategy.call_args
        assert call_args[0][0] == "prompt"
        assert isinstance(call_args[0][1], PromptGateResolver)


# ─── Tests: Question Building ─────────────────────────────────────────────


class TestBuildQuestion:
    """Tests for the _build_question helper."""

    def test_field_name_converted_to_label(self) -> None:
        """Snake_case field names become capitalized labels."""
        assert _build_question("target_region", "") == "Target region"

    def test_description_included_in_parentheses(self) -> None:
        """Field description is shown in parentheses."""
        result = _build_question("region", "AWS region to deploy to")
        assert result == "Region (AWS region to deploy to)"

    def test_no_description(self) -> None:
        """Without description, just the label is returned."""
        assert _build_question("name", "") == "Name"
