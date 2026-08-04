"""Unit tests for PluginLoader._resolve_plugin_directories()."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from functualize._plugins.loader import PluginLoader


class TestResolvePluginDirectories:
    """Tests for _resolve_plugin_directories method."""

    def setup_method(self):
        self.loader = PluginLoader()

    def test_returns_empty_list_when_no_config_and_no_convention_dir(self, tmp_path):
        """When app has no _resolution_chain and convention dir doesn't exist, return []."""
        app = MagicMock(spec=[])  # No _resolution_chain attribute

        with patch.object(Path, "cwd", return_value=tmp_path):
            result = self.loader._resolve_plugin_directories(app)

        assert result == []

    def test_returns_convention_dir_when_it_exists_and_no_config(self, tmp_path):
        """Convention fallback: .functualize/plugins/ in CWD returned when it exists."""
        app = MagicMock(spec=[])  # No _resolution_chain attribute
        convention_dir = tmp_path / ".functualize" / "plugins"
        convention_dir.mkdir(parents=True)

        with patch.object(Path, "cwd", return_value=tmp_path):
            result = self.loader._resolve_plugin_directories(app)

        assert result == [str(convention_dir)]

    def test_returns_config_paths_as_absolute_when_resolution_chain_available(
        self, tmp_path
    ):
        """When config resolves plugins_directories, return them as absolute paths."""
        resolved_mock = MagicMock()
        resolved_mock.value = ["plugins", "extra/plugins"]

        chain_mock = MagicMock()
        chain_mock.resolve.return_value = resolved_mock

        app = MagicMock()
        app._resolution_chain = chain_mock

        result = self.loader._resolve_plugin_directories(app)

        # Should return absolute paths
        assert len(result) == 2
        for p in result:
            assert Path(p).is_absolute()

        # The paths should be resolved versions of "plugins" and "extra/plugins"
        assert result[0] == str(Path("plugins").resolve())
        assert result[1] == str(Path("extra/plugins").resolve())

    def test_returns_config_single_string_as_list(self, tmp_path):
        """When config returns a single string, it's wrapped in a list."""
        resolved_mock = MagicMock()
        resolved_mock.value = "my_plugins"

        chain_mock = MagicMock()
        chain_mock.resolve.return_value = resolved_mock

        app = MagicMock()
        app._resolution_chain = chain_mock

        result = self.loader._resolve_plugin_directories(app)

        assert len(result) == 1
        assert result[0] == str(Path("my_plugins").resolve())

    def test_falls_through_to_convention_when_config_raises_exception(self, tmp_path):
        """When config resolution raises, suppress it, log debug, and check convention."""
        chain_mock = MagicMock()
        chain_mock.resolve.side_effect = RuntimeError("config error")

        app = MagicMock()
        app._resolution_chain = chain_mock

        convention_dir = tmp_path / ".functualize" / "plugins"
        convention_dir.mkdir(parents=True)

        with (
            patch.object(Path, "cwd", return_value=tmp_path),
            patch("functualize._plugins.loader.logger") as mock_logger,
        ):
            result = self.loader._resolve_plugin_directories(app)

        assert result == [str(convention_dir)]
        mock_logger.debug.assert_called_once_with(
            "Could not resolve plugins_directories from config"
        )

    def test_returns_empty_when_config_raises_and_no_convention(self, tmp_path):
        """When config raises and convention dir doesn't exist, return []."""
        chain_mock = MagicMock()
        chain_mock.resolve.side_effect = RuntimeError("config error")

        app = MagicMock()
        app._resolution_chain = chain_mock

        with (
            patch.object(Path, "cwd", return_value=tmp_path),
            patch("functualize._plugins.loader.logger") as mock_logger,
        ):
            result = self.loader._resolve_plugin_directories(app)

        assert result == []
        mock_logger.debug.assert_called_once_with(
            "Could not resolve plugins_directories from config"
        )

    def test_falls_through_to_convention_when_resolve_returns_none(self, tmp_path):
        """When resolve() returns None/falsy, fall through to convention check."""
        chain_mock = MagicMock()
        chain_mock.resolve.return_value = None

        app = MagicMock()
        app._resolution_chain = chain_mock

        convention_dir = tmp_path / ".functualize" / "plugins"
        convention_dir.mkdir(parents=True)

        with patch.object(Path, "cwd", return_value=tmp_path):
            result = self.loader._resolve_plugin_directories(app)

        assert result == [str(convention_dir)]

    def test_config_paths_include_nonexistent_dirs(self):
        """Config paths that don't exist are still included (filtering is done elsewhere)."""
        resolved_mock = MagicMock()
        resolved_mock.value = ["/nonexistent/path/plugins"]

        chain_mock = MagicMock()
        chain_mock.resolve.return_value = resolved_mock

        app = MagicMock()
        app._resolution_chain = chain_mock

        result = self.loader._resolve_plugin_directories(app)

        assert result == [str(Path("/nonexistent/path/plugins").resolve())]
