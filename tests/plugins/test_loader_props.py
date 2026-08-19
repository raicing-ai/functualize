"""Property-based tests for Plugin Config Protocol Detection, Resolution Precedence,
and Missing Required Field ValidationError.

Tests Property 1 (Plugin Config Protocol Detection),
Property 3 (Config Resolution Precedence), and
Property 4 (Missing Required Field Raises ValidationError) using Hypothesis.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.2, 2.4**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from functualize._plugins.config import PluginConfigRegistry
from functualize._plugins.loader import (
    PluginLoader,
    _has_config_declaration,
    _resolve_plugin_config,
)

# --- Strategies ---

# Strategy for valid config section names (dot-separated identifiers)
section_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="._-"
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s[0].isalpha())


# --- Test helpers ---


class SampleConfig(BaseModel):
    """A sample config model for testing resolution."""

    host: str = "localhost"
    port: int = 8080
    enabled: bool = True


class AnotherConfig(BaseModel):
    """Another config model with different fields."""

    name: str = "default"
    timeout: float = 30.0
    retries: int = 3


# Strategy to generate arbitrary resolved config instances
def _sample_config_strategy() -> st.SearchStrategy[SampleConfig]:
    return st.builds(
        SampleConfig,
        host=st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Nd"), whitelist_characters=".-"
            ),
            min_size=1,
            max_size=30,
        ),
        port=st.integers(min_value=1, max_value=65535),
        enabled=st.booleans(),
    )


def _another_config_strategy() -> st.SearchStrategy[AnotherConfig]:
    return st.builds(
        AnotherConfig,
        name=st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
            ),
            min_size=1,
            max_size=30,
        ),
        timeout=st.floats(min_value=0.1, max_value=300.0, allow_nan=False),
        retries=st.integers(min_value=0, max_value=10),
    )


# --- Property 1: Plugin Config Protocol Detection ---


class TestPluginConfigProtocolDetection:
    """Property 1: Plugins with both `config_model` (a type[BaseModel]) and
    `config_section` (a str) are detected as config-declaring. Plugins without
    either attribute, or with only one, are not detected. Legacy plugins load
    identically without config resolution.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """

    @given(
        section=section_names,
    )
    def test_plugin_with_both_config_model_and_section_is_detected(
        self,
        section: str,
    ) -> None:
        """A plugin exposing both config_model (a type[BaseModel]) and
        config_section (a str) is detected as config-declaring."""
        plugin = MagicMock()
        plugin.config_model = SampleConfig  # type[BaseModel]
        plugin.config_section = section  # str

        assert _has_config_declaration(plugin) is True

    @given(
        section=section_names,
    )
    def test_plugin_with_another_model_and_section_is_detected(
        self,
        section: str,
    ) -> None:
        """Detection works for any type[BaseModel] subclass, not just one
        specific model."""
        plugin = MagicMock()
        plugin.config_model = AnotherConfig  # Different BaseModel subclass
        plugin.config_section = section

        assert _has_config_declaration(plugin) is True

    @given(
        data=st.data(),
    )
    def test_plugin_without_either_attribute_is_not_detected(
        self,
        data: st.DataObject,
    ) -> None:
        """Plugins without config_model AND without config_section are not
        detected as config-declaring."""
        # Create a bare object without config attributes
        plugin = MagicMock(spec=[])
        # Ensure both attributes are absent
        assert not hasattr(plugin, "config_model")
        assert not hasattr(plugin, "config_section")

        assert _has_config_declaration(plugin) is False

    @given(
        section=section_names,
    )
    def test_plugin_with_only_config_section_is_not_detected(
        self,
        section: str,
    ) -> None:
        """Plugins with only config_section (no config_model) are not
        detected as config-declaring."""
        plugin = MagicMock(spec=["config_section"])
        plugin.config_section = section

        assert _has_config_declaration(plugin) is False

    @given(
        data=st.data(),
    )
    def test_plugin_with_only_config_model_is_not_detected(
        self,
        data: st.DataObject,
    ) -> None:
        """Plugins with only config_model (no config_section) are not
        detected as config-declaring."""
        plugin = MagicMock(spec=["config_model"])
        plugin.config_model = SampleConfig

        assert _has_config_declaration(plugin) is False

    @given(
        section=section_names,
    )
    def test_plugin_with_non_type_config_model_is_not_detected(
        self,
        section: str,
    ) -> None:
        """If config_model is not a type (e.g., an instance), the plugin is
        not detected as config-declaring."""
        plugin = MagicMock()
        plugin.config_model = SampleConfig()  # Instance, not class
        plugin.config_section = section

        assert _has_config_declaration(plugin) is False

    @given(
        non_str_section=st.integers(),
    )
    def test_plugin_with_non_str_config_section_is_not_detected(
        self,
        non_str_section: int,
    ) -> None:
        """If config_section is not a str (e.g., an int), the plugin is not
        detected as config-declaring."""
        plugin = MagicMock()
        plugin.config_model = SampleConfig
        plugin.config_section = non_str_section  # Not a string

        assert _has_config_declaration(plugin) is False

    @given(
        plugin_name=st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
            ),
            min_size=1,
            max_size=40,
        ).filter(lambda s: s[0].isalpha()),
    )
    def test_legacy_plugin_loads_without_config_resolution(
        self,
        plugin_name: str,
    ) -> None:
        """Legacy plugins (no config_model/config_section) load identically
        via __call__(app) without triggering config resolution."""
        # Create a legacy plugin: valid metadata but no config attributes
        mock_plugin = MagicMock(spec=["name", "version", "description", "__call__"])
        mock_plugin.name = plugin_name
        mock_plugin.version = "1.0.0"
        mock_plugin.description = "A legacy plugin"
        mock_plugin.depends_on = []

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = mock_plugin

        app = MagicMock()
        app.plugin_config_registry = PluginConfigRegistry()

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        # Plugin __call__ should have been invoked
        mock_plugin.assert_called_once_with(app)
        # Plugin should be loaded
        assert plugin_name in loader.loaded_plugins
        # No config resolution should have happened (resolve_model not called)
        app.resolve_model.assert_not_called()
        # Registry should be empty
        assert not app.plugin_config_registry.has(plugin_name)

    @given(
        section=section_names,
        plugin_name=st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
            ),
            min_size=1,
            max_size=40,
        ).filter(lambda s: s[0].isalpha()),
    )
    def test_config_declaring_plugin_triggers_resolution(
        self,
        section: str,
        plugin_name: str,
    ) -> None:
        """Plugins with both config_model and config_section trigger config
        resolution via the loader pipeline (contrasting with legacy behavior)."""
        resolved_config = SampleConfig()

        mock_plugin = MagicMock()
        mock_plugin.name = plugin_name
        mock_plugin.version = "1.0.0"
        mock_plugin.description = "A config plugin"
        mock_plugin.config_model = SampleConfig
        mock_plugin.config_section = section
        mock_plugin.depends_on = []
        # Remove on_config_resolved to avoid PluginWithConfigResolved check
        del mock_plugin.on_config_resolved

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = mock_plugin

        app = MagicMock()
        app.plugin_config_registry = PluginConfigRegistry()
        app.resolve_model.return_value = resolved_config

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        # Plugin should be loaded
        assert plugin_name in loader.loaded_plugins
        # resolve_model should have been called with the section and model class
        app.resolve_model.assert_called_once_with(section, SampleConfig)
        # Config should be stored in registry
        assert app.plugin_config_registry.has(section)


# --- Property 3: Config Resolution Precedence ---


class TestConfigResolutionPrecedence:
    """Property 3: The Resolution_Chain is invoked with the correct section
    name and model class, whatever value app.resolve_model returns becomes
    the stored config, and the framework does not override or modify the
    resolved values — it's a passthrough.

    **Validates: Requirements 2.2**
    """

    @given(
        section=section_names,
        config=_sample_config_strategy(),
    )
    def test_resolve_model_called_with_correct_section_and_model_class(
        self,
        section: str,
        config: SampleConfig,
    ) -> None:
        """_resolve_plugin_config invokes app.resolve_model with the plugin's
        config_section and config_model exactly."""
        plugin = MagicMock()
        plugin.config_section = section
        plugin.config_model = SampleConfig

        app = MagicMock()
        app.resolve_model.return_value = config

        _resolve_plugin_config(plugin, app)

        app.resolve_model.assert_called_once_with(section, SampleConfig)

    @given(
        section=section_names,
        config=_sample_config_strategy(),
    )
    def test_resolved_value_is_passthrough(
        self,
        section: str,
        config: SampleConfig,
    ) -> None:
        """Whatever app.resolve_model returns is the exact value returned by
        _resolve_plugin_config — no modification or wrapping occurs."""
        plugin = MagicMock()
        plugin.config_section = section
        plugin.config_model = SampleConfig

        app = MagicMock()
        app.resolve_model.return_value = config

        result = _resolve_plugin_config(plugin, app)

        assert result is config, (
            f"Expected exact same instance from resolve_model, "
            f"got {result!r} instead of {config!r}"
        )

    @given(
        section=section_names,
        config=_another_config_strategy(),
    )
    def test_resolved_values_are_unmodified(
        self,
        section: str,
        config: AnotherConfig,
    ) -> None:
        """The framework does not mutate or override any fields on the
        resolved config model instance."""
        # Record original values before resolution
        original_name = config.name
        original_timeout = config.timeout
        original_retries = config.retries

        plugin = MagicMock()
        plugin.config_section = section
        plugin.config_model = AnotherConfig

        app = MagicMock()
        app.resolve_model.return_value = config

        result = _resolve_plugin_config(plugin, app)

        # The returned instance has identical field values
        assert result.name == original_name
        assert result.timeout == original_timeout
        assert result.retries == original_retries

    @given(
        section=section_names,
    )
    def test_resolve_model_return_value_becomes_stored_config(
        self,
        section: str,
    ) -> None:
        """When _resolve_plugin_config is used within the loader pipeline,
        the return value of app.resolve_model becomes exactly the config
        stored in the registry — verifying end-to-end passthrough."""
        # Create a sentinel object to verify identity
        sentinel_config = SampleConfig(host="sentinel.test", port=12345, enabled=False)

        plugin = MagicMock()
        plugin.config_section = section
        plugin.config_model = SampleConfig

        app = MagicMock()
        app.resolve_model.return_value = sentinel_config

        result = _resolve_plugin_config(plugin, app)

        # Verify identity — the exact object returned by resolve_model
        assert result is sentinel_config
        # Verify the section was passed correctly
        call_args = app.resolve_model.call_args
        assert call_args[0][0] == section
        assert call_args[0][1] is SampleConfig

    @given(
        section_a=section_names,
        section_b=section_names,
        config_a=_sample_config_strategy(),
        config_b=_another_config_strategy(),
    )
    def test_different_plugins_resolve_independently(
        self,
        section_a: str,
        section_b: str,
        config_a: SampleConfig,
        config_b: AnotherConfig,
    ) -> None:
        """Each plugin's resolution uses its own section and model class,
        demonstrating that the Resolution_Chain is invoked with the correct
        per-plugin parameters."""
        plugin_a = MagicMock()
        plugin_a.config_section = section_a
        plugin_a.config_model = SampleConfig

        plugin_b = MagicMock()
        plugin_b.config_section = section_b
        plugin_b.config_model = AnotherConfig

        app = MagicMock()

        # Configure resolve_model to return different configs based on args
        def side_effect(section: str, model_cls: type[Any]) -> Any:
            if section == section_a and model_cls is SampleConfig:
                return config_a
            if section == section_b and model_cls is AnotherConfig:
                return config_b
            raise AssertionError(f"Unexpected call: ({section}, {model_cls})")

        app.resolve_model.side_effect = side_effect

        result_a = _resolve_plugin_config(plugin_a, app)
        result_b = _resolve_plugin_config(plugin_b, app)

        assert result_a is config_a
        assert result_b is config_b


# --- Helpers for Property 2 ---

# Strategy for valid plugin names (≤64 chars, starts with alpha)
plugin_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"
    ),
    min_size=1,
    max_size=40,
).filter(lambda s: s[0].isalpha())

# Strategy for string config values
config_str_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=100,
)

# Strategy for integer config values (ports / general ints)
config_int_values = st.integers(min_value=0, max_value=65535)

# Strategy for boolean config values
config_bool_values = st.booleans()


class SimpleConfig(BaseModel):
    """A simple config model for testing resolution round-trip."""

    host: str = "localhost"
    port: int = 8080
    enabled: bool = True


class ExtendedConfig(BaseModel):
    """An extended config model with more field types."""

    name: str = "default"
    timeout: int = 30
    debug: bool = False


def _make_config_plugin(
    name: str,
    section: str,
    config_model: type[BaseModel],
    *,
    has_on_config_resolved: bool = False,
) -> Any:
    """Create a mock plugin that declares config requirements."""
    plugin = MagicMock()
    plugin.name = name
    plugin.version = "1.0.0"
    plugin.description = "A config plugin"
    plugin.config_model = config_model
    plugin.config_section = section
    # Ensure depends_on is absent by default (no dependency ordering needed)
    plugin.depends_on = []

    if has_on_config_resolved:
        plugin.on_config_resolved = MagicMock()
    else:
        # Remove the attribute so isinstance check for PluginWithConfigResolved fails
        del plugin.on_config_resolved

    return plugin


def _make_app_mock(
    resolved_configs: dict[str, BaseModel] | None = None,
) -> MagicMock:
    """Create a mock app with a resolve_model method and plugin_config_registry."""
    app = MagicMock()
    registry = PluginConfigRegistry()
    app.plugin_config_registry = registry

    resolved = resolved_configs or {}

    def resolve_model(section: str, model_cls: type[Any]) -> Any:
        if section in resolved:
            return resolved[section]
        # Default: return model with defaults
        return model_cls()

    app.resolve_model = MagicMock(side_effect=resolve_model)
    return app


# --- Property 2: Plugin Config Resolution Round-Trip ---


class TestPluginConfigResolutionRoundTrip:
    """Property 2: When a plugin declares a config_model and the app resolves it,
    the resolved instance is stored in the PluginConfigRegistry, retrievable by
    section name and with the correct type. on_config_resolved is called with the
    resolved config if the plugin implements PluginWithConfigResolved. Resolution
    uses the app's resolve_model method with the correct section and model class.

    **Validates: Requirements 2.1, 2.3, 1.5**
    """

    @given(
        section=section_names,
        plugin_name=plugin_names,
        host=config_str_values,
        port=config_int_values,
        enabled=config_bool_values,
    )
    def test_resolved_config_stored_in_registry(
        self,
        section: str,
        plugin_name: str,
        host: str,
        port: int,
        enabled: bool,
    ) -> None:
        """When a plugin declares a config_model and the app resolves it,
        the resolved instance is stored in the PluginConfigRegistry keyed
        by config_section."""
        # Create a resolved config instance with the generated values
        resolved_config = SimpleConfig(host=host, port=port, enabled=enabled)

        # Create plugin and app mock
        plugin = _make_config_plugin(plugin_name, section, SimpleConfig)
        app = _make_app_mock(resolved_configs={section: resolved_config})

        # Create entry point mock
        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        # The config should be stored in the registry
        registry: PluginConfigRegistry = app.plugin_config_registry
        assert registry.has(section)
        stored = registry.get(section)
        assert stored is resolved_config

    @given(
        section=section_names,
        plugin_name=plugin_names,
        host=config_str_values,
        port=config_int_values,
        enabled=config_bool_values,
    )
    def test_stored_config_retrievable_by_section_with_correct_type(
        self,
        section: str,
        plugin_name: str,
        host: str,
        port: int,
        enabled: bool,
    ) -> None:
        """The stored config instance is retrievable by section name and
        is an instance of the declared config_model type."""
        resolved_config = SimpleConfig(host=host, port=port, enabled=enabled)

        plugin = _make_config_plugin(plugin_name, section, SimpleConfig)
        app = _make_app_mock(resolved_configs={section: resolved_config})

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        registry: PluginConfigRegistry = app.plugin_config_registry
        stored = registry.get(section)

        # Must be an instance of the declared config model
        assert isinstance(stored, SimpleConfig)
        # Field values should match
        assert stored.host == host
        assert stored.port == port
        assert stored.enabled == enabled

    @given(
        section=section_names,
        plugin_name=plugin_names,
        host=config_str_values,
        port=config_int_values,
    )
    def test_on_config_resolved_called_with_resolved_instance(
        self,
        section: str,
        plugin_name: str,
        host: str,
        port: int,
    ) -> None:
        """on_config_resolved is called with the resolved config instance
        if the plugin implements PluginWithConfigResolved."""
        resolved_config = SimpleConfig(host=host, port=port)

        plugin = _make_config_plugin(
            plugin_name, section, SimpleConfig, has_on_config_resolved=True
        )
        app = _make_app_mock(resolved_configs={section: resolved_config})

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        # on_config_resolved should have been called exactly once
        plugin.on_config_resolved.assert_called_once_with(resolved_config)

    @given(
        section=section_names,
        plugin_name=plugin_names,
    )
    def test_on_config_resolved_not_called_without_protocol(
        self,
        section: str,
        plugin_name: str,
    ) -> None:
        """on_config_resolved is NOT called when the plugin does not
        implement PluginWithConfigResolved (no on_config_resolved attr)."""
        resolved_config = SimpleConfig()

        plugin = _make_config_plugin(
            plugin_name, section, SimpleConfig, has_on_config_resolved=False
        )
        app = _make_app_mock(resolved_configs={section: resolved_config})

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        # on_config_resolved should not exist / not be called
        assert not hasattr(plugin, "on_config_resolved")

    @given(
        section=section_names,
        plugin_name=plugin_names,
        name_val=config_str_values,
        timeout_val=config_int_values,
        debug_val=config_bool_values,
    )
    def test_resolve_model_called_with_correct_section_and_model(
        self,
        section: str,
        plugin_name: str,
        name_val: str,
        timeout_val: int,
        debug_val: bool,
    ) -> None:
        """Resolution uses the app's resolve_model method with the correct
        section and model class arguments."""
        resolved_config = ExtendedConfig(
            name=name_val, timeout=timeout_val, debug=debug_val
        )

        plugin = _make_config_plugin(plugin_name, section, ExtendedConfig)
        app = _make_app_mock(resolved_configs={section: resolved_config})

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        # resolve_model must have been called with the plugin's section and model class
        app.resolve_model.assert_called_once_with(section, ExtendedConfig)

    @given(
        section=section_names,
        plugin_name=plugin_names,
    )
    def test_config_with_all_defaults_resolves_successfully(
        self,
        section: str,
        plugin_name: str,
    ) -> None:
        """When all fields have defaults, config resolution succeeds using
        only the declared defaults (zero external configuration required)."""
        # resolve_model returns model with defaults (simulating no external config)
        plugin = _make_config_plugin(plugin_name, section, SimpleConfig)
        app = _make_app_mock()  # No explicit resolved configs; defaults are used

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            loader.load_all(app)

        registry: PluginConfigRegistry = app.plugin_config_registry
        assert registry.has(section)
        stored = registry.get(section)
        assert isinstance(stored, SimpleConfig)
        # Should have default values
        assert stored.host == "localhost"
        assert stored.port == 8080
        assert stored.enabled is True


# --- Property 4: Missing Required Field Raises ValidationError ---


class RequiredFieldConfig(BaseModel):
    """A config model with a required field (no default) for testing ValidationError."""

    api_key: str  # Required: no default
    timeout: int = 30


class TestMissingRequiredFieldRaisesValidationError:
    """Property 4: When app.resolve_model() raises a Pydantic ValidationError
    (e.g., due to a missing required field), the error propagates from the
    PluginLoader. Additionally, on_config_resolved is NOT called when
    resolution fails.

    **Validates: Requirements 2.4**
    """

    @given(
        section=section_names,
        plugin_name=plugin_names,
    )
    def test_validation_error_propagates_from_loader(
        self,
        section: str,
        plugin_name: str,
    ) -> None:
        """When app.resolve_model() raises a pydantic ValidationError,
        the error propagates from the PluginLoader's load_all method."""
        # Create a ValidationError by attempting to construct model without required field
        try:
            RequiredFieldConfig()  # type: ignore[call-arg]
        except ValidationError as e:
            validation_error = e

        plugin = _make_config_plugin(plugin_name, section, RequiredFieldConfig)
        app = MagicMock()
        registry = PluginConfigRegistry()
        app.plugin_config_registry = registry

        # Configure resolve_model to raise the ValidationError
        app.resolve_model.side_effect = validation_error

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            with pytest.raises(ValidationError):
                loader.load_all(app)

    @given(
        section=section_names,
        plugin_name=plugin_names,
    )
    def test_on_config_resolved_not_called_when_resolution_fails(
        self,
        section: str,
        plugin_name: str,
    ) -> None:
        """on_config_resolved is NOT called when app.resolve_model() raises
        a ValidationError — the plugin never receives an invalid config."""
        # Create a ValidationError
        try:
            RequiredFieldConfig()  # type: ignore[call-arg]
        except ValidationError as e:
            validation_error = e

        plugin = _make_config_plugin(
            plugin_name, section, RequiredFieldConfig, has_on_config_resolved=True
        )
        app = MagicMock()
        registry = PluginConfigRegistry()
        app.plugin_config_registry = registry

        # Configure resolve_model to raise the ValidationError
        app.resolve_model.side_effect = validation_error

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            with pytest.raises(ValidationError):
                loader.load_all(app)

        # on_config_resolved must NOT have been called
        plugin.on_config_resolved.assert_not_called()

    @given(
        section=section_names,
        plugin_name=plugin_names,
        timeout=st.integers(min_value=1, max_value=300),
    )
    def test_validation_error_contains_field_information(
        self,
        section: str,
        plugin_name: str,
        timeout: int,
    ) -> None:
        """The propagated ValidationError identifies the missing required field,
        regardless of the section name or other valid field values provided."""
        # Create a ValidationError by attempting to construct model without required field
        try:
            RequiredFieldConfig()  # type: ignore[call-arg]
        except ValidationError as e:
            validation_error = e

        plugin = _make_config_plugin(plugin_name, section, RequiredFieldConfig)
        app = MagicMock()
        registry = PluginConfigRegistry()
        app.plugin_config_registry = registry
        app.resolve_model.side_effect = validation_error

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            with pytest.raises(ValidationError) as exc_info:
                loader.load_all(app)

        # The ValidationError should contain info about the missing 'api_key' field
        error_str = str(exc_info.value)
        assert "api_key" in error_str

    @given(
        section=section_names,
        plugin_name=plugin_names,
    )
    def test_config_not_registered_when_resolution_fails(
        self,
        section: str,
        plugin_name: str,
    ) -> None:
        """When resolution raises ValidationError, the config is NOT stored
        in the PluginConfigRegistry — partial/invalid state is never persisted."""
        try:
            RequiredFieldConfig()  # type: ignore[call-arg]
        except ValidationError as e:
            validation_error = e

        plugin = _make_config_plugin(plugin_name, section, RequiredFieldConfig)
        app = MagicMock()
        registry = PluginConfigRegistry()
        app.plugin_config_registry = registry
        app.resolve_model.side_effect = validation_error

        mock_ep = MagicMock()
        mock_ep.name = f"ep-{plugin_name}"
        mock_ep.load.return_value = plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            with pytest.raises(ValidationError):
                loader.load_all(app)

        # The registry should NOT have the section registered
        assert not registry.has(section)
