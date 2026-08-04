"""Unit tests for `func config` subcommands in _cli/builtins.py.

Tests cover:
- _resolve_editor(): $VISUAL → $EDITOR → platform default chain
- _toml_value(): formatting Python values as TOML strings
- _determine_source(): which config source provided a value
- config show: output format and source annotations (integration-style)
- config path: status indicators (✓ used / ○ found / ✗ missing)
- config edit: editor resolution, template creation, no-editor error

Requirements: 16.1–16.6
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from functualize._cli.builtins import (
    _CONFIG_TEMPLATE,
    _determine_source,
    _resolve_editor,
    _toml_value,
)

if TYPE_CHECKING:
    import pytest

# =============================================================================
# _resolve_editor tests
# =============================================================================


class TestResolveEditor:
    """Tests for _resolve_editor() — Req 16.3, 16.5."""

    def test_visual_set_returns_visual(self, monkeypatch: pytest.MonkeyPatch):
        """$VISUAL set → returns that value."""
        monkeypatch.setenv("VISUAL", "code")
        monkeypatch.setenv("EDITOR", "vim")
        assert _resolve_editor() == "code"

    def test_visual_empty_editor_set_returns_editor(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """$VISUAL empty, $EDITOR set → returns $EDITOR."""
        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "nano")
        assert _resolve_editor() == "nano"

    def test_both_empty_linux_vi_on_path(self, monkeypatch: pytest.MonkeyPatch):
        """Both empty, platform Linux + vi on PATH → returns 'vi'."""
        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "")
        with (
            patch("functualize._cli.builtins.platform.system", return_value="Linux"),
            patch("functualize._cli.builtins.shutil.which", return_value="/usr/bin/vi"),
        ):
            assert _resolve_editor() == "vi"

    def test_both_empty_windows(self, monkeypatch: pytest.MonkeyPatch):
        """Both empty, platform Windows → returns 'notepad'."""
        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "")
        with patch("functualize._cli.builtins.platform.system", return_value="Windows"):
            assert _resolve_editor() == "notepad"

    def test_both_empty_darwin_vi_on_path(self, monkeypatch: pytest.MonkeyPatch):
        """Both empty, platform Darwin + vi on PATH → returns 'vi'."""
        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "")
        with (
            patch("functualize._cli.builtins.platform.system", return_value="Darwin"),
            patch("functualize._cli.builtins.shutil.which", return_value="/usr/bin/vi"),
        ):
            assert _resolve_editor() == "vi"

    def test_both_empty_no_vi_on_path(self, monkeypatch: pytest.MonkeyPatch):
        """Both empty, no vi on PATH → returns None."""
        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "")
        with (
            patch("functualize._cli.builtins.platform.system", return_value="Linux"),
            patch("functualize._cli.builtins.shutil.which", return_value=None),
        ):
            assert _resolve_editor() is None

    def test_visual_unset_editor_set(self, monkeypatch: pytest.MonkeyPatch):
        """$VISUAL unset, $EDITOR set → returns $EDITOR."""
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setenv("EDITOR", "emacs")
        assert _resolve_editor() == "emacs"

    def test_visual_whitespace_only_uses_editor(self, monkeypatch: pytest.MonkeyPatch):
        """$VISUAL whitespace-only → falls through to $EDITOR."""
        monkeypatch.setenv("VISUAL", "   ")
        monkeypatch.setenv("EDITOR", "vim")
        assert _resolve_editor() == "vim"


# =============================================================================
# _toml_value tests
# =============================================================================


class TestTomlValue:
    """Tests for _toml_value() — formatting Python values as TOML."""

    def test_none_returns_not_set(self):
        """None → '# (not set)'."""
        assert _toml_value(None) == "# (not set)"

    def test_true_returns_true(self):
        """True → 'true'."""
        assert _toml_value(True) == "true"

    def test_false_returns_false(self):
        """False → 'false'."""
        assert _toml_value(False) == "false"

    def test_string_returns_quoted(self):
        """String → quoted string."""
        assert _toml_value("rich") == '"rich"'

    def test_list_returns_formatted(self):
        """List → formatted TOML array."""
        assert _toml_value(["a", "b", "c"]) == '["a", "b", "c"]'

    def test_empty_list_returns_brackets(self):
        """Empty list → '[]'."""
        assert _toml_value([]) == "[]"

    def test_tuple_returns_formatted(self):
        """Tuple behaves like list."""
        assert _toml_value(("x", "y")) == '["x", "y"]'

    def test_single_item_list(self):
        """Single-item list → formatted."""
        assert _toml_value(["only"]) == '["only"]'


# =============================================================================
# _determine_source tests
# =============================================================================


class TestDetermineSource:
    """Tests for _determine_source() — Req 16.1."""

    def test_key_in_project_config(self, monkeypatch: pytest.MonkeyPatch):
        """Key present in project config → returns 'project'."""
        monkeypatch.delenv("FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT", raising=False)
        project_config = {"discovery": {"require_file_import": "functualize"}}
        global_config: dict = {}
        result = _determine_source(
            "require_file_import",
            "functualize",
            project_config,
            global_config,
            "discovery",
        )
        assert result == "project"

    def test_key_in_global_config_not_project(self, monkeypatch: pytest.MonkeyPatch):
        """Key in global config (not in project) → returns 'global'."""
        monkeypatch.delenv("FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT", raising=False)
        project_config: dict = {}
        global_config = {"discovery": {"require_file_import": "functualize"}}
        result = _determine_source(
            "require_file_import",
            "functualize",
            project_config,
            global_config,
            "discovery",
        )
        assert result == "global"

    def test_env_var_set(self, monkeypatch: pytest.MonkeyPatch):
        """Env var set → returns 'env'."""
        monkeypatch.setenv("FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT", "functualize")
        project_config: dict = {}
        global_config: dict = {}
        result = _determine_source(
            "require_file_import",
            "functualize",
            project_config,
            global_config,
            "discovery",
        )
        assert result == "env"

    def test_none_of_above_returns_default(self, monkeypatch: pytest.MonkeyPatch):
        """None of the above → returns 'default'."""
        monkeypatch.delenv("FUNCTUALIZE_DISCOVERY_OUTPUT", raising=False)
        monkeypatch.delenv("FUNCTUALIZE_CLI_OUTPUT", raising=False)
        project_config: dict = {}
        global_config: dict = {}
        result = _determine_source(
            "output", "rich", project_config, global_config, "cli"
        )
        assert result == "default"

    def test_project_takes_precedence_over_global(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Key in both project and global → returns 'project' (checked first)."""
        monkeypatch.delenv("FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT", raising=False)
        project_config = {"discovery": {"require_file_import": "proj_val"}}
        global_config = {"discovery": {"require_file_import": "glob_val"}}
        result = _determine_source(
            "require_file_import",
            "proj_val",
            project_config,
            global_config,
            "discovery",
        )
        assert result == "project"


# =============================================================================
# config show integration tests
# =============================================================================


class TestConfigShow:
    """Integration-style tests for `config show` — Req 16.1."""

    def test_default_config_outputs_toml_with_all_fields(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """With default config → outputs TOML with all discovery/cli/alias fields."""
        import click
        from click.testing import CliRunner

        # Clear env vars that could affect resolution
        for key in list(os.environ.keys()):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        result = runner.invoke(app, ["builtin", "config", "show"])

        assert result.exit_code == 0
        output = result.output

        # Should contain section headers
        assert "[discovery]" in output
        assert "[cli]" in output
        assert "[aliases]" in output

        # Should contain key fields (some as comments for None values)
        assert "exclude_patterns" in output
        assert "output" in output
        assert "show_timing" in output

    def test_config_show_with_aliases(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """With aliases configured → aliases section populated."""
        import click
        from click.testing import CliRunner

        # Clear env vars
        for key in list(os.environ.keys()):
            if key.startswith("FUNCTUALIZE_"):
                monkeypatch.delenv(key, raising=False)

        # Set up XDG config with aliases
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        config_file = xdg_dir / "config.toml"
        config_file.write_text('[aliases]\nd = "deploy"\nr = "run"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        result = runner.invoke(app, ["builtin", "config", "show"])

        assert result.exit_code == 0
        output = result.output

        assert "[aliases]" in output
        assert 'd = "deploy"' in output
        assert 'r = "run"' in output
        assert "source: global" in output


# =============================================================================
# config path integration tests
# =============================================================================


class TestConfigPath:
    """Integration-style tests for `config path` — Req 16.2."""

    def test_global_config_exists_shows_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Global config exists with values → shows '✓ used'."""
        import click
        from click.testing import CliRunner

        # Create global config with values
        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        config_file = xdg_dir / "config.toml"
        config_file.write_text('[cli]\noutput = "plain"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        result = runner.invoke(app, ["builtin", "config", "path"])

        assert result.exit_code == 0
        output = result.output
        assert "✓ used" in output
        assert str(config_file) in output

    def test_global_config_missing_shows_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Global config missing → shows '✗ missing'."""
        import click
        from click.testing import CliRunner

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        result = runner.invoke(app, ["builtin", "config", "path"])

        assert result.exit_code == 0
        output = result.output
        assert "✗ missing" in output

    def test_pyproject_with_tool_functualize_shows_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """pyproject.toml with [tool.functualize] → shows '✓ used'."""
        import click
        from click.testing import CliRunner

        # Create pyproject.toml with [tool.functualize]
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n\n'
            "[tool.functualize.discovery]\n"
            'require_file_import = "functualize"\n'
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        result = runner.invoke(app, ["builtin", "config", "path"])

        assert result.exit_code == 0
        output = result.output
        assert "✓ used" in output
        assert "pyproject.toml" in output
        assert "[tool.functualize]" in output

    def test_pyproject_without_tool_functualize_shows_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """pyproject.toml without [tool.functualize] → shows '○ found'."""
        import click
        from click.testing import CliRunner

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        result = runner.invoke(app, ["builtin", "config", "path"])

        assert result.exit_code == 0
        output = result.output
        assert "○ found" in output
        assert "no [tool.functualize]" in output


# =============================================================================
# config edit tests
# =============================================================================


class TestConfigEdit:
    """Tests for `config edit` — Req 16.3, 16.4, 16.5."""

    def test_no_editor_found_exits_with_code_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """No editor resolved → exits with code 1 and error message."""
        import click
        from click.testing import CliRunner

        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "functualize._cli.builtins.platform.system",
                return_value="Linux",
            ),
            patch("functualize._cli.builtins.shutil.which", return_value=None),
        ):
            app = click.Group(name="func")
            from functualize._cli.builtins import register_builtin_commands

            register_builtin_commands(app)

            runner = CliRunner()
            result = runner.invoke(app, ["builtin", "config", "edit"])

        assert result.exit_code == 1
        # Error message may be in output (CliRunner captures both)
        assert "No editor found" in result.output

    def test_config_directory_created_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Config directory is created if it doesn't exist."""
        import click
        from click.testing import CliRunner

        xdg_dir = tmp_path / "xdg" / "functualize"
        assert not xdg_dir.exists()

        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "cat")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        with patch("functualize._cli.builtins.subprocess.run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["builtin", "config", "edit"])

        # Directory should now exist
        assert xdg_dir.exists()
        assert result.exit_code == 0

    def test_template_file_created_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Template config file is created if it doesn't exist."""
        import click
        from click.testing import CliRunner

        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        config_path = xdg_dir / "config.toml"
        assert not config_path.exists()

        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "cat")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        with patch("functualize._cli.builtins.subprocess.run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["builtin", "config", "edit"])

        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert content == _CONFIG_TEMPLATE
        assert "[discovery]" in content
        assert "[cli]" in content
        assert "[aliases]" in content

    def test_existing_config_not_overwritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If config file already exists, it is NOT overwritten with template."""
        import click
        from click.testing import CliRunner

        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)
        config_path = xdg_dir / "config.toml"
        original_content = '[cli]\noutput = "json"\n'
        config_path.write_text(original_content)

        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "cat")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        with patch("functualize._cli.builtins.subprocess.run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["builtin", "config", "edit"])

        assert result.exit_code == 0
        # File content should not have changed
        assert config_path.read_text() == original_content

    def test_editor_invoked_with_config_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Editor is invoked with the config file path as argument."""
        import click
        from click.testing import CliRunner

        xdg_dir = tmp_path / "xdg" / "functualize"
        xdg_dir.mkdir(parents=True)

        monkeypatch.setenv("VISUAL", "")
        monkeypatch.setenv("EDITOR", "myeditor")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(tmp_path)

        app = click.Group(name="func")
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(app)

        runner = CliRunner()
        with patch("functualize._cli.builtins.subprocess.run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["builtin", "config", "edit"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["myeditor", str(xdg_dir / "config.toml")]
