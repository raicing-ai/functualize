"""Unit tests for ArgumentHistory persistence edge cases.

# Feature: tui-foundation, Task 1.4

Tests the load/flush lifecycle covering missing files, corrupted JSON,
directory creation, and XDG_DATA_HOME environment variable override.

Requirements: 1.4, 1.5, 1.6, 1.7
"""

from __future__ import annotations

import json
from pathlib import Path

from functualize._cli.data.argument_history import ArgumentHistory

# =============================================================================
# Test: Loading from non-existent file
# =============================================================================


class TestLoadNonExistentFile:
    """Loading from a path that does not exist returns empty history.

    **Validates: Requirement 1.6**
    """

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        """When the history file doesn't exist, load() returns empty state."""
        missing = tmp_path / "does_not_exist.json"
        history = ArgumentHistory.load(path=missing)

        assert history.get_history("any_job", "any_field") == []

    def test_load_missing_file_sets_path(self, tmp_path: Path):
        """The returned instance remembers the path for future flush."""
        missing = tmp_path / "does_not_exist.json"
        history = ArgumentHistory.load(path=missing)

        assert history._path == missing

    def test_load_missing_file_not_dirty(self, tmp_path: Path):
        """A freshly loaded empty history should not be marked dirty."""
        missing = tmp_path / "does_not_exist.json"
        history = ArgumentHistory.load(path=missing)

        assert history._dirty is False


# =============================================================================
# Test: Loading from corrupted JSON
# =============================================================================


class TestLoadCorruptedJSON:
    """Corrupted history file is renamed to .bak and empty state is returned.

    **Validates: Requirement 1.6**
    """

    def test_corrupted_json_returns_empty(self, tmp_path: Path):
        """When file contains invalid JSON, load() returns empty state."""
        corrupt_file = tmp_path / "argument_history.json"
        corrupt_file.write_text("{not valid json!!!", encoding="utf-8")

        history = ArgumentHistory.load(path=corrupt_file)

        assert history.get_history("any_job", "any_field") == []

    def test_corrupted_json_renames_to_bak(self, tmp_path: Path):
        """Corrupted file is renamed to .json.bak."""
        corrupt_file = tmp_path / "argument_history.json"
        corrupt_file.write_text("corrupted content", encoding="utf-8")

        ArgumentHistory.load(path=corrupt_file)

        bak_file = tmp_path / "argument_history.json.bak"
        assert bak_file.exists()
        assert bak_file.read_text(encoding="utf-8") == "corrupted content"

    def test_corrupted_json_original_removed(self, tmp_path: Path):
        """After renaming to .bak, the original corrupt file no longer exists."""
        corrupt_file = tmp_path / "argument_history.json"
        corrupt_file.write_text("bad data", encoding="utf-8")

        ArgumentHistory.load(path=corrupt_file)

        assert not corrupt_file.exists()

    def test_partial_json_treated_as_corrupted(self, tmp_path: Path):
        """Truncated/partial JSON is also treated as corruption."""
        corrupt_file = tmp_path / "argument_history.json"
        corrupt_file.write_text('{"version": 1, "history": {', encoding="utf-8")

        history = ArgumentHistory.load(path=corrupt_file)

        assert history.get_history("any_job", "any_field") == []
        bak_file = tmp_path / "argument_history.json.bak"
        assert bak_file.exists()


# =============================================================================
# Test: Flush creates directory if missing
# =============================================================================


class TestFlushCreatesDirectory:
    """flush() creates parent directories when they don't exist.

    **Validates: Requirement 1.7**
    """

    def test_flush_creates_missing_parent_dirs(self, tmp_path: Path):
        """Flushing to a path with non-existent parent dirs creates them."""
        nested_path = tmp_path / "deep" / "nested" / "dir" / "history.json"
        history = ArgumentHistory.load(path=nested_path)
        history.record("test_job", "field", "value")

        history.flush()

        assert nested_path.exists()
        data = json.loads(nested_path.read_text(encoding="utf-8"))
        assert data["history"]["test_job"]["field"] == ["value"]

    def test_flush_noop_when_not_dirty(self, tmp_path: Path):
        """flush() does nothing if there are no unsaved changes."""
        file_path = tmp_path / "history.json"
        history = ArgumentHistory.load(path=file_path)

        history.flush()

        assert not file_path.exists()

    def test_flush_writes_valid_json(self, tmp_path: Path):
        """The flushed file contains valid parseable JSON."""
        file_path = tmp_path / "history.json"
        history = ArgumentHistory.load(path=file_path)
        history.record("deploy", "env", "production")
        history.record("deploy", "env", "staging")

        history.flush()

        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert data["history"]["deploy"]["env"] == ["production", "staging"]


# =============================================================================
# Test: XDG_DATA_HOME environment variable override
# =============================================================================


class TestXDGDataHomeOverride:
    """_default_path() respects XDG_DATA_HOME environment variable.

    **Validates: Requirement 1.4**
    """

    def test_default_path_uses_xdg_data_home(self, monkeypatch, tmp_path: Path):
        """When XDG_DATA_HOME is set, _default_path() uses it as base."""
        custom_data = tmp_path / "custom_data"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom_data))

        result = ArgumentHistory._default_path()

        assert result == custom_data / "functualize" / "argument_history.json"

    def test_default_path_fallback_without_xdg(self, monkeypatch):
        """When XDG_DATA_HOME is not set, falls back to ~/.local/share/."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)

        result = ArgumentHistory._default_path()

        expected = (
            Path.home() / ".local" / "share" / "functualize" / "argument_history.json"
        )
        assert result == expected

    def test_load_uses_xdg_data_home_when_no_path(self, monkeypatch, tmp_path: Path):
        """load() without explicit path uses XDG_DATA_HOME-based path."""
        custom_data = tmp_path / "xdg_data"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom_data))

        history = ArgumentHistory.load()

        expected_path = custom_data / "functualize" / "argument_history.json"
        assert history._path == expected_path

    def test_full_round_trip_with_xdg(self, monkeypatch, tmp_path: Path):
        """Full save/load cycle works with XDG_DATA_HOME override."""
        custom_data = tmp_path / "xdg_data"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom_data))

        # Save
        history = ArgumentHistory.load()
        history.record("build", "target", "release")
        history.flush()

        # Load again
        loaded = ArgumentHistory.load()

        assert loaded.get_history("build", "target") == ["release"]
