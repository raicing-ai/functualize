"""Tests for config file discovery logic.

Verifies:
- Standard locations are always included (R2-AC2)
- pyproject.toml is always present (R2-AC3)
- Status detection: exists/not_found/read_only (R2-AC4, R2-AC5, R2-AC6)
- Section naming for ungrouped/grouped/pyproject (R2-AC7)
- fields_from_file matching from chain entries
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._cli.tui.panels.config_files import (
    _determine_file_status,
    _determine_section,
    _is_writable,
    _make_display_name,
    discover_config_files,
)
from functualize._cli.tui.panels.config_table import ChainEntry, FieldDef
from functualize.types import ConfigFileRole

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_field(
    name: str,
    file_value: str = "",
) -> FieldDef:
    """Create a FieldDef with a populated chain for testing."""
    chain = [
        ChainEntry(source="CLI", value=""),
        ChainEntry(source="Session", value=""),
        ChainEntry(source="Env", value=""),
        ChainEntry(source="File", value=file_value),
        ChainEntry(source="Remote", value=""),
        ChainEntry(source="Default", value="fallback"),
    ]
    return FieldDef(
        name=name,
        value=file_value or "fallback",
        source="file" if file_value else "default",
        chain=chain,
    )


# ---------------------------------------------------------------------------
# Section naming tests (R2-AC7)
# ---------------------------------------------------------------------------


class TestDetermineSection:
    """Test section name determination for different group configurations."""

    def test_ungrouped_job_uses_job_name(self):
        """Ungrouped jobs use the job name as section."""
        assert _determine_section("serve", None, is_pyproject=False) == "serve"

    def test_grouped_job_uses_group_path(self):
        """Grouped jobs use the group path as section."""
        assert (
            _determine_section("infra.deploy", "infra", is_pyproject=False) == "infra"
        )

    def test_nested_group_uses_full_group_path(self):
        """Nested grouped jobs use the full group path."""
        assert (
            _determine_section("infra.aws.deploy", "infra.aws", is_pyproject=False)
            == "infra.aws"
        )

    def test_pyproject_ungrouped_uses_tool_prefix(self):
        """Pyproject.toml for ungrouped jobs uses tool.functualize.<job_name>."""
        assert (
            _determine_section("serve", None, is_pyproject=True)
            == "tool.functualize.serve"
        )

    def test_pyproject_grouped_uses_tool_prefix_with_group(self):
        """Pyproject.toml for grouped jobs uses tool.functualize.<group>."""
        assert (
            _determine_section("infra.deploy", "infra", is_pyproject=True)
            == "tool.functualize.infra"
        )


# ---------------------------------------------------------------------------
# Status detection tests (R2-AC4, R2-AC5, R2-AC6)
# ---------------------------------------------------------------------------


class TestDetermineFileStatus:
    """Test file status detection."""

    def test_existing_writable_file(self, tmp_path: Path):
        """An existing file with no known role is treated as contributing."""
        f = tmp_path / "config.toml"
        f.write_text("[test]\n")
        assert _determine_file_status(f) == "active"

    def test_non_existent_file(self, tmp_path: Path):
        """Non-existent file → 'not_found' (R2-AC5)."""
        f = tmp_path / "missing.toml"
        assert _determine_file_status(f) == "not_found"

    def test_read_only_file_still_contributes(self, tmp_path: Path):
        """Writability is not contribution — a read-only file still applies.

        Status answers "is this file being used?"; whether it can be edited
        is a separate axis carried on the entry.
        """
        f = tmp_path / "readonly.toml"
        f.write_text("[test]\n")
        # Remove write permission
        f.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        try:
            assert _determine_file_status(f) == "active"
            assert _is_writable(f) is False
        finally:
            # Restore permissions for cleanup
            f.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_inert_file_is_inactive(self, tmp_path: Path):
        """A file the kernel classified as belonging to another environment."""
        f = tmp_path / "config.prod.toml"
        f.write_text("[test]\n")
        assert _determine_file_status(f, ConfigFileRole.INERT) == "inactive"
        assert _determine_file_status(f, ConfigFileRole.OVERLAY) == "active"


# ---------------------------------------------------------------------------
# Display name tests
# ---------------------------------------------------------------------------


class TestMakeDisplayName:
    """Test display name formatting."""

    def test_file_under_cwd_shows_relative(self, tmp_path: Path):
        """Files under cwd show relative path."""
        f = tmp_path / "config.toml"
        assert _make_display_name(f, tmp_path) == "config.toml"

    def test_nested_file_under_cwd(self, tmp_path: Path):
        """Nested files under cwd show relative path."""
        f = tmp_path / "sub" / "config.toml"
        assert _make_display_name(f, tmp_path) == "sub/config.toml"

    def test_file_outside_cwd_uses_home_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Files outside cwd but under home use ~ prefix."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        f = home / ".config" / "functualize" / "config.toml"
        cwd = tmp_path / "project"
        cwd.mkdir()
        assert _make_display_name(f, cwd) == "~/.config/functualize/config.toml"


# ---------------------------------------------------------------------------
# Full discovery tests (R2-AC2, R2-AC3)
# ---------------------------------------------------------------------------


class TestDiscoverConfigFiles:
    """Test the full config file discovery function."""

    def test_standard_locations_always_included(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Standard locations that exist are included in discovery."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        # Create the standard files so they appear
        (tmp_path / ".functualize.toml").write_text("[serve]\n")
        (tmp_path / "functualize.toml").write_text("[serve]\n")
        (tmp_path / "pyproject.toml").write_text("[tool.functualize.serve]\n")

        fields = [_make_field("port")]
        entries = discover_config_files(fields, "serve", None, tmp_path)

        paths = [e.path for e in entries]
        assert tmp_path / ".functualize.toml" in paths
        assert tmp_path / "functualize.toml" in paths
        assert tmp_path / "pyproject.toml" in paths

    def test_pyproject_always_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """pyproject.toml is included when it exists."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        (tmp_path / "pyproject.toml").write_text("[tool.functualize.serve]\n")
        fields: list[FieldDef] = []  # No fields at all
        entries = discover_config_files(fields, "serve", None, tmp_path)

        pyproject_entries = [e for e in entries if e.path.name == "pyproject.toml"]
        assert len(pyproject_entries) == 1

    def test_status_for_existing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Existing writable file is reported as contributing."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        (tmp_path / ".functualize.toml").write_text("[serve]\nport = 8080\n")
        fields = [_make_field("port")]
        entries = discover_config_files(fields, "serve", None, tmp_path)

        dot_entry = next(e for e in entries if e.path == tmp_path / ".functualize.toml")
        assert dot_entry.status == "active"

    def test_status_for_missing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Non-existent files are excluded from discovery results."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        fields = [_make_field("port")]
        entries = discover_config_files(fields, "serve", None, tmp_path)

        # functualize.toml should not exist — therefore not in results
        func_entries = [e for e in entries if e.path == tmp_path / "functualize.toml"]
        assert len(func_entries) == 0

    def test_read_only_reported_separately_from_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A read-only file is reported writable=False, not a distinct status."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        readonly = tmp_path / "pyproject.toml"
        readonly.write_text("[tool.functualize.serve]\n")
        readonly.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        try:
            fields = [_make_field("port")]
            entries = discover_config_files(fields, "serve", None, tmp_path)

            pyproject_entry = next(
                e for e in entries if e.path.name == "pyproject.toml"
            )
            assert pyproject_entry.status == "active"
            assert pyproject_entry.writable is False
        finally:
            readonly.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_section_for_ungrouped_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Ungrouped job: regular files get job_name section, pyproject gets tool.functualize.<name>."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        # Create files so they appear in discovery
        (tmp_path / ".functualize.toml").write_text("[serve]\n")
        (tmp_path / "pyproject.toml").write_text("[tool.functualize.serve]\n")

        fields = [_make_field("port")]
        entries = discover_config_files(fields, "serve", None, tmp_path)

        dot_entry = next(e for e in entries if e.path == tmp_path / ".functualize.toml")
        assert dot_entry.section == "serve"

        pyproject_entry = next(e for e in entries if e.path.name == "pyproject.toml")
        assert pyproject_entry.section == "tool.functualize.serve"

    def test_section_for_grouped_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Grouped job: regular files get group path section, pyproject gets tool.functualize.<group>."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        # Create files so they appear in discovery
        (tmp_path / ".functualize.toml").write_text("[infra]\n")
        (tmp_path / "pyproject.toml").write_text("[tool.functualize.infra]\n")

        fields = [_make_field("region")]
        entries = discover_config_files(fields, "infra.deploy", "infra", tmp_path)

        dot_entry = next(e for e in entries if e.path == tmp_path / ".functualize.toml")
        assert dot_entry.section == "infra"

        pyproject_entry = next(e for e in entries if e.path.name == "pyproject.toml")
        assert pyproject_entry.section == "tool.functualize.infra"

    def test_fields_from_file_matching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Fields appear in fields_from_file when the file contains those keys."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))

        # Create a .functualize.toml with [serve] section containing port and debug
        toml_file = tmp_path / ".functualize.toml"
        toml_file.write_text('[serve]\nport = "8080"\ndebug = "true"\n')

        fields = [
            _make_field("port", file_value="8080"),
            _make_field("host", file_value=""),  # Not in file
            _make_field("debug", file_value="true"),
        ]
        entries = discover_config_files(fields, "serve", None, tmp_path)

        # The .functualize.toml entry should list fields that are in the file
        functualize_entry = next(
            (e for e in entries if e.path.name == ".functualize.toml"), None
        )
        assert functualize_entry is not None
        assert "port" in functualize_entry.fields_from_file
        assert "host" not in functualize_entry.fields_from_file
        assert "debug" in functualize_entry.fields_from_file

    def test_no_duplicate_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Discovery produces no duplicate paths."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        # Create files to have entries to check
        (tmp_path / ".functualize.toml").write_text("[serve]\nport = 8080\n")
        (tmp_path / "functualize.toml").write_text("[serve]\nport = 8080\n")

        fields = [_make_field("port")]
        entries = discover_config_files(fields, "serve", None, tmp_path)

        # All paths should be unique when resolved
        resolved_paths = [e.path.resolve() for e in entries]
        assert len(resolved_paths) == len(set(resolved_paths))

    def test_returns_only_existing_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """With no files existing, returns empty list (non-existent files excluded)."""
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
        fields = [_make_field("port")]
        entries = discover_config_files(fields, "serve", None, tmp_path)
        assert len(entries) == 0
