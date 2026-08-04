"""Unit tests for RunContext plugin config access (task 6.1)."""

import logging
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from functualize._config.job_config import JobConfigView
from functualize.job._state_store import StateStore
from functualize.job.context import RunContext


class SamplePluginConfig(BaseModel):
    """Sample plugin config model for testing."""

    webhook_url: str = "https://example.com/hook"
    timeout: int = 30
    enabled: bool = True


class AnotherPluginConfig(BaseModel):
    """Another plugin config model for testing."""

    api_key: str = "default-key"
    max_retries: int = 3


@pytest.fixture
def mock_config():
    """Create a mock JobConfigView instance."""
    return MagicMock(spec=JobConfigView)


@pytest.fixture
def mock_logger():
    """Create a mock Logger instance."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def sample_configs():
    """Create sample plugin configs dict."""
    return {
        "plugin.notifications": SamplePluginConfig(),
        "plugin.api": AnotherPluginConfig(api_key="real-key"),
    }


@pytest.fixture
def rc_with_configs(mock_config, mock_logger, sample_configs):
    """RunContext with plugin configs populated."""
    return RunContext(
        name="test-job",
        config=mock_config,
        logger=mock_logger,
        plugin_configs=sample_configs,
    )


@pytest.fixture
def rc_without_configs(mock_config, mock_logger):
    """RunContext without plugin configs (backward compatible)."""
    return RunContext(name="test-job", config=mock_config, logger=mock_logger)


class TestRunContextBackwardCompatibility:
    """Test that new params don't break existing constructor."""

    def test_constructor_without_new_params(self, mock_config, mock_logger):
        """Existing constructor signature still works."""
        rc = RunContext(name="test", config=mock_config, logger=mock_logger)
        assert rc.name == "test"
        assert rc.config is mock_config

    def test_constructor_with_metadata_only(self, mock_config, mock_logger):
        """Constructor with only metadata param still works."""
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            metadata={"custom": "value"},
        )
        assert rc.metadata["custom"] == "value"

    def test_all_existing_properties_preserved(self, rc_without_configs):
        """All existing properties remain accessible."""
        assert rc_without_configs.name == "test-job"
        assert rc_without_configs.config is not None
        assert isinstance(rc_without_configs.metadata, dict)
        assert rc_without_configs.phases == []
        assert rc_without_configs.job_config is None


class TestPluginConfigsProperty:
    """Tests for RunContext.plugin_configs property."""

    def test_returns_mapping_proxy(self, rc_with_configs):
        """plugin_configs returns a MappingProxyType."""
        result = rc_with_configs.plugin_configs
        assert isinstance(result, MappingProxyType)

    def test_contains_registered_sections(self, rc_with_configs):
        """All registered sections are present."""
        configs = rc_with_configs.plugin_configs
        assert "plugin.notifications" in configs
        assert "plugin.api" in configs

    def test_returns_correct_models(self, rc_with_configs):
        """Correct model instances are returned."""
        configs = rc_with_configs.plugin_configs
        assert isinstance(configs["plugin.notifications"], SamplePluginConfig)
        assert isinstance(configs["plugin.api"], AnotherPluginConfig)

    def test_is_immutable(self, rc_with_configs):
        """The mapping cannot be modified from outside."""
        configs = rc_with_configs.plugin_configs
        with pytest.raises(TypeError):
            configs["new_section"] = SamplePluginConfig()  # type: ignore[index]

    def test_empty_when_no_configs_provided(self, rc_without_configs):
        """Returns empty mapping when no plugin configs registered."""
        configs = rc_without_configs.plugin_configs
        assert len(configs) == 0
        assert isinstance(configs, MappingProxyType)

    def test_lazy_initialization(self, mock_config, mock_logger):
        """Internal dict is None until first access."""
        rc = RunContext(name="test", config=mock_config, logger=mock_logger)
        # Access internal directly - should be None before first access
        assert rc._plugin_configs is None
        # Now access the property
        _ = rc.plugin_configs
        # Should be initialized now
        assert rc._plugin_configs is not None


class TestGetPluginConfig:
    """Tests for RunContext.get_plugin_config() method."""

    def test_returns_config_for_registered_section(self, rc_with_configs):
        """Returns the correct config model for a registered section."""
        config = rc_with_configs.get_plugin_config("plugin.notifications")
        assert isinstance(config, SamplePluginConfig)
        assert config.webhook_url == "https://example.com/hook"
        assert config.timeout == 30

    def test_raises_key_error_for_unknown_section(self, rc_with_configs):
        """Raises KeyError when section is not registered."""
        with pytest.raises(KeyError, match="No plugin config for section"):
            rc_with_configs.get_plugin_config("plugin.nonexistent")

    def test_error_message_lists_available_sections(self, rc_with_configs):
        """KeyError message lists available sections."""
        with pytest.raises(KeyError, match="Available:"):
            rc_with_configs.get_plugin_config("plugin.nonexistent")

    def test_raises_key_error_when_no_configs(self, rc_without_configs):
        """Raises KeyError when no configs are registered at all."""
        with pytest.raises(KeyError):
            rc_without_configs.get_plugin_config("plugin.anything")

    def test_returns_config_with_custom_values(self, rc_with_configs):
        """Returns config with custom values from registration."""
        config = rc_with_configs.get_plugin_config("plugin.api")
        assert isinstance(config, AnotherPluginConfig)
        assert config.api_key == "real-key"
        assert config.max_retries == 3


class TestWithPluginConfig:
    """Tests for RunContext.with_plugin_config() method."""

    def test_returns_new_runcontext(self, rc_with_configs):
        """Returns a new RunContext instance."""
        new_rc = rc_with_configs.with_plugin_config("plugin.notifications", timeout=60)
        assert new_rc is not rc_with_configs

    def test_override_applied_in_new_context(self, rc_with_configs):
        """The override is applied in the new RunContext."""
        new_rc = rc_with_configs.with_plugin_config("plugin.notifications", timeout=60)
        config = new_rc.get_plugin_config("plugin.notifications")
        assert config.timeout == 60

    def test_original_unchanged(self, rc_with_configs):
        """The original RunContext's config remains unchanged."""
        rc_with_configs.with_plugin_config("plugin.notifications", timeout=60)
        original_config = rc_with_configs.get_plugin_config("plugin.notifications")
        assert original_config.timeout == 30

    def test_non_overridden_fields_preserved(self, rc_with_configs):
        """Fields not overridden retain their original values."""
        new_rc = rc_with_configs.with_plugin_config("plugin.notifications", timeout=60)
        config = new_rc.get_plugin_config("plugin.notifications")
        assert config.webhook_url == "https://example.com/hook"
        assert config.enabled is True

    def test_other_sections_preserved(self, rc_with_configs):
        """Other plugin config sections are preserved unchanged."""
        new_rc = rc_with_configs.with_plugin_config("plugin.notifications", timeout=60)
        api_config = new_rc.get_plugin_config("plugin.api")
        assert api_config.api_key == "real-key"

    def test_raises_key_error_for_unknown_section(self, rc_with_configs):
        """Raises KeyError for unregistered section."""
        with pytest.raises(KeyError):
            rc_with_configs.with_plugin_config("plugin.nonexistent", value=1)

    def test_raises_validation_error_for_invalid_overrides(self, rc_with_configs):
        """Raises ValidationError when overrides fail Pydantic validation."""
        with pytest.raises(ValidationError):
            rc_with_configs.with_plugin_config(
                "plugin.notifications", timeout="not-an-int"
            )

    def test_new_context_preserves_name(self, rc_with_configs):
        """The new RunContext preserves the original name."""
        new_rc = rc_with_configs.with_plugin_config("plugin.notifications", timeout=60)
        assert new_rc.name == rc_with_configs.name

    def test_new_context_shares_state_store(self, mock_config, mock_logger):
        """The new RunContext shares the same state_store reference."""
        store = StateStore()
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            plugin_configs={"plugin.notifications": SamplePluginConfig()},
            state_store=store,
        )
        new_rc = rc.with_plugin_config("plugin.notifications", timeout=99)
        assert new_rc._state_store is store


class TestConstructorNewParams:
    """Tests for new optional constructor parameters."""

    def test_plugin_configs_param(self, mock_config, mock_logger):
        """plugin_configs kwarg populates the property."""
        configs = {"section": SamplePluginConfig()}
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            plugin_configs=configs,
        )
        assert rc.get_plugin_config("section").timeout == 30

    def test_state_store_param(self, mock_config, mock_logger):
        """state_store kwarg is stored for later use."""
        store = StateStore()
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            state_store=store,
        )
        assert rc._state_store is store

    def test_resources_param(self, mock_config, mock_logger):
        """resources kwarg is stored for later use."""
        resources = {"db": "fake-client"}
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            resources=resources,
        )
        assert rc._resources is resources

    def test_all_new_params_together(self, mock_config, mock_logger):
        """All new params work together."""
        store = StateStore()
        configs = {"section": SamplePluginConfig()}
        resources = {"db": "client"}
        rc = RunContext(
            name="test",
            config=mock_config,
            logger=mock_logger,
            plugin_configs=configs,
            state_store=store,
            resources=resources,
        )
        assert rc._plugin_configs is configs
        assert rc._state_store is store
        assert rc._resources is resources
