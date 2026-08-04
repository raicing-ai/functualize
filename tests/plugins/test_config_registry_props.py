"""Property-based tests for Config Section Uniqueness Enforcement.

Tests Property 5 (Config Section Uniqueness Enforcement) using Hypothesis.

**Validates: Requirements 1.6**
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from functualize._plugins.config import PluginConfigRegistry

# --- Strategies ---

# Strategy for valid config section names (dot-separated identifiers)
section_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="._-"
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s[0].isalpha())

# Strategy for valid plugin names
plugin_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
    ),
    min_size=1,
    max_size=40,
).filter(lambda s: s[0].isalpha())


# --- Test helpers ---


class DummyConfigA(BaseModel):
    """A dummy config model for testing."""

    host: str = "localhost"
    port: int = 8080


class DummyConfigB(BaseModel):
    """Another dummy config model for testing."""

    enabled: bool = True
    timeout: float = 30.0


# --- Property 5: Config Section Uniqueness Enforcement ---


class TestConfigSectionUniquenessEnforcement:
    """Property 5: If two plugins declare the same config_section value,
    the PluginLoader SHALL raise a descriptive error identifying both plugin
    names and the conflicting section name at load time.

    **Validates: Requirements 1.6**
    """

    @settings(max_examples=100)
    @given(
        section_a=section_names,
        section_b=section_names,
        plugin_a=plugin_names,
        plugin_b=plugin_names,
    )
    def test_different_sections_always_succeed(
        self,
        section_a: str,
        section_b: str,
        plugin_a: str,
        plugin_b: str,
    ) -> None:
        """Registering two configs with different section names always succeeds."""
        assume(section_a != section_b)

        registry = PluginConfigRegistry()
        config_a = DummyConfigA()
        config_b = DummyConfigB()

        # Both registrations should succeed without raising
        registry.register(section_a, config_a, plugin_a)
        registry.register(section_b, config_b, plugin_b)

        # Both configs should be retrievable
        assert registry.get(section_a) is config_a
        assert registry.get(section_b) is config_b

    @settings(max_examples=100)
    @given(
        section=section_names,
        plugin_a=plugin_names,
        plugin_b=plugin_names,
    )
    def test_same_section_always_raises_value_error(
        self,
        section: str,
        plugin_a: str,
        plugin_b: str,
    ) -> None:
        """Registering two configs with the SAME section name always raises
        ValueError."""
        registry = PluginConfigRegistry()
        config_a = DummyConfigA()
        config_b = DummyConfigB()

        registry.register(section, config_a, plugin_a)

        with pytest.raises(ValueError):
            registry.register(section, config_b, plugin_b)

    @settings(max_examples=100)
    @given(
        section=section_names,
        plugin_a=plugin_names,
        plugin_b=plugin_names,
    )
    def test_error_message_contains_both_plugins_and_section(
        self,
        section: str,
        plugin_a: str,
        plugin_b: str,
    ) -> None:
        """The ValueError message always contains both plugin names and the
        section name."""
        registry = PluginConfigRegistry()
        config_a = DummyConfigA()
        config_b = DummyConfigB()

        registry.register(section, config_a, plugin_a)

        with pytest.raises(ValueError) as exc_info:
            registry.register(section, config_b, plugin_b)

        error_msg = str(exc_info.value)
        assert plugin_a in error_msg, (
            f"Expected original plugin name '{plugin_a}' in error: {error_msg}"
        )
        assert plugin_b in error_msg, (
            f"Expected conflicting plugin name '{plugin_b}' in error: {error_msg}"
        )
        assert section in error_msg, (
            f"Expected section name '{section}' in error: {error_msg}"
        )

    @settings(max_examples=100)
    @given(
        section=section_names,
        plugin_a=plugin_names,
        plugin_b=plugin_names,
    )
    def test_original_config_unchanged_after_failed_duplicate(
        self,
        section: str,
        plugin_a: str,
        plugin_b: str,
    ) -> None:
        """After a failed duplicate registration, the original config remains
        unchanged in the registry."""
        registry = PluginConfigRegistry()
        config_a = DummyConfigA(host="original.example.com", port=9999)
        config_b = DummyConfigB()

        registry.register(section, config_a, plugin_a)

        with pytest.raises(ValueError):
            registry.register(section, config_b, plugin_b)

        # Original config is still accessible and unchanged
        retrieved = registry.get(section)
        assert retrieved is config_a
        assert retrieved.host == "original.example.com"
        assert retrieved.port == 9999

        # Registry state is consistent
        assert registry.has(section)
        all_configs = registry.get_all()
        assert len(all_configs) == 1
        assert all_configs[section] is config_a
