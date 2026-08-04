"""Unit tests for _cli/config.py — read_global_config, resolve_env_overrides.

Tests cover:
- Missing files → empty dict
- TOML syntax errors → warning + empty dict
- Unrecognized keys → warning + ignored
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

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from functualize._cli.config import read_global_config, resolve_env_overrides

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

    def test_unrecognized_key_in_recognized_section_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """Unrecognized key in recognized section → warn, ignore key (Req 1.5)."""
        config = tmp_path / "config.toml"
        config.write_text(
            "[discovery]\n"
            'require_file_import = "functualize"\n'
            'bogus_key = "should_warn"\n'
        )

        result = read_global_config(tmp_path)

        assert result["discovery"]["require_file_import"] == "functualize"
        assert "bogus_key" not in result.get("discovery", {})
        captured = capsys.readouterr()
        assert "bogus_key" in captured.err
        assert "Warning:" in captured.err

    def test_unrecognized_key_other_keys_still_returned(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """Unrecognized keys don't prevent valid keys from being returned (Req 1.5)."""
        config = tmp_path / "config.toml"
        config.write_text(
            '[cli]\noutput = "json"\nshow_timing = true\ninvalid_key = "bad"\n'
        )

        result = read_global_config(tmp_path)

        # Valid keys are still present
        assert result["cli"]["output"] == "json"
        assert result["cli"]["show_timing"] is True
        # Invalid key was filtered out
        assert "invalid_key" not in result["cli"]
        captured = capsys.readouterr()
        assert "invalid_key" in captured.err

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

    def test_discovery_section_filters_recognized_keys_only(self, tmp_path: Path):
        """Only recognized keys are kept in the discovery section."""
        config = tmp_path / "config.toml"
        config.write_text(
            "[discovery]\n"
            'require_file_prefix = "job_"\n'
            'require_file_postfix = "_task"\n'
            'extra_directories = ["~/jobs"]\n'
            'unknown = "ignored"\n'
        )

        result = read_global_config(tmp_path)

        assert result["discovery"]["require_file_prefix"] == "job_"
        assert result["discovery"]["require_file_postfix"] == "_task"
        assert result["discovery"]["extra_directories"] == ["~/jobs"]
        assert "unknown" not in result["discovery"]

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
# resolve_env_overrides tests
# =============================================================================


class TestResolveEnvOverrides:
    """Tests for resolve_env_overrides()."""

    def test_maps_discovery_env_var(self):
        """FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT → discovery.require_file_import."""
        env = {"FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT": "functualize"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["discovery"]["require_file_import"] == "functualize"

    def test_maps_cli_env_var(self):
        """FUNCTUALIZE_CLI_OUTPUT → cli.output."""
        env = {"FUNCTUALIZE_CLI_OUTPUT": "json"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["cli"]["output"] == "json"

    def test_maps_cli_show_timing(self):
        """FUNCTUALIZE_CLI_SHOW_TIMING → cli.show_timing."""
        env = {"FUNCTUALIZE_CLI_SHOW_TIMING": "true"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["cli"]["show_timing"] == "true"

    def test_empty_string_skipped(self):
        """Empty string values are treated as unset."""
        env = {"FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT": ""}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        # Should not include the empty value
        assert "discovery" not in result or "require_file_import" not in result.get(
            "discovery", {}
        )

    def test_multiple_env_vars(self):
        """Multiple FUNCTUALIZE_* vars collected into nested dict."""
        env = {
            "FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT": "functualize",
            "FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX": "job_",
            "FUNCTUALIZE_CLI_OUTPUT": "plain",
        }
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["discovery"]["require_file_import"] == "functualize"
        assert result["discovery"]["require_file_prefix"] == "job_"
        assert result["cli"]["output"] == "plain"

    def test_non_functualize_vars_ignored(self):
        """Env vars without FUNCTUALIZE_ prefix are ignored."""
        env = {"HOME": "/home/user", "PATH": "/usr/bin"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        # HOME and PATH should not appear
        assert "home" not in result
        assert "path" not in result

    def test_single_word_after_prefix_skipped(self):
        """FUNCTUALIZE_SOMETHING with no underscore after section → skipped."""
        # Clear existing FUNCTUALIZE_ vars to isolate
        clean_env = {
            k: v for k, v in os.environ.items() if not k.startswith("FUNCTUALIZE_")
        }
        clean_env["FUNCTUALIZE_NOSECTION"] = "value"
        with patch.dict(os.environ, clean_env, clear=True):
            result = resolve_env_overrides()

        # Single word can't be split into section + key, so skipped
        assert result == {}

    def test_case_insensitive_section_and_key(self):
        """Section and key are lowercased from the env var name."""
        env = {"FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT": "pkg"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        # Section and key should be lowercased
        assert "discovery" in result
        assert "require_file_import" in result["discovery"]

    def test_dotenv_maps_to_top_level_key(self):
        """FUNCTUALIZE_DOTENV → top-level {"dotenv": ...}, not skipped."""
        env = {"FUNCTUALIZE_DOTENV": "true"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["dotenv"] == "true"

    def test_dotenv_path_maps_to_top_level_key(self):
        """FUNCTUALIZE_DOTENV_PATH → {"dotenv_path": ...}, not {"dotenv": {"path": ...}}."""
        env = {"FUNCTUALIZE_DOTENV_PATH": ".env.local"}
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["dotenv_path"] == ".env.local"
        # Must NOT create a nested "dotenv" section that shadows the boolean
        assert not isinstance(result.get("dotenv"), dict)

    def test_other_top_level_keys_map_directly(self):
        """FUNCTUALIZE_IMPORT_LIBS / EXTRA_DIRECTORIES → top-level keys."""
        env = {
            "FUNCTUALIZE_IMPORT_LIBS": "lib",
            "FUNCTUALIZE_EXTRA_DIRECTORIES": "extra",
            "FUNCTUALIZE_JOBS_DIRECTORIES": "jobs",
        }
        with patch.dict(os.environ, env, clear=False):
            result = resolve_env_overrides()

        assert result["import_libs"] == "lib"
        assert result["extra_directories"] == "extra"
        assert result["jobs_directories"] == "jobs"
