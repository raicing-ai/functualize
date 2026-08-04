"""Tests for the atomic TOML section writer.

Covers:
- Write edits to existing file with existing section
- Write edits to existing file, section doesn't exist (append)
- Create new file with minimal template
- Handle pyproject.toml nested section correctly
- Remove a key from existing section
- Atomic write safety (tempfile + replace)
- Typed literal emission (type_hints) — an int field must not round-trip
  through the TUI as a quoted string

The staged-edit/save *flow* is covered end-to-end with real keypresses in
tests/_cli/test_source_chain_detail_pilot.py; this file covers the writer.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from functualize._cli.data.toml_writer import format_toml_value, write_toml_section

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_existing_toml(tmp_path: Path, content: str) -> Path:
    """Write a TOML file with given content and return its path."""
    p = tmp_path / "config.toml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# write_toml_section — existing file with existing section
# ---------------------------------------------------------------------------


class TestWriteTomlExistingFileExistingSection:
    """Test editing existing keys in an existing section."""

    def test_edit_existing_key(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "old-host"\nport = "3000"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"host": "new-host"}, set())

        result = p.read_text()
        assert 'host = "new-host"' in result
        assert 'port = "3000"' in result

    def test_edit_multiple_keys(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "old"\nport = "3000"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"host": "new", "port": "9090"}, set())

        result = p.read_text()
        assert 'host = "new"' in result
        assert 'port = "9090"' in result

    def test_add_new_key_to_existing_section(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "localhost"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"timeout": "30"}, set())

        result = p.read_text()
        assert 'host = "localhost"' in result
        assert 'timeout = "30"' in result

    def test_preserves_other_sections(self, tmp_path: Path) -> None:
        content = '[server]\nname = "web"\n\n[deploy]\nhost = "old"\n\n[logging]\nlevel = "info"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"host": "new"}, set())

        result = p.read_text()
        assert 'name = "web"' in result
        assert 'host = "new"' in result
        assert 'level = "info"' in result

    def test_preserves_comments(self, tmp_path: Path) -> None:
        content = '[deploy]\n# Server host\nhost = "localhost"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"host": "prod.example.com"}, set())

        result = p.read_text()
        assert "# Server host" in result
        assert 'host = "prod.example.com"' in result


# ---------------------------------------------------------------------------
# write_toml_section — section doesn't exist (append)
# ---------------------------------------------------------------------------


class TestWriteTomlAppendSection:
    """Test appending a new section when it doesn't exist in the file."""

    def test_append_new_section(self, tmp_path: Path) -> None:
        content = '[server]\nname = "web"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"host": "localhost"}, set())

        result = p.read_text()
        assert "[deploy]" in result
        assert 'host = "localhost"' in result
        # Original content preserved
        assert 'name = "web"' in result


# ---------------------------------------------------------------------------
# write_toml_section — new file creation
# ---------------------------------------------------------------------------


class TestWriteTomlNewFile:
    """Test creating a new file with minimal template."""

    def test_create_new_file(self, tmp_path: Path) -> None:
        p = tmp_path / "new_config.toml"
        assert not p.exists()

        write_toml_section(p, "serve", {"port": "8080", "host": "0.0.0.0"}, set())

        assert p.exists()
        result = p.read_text()
        assert "[serve]" in result
        assert 'port = "8080"' in result
        assert 'host = "0.0.0.0"' in result

    def test_create_new_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "subdir" / "deep" / "config.toml"
        assert not p.exists()

        write_toml_section(p, "serve", {"port": "8080"}, set())

        assert p.exists()
        result = p.read_text()
        assert "[serve]" in result
        assert 'port = "8080"' in result


# ---------------------------------------------------------------------------
# write_toml_section — pyproject.toml nested section
# ---------------------------------------------------------------------------


class TestWriteTomlPyproject:
    """Test handling of nested sections like [tool.functualize.serve]."""

    def test_nested_section_new_file(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"

        write_toml_section(p, "tool.functualize.serve", {"port": "8080"}, set())

        result = p.read_text()
        assert "[tool.functualize.serve]" in result
        assert 'port = "8080"' in result

    def test_nested_section_existing_file(self, tmp_path: Path) -> None:
        content = (
            '[project]\nname = "myapp"\n\n[tool.functualize.serve]\nhost = "old"\n'
        )
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(
            p, "tool.functualize.serve", {"host": "new", "port": "9090"}, set()
        )

        result = p.read_text()
        assert 'name = "myapp"' in result
        assert "[tool.functualize.serve]" in result
        assert 'host = "new"' in result
        assert 'port = "9090"' in result

    def test_nested_section_append_to_existing_pyproject(self, tmp_path: Path) -> None:
        content = '[project]\nname = "myapp"\nversion = "1.0.0"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "tool.functualize.deploy", {"region": "us-east-1"}, set())

        result = p.read_text()
        assert 'name = "myapp"' in result
        assert "[tool.functualize.deploy]" in result
        assert 'region = "us-east-1"' in result


# ---------------------------------------------------------------------------
# write_toml_section — removal
# ---------------------------------------------------------------------------


class TestWriteTomlRemoval:
    """Test removing keys from a section."""

    def test_remove_single_key(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "localhost"\nport = "8080"\ntimeout = "30"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {}, {"port"})

        result = p.read_text()
        assert 'host = "localhost"' in result
        assert "port" not in result
        assert 'timeout = "30"' in result

    def test_remove_multiple_keys(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "localhost"\nport = "8080"\ntimeout = "30"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {}, {"port", "timeout"})

        result = p.read_text()
        assert 'host = "localhost"' in result
        assert "port" not in result
        assert "timeout" not in result

    def test_edit_and_remove_simultaneously(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "old"\nport = "8080"\ntimeout = "30"\n'
        p = _make_existing_toml(tmp_path, content)

        write_toml_section(p, "deploy", {"host": "new"}, {"timeout"})

        result = p.read_text()
        assert 'host = "new"' in result
        assert 'port = "8080"' in result
        assert "timeout" not in result


# ---------------------------------------------------------------------------
# write_toml_section — atomic write safety
# ---------------------------------------------------------------------------


class TestWriteTomlAtomicSafety:
    """Test that writes use tempfile+replace for atomicity."""

    def test_original_file_not_corrupted_on_write_failure(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "original"\n'
        p = _make_existing_toml(tmp_path, content)

        # Patch os.replace to simulate failure
        with (
            patch("os.replace", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            write_toml_section(p, "deploy", {"host": "new"}, set())

        # Original file should be unchanged
        assert p.read_text() == content

    def test_no_temp_file_left_on_failure(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "original"\n'
        p = _make_existing_toml(tmp_path, content)

        with (
            patch("os.replace", side_effect=OSError("disk full")),
            pytest.raises(OSError),
        ):
            write_toml_section(p, "deploy", {"host": "new"}, set())

        # No temp files should remain in the directory
        toml_tmp_files = list(tmp_path.glob("*.toml.tmp"))
        assert toml_tmp_files == []

    def test_file_written_via_replace(self, tmp_path: Path) -> None:
        """Verify os.replace is actually called (atomic semantics)."""
        content = '[deploy]\nhost = "old"\n'
        p = _make_existing_toml(tmp_path, content)

        with patch("os.replace", wraps=os.replace) as mock_replace:
            write_toml_section(p, "deploy", {"host": "new"}, set())
            mock_replace.assert_called_once()


# ---------------------------------------------------------------------------
# write_toml_section — edge cases
# ---------------------------------------------------------------------------


class TestWriteTomlEdgeCases:
    """Test edge cases for the TOML writer."""

    def test_noop_when_no_edits_and_no_removals(self, tmp_path: Path) -> None:
        content = '[deploy]\nhost = "localhost"\n'
        p = _make_existing_toml(tmp_path, content)
        mtime_before = p.stat().st_mtime

        write_toml_section(p, "deploy", {}, set())

        # File should not be touched at all
        assert p.stat().st_mtime == mtime_before

    def test_empty_file_with_section_appended(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.toml"
        p.write_text("")

        write_toml_section(p, "deploy", {"host": "localhost"}, set())

        result = p.read_text()
        assert "[deploy]" in result
        assert 'host = "localhost"' in result


# ---------------------------------------------------------------------------
# format_toml_value — typed literal emission
# ---------------------------------------------------------------------------


class TestFormatTomlValue:
    """The TUI edits everything as text; TOML is typed."""

    def test_unknown_type_is_quoted(self) -> None:
        assert format_toml_value("8080") == '"8080"'
        assert format_toml_value("8080", None) == '"8080"'

    def test_str_is_quoted(self) -> None:
        assert format_toml_value("localhost", "str") == '"localhost"'

    def test_int_is_bare(self) -> None:
        assert format_toml_value("9090", "int") == "9090"
        assert format_toml_value("  9090  ", "int") == "9090"
        assert format_toml_value("-5", "int") == "-5"

    def test_bool_is_bare_lowercase(self) -> None:
        assert format_toml_value("true", "bool") == "true"
        assert format_toml_value("True", "bool") == "true"
        assert format_toml_value("false", "bool") == "false"

    def test_float_is_bare(self) -> None:
        assert format_toml_value("1.5", "float") == "1.5"

    def test_list_becomes_an_array(self) -> None:
        assert format_toml_value("a,b , c", "list") == '["a", "b", "c"]'
        assert format_toml_value("", "list") == "[]"

    def test_optional_int_still_writes_bare(self) -> None:
        assert format_toml_value("7", "Optional[int]") == "7"
        assert format_toml_value("7", "int | None") == "7"

    def test_mistyped_value_falls_back_to_quoted_not_broken_toml(self) -> None:
        """A bad int must not produce a file that no longer parses."""
        assert format_toml_value("eight", "int") == '"eight"'
        assert format_toml_value("yes", "bool") == '"yes"'

    def test_quotes_and_backslashes_are_escaped(self) -> None:
        assert format_toml_value('say "hi"', "str") == '"say \\"hi\\""'
        assert format_toml_value("C:\\path", "str") == '"C:\\\\path"'

    def test_escaped_output_round_trips_through_tomllib(self) -> None:
        raw = 'tricky "quoted" \\ value'
        literal = format_toml_value(raw, "str")
        assert tomllib.loads(f"key = {literal}")["key"] == raw


class TestWriteTomlTypedValues:
    """type_hints keeps a file's types intact across a TUI edit."""

    def test_int_field_stays_an_int(self, tmp_path: Path) -> None:
        p = _make_existing_toml(tmp_path, "[serve]\nport = 8080\n")

        write_toml_section(p, "serve", {"port": "9090"}, set(), {"port": "int"})

        assert "port = 9090" in p.read_text()
        assert tomllib.loads(p.read_text())["serve"]["port"] == 9090

    def test_bool_field_stays_a_bool(self, tmp_path: Path) -> None:
        p = _make_existing_toml(tmp_path, "[serve]\ndebug = true\n")

        write_toml_section(p, "serve", {"debug": "false"}, set(), {"debug": "bool"})

        assert tomllib.loads(p.read_text())["serve"]["debug"] is False

    def test_without_hints_values_are_quoted(self, tmp_path: Path) -> None:
        """Unchanged default: no type info means the safe, quoted form."""
        p = _make_existing_toml(tmp_path, '[serve]\nport = "8080"\n')

        write_toml_section(p, "serve", {"port": "9090"}, set())

        assert tomllib.loads(p.read_text())["serve"]["port"] == "9090"

    def test_new_file_emits_typed_values(self, tmp_path: Path) -> None:
        p = tmp_path / "config.dev.toml"

        write_toml_section(
            p,
            "serve",
            {"port": "9090", "host": "0.0.0.0", "debug": "true"},
            set(),
            {"port": "int", "host": "str", "debug": "bool"},
        )

        parsed = tomllib.loads(p.read_text())["serve"]
        assert parsed == {"port": 9090, "host": "0.0.0.0", "debug": True}

    def test_appended_section_emits_typed_values(self, tmp_path: Path) -> None:
        p = _make_existing_toml(tmp_path, '[other]\nx = "1"\n')

        write_toml_section(p, "serve", {"port": "9090"}, set(), {"port": "int"})

        assert tomllib.loads(p.read_text())["serve"]["port"] == 9090
