"""Unit tests for _cli/config.py — read_global_config and ``config path``.

Tests cover:
- Missing files → empty dict
- TOML syntax errors → warning + empty dict
- Unrecognized keys are tolerated by ``config path``
- Type mismatches → warning + section ignored
- Permission errors → warning + empty dict
- FUNCTUALIZE_* env var mapping
- Empty string env vars → skipped

Project-level config resolution (pyproject.toml → .functualize.toml
fallback, upward walk) is now handled by the shared
``functualize.app.utils.resolve_project_config`` and is covered by
``tests/cli/test_config_upward_walk.py`` instead of duplicating it here.

Requirements: 1.2–1.8, 4.1–4.6
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click
from click.testing import CliRunner, Result

from functualize._cli.builtins._config import register_config
from functualize._cli.config import read_global_config

if TYPE_CHECKING:
    import pytest

# =============================================================================
# read_global_config tests
# =============================================================================


class TestReadGlobalConfig:
    """Tests for read_global_config()."""

    def test_missing_file_returns_empty(self, tmp_path: Path):
        """Missing config file → empty dict, no error (Req 1.2)."""
        result = read_global_config(tmp_path)
        assert result == {}

    def test_missing_dir_returns_empty(self, tmp_path: Path):
        """Non-existent directory → empty dict, no error (Req 1.8)."""
        result = read_global_config(tmp_path / "nonexistent" / "subdir")
        assert result == {}

    def test_valid_config_all_sections(self, tmp_path: Path):
        """Parse a valid config with [discovery], [cli], [aliases] (Req 1.3)."""
        config = tmp_path / "config.toml"
        config.write_text(
            "[discovery]\n"
            'require_file_import = "functualize"\n'
            'exclude_patterns = ["**/test_*.py"]\n'
            "\n"
            "[cli]\n"
            'output = "plain"\n'
            "show_timing = true\n"
            "\n"
            "[aliases]\n"
            'd = "deploy"\n'
            'r = "run"\n'
        )

        result = read_global_config(tmp_path)

        assert result["discovery"]["require_file_import"] == "functualize"
        assert result["discovery"]["exclude_patterns"] == ["**/test_*.py"]
        assert result["cli"]["output"] == "plain"
        assert result["cli"]["show_timing"] is True
        assert result["aliases"]["d"] == "deploy"
        assert result["aliases"]["r"] == "run"

    def test_toml_syntax_error_warns_and_returns_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """TOML syntax error → warn to stderr, return empty dict (Req 1.4)."""
        config = tmp_path / "config.toml"
        config.write_text("[discovery\n")  # Missing closing bracket

        result = read_global_config(tmp_path)

        assert result == {}
        captured = capsys.readouterr()
        assert "Warning:" in captured.err
        assert str(config) in captured.err

    def test_unrecognized_top_level_section_silently_ignored(self, tmp_path: Path):
        """Unrecognized top-level sections are silently ignored (Req 1.3)."""
        config = tmp_path / "config.toml"
        config.write_text('[unknown_section]\nfoo = "bar"\n\n[cli]\noutput = "json"\n')

        result = read_global_config(tmp_path)

        assert "unknown_section" not in result
        assert result["cli"]["output"] == "json"

    def test_permission_error_warns_and_returns_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """Unreadable file → warn to stderr, return empty dict (Req 1.7)."""
        config = tmp_path / "config.toml"
        config.write_text('[cli]\noutput = "rich"\n')
        config.chmod(0o000)

        try:
            result = read_global_config(tmp_path)
            assert result == {}
            captured = capsys.readouterr()
            assert "Warning:" in captured.err
            assert "permission" in captured.err.lower()
        finally:
            config.chmod(0o644)

    def test_empty_file_returns_empty(self, tmp_path: Path):
        """Empty TOML file is valid → returns empty dict."""
        config = tmp_path / "config.toml"
        config.write_text("")

        result = read_global_config(tmp_path)
        assert result == {}

    def test_type_mismatch_section_not_table_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """Section value that is not a table → warn and ignore (type mismatch)."""
        config = tmp_path / "config.toml"
        # In TOML, you can't directly assign a non-table to a section key at top level
        # but you can have a key that shadows a section. Use a valid TOML where
        # a recognized section is assigned a non-dict value via inline table trickery.
        # Actually in pure TOML, top-level keys are either tables or scalars.
        # A scalar key named "cli" would be: cli = "not a table"
        config.write_text('cli = "not a table"\n')

        result = read_global_config(tmp_path)

        assert result == {}
        captured = capsys.readouterr()
        assert "Warning:" in captured.err
        assert "not a table" in captured.err

    def test_multiple_unrecognized_top_level_sections_all_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """Multiple unrecognized sections are all silently ignored without warnings."""
        config = tmp_path / "config.toml"
        config.write_text(
            '[custom1]\nfoo = "bar"\n\n[custom2]\nbaz = 42\n\n[cli]\noutput = "plain"\n'
        )

        result = read_global_config(tmp_path)

        assert "custom1" not in result
        assert "custom2" not in result
        assert result["cli"]["output"] == "plain"
        # No warnings for unrecognized top-level sections
        captured = capsys.readouterr()
        assert "custom1" not in captured.err
        assert "custom2" not in captured.err


# =============================================================================
# config path tolerates keys it does not recognize
# =============================================================================


def _config_path() -> Result:
    group = click.Group(name="func")
    register_config(group)
    return CliRunner().invoke(group, ["config", "path"])


class TestConfigPathAfterUnknownKeys:
    """Unknown keys are the config path's business, not resolve-time noise."""

    def _write_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
    ) -> Path:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        path = tmp_path / "xdg" / "functualize" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def test_a_bogus_key_in_a_recognized_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        global_path = self._write_global(
            tmp_path,
            monkeypatch,
            '[discovery]\nrequire_file_import = "functualize"\nbogus_key = "x"\n',
        )
        result = _config_path()
        assert result.exit_code == 0
        assert f"✓ used    {global_path}" in result.output
        assert "unrecognized key" not in result.output
        assert "Warning:" not in result.output

    def test_an_invalid_cli_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        global_path = self._write_global(
            tmp_path,
            monkeypatch,
            '[cli]\noutput = "json"\nshow_timing = true\ninvalid_key = "bad"\n',
        )
        result = _config_path()
        assert result.exit_code == 0
        assert f"✓ used    {global_path}" in result.output
        assert "unrecognized key" not in result.output
        assert "Warning:" not in result.output

    def test_an_unknown_discovery_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        global_path = self._write_global(
            tmp_path,
            monkeypatch,
            '[discovery]\nrequire_file_prefix = "job_"\nunknown = "ignored"\n',
        )
        result = _config_path()
        assert result.exit_code == 0
        assert f"✓ used    {global_path}" in result.output
        assert "unrecognized key" not in result.output
        assert "Warning:" not in result.output
