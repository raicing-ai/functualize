"""Unit tests for the PluginLoader."""

import logging
from unittest.mock import MagicMock, patch

from functualize._plugins.loader import (
    PluginLoader,
    PluginMetadata,
    _validate_metadata,
    _validate_pep440,
)


class TestValidatePep440:
    """Tests for PEP 440 version validation."""

    def test_simple_version(self):
        assert _validate_pep440("1.0.0") is True

    def test_two_part_version(self):
        assert _validate_pep440("1.0") is True

    def test_single_part_version(self):
        assert _validate_pep440("1") is True

    def test_pre_release_alpha(self):
        assert _validate_pep440("1.0.0a1") is True

    def test_pre_release_beta(self):
        assert _validate_pep440("2.1.0b3") is True

    def test_pre_release_rc(self):
        assert _validate_pep440("1.0.0rc1") is True

    def test_post_release(self):
        assert _validate_pep440("1.0.0.post1") is True

    def test_dev_release(self):
        assert _validate_pep440("1.0.0.dev0") is True

    def test_epoch(self):
        assert _validate_pep440("1!1.0.0") is True

    def test_invalid_version_letters(self):
        assert _validate_pep440("abc") is False

    def test_invalid_version_empty(self):
        assert _validate_pep440("") is False

    def test_invalid_version_leading_v(self):
        assert _validate_pep440("v1.0.0") is False

    def test_invalid_version_leading_zero(self):
        assert _validate_pep440("01.0.0") is False


class TestValidateMetadata:
    """Tests for plugin metadata validation."""

    def test_valid_metadata(self):
        plugin = MagicMock()
        plugin.name = "my-plugin"
        plugin.version = "1.0.0"
        plugin.description = "A test plugin"
        errors = _validate_metadata(plugin, "test-ep")
        assert errors == []

    def test_missing_name(self):
        plugin = MagicMock(spec=[])
        plugin.version = "1.0.0"
        plugin.description = "A test plugin"
        # Remove name attribute
        del plugin.name
        errors = _validate_metadata(plugin, "test-ep")
        assert any("missing 'name'" in e for e in errors)

    def test_name_too_long(self):
        plugin = MagicMock()
        plugin.name = "x" * 65
        plugin.version = "1.0.0"
        plugin.description = "A test plugin"
        errors = _validate_metadata(plugin, "test-ep")
        assert any("exceeds 64 characters" in e for e in errors)

    def test_name_not_string(self):
        plugin = MagicMock()
        plugin.name = 123
        plugin.version = "1.0.0"
        plugin.description = "A test plugin"
        errors = _validate_metadata(plugin, "test-ep")
        assert any("must be a string" in e for e in errors)

    def test_missing_version(self):
        plugin = MagicMock(spec=[])
        plugin.name = "my-plugin"
        plugin.description = "A test plugin"
        del plugin.version
        errors = _validate_metadata(plugin, "test-ep")
        assert any("missing 'version'" in e for e in errors)

    def test_invalid_version(self):
        plugin = MagicMock()
        plugin.name = "my-plugin"
        plugin.version = "not-a-version"
        plugin.description = "A test plugin"
        errors = _validate_metadata(plugin, "test-ep")
        assert any("PEP 440" in e for e in errors)

    def test_missing_description(self):
        plugin = MagicMock(spec=[])
        plugin.name = "my-plugin"
        plugin.version = "1.0.0"
        del plugin.description
        errors = _validate_metadata(plugin, "test-ep")
        assert any("missing 'description'" in e for e in errors)

    def test_description_too_long(self):
        plugin = MagicMock()
        plugin.name = "my-plugin"
        plugin.version = "1.0.0"
        plugin.description = "x" * 257
        errors = _validate_metadata(plugin, "test-ep")
        assert any("exceeds 256 characters" in e for e in errors)


class TestPluginMetadataProtocol:
    """Tests for the PluginMetadata protocol."""

    def test_satisfies_protocol(self):
        class MyPlugin:
            name = "test"
            version = "1.0.0"
            description = "A test"

            def __call__(self, app):
                pass

        assert isinstance(MyPlugin(), PluginMetadata)

    def test_missing_attribute_fails_protocol(self):
        class BadPlugin:
            name = "test"
            # missing version and description

        assert not isinstance(BadPlugin(), PluginMetadata)


class TestPluginLoader:
    """Tests for the PluginLoader class."""

    def test_init_default_group(self):
        loader = PluginLoader()
        assert loader._group == "functualize.plugins"

    def test_init_custom_group(self):
        loader = PluginLoader(group="my.plugins")
        assert loader._group == "my.plugins"

    def test_loaded_plugins_initially_empty(self):
        loader = PluginLoader()
        assert loader.loaded_plugins == {}

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_successful_plugin(self, mock_entry_points):
        """Test loading a valid plugin successfully."""
        # Create a mock plugin module/callable
        mock_plugin = MagicMock()
        mock_plugin.name = "test-plugin"
        mock_plugin.version = "1.0.0"
        mock_plugin.description = "A test plugin"

        # Create a mock entry point
        mock_ep = MagicMock()
        mock_ep.name = "test-ep"
        mock_ep.load.return_value = mock_plugin

        mock_entry_points.return_value = [mock_ep]

        loader = PluginLoader()
        app = MagicMock()
        loader.load_all(app)

        # Plugin should be called with app
        mock_plugin.assert_called_once_with(app)
        assert "test-plugin" in loader.loaded_plugins
        assert loader.loaded_plugins["test-plugin"] == "test-ep"

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_import_error(self, mock_entry_points, caplog):
        """Test that import errors are handled gracefully."""
        mock_ep = MagicMock()
        mock_ep.name = "bad-ep"
        mock_ep.load.side_effect = ImportError("module not found")

        mock_entry_points.return_value = [mock_ep]

        loader = PluginLoader()
        app = MagicMock()

        with caplog.at_level(logging.WARNING):
            loader.load_all(app)

        assert loader.loaded_plugins == {}
        assert "bad-ep" in caplog.text
        assert "missing dependency" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_module_not_found_error_with_name(self, mock_entry_points, caplog):
        """Test that ModuleNotFoundError includes the module name in the warning."""
        mock_ep = MagicMock()
        mock_ep.name = "tui-plugin"
        err = ModuleNotFoundError("No module named 'textual'")
        err.name = "textual"
        mock_ep.load.side_effect = err

        mock_entry_points.return_value = [mock_ep]

        loader = PluginLoader()
        app = MagicMock()

        with caplog.at_level(logging.WARNING):
            loader.load_all(app)

        assert loader.loaded_plugins == {}
        assert "tui-plugin" in caplog.text
        assert "textual" in caplog.text
        assert "missing dependency" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_non_import_error_uses_generic_message(
        self, mock_entry_points, caplog
    ):
        """Test that non-ImportError load failures use a generic warning message."""
        mock_ep = MagicMock()
        mock_ep.name = "broken-ep"
        mock_ep.load.side_effect = RuntimeError("something went wrong")

        mock_entry_points.return_value = [mock_ep]

        loader = PluginLoader()
        app = MagicMock()

        with caplog.at_level(logging.WARNING):
            loader.load_all(app)

        assert loader.loaded_plugins == {}
        assert "broken-ep" in caplog.text
        assert "failed to load" in caplog.text
        assert "something went wrong" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_invalid_metadata(self, mock_entry_points, caplog):
        """Test that plugins with invalid metadata are skipped."""
        mock_plugin = MagicMock()
        mock_plugin.name = "x" * 65  # Too long
        mock_plugin.version = "1.0.0"
        mock_plugin.description = "A test plugin"

        mock_ep = MagicMock()
        mock_ep.name = "bad-meta-ep"
        mock_ep.load.return_value = mock_plugin

        mock_entry_points.return_value = [mock_ep]

        loader = PluginLoader()
        app = MagicMock()

        with caplog.at_level(logging.WARNING):
            loader.load_all(app)

        assert loader.loaded_plugins == {}
        assert "does not satisfy metadata protocol" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_duplicate_name(self, mock_entry_points, caplog):
        """Test that duplicate plugin names are skipped."""
        mock_plugin1 = MagicMock()
        mock_plugin1.name = "same-name"
        mock_plugin1.version = "1.0.0"
        mock_plugin1.description = "First plugin"

        mock_plugin2 = MagicMock()
        mock_plugin2.name = "same-name"
        mock_plugin2.version = "2.0.0"
        mock_plugin2.description = "Second plugin"

        mock_ep1 = MagicMock()
        mock_ep1.name = "ep1"
        mock_ep1.load.return_value = mock_plugin1

        mock_ep2 = MagicMock()
        mock_ep2.name = "ep2"
        mock_ep2.load.return_value = mock_plugin2

        mock_entry_points.return_value = [mock_ep1, mock_ep2]

        loader = PluginLoader()
        app = MagicMock()

        with caplog.at_level(logging.WARNING):
            loader.load_all(app)

        # Only first should be loaded
        assert loader.loaded_plugins == {"same-name": "ep1"}
        assert "Duplicate plugin name" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_registration_error(self, mock_entry_points, caplog):
        """Test that registration errors are handled gracefully."""
        mock_plugin = MagicMock()
        mock_plugin.name = "error-plugin"
        mock_plugin.version = "1.0.0"
        mock_plugin.description = "A plugin that errors"
        mock_plugin.side_effect = RuntimeError("registration failed")

        mock_ep = MagicMock()
        mock_ep.name = "error-ep"
        mock_ep.load.return_value = mock_plugin

        mock_entry_points.return_value = [mock_ep]

        loader = PluginLoader()
        app = MagicMock()

        with caplog.at_level(logging.WARNING):
            loader.load_all(app)

        assert loader.loaded_plugins == {}
        assert "raised an error during registration" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_continues_after_failures(self, mock_entry_points):
        """Test that loading continues after individual plugin failures."""
        # First plugin fails to import
        mock_ep1 = MagicMock()
        mock_ep1.name = "fail-ep"
        mock_ep1.load.side_effect = ImportError("nope")

        # Second plugin is valid
        mock_plugin2 = MagicMock()
        mock_plugin2.name = "good-plugin"
        mock_plugin2.version = "1.0.0"
        mock_plugin2.description = "A good plugin"

        mock_ep2 = MagicMock()
        mock_ep2.name = "good-ep"
        mock_ep2.load.return_value = mock_plugin2

        mock_entry_points.return_value = [mock_ep1, mock_ep2]

        loader = PluginLoader()
        app = MagicMock()
        loader.load_all(app)

        # Second plugin should still be loaded
        assert "good-plugin" in loader.loaded_plugins

    @patch("functualize._plugins.loader.entry_points")
    def test_load_all_no_plugins(self, mock_entry_points):
        """Test loading when no plugins are discovered."""
        mock_entry_points.return_value = []

        loader = PluginLoader()
        app = MagicMock()
        loader.load_all(app)

        assert loader.loaded_plugins == {}


class TestSurfaceDetection:
    """Tests for surface auto-detection during load_all."""

    def _make_ep(self, plugin_instance):
        """Create a mock entry point that returns plugin_instance."""
        ep = MagicMock()
        ep.name = plugin_instance.name
        ep.load.return_value = plugin_instance
        return ep

    def _make_app(self):
        class _App:
            pass

        app = _App()
        app.event_bus = MagicMock()
        app.event_bus.has_subscribers = False
        app.event_bus.emit = MagicMock()
        app._resolution_chain = MagicMock()
        app.plugin_config_registry = MagicMock()
        return app

    def test_non_surface_plugin_not_added(self):
        """A plugin satisfying neither surface protocol does not create _surfaces."""

        class PlainPlugin:
            name = "plain"
            version = "1.0.0"
            description = "Plain plugin"
            config_model = None
            config_section = "plugin.plain"

            def __call__(self, app):
                pass

        plugin = PlainPlugin()
        ep = self._make_ep(plugin)
        app = self._make_app()

        with patch("functualize._plugins.loader.entry_points", return_value=[ep]):
            loader = PluginLoader()
            loader.load_all(app)

        assert not hasattr(app, "_surfaces")
