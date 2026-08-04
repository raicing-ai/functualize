"""Unit tests for AI provider discovery and auto-selection.

Tests the logic in functualize_ai._provider_discovery that reads the
[ai] config section and selects an AI provider plugin from the
functualize.ai_providers entry point group.

Validates: Requirements 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from functualize_ai._config import AIConfig
from functualize_ai._errors import AINotAvailableError
from functualize_ai._provider_discovery import (
    ENTRY_POINT_GROUP,
    _auto_select_provider,
    _load_entry_point,
    _select_explicit_provider,
    discover_ai_providers,
    resolve_ai_provider,
    select_ai_provider,
)


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint for testing."""

    def __init__(self, name: str, load_result: object | None = None) -> None:
        self.name = name
        self._load_result = load_result

    def load(self) -> object:
        if self._load_result is None:
            return MagicMock(name=f"MockPlugin({self.name})")
        if isinstance(self._load_result, Exception):
            raise self._load_result
        return self._load_result


class TestDiscoverAiProviders:
    """Test discover_ai_providers scans the correct entry point group."""

    @patch("functualize_ai._provider_discovery.importlib.metadata.entry_points")
    def test_discovers_providers_from_entry_point_group(
        self, mock_entry_points: MagicMock
    ) -> None:
        """discover_ai_providers queries the correct entry point group."""
        ep1 = _FakeEntryPoint("pydantic")
        ep2 = _FakeEntryPoint("openai")
        mock_entry_points.return_value = [ep1, ep2]

        result = discover_ai_providers()

        mock_entry_points.assert_called_once_with(group=ENTRY_POINT_GROUP)
        assert "pydantic" in result
        assert "openai" in result
        assert result["pydantic"] is ep1
        assert result["openai"] is ep2

    @patch("functualize_ai._provider_discovery.importlib.metadata.entry_points")
    def test_returns_empty_when_no_providers_installed(
        self, mock_entry_points: MagicMock
    ) -> None:
        """Returns empty dict when no providers are installed."""
        mock_entry_points.return_value = []

        result = discover_ai_providers()

        assert result == {}


class TestSelectExplicitProvider:
    """Test selecting a provider by explicit name from config."""

    def test_selects_matching_provider(self) -> None:
        """Loads the named provider when it exists in available providers."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        providers = {"pydantic": ep}

        result = _select_explicit_provider("pydantic", providers)

        assert result is plugin_obj

    def test_raises_when_provider_not_found(self) -> None:
        """Raises AINotAvailableError when the configured provider is not installed."""
        ep = _FakeEntryPoint("openai")
        providers = {"openai": ep}

        with pytest.raises(AINotAvailableError, match="pydantic.*not found"):
            _select_explicit_provider("pydantic", providers)

    def test_raises_with_available_list_when_not_found(self) -> None:
        """Error message lists available providers."""
        providers = {
            "openai": _FakeEntryPoint("openai"),
            "anthropic": _FakeEntryPoint("anthropic"),
        }

        with pytest.raises(AINotAvailableError) as exc_info:
            _select_explicit_provider("pydantic", providers)

        msg = str(exc_info.value)
        assert "anthropic" in msg
        assert "openai" in msg

    def test_raises_install_instructions_when_empty(self) -> None:
        """Raises with install instructions when no providers available."""
        with pytest.raises(AINotAvailableError, match="Install one"):
            _select_explicit_provider("pydantic", {})


class TestAutoSelectProvider:
    """Test auto-selection logic when no provider is configured."""

    def test_auto_selects_single_installed_provider(self) -> None:
        """When exactly one provider is installed, auto-selects it."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        providers = {"pydantic": ep}

        result = _auto_select_provider(providers)

        assert result is plugin_obj

    def test_raises_when_no_providers_installed(self) -> None:
        """Raises AINotAvailableError with install instructions when none available."""
        with pytest.raises(AINotAvailableError, match="Install one"):
            _auto_select_provider({})

    def test_raises_when_multiple_providers_no_config(self) -> None:
        """Raises AINotAvailableError when multiple providers but no config."""
        providers = {
            "pydantic": _FakeEntryPoint("pydantic"),
            "openai": _FakeEntryPoint("openai"),
        }

        with pytest.raises(AINotAvailableError, match="Multiple AI provider"):
            _auto_select_provider(providers)

    def test_error_lists_available_providers_when_multiple(self) -> None:
        """Error message includes names of available providers."""
        providers = {
            "pydantic": _FakeEntryPoint("pydantic"),
            "openai": _FakeEntryPoint("openai"),
        }

        with pytest.raises(AINotAvailableError) as exc_info:
            _auto_select_provider(providers)

        msg = str(exc_info.value)
        assert "openai" in msg
        assert "pydantic" in msg


class TestLoadEntryPoint:
    """Test entry point loading with error handling."""

    def test_loads_successfully(self) -> None:
        """Successfully loads and returns the plugin object."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)

        result = _load_entry_point(ep)

        assert result is plugin_obj

    def test_raises_ai_not_available_on_load_failure(self) -> None:
        """Wraps load errors in AINotAvailableError."""
        ep = _FakeEntryPoint("broken", load_result=ImportError("missing dep"))

        with pytest.raises(AINotAvailableError, match="Failed to load"):
            _load_entry_point(ep)


class TestSelectAiProvider:
    """Integration test for the full select_ai_provider flow."""

    def test_explicit_provider_selection(self) -> None:
        """Uses explicit provider name from config.

        Validates: Requirement 12.2
        """
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        config = AIConfig(provider="pydantic")

        result = select_ai_provider(config, available_providers={"pydantic": ep})

        assert result is plugin_obj

    def test_auto_selection_single_provider(self) -> None:
        """Auto-selects when only one provider and no config.

        Validates: Requirement 12.3
        """
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        config = AIConfig(provider="")

        result = select_ai_provider(config, available_providers={"pydantic": ep})

        assert result is plugin_obj

    def test_raises_when_no_providers(self) -> None:
        """Raises with install instructions when nothing installed.

        Validates: Requirement 12.4
        """
        config = AIConfig(provider="")

        with pytest.raises(AINotAvailableError, match="Install one"):
            select_ai_provider(config, available_providers={})


class TestResolveAiProvider:
    """Test the top-level resolve_ai_provider convenience function."""

    @patch("functualize_ai._provider_discovery.discover_ai_providers")
    def test_with_explicit_config(self, mock_discover: MagicMock) -> None:
        """Uses provided config without needing an app instance."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        mock_discover.return_value = {"pydantic": ep}

        config = AIConfig(provider="pydantic")
        result = resolve_ai_provider(config=config)

        assert result is plugin_obj

    @patch("functualize_ai._provider_discovery.discover_ai_providers")
    def test_with_app_resolve_model(self, mock_discover: MagicMock) -> None:
        """Reads config from app's resolution chain when no config provided."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        mock_discover.return_value = {"pydantic": ep}

        mock_app = MagicMock()
        mock_app.resolve_model.return_value = AIConfig(provider="pydantic")

        result = resolve_ai_provider(mock_app)

        mock_app.resolve_model.assert_called_once_with("ai", AIConfig)
        assert result is plugin_obj

    @patch("functualize_ai._provider_discovery.discover_ai_providers")
    def test_defaults_config_when_app_resolve_fails(
        self, mock_discover: MagicMock
    ) -> None:
        """Falls back to default AIConfig when app resolution fails."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        mock_discover.return_value = {"pydantic": ep}

        mock_app = MagicMock()
        mock_app.resolve_model.side_effect = Exception("no config")

        # Default config has provider="pydantic", so it should try explicit selection
        result = resolve_ai_provider(mock_app)

        assert result is plugin_obj

    @patch("functualize_ai._provider_discovery.discover_ai_providers")
    def test_defaults_config_when_no_app(self, mock_discover: MagicMock) -> None:
        """Uses default AIConfig when no app is provided."""
        plugin_obj = MagicMock()
        ep = _FakeEntryPoint("pydantic", load_result=plugin_obj)
        mock_discover.return_value = {"pydantic": ep}

        # Default AIConfig has provider="pydantic"
        result = resolve_ai_provider()

        assert result is plugin_obj
