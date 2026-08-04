"""Tests for the `func cache` sub-commands.

Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 6.6
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from click.testing import CliRunner

runner = CliRunner()


def _create_typer_with_cache() -> click.Group:
    """Create a Typer app with cache commands registered for testing."""
    from functualize._cli.builtins import register_builtin_commands

    app = click.Group(name="func")
    register_builtin_commands(app)
    return app


class TestCacheClear:
    """Tests for `func cache clear`."""

    def test_no_cache_file_exits_silently(self, tmp_path: Path) -> None:
        app = _create_typer_with_cache()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["builtin", "cache", "clear"])
        finally:
            os.chdir(old_cwd)
        # Should exit 0 without error
        assert result.exit_code == 0
        assert "Cache cleared" not in result.output

    def test_cache_file_deleted_with_confirmation(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / ".functualize"
        cache_dir.mkdir()
        cache_path = cache_dir / "cache.json"
        cache_path.write_text("{}")
        assert cache_path.exists()

        app = _create_typer_with_cache()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["builtin", "cache", "clear"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code == 0
        assert "Cache cleared" in result.output
        assert not cache_path.exists()


class TestCacheCheck:
    """Tests for `func cache check`."""

    def test_no_cache_file_reports_no_cache(self, tmp_path: Path) -> None:
        app = _create_typer_with_cache()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["builtin", "cache", "check"])
        finally:
            os.chdir(old_cwd)
        assert result.exit_code == 0
        assert "No cache file found" in result.output


class TestCacheSubcommandRegistration:
    """Tests for cache subcommand availability in help output."""

    def test_cache_subcommands_visible(self) -> None:
        """Running 'cache --help' shows sub-commands: show, clear, rebuild, check."""
        app = _create_typer_with_cache()
        result = runner.invoke(app, ["builtin", "cache", "--help"])

        assert result.exit_code == 0
        assert "show" in result.output
        assert "clear" in result.output
        assert "rebuild" in result.output
        assert "check" in result.output
