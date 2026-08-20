"""Property-based tests for domain auto-selection.

Tests Property 32 from the Phase 2–5 Domain SDKs design document.

Property 32: Domain auto-selection — For any domain where exactly one
implementation plugin is installed and no `provider` config is specified,
the system SHALL auto-select that single implementation as the active provider.

Also tests the related behaviors:
- For N>1 installed providers with no config, raises AINotAvailableError
- For any provider name configured that matches an installed provider,
  selects it correctly

**Validates: Requirements 22.4**
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from functualize_ai._config import AIConfig
from functualize_ai._errors import AINotAvailableError
from functualize_ai._provider_discovery import (
    _auto_select_provider,
    select_ai_provider,
)
from hypothesis import assume, given
from hypothesis import strategies as st

# --- Helpers ---


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint for testing."""

    def __init__(self, name: str, load_result: object | None = None) -> None:
        self.name = name
        self._load_result = load_result if load_result is not None else MagicMock()

    def load(self) -> object:
        if isinstance(self._load_result, Exception):
            raise self._load_result
        return self._load_result


# --- Strategies ---

# Strategy for valid provider names (non-empty, alphanumeric + hyphens/underscores)
provider_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s[0].isalpha())

# Strategy for lists of distinct provider names (at least 2 for multi-provider tests)
multiple_provider_names = st.lists(
    provider_names,
    min_size=2,
    max_size=10,
    unique=True,
)


# --- Property 32: Domain auto-selection ---


class TestSingleProviderAutoSelection:
    """Property 32a: For any single installed provider in the entry point group,
    when no provider is configured in AIConfig (empty string), the system SHALL
    auto-select that single provider.

    **Validates: Requirements 22.4**
    """

    @given(name=provider_names)
    def test_auto_selects_single_installed_provider(self, name: str) -> None:
        """When exactly one provider is installed and no provider is configured,
        the system auto-selects that single implementation.

        **Validates: Requirements 22.4**
        """
        plugin_obj = MagicMock(name=f"Plugin({name})")
        ep = _FakeEntryPoint(name, load_result=plugin_obj)
        providers = {name: ep}

        # No provider configured (empty string means "not set")
        config = AIConfig(provider="")

        result = select_ai_provider(config, available_providers=providers)

        assert result is plugin_obj

    @given(name=provider_names)
    def test_auto_select_provider_returns_loaded_object(self, name: str) -> None:
        """Auto-selection loads the entry point and returns the loaded object,
        regardless of the provider name.

        **Validates: Requirements 22.4**
        """
        plugin_obj = MagicMock(name=f"Plugin({name})")
        ep = _FakeEntryPoint(name, load_result=plugin_obj)
        providers = {name: ep}

        result = _auto_select_provider(providers)

        assert result is plugin_obj


class TestMultipleProvidersNoConfig:
    """Property 32b: For any N>1 installed providers with no config, the system
    SHALL raise AINotAvailableError listing available providers.

    **Validates: Requirements 22.4**
    """

    @given(names=multiple_provider_names)
    def test_raises_when_multiple_providers_no_config(self, names: list[str]) -> None:
        """When multiple providers are installed and no provider is configured,
        the system raises AINotAvailableError.

        **Validates: Requirements 22.4**
        """
        providers = {name: _FakeEntryPoint(name) for name in names}

        config = AIConfig(provider="")

        with pytest.raises(AINotAvailableError):
            select_ai_provider(config, available_providers=providers)

    @given(names=multiple_provider_names)
    def test_error_message_lists_available_providers(self, names: list[str]) -> None:
        """When multiple providers trigger an error, the error message lists
        all available provider names so the user knows what to configure.

        **Validates: Requirements 22.4**
        """
        providers = {name: _FakeEntryPoint(name) for name in names}

        config = AIConfig(provider="")

        with pytest.raises(AINotAvailableError) as exc_info:
            select_ai_provider(config, available_providers=providers)

        error_msg = str(exc_info.value)
        # All provider names should be mentioned in the error
        for name in names:
            assert name in error_msg


class TestExplicitProviderSelection:
    """Property 32c: For any provider name configured that matches an installed
    provider, the system SHALL select it correctly.

    **Validates: Requirements 22.4**
    """

    @given(names=multiple_provider_names, data=st.data())
    def test_explicit_config_selects_correct_provider(
        self, names: list[str], data: st.DataObject
    ) -> None:
        """When a provider name is explicitly configured and matches an installed
        provider, the system selects that specific provider from among multiple.

        **Validates: Requirements 22.4**
        """
        # Create distinct plugin objects for each provider
        plugins = {name: MagicMock(name=f"Plugin({name})") for name in names}
        providers = {
            name: _FakeEntryPoint(name, load_result=plugins[name]) for name in names
        }

        # Pick one provider to configure
        chosen = data.draw(st.sampled_from(names))
        config = AIConfig(provider=chosen)

        result = select_ai_provider(config, available_providers=providers)

        # The result must be exactly the plugin object for the chosen provider
        assert result is plugins[chosen]

    @given(name=provider_names)
    def test_explicit_config_selects_single_provider(self, name: str) -> None:
        """When a provider name is explicitly configured and only one is installed,
        it selects that provider via explicit path (not auto-select).

        **Validates: Requirements 22.4**
        """
        plugin_obj = MagicMock(name=f"Plugin({name})")
        ep = _FakeEntryPoint(name, load_result=plugin_obj)
        providers = {name: ep}

        config = AIConfig(provider=name)

        result = select_ai_provider(config, available_providers=providers)

        assert result is plugin_obj

    @given(
        installed_name=provider_names,
        configured_name=provider_names,
    )
    def test_mismatched_config_raises_not_available(
        self, installed_name: str, configured_name: str
    ) -> None:
        """When a configured provider name does not match any installed provider,
        the system raises AINotAvailableError.

        **Validates: Requirements 22.4**
        """
        assume(installed_name != configured_name)

        providers = {installed_name: _FakeEntryPoint(installed_name)}
        config = AIConfig(provider=configured_name)

        with pytest.raises(AINotAvailableError):
            select_ai_provider(config, available_providers=providers)
