"""Unit tests for file-based discovery integration in load_all()."""

import logging
from unittest.mock import MagicMock, patch

from functualize._plugins.loader import PluginLoader


class TestFileDiscoveryIntegration:
    """Tests for _discover_from_files integration into load_all() and precedence."""

    @patch("functualize._plugins.loader.entry_points")
    def test_file_plugins_loaded_when_no_entry_points(self, mock_entry_points, caplog):
        """File plugins are loaded and registered when no entry-point plugins exist."""
        mock_entry_points.return_value = []

        # Create a mock file plugin
        file_plugin = MagicMock()
        file_plugin.name = "file-only-plugin"
        file_plugin.version = "1.0.0"
        file_plugin.description = "A file-only plugin"

        loader = PluginLoader()
        app = MagicMock()

        with patch.object(loader, "_discover_from_files", return_value=[file_plugin]):
            loader.load_all(app)

        file_plugin.assert_called_once_with(app)
        assert "file-only-plugin" in loader.loaded_plugins
        assert loader.loaded_plugins["file-only-plugin"] == "file:file-only-plugin"

    @patch("functualize._plugins.loader.entry_points")
    def test_file_plugins_merged_with_entry_point_plugins(self, mock_entry_points):
        """Both entry-point and file plugins are loaded when no name collision."""
        # Entry-point plugin
        ep_plugin = MagicMock()
        ep_plugin.name = "ep-plugin"
        ep_plugin.version = "1.0.0"
        ep_plugin.description = "An entry-point plugin"

        mock_ep = MagicMock()
        mock_ep.name = "ep-ep"
        mock_ep.load.return_value = ep_plugin
        mock_entry_points.return_value = [mock_ep]

        # File plugin
        file_plugin = MagicMock()
        file_plugin.name = "file-plugin"
        file_plugin.version = "0.1.0"
        file_plugin.description = "A file plugin"

        loader = PluginLoader()
        app = MagicMock()

        with patch.object(loader, "_discover_from_files", return_value=[file_plugin]):
            loader.load_all(app)

        # Both should be registered
        ep_plugin.assert_called_once_with(app)
        file_plugin.assert_called_once_with(app)
        assert "ep-plugin" in loader.loaded_plugins
        assert "file-plugin" in loader.loaded_plugins

    @patch("functualize._plugins.loader.entry_points")
    def test_entry_point_takes_precedence_on_name_collision(
        self, mock_entry_points, caplog
    ):
        """Entry-point plugin wins when it has the same name as a file plugin."""
        # Entry-point plugin
        ep_plugin = MagicMock()
        ep_plugin.name = "my-plugin"
        ep_plugin.version = "2.0.0"
        ep_plugin.description = "Entry-point version"

        mock_ep = MagicMock()
        mock_ep.name = "my-ep"
        mock_ep.load.return_value = ep_plugin
        mock_entry_points.return_value = [mock_ep]

        # File plugin with same name
        file_plugin = MagicMock()
        file_plugin.name = "my-plugin"
        file_plugin.version = "1.0.0"
        file_plugin.description = "File version"

        loader = PluginLoader()
        app = MagicMock()

        with (
            patch.object(loader, "_discover_from_files", return_value=[file_plugin]),
            caplog.at_level(logging.WARNING),
        ):
            loader.load_all(app)

        # Entry-point plugin registered, file plugin skipped
        ep_plugin.assert_called_once_with(app)
        file_plugin.assert_not_called()
        assert "my-plugin" in loader.loaded_plugins
        assert loader.loaded_plugins["my-plugin"] == "my-ep"

        # Warning about collision
        assert "File plugin 'my-plugin' collides with entry-point" in caplog.text
        assert "Skipping" in caplog.text

    @patch("functualize._plugins.loader.entry_points")
    def test_multiple_file_plugins_collision_only_colliding_skipped(
        self, mock_entry_points, caplog
    ):
        """Only the colliding file plugin is skipped; others are still loaded."""
        # Entry-point plugin
        ep_plugin = MagicMock()
        ep_plugin.name = "collider"
        ep_plugin.version = "1.0.0"
        ep_plugin.description = "EP collider"

        mock_ep = MagicMock()
        mock_ep.name = "collider-ep"
        mock_ep.load.return_value = ep_plugin
        mock_entry_points.return_value = [mock_ep]

        # File plugins: one collides, one doesn't
        file_plugin_collides = MagicMock()
        file_plugin_collides.name = "collider"
        file_plugin_collides.version = "0.1.0"
        file_plugin_collides.description = "File collider"

        file_plugin_unique = MagicMock()
        file_plugin_unique.name = "unique-file-plugin"
        file_plugin_unique.version = "0.2.0"
        file_plugin_unique.description = "Unique file plugin"

        loader = PluginLoader()
        app = MagicMock()

        with (
            patch.object(
                loader,
                "_discover_from_files",
                return_value=[file_plugin_collides, file_plugin_unique],
            ),
            caplog.at_level(logging.WARNING),
        ):
            loader.load_all(app)

        # EP plugin and unique file plugin loaded; colliding file plugin skipped
        ep_plugin.assert_called_once_with(app)
        file_plugin_collides.assert_not_called()
        file_plugin_unique.assert_called_once_with(app)
        assert "collider" in loader.loaded_plugins
        assert "unique-file-plugin" in loader.loaded_plugins
        assert loader.loaded_plugins["collider"] == "collider-ep"
        assert loader.loaded_plugins["unique-file-plugin"] == "file:unique-file-plugin"

    @patch("functualize._plugins.loader.entry_points")
    def test_no_plugins_from_either_source_returns_early(self, mock_entry_points):
        """When no plugins found from either source, load_all returns without error."""
        mock_entry_points.return_value = []

        loader = PluginLoader()
        app = MagicMock()

        with patch.object(loader, "_discover_from_files", return_value=[]):
            loader.load_all(app)

        assert loader.loaded_plugins == {}

    @patch("functualize._plugins.loader.entry_points")
    def test_file_plugins_participate_in_topological_sort(self, mock_entry_points):
        """File plugins are included in the topological sort with entry-point plugins."""
        # Entry-point plugin
        ep_plugin = MagicMock()
        ep_plugin.name = "base-plugin"
        ep_plugin.version = "1.0.0"
        ep_plugin.description = "Base plugin"
        ep_plugin.depends_on = []

        mock_ep = MagicMock()
        mock_ep.name = "base-ep"
        mock_ep.load.return_value = ep_plugin
        mock_entry_points.return_value = [mock_ep]

        # File plugin that depends on entry-point plugin
        file_plugin = MagicMock()
        file_plugin.name = "dependent-plugin"
        file_plugin.version = "1.0.0"
        file_plugin.description = "Depends on base"
        file_plugin.depends_on = ["base-plugin"]

        loader = PluginLoader()
        app = MagicMock()

        with patch.object(loader, "_discover_from_files", return_value=[file_plugin]):
            loader.load_all(app)

        # Both should be loaded (topological sort handles ordering)
        assert "base-plugin" in loader.loaded_plugins
        assert "dependent-plugin" in loader.loaded_plugins
