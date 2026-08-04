"""Unit tests for the PluginConfigRegistry."""

import pytest
from pydantic import BaseModel

from functualize._plugins.config import PluginConfigRegistry


class SampleConfig(BaseModel):
    """A sample plugin config model for testing."""

    host: str = "localhost"
    port: int = 8080


class AnotherConfig(BaseModel):
    """Another sample config model."""

    enabled: bool = True
    timeout: float = 30.0


class TestPluginConfigRegistry:
    """Tests for PluginConfigRegistry."""

    def test_register_and_get(self) -> None:
        registry = PluginConfigRegistry()
        config = SampleConfig(host="example.com", port=9090)
        registry.register("plugin.sample", config, "sample-plugin")

        result = registry.get("plugin.sample")
        assert result is config

    def test_register_multiple_sections(self) -> None:
        registry = PluginConfigRegistry()
        config1 = SampleConfig()
        config2 = AnotherConfig()

        registry.register("plugin.sample", config1, "sample-plugin")
        registry.register("plugin.another", config2, "another-plugin")

        assert registry.get("plugin.sample") is config1
        assert registry.get("plugin.another") is config2

    def test_has_returns_true_for_registered(self) -> None:
        registry = PluginConfigRegistry()
        config = SampleConfig()
        registry.register("plugin.sample", config, "sample-plugin")

        assert registry.has("plugin.sample") is True

    def test_has_returns_false_for_unregistered(self) -> None:
        registry = PluginConfigRegistry()
        assert registry.has("plugin.missing") is False

    def test_get_all_returns_copy(self) -> None:
        registry = PluginConfigRegistry()
        config1 = SampleConfig()
        config2 = AnotherConfig()

        registry.register("plugin.sample", config1, "sample-plugin")
        registry.register("plugin.another", config2, "another-plugin")

        all_configs = registry.get_all()
        assert all_configs == {"plugin.sample": config1, "plugin.another": config2}

        # Verify it's a copy - mutating it doesn't affect registry
        all_configs["plugin.new"] = SampleConfig()
        assert not registry.has("plugin.new")

    def test_get_all_empty(self) -> None:
        registry = PluginConfigRegistry()
        assert registry.get_all() == {}

    def test_duplicate_section_raises_value_error(self) -> None:
        registry = PluginConfigRegistry()
        config1 = SampleConfig()
        config2 = AnotherConfig()

        registry.register("plugin.shared", config1, "first-plugin")

        with pytest.raises(ValueError, match="already registered") as exc_info:
            registry.register("plugin.shared", config2, "second-plugin")

        error_msg = str(exc_info.value)
        assert "first-plugin" in error_msg
        assert "second-plugin" in error_msg
        assert "plugin.shared" in error_msg

    def test_get_unregistered_section_raises_key_error(self) -> None:
        registry = PluginConfigRegistry()
        config = SampleConfig()
        registry.register("plugin.sample", config, "sample-plugin")

        with pytest.raises(KeyError, match="No plugin config registered") as exc_info:
            registry.get("plugin.missing")

        error_msg = str(exc_info.value)
        assert "plugin.missing" in error_msg
        assert "plugin.sample" in error_msg  # lists available sections

    def test_get_empty_registry_raises_key_error(self) -> None:
        registry = PluginConfigRegistry()

        with pytest.raises(KeyError, match="Available sections: \\[\\]"):
            registry.get("plugin.any")
