"""Property-based tests for file plugin discovery (Properties 11-13).

Tests Properties 11, 12, and 13 from the design document for the
layered-architecture-lazy-boot spec.

**Validates: Requirements 12.1, 12.2, 12.9, 14.4**
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._plugins.loader import PluginLoader

# --- Strategies ---

# Strategy for valid Python identifiers that are valid filenames
_valid_filename_chars = "abcdefghijklmnopqrstuvwxyz0123456789"

# Strategy for generating valid plugin file stem names (no underscore prefix)
_valid_plugin_stems = st.text(
    alphabet=_valid_filename_chars, min_size=1, max_size=20
).filter(lambda s: s[0].isalpha())

# Strategy for generating underscore-prefixed file stems (should be skipped)
_underscore_prefixed_stems = st.text(
    alphabet=_valid_filename_chars, min_size=1, max_size=20
).map(lambda s: f"_{s}")

# Strategy for valid plugin names (used as the `name` attribute)
_plugin_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=1,
    max_size=30,
).filter(lambda s: s[0].isalpha())


def _write_plugin_file(directory: Path, filename: str, plugin_name: str) -> Path:
    """Write a minimal valid plugin .py file to the directory.

    Args:
        directory: The directory to write the file into.
        filename: The filename (with .py extension).
        plugin_name: The name attribute for the plugin.

    Returns:
        The Path to the written file.
    """
    filepath = directory / filename
    filepath.write_text(
        f"""class _Plugin:
    name = "{plugin_name}"
    version = "1.0.0"
    description = "A test plugin"
    def __call__(self, app): pass

plugin = _Plugin()
""",
        encoding="utf-8",
    )
    return filepath


class _LogCapture(logging.Handler):
    """Simple log handler that captures log records for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


# --- Composite strategies ---


@st.composite
def plugin_directory_structure(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a plugin directory structure with a mix of valid, underscore-prefixed,
    and subdirectory files.

    Returns a dict with:
        - valid_stems: list of file stems that should be discovered (no _ prefix)
        - underscore_stems: list of file stems prefixed with _ (should be skipped)
        - subdir_stems: list of file stems in subdirectories (should NOT be found)
        - plugin_name_map: dict mapping file stem -> plugin name
    """
    # Generate valid plugin file stems (0 to 5)
    num_valid = draw(st.integers(min_value=0, max_value=5))
    valid_stems = draw(
        st.lists(
            _valid_plugin_stems,
            min_size=num_valid,
            max_size=num_valid,
            unique=True,
        )
    )

    # Generate underscore-prefixed stems (0 to 3)
    num_underscore = draw(st.integers(min_value=0, max_value=3))
    underscore_stems = draw(
        st.lists(
            _underscore_prefixed_stems,
            min_size=num_underscore,
            max_size=num_underscore,
            unique=True,
        )
    )

    # Generate subdirectory file stems (0 to 3)
    num_subdir = draw(st.integers(min_value=0, max_value=3))
    subdir_stems = draw(
        st.lists(
            _valid_plugin_stems,
            min_size=num_subdir,
            max_size=num_subdir,
            unique=True,
        )
    )

    # Ensure no overlap between valid and subdir stems
    subdir_stems = [s for s in subdir_stems if s not in valid_stems]

    # Generate unique plugin names for each valid file
    plugin_name_map: dict[str, str] = {}
    used_names: set[str] = set()
    for stem in valid_stems:
        name = draw(_plugin_names.filter(lambda n, used=used_names: n not in used))
        used_names.add(name)
        plugin_name_map[stem] = name

    return {
        "valid_stems": valid_stems,
        "underscore_stems": underscore_stems,
        "subdir_stems": subdir_stems,
        "plugin_name_map": plugin_name_map,
    }


# --- Property 11: File plugin discovery filtering ---


# Feature: layered-architecture-lazy-boot, Property 11: File plugin discovery filtering
class TestFilePluginDiscoveryFiltering:
    """Property 11: File plugin discovery filtering.

    For any plugin directory structure, _discover_from_files() SHALL:
    (a) only scan top-level .py files (non-recursive), and
    (b) skip any file whose name starts with _.
    All other .py files at the top level SHALL be attempted for loading.

    **Validates: Requirements 12.1, 12.2**
    """

    @given(structure=plugin_directory_structure())
    @settings(max_examples=100)
    def test_only_top_level_non_underscore_py_files_are_loaded(
        self, structure: dict[str, Any]
    ):
        """_discover_from_files only loads top-level .py files that don't start with _.

        # Feature: layered-architecture-lazy-boot, Property 11: File plugin discovery filtering
        **Validates: Requirements 12.1, 12.2**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "plugins"
            plugin_dir.mkdir()

            valid_stems = structure["valid_stems"]
            underscore_stems = structure["underscore_stems"]
            subdir_stems = structure["subdir_stems"]
            plugin_name_map = structure["plugin_name_map"]

            # Write valid top-level plugin files
            for stem in valid_stems:
                _write_plugin_file(plugin_dir, f"{stem}.py", plugin_name_map[stem])

            # Write underscore-prefixed files (should be skipped)
            for i, stem in enumerate(underscore_stems):
                _write_plugin_file(plugin_dir, f"{stem}.py", f"underscore-plugin-{i}")

            # Write files in a subdirectory (should NOT be discovered)
            if subdir_stems:
                subdir = plugin_dir / "nested"
                subdir.mkdir()
                for i, stem in enumerate(subdir_stems):
                    _write_plugin_file(subdir, f"{stem}.py", f"nested-plugin-{i}")

            # Create loader and mock app
            loader = PluginLoader()
            app = MagicMock()

            # Mock _resolve_plugin_directories to return our test directory
            with patch.object(
                loader,
                "_resolve_plugin_directories",
                return_value=[str(plugin_dir)],
            ):
                result = loader._discover_from_files(app)

            # Assert: only valid (non-underscore, top-level) files are loaded
            loaded_names = {p.name for p in result}
            expected_names = set(plugin_name_map.values())
            assert loaded_names == expected_names, (
                f"Expected plugins {expected_names}, got {loaded_names}"
            )

            # Assert: no underscore-prefixed or subdirectory plugins are loaded
            for p in result:
                assert not any(
                    p.name == f"underscore-plugin-{i}"
                    for i in range(len(underscore_stems))
                )
                assert not any(
                    p.name == f"nested-plugin-{i}" for i in range(len(subdir_stems))
                )


# --- Property 12: Entry-point plugin precedence on name collision ---


# Feature: layered-architecture-lazy-boot, Property 12: Entry-point plugin precedence on name collision
class TestEntryPointPluginPrecedence:
    """Property 12: Entry-point plugin precedence on name collision.

    For any set of plugins where an entry-point plugin and a file plugin share
    the same name attribute, the entry-point plugin SHALL be loaded and the file
    plugin SHALL be skipped with a warning.

    **Validates: Requirements 12.9**
    """

    @given(
        plugin_name=_plugin_names,
        ep_version=st.sampled_from(["1.0.0", "2.0.0", "0.1.0", "3.5.2"]),
    )
    @settings(max_examples=100)
    def test_entry_point_plugin_takes_precedence_over_file_plugin(
        self,
        plugin_name: str,
        ep_version: str,
    ):
        """Entry-point plugin is loaded when it shares a name with a file plugin.

        # Feature: layered-architecture-lazy-boot, Property 12: Entry-point plugin precedence on name collision
        **Validates: Requirements 12.9**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up log capture
            log_capture = _LogCapture()
            logger = logging.getLogger("functualize._plugins.loader")
            logger.addHandler(log_capture)
            logger.setLevel(logging.WARNING)

            try:
                # Create the entry-point plugin mock
                ep_plugin = MagicMock()
                ep_plugin.name = plugin_name
                ep_plugin.version = ep_version
                ep_plugin.description = "Entry-point plugin"
                ep_plugin.depends_on = []

                mock_ep = MagicMock()
                mock_ep.name = f"ep-{plugin_name}"
                mock_ep.load.return_value = ep_plugin

                # Create a file plugin with the same name
                plugin_dir = Path(tmpdir) / "plugins"
                plugin_dir.mkdir()
                _write_plugin_file(plugin_dir, "collision.py", plugin_name)

                loader = PluginLoader()
                app = MagicMock()
                app.plugin_config_registry = MagicMock()
                app.plugin_config_registry.has.return_value = False

                with (
                    patch(
                        "functualize._plugins.loader.entry_points",
                        return_value=[mock_ep],
                    ),
                    patch.object(
                        loader,
                        "_resolve_plugin_directories",
                        return_value=[str(plugin_dir)],
                    ),
                ):
                    loader.load_all(app)

                # Entry-point plugin MUST be loaded (called with app)
                ep_plugin.assert_called_once_with(app)

                # The loaded plugin must be the entry-point one
                assert plugin_name in loader.loaded_plugins
                assert loader.loaded_plugins[plugin_name] == f"ep-{plugin_name}"

                # A warning about the collision must be logged
                collision_warnings = [
                    m
                    for m in log_capture.messages
                    if "collides with entry-point" in m and plugin_name in m
                ]
                assert len(collision_warnings) > 0, (
                    f"Expected collision warning for '{plugin_name}' in logs, "
                    f"got: {log_capture.messages}"
                )
            finally:
                logger.removeHandler(log_capture)


# --- Property 13: Alphabetical file plugin precedence on same-name duplicate ---


@st.composite
def duplicate_name_file_pairs(draw: st.DrawFn) -> dict[str, Any]:
    """Generate two or more filenames that will export plugins with the same name.

    Returns a dict with:
        - filenames: list of .py filenames (at least 2)
        - plugin_name: the shared plugin name
        - expected_winner: the filename that sorts first (case-insensitive)
    """
    plugin_name = draw(_plugin_names)

    # Generate 2-5 distinct filenames for the duplicate
    num_files = draw(st.integers(min_value=2, max_value=5))
    stems = draw(
        st.lists(
            _valid_plugin_stems, min_size=num_files, max_size=num_files, unique=True
        )
    )

    filenames = [f"{stem}.py" for stem in stems]

    # The winner is the one that sorts first case-insensitively
    sorted_filenames = sorted(filenames, key=lambda f: f.lower())
    expected_winner = sorted_filenames[0]

    return {
        "filenames": filenames,
        "plugin_name": plugin_name,
        "expected_winner": expected_winner,
    }


# Feature: layered-architecture-lazy-boot, Property 13: Alphabetical file plugin precedence on same-name duplicate
class TestAlphabeticalFilePluginPrecedence:
    """Property 13: Alphabetical file plugin precedence on same-name duplicate.

    For any plugin directory containing two or more .py files that export plugins
    with the same name, only the file that sorts first alphabetically (case-insensitive)
    SHALL be loaded, and subsequent duplicates SHALL be skipped with a warning.

    **Validates: Requirements 14.4**
    """

    @given(data=duplicate_name_file_pairs())
    @settings(max_examples=100)
    def test_first_alphabetically_wins_on_same_name(self, data: dict[str, Any]):
        """Only the file sorting first alphabetically (case-insensitive) is loaded.

        # Feature: layered-architecture-lazy-boot, Property 13: Alphabetical file plugin precedence on same-name duplicate
        **Validates: Requirements 14.4**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up log capture
            log_capture = _LogCapture()
            logger = logging.getLogger("functualize._plugins.loader")
            logger.addHandler(log_capture)
            logger.setLevel(logging.WARNING)

            try:
                plugin_dir = Path(tmpdir) / "plugins"
                plugin_dir.mkdir()

                filenames = data["filenames"]
                plugin_name = data["plugin_name"]
                expected_winner = data["expected_winner"]

                # Write all files with the same plugin name
                for filename in filenames:
                    _write_plugin_file(plugin_dir, filename, plugin_name)

                loader = PluginLoader()
                app = MagicMock()

                with patch.object(
                    loader,
                    "_resolve_plugin_directories",
                    return_value=[str(plugin_dir)],
                ):
                    result = loader._discover_from_files(app)

                # Exactly one plugin should be loaded
                assert len(result) == 1, (
                    f"Expected exactly 1 plugin loaded, got {len(result)}"
                )
                assert result[0].name == plugin_name

                # A warning about duplicate(s) must be logged
                duplicate_warnings = [
                    m
                    for m in log_capture.messages
                    if "Duplicate file plugin name" in m and plugin_name in m
                ]
                assert len(duplicate_warnings) > 0, (
                    f"Expected duplicate warning for '{plugin_name}' in logs, "
                    f"got: {log_capture.messages}"
                )

                # The loaded plugin must come from the file that sorts first
                # alphabetically (case-insensitive)
                sorted_filenames = sorted(filenames, key=lambda f: f.lower())
                assert expected_winner == sorted_filenames[0]
            finally:
                logger.removeHandler(log_capture)
