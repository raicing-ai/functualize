"""Functional tests for functualize-ai-pydantic plugin.

Tests provider registration, tool translation (functualize→pydantic-ai shape),
and configuration parsing. All LLM calls are mocked — no API key required.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from functualize_ai._config import AIConfig
from functualize_ai._types import ToolDef
from functualize_ai_pydantic import (
    PydanticAIPlugin,
    PydanticAIProvider,
    ToolScopeTranslator,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ai_config() -> AIConfig:
    """Minimal AIConfig for testing without real API calls."""
    return AIConfig(
        provider="pydantic",
        model="test-model",
        max_tokens=1024,
        timeout_seconds=30,
    )


@pytest.fixture
def provider(ai_config: AIConfig) -> PydanticAIProvider:
    """A PydanticAIProvider initialized with test config."""
    return PydanticAIProvider(ai_config)


@pytest.fixture
def translator() -> ToolScopeTranslator:
    """A fresh ToolScopeTranslator instance."""
    return ToolScopeTranslator()


# ---------------------------------------------------------------------------
# Tests: Provider Registration (Plugin metadata & wiring)
# ---------------------------------------------------------------------------


class TestProviderRegistration:
    """Tests for PydanticAIPlugin registration and metadata."""

    def test_plugin_has_correct_metadata(self) -> None:
        """Plugin exposes name, version, description, and domain attributes."""
        plugin = PydanticAIPlugin()

        assert plugin.name == "ai-pydantic"
        assert plugin.version == "0.1.0"
        assert plugin.domain == "ai"
        assert "PydanticAI" in plugin.description

    def test_plugin_registers_hook_on_call(self) -> None:
        """Calling the plugin with an app registers the APP_READY hook."""
        plugin = PydanticAIPlugin()

        # Create a fake app with a mock hook_registry
        fake_hook_registry = MagicMock()
        fake_app = MagicMock()
        fake_app.hook_registry = fake_hook_registry

        plugin(fake_app)

        # Verify that register_global was called with HookEvent.APP_READY
        fake_hook_registry.register_global.assert_called_once()
        call_args = fake_hook_registry.register_global.call_args
        # First positional arg is the HookEvent
        from functualize._events.hooks import HookEvent

        assert call_args[0][0] == HookEvent.APP_READY


# ---------------------------------------------------------------------------
# Tests: Tool Translation (functualize ToolDef → PydanticAI Tool shape)
# ---------------------------------------------------------------------------


class TestToolTranslation:
    """Tests for ToolScopeTranslator converting ToolDef to PydanticAI Tools."""

    def test_translate_single_tool_with_schema(
        self, translator: ToolScopeTranslator
    ) -> None:
        """A ToolDef with a function and schema produces a PydanticAI Tool."""

        def greet(name: str) -> str:
            return f"Hello, {name}"

        tool_def = ToolDef(
            name="greet",
            description="Greet a user by name",
            parameters_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            function=greet,
        )

        result = translator.translate([tool_def])

        assert len(result) == 1
        tool = result[0]
        # PydanticAI Tool exposes name and description
        assert tool.name == "greet"
        assert tool.description == "Greet a user by name"

    def test_translate_multiple_tools(self, translator: ToolScopeTranslator) -> None:
        """Multiple ToolDefs are translated into corresponding PydanticAI Tools."""

        def add(a: int, b: int) -> int:
            return a + b

        def multiply(x: int, y: int) -> int:
            return x * y

        tool_defs = [
            ToolDef(
                name="add",
                description="Add two numbers",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                },
                function=add,
            ),
            ToolDef(
                name="multiply",
                description="Multiply two numbers",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                    },
                },
                function=multiply,
            ),
        ]

        result = translator.translate(tool_defs)

        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"add", "multiply"}

    def test_translate_skips_tool_without_function(
        self, translator: ToolScopeTranslator
    ) -> None:
        """A ToolDef with function=None is skipped (returns empty list)."""
        tool_def = ToolDef(
            name="no_fn",
            description="Tool with no backing function",
            parameters_schema={"type": "object", "properties": {}},
            function=None,
        )

        result = translator.translate([tool_def])

        assert result == []


# ---------------------------------------------------------------------------
# Tests: Config Parsing (AIConfig → PydanticAIProvider initialization)
# ---------------------------------------------------------------------------


class TestConfigParsing:
    """Tests for PydanticAIProvider configuration handling."""

    def test_provider_stores_config(self, ai_config: AIConfig) -> None:
        """Provider stores the AIConfig and creates a ToolScopeTranslator."""
        provider = PydanticAIProvider(ai_config)

        assert provider._config is ai_config
        assert isinstance(provider._translator, ToolScopeTranslator)

    def test_provider_default_config(self) -> None:
        """Provider works with default AIConfig values."""
        config = AIConfig()  # All defaults
        provider = PydanticAIProvider(config)

        assert provider._config.model == "claude-sonnet-4-20250514"
        assert provider._config.max_tokens == 4096
        assert provider._config.timeout_seconds == 120

    def test_run_with_empty_messages_raises_value_error(self) -> None:
        """PydanticAI.run_with_history raises ValueError on empty messages."""
        from functualize_ai_pydantic import PydanticAI

        pydantic_ai = PydanticAI(
            _provider=MagicMock(),
            _model="test-model",
        )

        with pytest.raises(ValueError, match="messages list must not be empty"):
            pydantic_ai.run_with_history(messages=[])
