"""Edge cases for FilePluginSource — directory scanning and file loading.

Tests plugin directory resolution and loading with real Python files using tmp_path.
Validates Requirements: 12.1–12.10, 13.1–13.7
"""

import logging

from functualize._plugins.file_source import FilePluginSource


class TestDiscoverFromFilesNonExistentDirectory:
    """A directory that does not exist is skipped, not fatal."""

    def test_nonexistent_directory_logs_debug_and_skips(self, tmp_path, caplog):
        """When a resolved plugin dir doesn't exist, log debug and skip it."""
        source = FilePluginSource()

        nonexistent = str(tmp_path / "does_not_exist")

        with caplog.at_level(logging.DEBUG, logger="functualize._plugins.file_source"):
            result = source.discover([nonexistent])

        assert result == []
        assert "Plugin directory does not exist" in caplog.text
        assert nonexistent in caplog.text


class TestDiscoverFromFilesUnderscorePrefixed:
    """Underscore-prefixed files are not plugins."""

    def test_skips_underscore_prefixed_files(self, tmp_path):
        """Files starting with _ are skipped during discovery."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        # Create a valid plugin file
        valid_plugin = plugin_dir / "good_plugin.py"
        valid_plugin.write_text(
            "class MyPlugin:\n"
            '    name = "good"\n'
            '    version = "1.0.0"\n'
            '    description = "Good plugin"\n'
            "    def __call__(self, app): pass\n"
            "plugin = MyPlugin()\n"
        )

        # Create underscore-prefixed files that should be skipped
        (plugin_dir / "_helper.py").write_text("# helper module\n")
        (plugin_dir / "__init__.py").write_text("# init\n")
        (plugin_dir / "_private_plugin.py").write_text(
            "class Secret:\n"
            '    name = "secret"\n'
            '    version = "1.0.0"\n'
            '    description = "Should not load"\n'
            "    def __call__(self, app): pass\n"
            "plugin = Secret()\n"
        )

        source = FilePluginSource()

        result = source.discover([str(plugin_dir)])

        # Only the valid plugin (not underscore-prefixed) should be loaded
        assert len(result) == 1
        assert result[0].name == "good"


class TestLoadFilePluginWithPluginAttribute:
    """A module-level `plugin` attribute is used directly."""

    def test_uses_plugin_attribute_when_present(self, tmp_path):
        """When a module defines a module-level `plugin`, it is used directly."""
        plugin_file = tmp_path / "my_plugin.py"
        plugin_file.write_text(
            "class _InternalPlugin:\n"
            '    name = "explicit-plugin"\n'
            '    version = "2.0.0"\n'
            '    description = "Plugin via explicit attribute"\n'
            "    def __call__(self, app): pass\n"
            "\n"
            "plugin = _InternalPlugin()\n"
        )

        source = FilePluginSource()
        result = source._load_file_plugin(plugin_file)

        assert result is not None
        assert result.name == "explicit-plugin"
        assert result.version == "2.0.0"
        assert result.description == "Plugin via explicit attribute"


class TestLoadFilePluginWithoutPluginAttribute:
    """Test _load_file_plugin() with fallback to PluginMetadata inspection."""

    def test_finds_plugin_via_protocol_inspection(self, tmp_path):
        """When no `plugin` attr exists, inspect module for PluginMetadata objects."""
        plugin_file = tmp_path / "auto_plugin.py"
        plugin_file.write_text(
            "class AutoPlugin:\n"
            '    name = "auto-discovered"\n'
            '    version = "0.5.0"\n'
            '    description = "Auto-discovered via inspection"\n'
            "    def __call__(self, app): pass\n"
            "\n"
            "my_instance = AutoPlugin()\n"
        )

        source = FilePluginSource()
        result = source._load_file_plugin(plugin_file)

        assert result is not None
        assert result.name == "auto-discovered"
        assert result.version == "0.5.0"

    def test_returns_none_when_no_candidate_found(self, tmp_path):
        """When no plugin attr and no PluginMetadata object, return None."""
        plugin_file = tmp_path / "empty_module.py"
        plugin_file.write_text(
            "# This module has no plugin-like objects\nx = 42\ndef helper(): pass\n"
        )

        source = FilePluginSource()
        result = source._load_file_plugin(plugin_file)

        assert result is None


class TestLoadFilePluginInvalidMetadata:
    """Test _load_file_plugin() with invalid metadata."""

    def test_invalid_metadata_returns_none_and_logs_warning(self, tmp_path, caplog):
        """Plugin with invalid metadata (e.g., name too long) returns None with warning."""
        plugin_file = tmp_path / "bad_meta.py"
        plugin_file.write_text(
            "class BadPlugin:\n"
            '    name = "' + "x" * 65 + '"\n'
            '    version = "1.0.0"\n'
            '    description = "Has too-long name"\n'
            "    def __call__(self, app): pass\n"
            "\n"
            "plugin = BadPlugin()\n"
        )

        source = FilePluginSource()

        with caplog.at_level(
            logging.WARNING, logger="functualize._plugins.file_source"
        ):
            result = source._load_file_plugin(plugin_file)

        assert result is None
        assert "invalid" in caplog.text.lower()
        assert "exceeds 64 characters" in caplog.text

    def test_invalid_version_returns_none_and_logs_warning(self, tmp_path, caplog):
        """Plugin with non-PEP-440 version returns None with warning."""
        plugin_file = tmp_path / "bad_version.py"
        plugin_file.write_text(
            "class BadVersion:\n"
            '    name = "bad-ver"\n'
            '    version = "not-a-version"\n'
            '    description = "Has bad version"\n'
            "    def __call__(self, app): pass\n"
            "\n"
            "plugin = BadVersion()\n"
        )

        source = FilePluginSource()

        with caplog.at_level(
            logging.WARNING, logger="functualize._plugins.file_source"
        ):
            result = source._load_file_plugin(plugin_file)

        assert result is None
        assert "PEP 440" in caplog.text


class TestLoadFilePluginImportError:
    """Test _load_file_plugin() with import errors."""

    def test_syntax_error_returns_none_and_logs_warning(self, tmp_path, caplog):
        """File with syntax error returns None and logs warning."""
        plugin_file = tmp_path / "syntax_error.py"
        plugin_file.write_text(
            "class Broken:\n"
            '    name = "broken"\n'
            "    def __call__(self app):  # missing comma -> syntax error\n"
            "        pass\n"
        )

        source = FilePluginSource()

        with caplog.at_level(
            logging.WARNING, logger="functualize._plugins.file_source"
        ):
            result = source._load_file_plugin(plugin_file)

        assert result is None
        assert "Failed to load file plugin" in caplog.text
        assert str(plugin_file) in caplog.text

    def test_runtime_import_error_returns_none_and_logs_warning(self, tmp_path, caplog):
        """File that raises an error during import returns None and logs warning."""
        plugin_file = tmp_path / "import_crash.py"
        plugin_file.write_text(
            "import nonexistent_module_xyz_abc\n"
            "\n"
            "class NeverReached:\n"
            '    name = "never"\n'
            '    version = "1.0.0"\n'
            '    description = "Never loaded"\n'
            "    def __call__(self, app): pass\n"
            "plugin = NeverReached()\n"
        )

        source = FilePluginSource()

        with caplog.at_level(
            logging.WARNING, logger="functualize._plugins.file_source"
        ):
            result = source._load_file_plugin(plugin_file)

        assert result is None
        assert "Failed to load file plugin" in caplog.text

    def test_exception_during_module_exec_returns_none(self, tmp_path, caplog):
        """File that raises RuntimeError during exec returns None."""
        plugin_file = tmp_path / "runtime_crash.py"
        plugin_file.write_text('raise RuntimeError("deliberate crash during import")\n')

        source = FilePluginSource()

        with caplog.at_level(
            logging.WARNING, logger="functualize._plugins.file_source"
        ):
            result = source._load_file_plugin(plugin_file)

        assert result is None
        assert "Failed to load file plugin" in caplog.text
        assert "deliberate crash during import" in caplog.text


class TestDiscoverFromFilesDuplicateNames:
    """Same-name duplicates: first alphabetically wins."""

    def test_first_alphabetically_wins_and_warning_logged(self, tmp_path, caplog):
        """When two files export same plugin name, first alphabetically wins."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        # Create two plugin files with the same plugin name
        # "alpha.py" sorts before "beta.py"
        (plugin_dir / "alpha.py").write_text(
            "class AlphaPlugin:\n"
            '    name = "duplicate-name"\n'
            '    version = "1.0.0"\n'
            '    description = "From alpha file"\n'
            "    def __call__(self, app): pass\n"
            "plugin = AlphaPlugin()\n"
        )

        (plugin_dir / "beta.py").write_text(
            "class BetaPlugin:\n"
            '    name = "duplicate-name"\n'
            '    version = "2.0.0"\n'
            '    description = "From beta file"\n'
            "    def __call__(self, app): pass\n"
            "plugin = BetaPlugin()\n"
        )

        source = FilePluginSource()

        with (
            caplog.at_level(logging.WARNING, logger="functualize._plugins.file_source"),
        ):
            result = source.discover([str(plugin_dir)])

        # Only the first alphabetically should be loaded
        assert len(result) == 1
        assert result[0].name == "duplicate-name"
        assert result[0].description == "From alpha file"

        # Warning about duplicate
        assert "Duplicate file plugin name" in caplog.text
        assert "duplicate-name" in caplog.text


class TestDiscoverFromFilesCaseInsensitiveSorting:
    """Test that file discovery uses case-insensitive sorting."""

    def test_case_insensitive_alphabetical_ordering(self, tmp_path):
        """Files are sorted case-insensitively for deterministic ordering."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        # Create files with mixed case that would sort differently
        # with case-sensitive vs case-insensitive sort.
        # Case-sensitive ASCII sort: A < B < Z < a < b < z
        # Case-insensitive sort: a/A < b/B < z/Z
        (plugin_dir / "Zebra.py").write_text(
            "class ZebraPlugin:\n"
            '    name = "zebra"\n'
            '    version = "1.0.0"\n'
            '    description = "Zebra"\n'
            "    def __call__(self, app): pass\n"
            "plugin = ZebraPlugin()\n"
        )

        (plugin_dir / "alpha.py").write_text(
            "class AlphaPlugin:\n"
            '    name = "alpha"\n'
            '    version = "1.0.0"\n'
            '    description = "Alpha"\n'
            "    def __call__(self, app): pass\n"
            "plugin = AlphaPlugin()\n"
        )

        (plugin_dir / "Beta.py").write_text(
            "class BetaPlugin:\n"
            '    name = "beta"\n'
            '    version = "1.0.0"\n'
            '    description = "Beta"\n'
            "    def __call__(self, app): pass\n"
            "plugin = BetaPlugin()\n"
        )

        source = FilePluginSource()

        result = source.discover([str(plugin_dir)])

        # Case-insensitive sort: alpha < Beta < Zebra
        assert len(result) == 3
        names = [p.name for p in result]
        assert names == ["alpha", "beta", "zebra"]

    def test_case_insensitive_duplicate_resolution(self, tmp_path, caplog):
        """When duplicates exist, case-insensitive sort determines which is first."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        # "Aardvark.py" and "aardvark_alt.py" both export same name
        # Case-insensitive: "Aardvark.py" < "aardvark_alt.py"
        (plugin_dir / "aardvark_alt.py").write_text(
            "class AltPlugin:\n"
            '    name = "shared-name"\n'
            '    version = "2.0.0"\n'
            '    description = "Alt version"\n'
            "    def __call__(self, app): pass\n"
            "plugin = AltPlugin()\n"
        )

        (plugin_dir / "Aardvark.py").write_text(
            "class MainPlugin:\n"
            '    name = "shared-name"\n'
            '    version = "1.0.0"\n'
            '    description = "Main version"\n'
            "    def __call__(self, app): pass\n"
            "plugin = MainPlugin()\n"
        )

        source = FilePluginSource()

        with (
            caplog.at_level(logging.WARNING, logger="functualize._plugins.file_source"),
        ):
            result = source.discover([str(plugin_dir)])

        # "Aardvark.py" sorts before "aardvark_alt.py" case-insensitively
        assert len(result) == 1
        assert result[0].description == "Main version"
        assert "Duplicate file plugin name" in caplog.text
