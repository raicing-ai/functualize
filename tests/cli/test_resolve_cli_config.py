"""Unit tests for resolve_cli_config() and CliConfig.

Tests cover:
- Default values with no config
- CLI flags override everything
- Env vars override project/global config
- Project config overrides global config
- List merge with deduplication
- Alias validation (pattern, max length)
- Output validation (warns on invalid, falls back to "rich")
- Boolean env var parsing (true/1/false/0, case-insensitive)
- XDG config path resolution
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._cli.config import (
    CliConfig,
    _merge_lists_dedup,
    _parse_bool_env,
    _validate_aliases,
    resolve_cli_config,
)
from functualize.app.config import DiscoveryConfig
from functualize.app.utils import resolve_user_config_dir

if TYPE_CHECKING:
    import pytest


# =============================================================================
# CliConfig dataclass
# =============================================================================


class TestCliConfig:
    """Tests for CliConfig frozen dataclass."""

    def test_frozen_immutability(self):
        """CliConfig is frozen — attributes cannot be changed after construction."""
        config = CliConfig(
            discovery=DiscoveryConfig(),
            output="rich",
            show_timing=False,
            aliases={},
            dotenv=False,
            dotenv_path=None,
        )
        import dataclasses

        assert dataclasses.is_dataclass(config)
        # Frozen check — should raise
        try:
            config.output = "plain"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except dataclasses.FrozenInstanceError:
            pass

    def test_default_values_via_resolve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """resolve_cli_config with no config → sensible defaults."""
        monkeypatch.chdir(tmp_path)
        # Ensure no global config is found
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        # Clear FUNCTUALIZE_ env vars
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        config = resolve_cli_config()

        assert config.output == "rich"
        assert config.show_timing is False
        assert config.aliases == {}
        assert config.dotenv is False
        assert config.dotenv_path is None
        assert config.discovery == DiscoveryConfig()


# =============================================================================
# resolve_cli_config — precedence
# =============================================================================


class TestResolvePrecedence:
    """Tests for config precedence: CLI flags → env → project → global → defaults."""

    def test_cli_flags_override_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CLI flags take highest precedence."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        # Set up global config with one value
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(
            '[discovery]\nrequire_file_import = "from_global"\n'
        )

        # CLI flag should override
        config = resolve_cli_config(cli_flags={"require_file_import": "from_cli"})

        assert config.discovery.require_file_import == "from_cli"

    def test_env_overrides_project_and_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Env vars override project and global config."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        # Global config
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(
            '[discovery]\nrequire_file_import = "from_global"\n'
        )

        # Project config
        (tmp_path / "pyproject.toml").write_text(
            '[tool.functualize.discovery]\nrequire_file_import = "from_project"\n'
        )

        # Env var should override both
        monkeypatch.setenv("FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT", "from_env")

        config = resolve_cli_config()

        assert config.discovery.require_file_import == "from_env"

    def test_project_overrides_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Project config overrides global config."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        # Global config
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(
            '[discovery]\nrequire_file_import = "from_global"\n'
        )

        # Project config
        (tmp_path / "pyproject.toml").write_text(
            '[tool.functualize.discovery]\nrequire_file_import = "from_project"\n'
        )

        config = resolve_cli_config()

        assert config.discovery.require_file_import == "from_project"

    def test_global_used_when_no_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Global config is used when no project config exists."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        # Global config only
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(
            '[discovery]\nrequire_file_import = "from_global"\n'
        )

        config = resolve_cli_config()

        assert config.discovery.require_file_import == "from_global"


# =============================================================================
# resolve_cli_config — output validation
# =============================================================================


class TestDotenvResolution:
    """Tests for dotenv/dotenv_path resolution across sources."""

    def _clean_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

    def test_dotenv_env_var_enables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """FUNCTUALIZE_DOTENV=true enables dotenv."""
        self._clean_env(monkeypatch, tmp_path)
        monkeypatch.setenv("FUNCTUALIZE_DOTENV", "true")

        config = resolve_cli_config()

        assert config.dotenv is True

    def test_dotenv_path_env_var_sets_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """FUNCTUALIZE_DOTENV_PATH sets dotenv_path."""
        self._clean_env(monkeypatch, tmp_path)
        monkeypatch.setenv("FUNCTUALIZE_DOTENV_PATH", ".env.local")

        config = resolve_cli_config()

        assert config.dotenv_path == ".env.local"

    def test_dotenv_path_env_var_does_not_disable_project_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression: FUNCTUALIZE_DOTENV_PATH must not shadow project dotenv=true."""
        self._clean_env(monkeypatch, tmp_path)
        (tmp_path / "pyproject.toml").write_text("[tool.functualize]\ndotenv = true\n")
        monkeypatch.setenv("FUNCTUALIZE_DOTENV_PATH", ".env.local")

        config = resolve_cli_config()

        assert config.dotenv is True
        assert config.dotenv_path == ".env.local"

    def test_project_dotenv_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Top-level dotenv=true in pyproject [tool.functualize] is honored."""
        self._clean_env(monkeypatch, tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[tool.functualize]\ndotenv = true\ndotenv_path = ".env.proj"\n'
        )

        config = resolve_cli_config()

        assert config.dotenv is True
        assert config.dotenv_path == ".env.proj"


class TestOutputValidation:
    """Tests for output format validation."""

    def test_valid_output_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Valid output values are accepted."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        for fmt in ("rich", "plain", "json"):
            config = resolve_cli_config(cli_flags={"output": fmt})
            assert config.output == fmt

    def test_invalid_output_warns_and_falls_back(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """Invalid output value → warn + fall back to 'rich'."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        config = resolve_cli_config(cli_flags={"output": "xml"})

        assert config.output == "rich"
        captured = capsys.readouterr()
        assert "Warning:" in captured.err
        assert "xml" in captured.err


# =============================================================================
# resolve_cli_config — list merge
# =============================================================================


class TestListMerge:
    """Tests for list merge and deduplication."""

    def test_merge_exclude_patterns_project_and_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Exclude patterns from project + global are merged and deduplicated."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        # Global config
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(
            '[discovery]\nexclude_patterns = ["**/test_*.py", "**/migrations/*"]\n'
        )

        # Project config
        (tmp_path / "pyproject.toml").write_text(
            '[tool.functualize.discovery]\nexclude_patterns = ["**/test_*.py", "build/*"]\n'
        )

        config = resolve_cli_config()

        # Project comes first, global entries that are unique come after
        assert "**/test_*.py" in config.discovery.exclude_patterns
        assert "build/*" in config.discovery.exclude_patterns
        assert "**/migrations/*" in config.discovery.exclude_patterns
        # No duplicates
        assert config.discovery.exclude_patterns.count("**/test_*.py") == 1

    def test_cli_exclude_appended_on_top(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """CLI --exclude patterns are appended after project+global."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        # Project config
        (tmp_path / "pyproject.toml").write_text(
            '[tool.functualize.discovery]\nexclude_patterns = ["existing/*"]\n'
        )

        config = resolve_cli_config(cli_flags={"exclude_patterns": ["new_pattern/*"]})

        assert "existing/*" in config.discovery.exclude_patterns
        assert "new_pattern/*" in config.discovery.exclude_patterns

    def test_merge_lists_dedup_function(self):
        """Direct test of _merge_lists_dedup helper."""
        result = _merge_lists_dedup(["a", "b", "c"], ["b", "d", "e"])
        assert result == ("a", "b", "c", "d", "e")

    def test_merge_lists_dedup_none_inputs(self):
        """_merge_lists_dedup handles None inputs gracefully."""
        assert _merge_lists_dedup(None, None) == ()
        assert _merge_lists_dedup(["a"], None) == ("a",)
        assert _merge_lists_dedup(None, ["b"]) == ("b",)


# =============================================================================
# resolve_cli_config — boolean parsing
# =============================================================================


class TestBooleanParsing:
    """Tests for boolean environment variable parsing."""

    def test_parse_bool_env_true_values(self):
        """true/1 → True (case-insensitive)."""
        assert _parse_bool_env("true") is True
        assert _parse_bool_env("True") is True
        assert _parse_bool_env("TRUE") is True
        assert _parse_bool_env("1") is True

    def test_parse_bool_env_false_values(self):
        """false/0 → False (case-insensitive)."""
        assert _parse_bool_env("false") is False
        assert _parse_bool_env("False") is False
        assert _parse_bool_env("FALSE") is False
        assert _parse_bool_env("0") is False

    def test_parse_bool_env_invalid_returns_none(self):
        """Invalid boolean strings return None."""
        assert _parse_bool_env("yes") is None
        assert _parse_bool_env("no") is None
        assert _parse_bool_env("2") is None
        assert _parse_bool_env("") is None

    def test_show_timing_env_var_parsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """FUNCTUALIZE_CLI_SHOW_TIMING=true → show_timing=True."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)
        monkeypatch.setenv("FUNCTUALIZE_CLI_SHOW_TIMING", "True")

        config = resolve_cli_config()

        assert config.show_timing is True


# =============================================================================
# resolve_cli_config — alias validation
# =============================================================================


class TestAliasValidation:
    """Tests for alias name validation."""

    def test_valid_aliases_accepted(self):
        """Valid alias names pass validation."""
        aliases = _validate_aliases(
            {"d": "deploy", "run-tests": "test", "abc_123": "job"}
        )
        assert aliases == {"d": "deploy", "run-tests": "test", "abc_123": "job"}

    def test_invalid_alias_starting_with_number_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Alias starting with a number is rejected with warning."""
        aliases = _validate_aliases({"1bad": "deploy"})
        assert "1bad" not in aliases
        captured = capsys.readouterr()
        assert "Warning:" in captured.err
        assert "1bad" in captured.err

    def test_alias_too_long_rejected(self, capsys: pytest.CaptureFixture[str]):
        """Alias exceeding 32 characters is rejected with warning."""
        long_name = "a" * 33
        aliases = _validate_aliases({long_name: "deploy"})
        assert long_name not in aliases
        captured = capsys.readouterr()
        assert "Warning:" in captured.err
        assert "32" in captured.err

    def test_alias_with_special_chars_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Alias with special characters is rejected with warning."""
        aliases = _validate_aliases({"d@ploy": "deploy"})
        assert "d@ploy" not in aliases
        captured = capsys.readouterr()
        assert "Warning:" in captured.err

    def test_alias_max_length_accepted(self):
        """Alias exactly at 32 characters is accepted."""
        name = "a" * 32
        aliases = _validate_aliases({name: "deploy"})
        assert name in aliases

    def test_non_string_value_rejected(self, capsys: pytest.CaptureFixture[str]):
        """Alias with non-string value is rejected."""
        aliases = _validate_aliases({"d": 123})  # type: ignore[dict-item]
        assert "d" not in aliases
        captured = capsys.readouterr()
        assert "Warning:" in captured.err

    def test_aliases_merged_project_over_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Project aliases override global aliases on conflict."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        for key in list(os.environ):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key)

        # Global config
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(
            '[aliases]\nd = "deploy-global"\nr = "run"\n'
        )

        # Project config
        (tmp_path / "pyproject.toml").write_text(
            '[tool.functualize.aliases]\nd = "deploy-project"\n'
        )

        config = resolve_cli_config()

        # Project wins for 'd'
        assert config.aliases["d"] == "deploy-project"
        # Global 'r' still present
        assert config.aliases["r"] == "run"


# =============================================================================
# XDG config path resolution
# =============================================================================


class TestXdgResolution:
    """Tests for resolve_user_config_dir (shared with app.utils)."""

    def test_xdg_set_uses_custom_path(self, monkeypatch: pytest.MonkeyPatch):
        """$XDG_CONFIG_HOME set → uses that directory."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
        result = resolve_user_config_dir()
        assert result == Path("/custom/config/functualize")

    def test_xdg_empty_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        """$XDG_CONFIG_HOME empty → falls back to ~/.config/functualize."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        result = resolve_user_config_dir()
        assert result == Path.home() / ".config" / "functualize"

    def test_xdg_unset_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        """$XDG_CONFIG_HOME unset → falls back to ~/.config/functualize."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = resolve_user_config_dir()
        assert result == Path.home() / ".config" / "functualize"
