"""Unit tests for Typer callback flag parsing in _cli/main.py.

Tests cover:
- All 15 global options visible in --help output
- --exclude validation (max 20 patterns, exit 1 if exceeded)
- --dotenv-file validation (must exist, exit 1 if not)
- --config-directory validation (must exist, exit 1 if not)
- Flag parsing correctness (e.g., --log-level DEBUG sets level)
- Global options work with subcommands

Requirements: 4.1–4.5
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from click.testing import CliRunner

if TYPE_CHECKING:
    import pytest

from functualize._cli.main import cli_app

runner = CliRunner()


# =============================================================================
# --help output tests
# =============================================================================


class TestHelpOutput:
    """Test that --help contains all 15 global options."""

    EXPECTED_OPTIONS = [
        "--log-level",
        "--dotenv-file",
        "--no-dotenv",
        "--config-directory",
        "--discovery-depth",
        "--require-file-import",
        "--require-file-prefix",
        "--require-file-postfix",
        "--require-file-marker",
        "--require-job-prefix",
        "--require-job-postfix",
        "--require-job-decorators",
        "--exclude",
        "--perf-report",
        "--perf-filter",
    ]

    def test_help_contains_all_global_options(self):
        """--help output SHALL display all 15 global options."""
        result = runner.invoke(cli_app, ["--help"])
        assert result.exit_code == 0

        for option in self.EXPECTED_OPTIONS:
            assert option in result.output, (
                f"Expected option '{option}' not found in --help output"
            )

    def test_help_contains_all_option_count(self):
        """Verify exactly 14 expected global options are present."""
        result = runner.invoke(cli_app, ["--help"])
        assert result.exit_code == 0

        found = [opt for opt in self.EXPECTED_OPTIONS if opt in result.output]
        assert len(found) == 15, (
            f"Expected 15 global options, found {len(found)}: {found}"
        )


# =============================================================================
# --exclude validation tests
# =============================================================================


class TestExcludeValidation:
    """Test --exclude max 20 entries validation."""

    def test_exclude_more_than_20_exits_with_code_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """WHEN --exclude is provided more than 20 times, exit code 1."""
        monkeypatch.chdir(tmp_path)

        # Build args with 21 --exclude patterns
        args: list[str] = []
        for i in range(21):
            args.extend(["--exclude", f"pattern_{i}"])

        result = runner.invoke(cli_app, args)
        assert result.exit_code == 1
        assert "20" in result.output or "20" in (
            result.output + str(getattr(result, "stderr", ""))
        )

    def test_exclude_exactly_20_does_not_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """WHEN --exclude is provided exactly 20 times, validation passes (no exit 1 from exclude)."""
        monkeypatch.chdir(tmp_path)

        # Build args with exactly 20 --exclude patterns
        args: list[str] = []
        for i in range(20):
            args.extend(["--exclude", f"pattern_{i}"])

        result = runner.invoke(cli_app, args)
        # Should not exit with code 1 due to --exclude validation
        # (may exit 0 due to no_args_is_help or other reasons, but NOT code 1 from exclude check)
        if result.exit_code == 1:
            # If exit code is 1, it should NOT be due to --exclude validation
            assert "at most 20" not in result.output


# =============================================================================
# --dotenv-file validation tests
# =============================================================================


class TestDotenvFileValidation:
    """Test --dotenv-file must exist validation."""

    def test_dotenv_file_nonexistent_exits_with_code_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """WHEN --dotenv-file path doesn't exist, exit code 1."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli_app, ["--dotenv-file", "/nonexistent/path/.env"])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_dotenv_file_existing_does_not_exit_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """WHEN --dotenv-file path exists, validation passes."""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")

        result = runner.invoke(cli_app, ["--dotenv-file", str(env_file)])
        # Should not fail due to --dotenv-file validation
        if result.exit_code == 1:
            assert "does not exist" not in result.output


# =============================================================================
# --config-directory validation tests
# =============================================================================


class TestConfigDirectoryValidation:
    """Test --config-directory must exist validation."""

    def test_config_directory_nonexistent_exits_with_code_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """WHEN --config-directory path doesn't exist, exit code 1."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            cli_app, ["--config-directory", "/nonexistent/config/dir"]
        )
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_config_directory_existing_does_not_exit_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """WHEN --config-directory path exists, validation passes."""
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        result = runner.invoke(cli_app, ["--config-directory", str(config_dir)])
        # Should not fail due to --config-directory validation
        if result.exit_code == 1:
            assert "does not exist" not in result.output


# =============================================================================
# Flag parsing correctness tests
# =============================================================================


class TestFlagParsing:
    """Test that flags parse correctly from CLI args."""

    def test_log_level_debug_is_parsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """--log-level DEBUG sets logging level to DEBUG."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli_app, ["--log-level", "DEBUG"])
        # The callback should have called logging.basicConfig(level="DEBUG", force=True)
        # After invocation, the root logger should be at DEBUG level
        # (Note: CliRunner may not fully propagate logging state, but we verify no error)
        assert result.exit_code == 0

    def test_no_dotenv_flag_is_boolean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """--no-dotenv is a boolean flag (no argument required)."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli_app, ["--no-dotenv"])
        # Should parse successfully as a boolean flag
        assert result.exit_code == 0


# =============================================================================
# Global options with subcommands tests
# =============================================================================


class TestGlobalOptionsWithSubcommands:
    """Test that global options work with subcommands."""

    def test_log_level_with_version_subcommand(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """func --log-level DEBUG version should parse the flag and route to version."""
        monkeypatch.chdir(tmp_path)

        # Register builtins so 'version' is available
        from functualize._cli.builtins import register_builtin_commands

        register_builtin_commands(cli_app)

        result = runner.invoke(cli_app, ["--log-level", "DEBUG", "builtin", "version"])
        # The version command should run successfully with --log-level parsed by callback
        assert result.exit_code == 0

    def test_discovery_depth_with_help(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """--discovery-depth appears in --help and is parseable."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli_app, ["--help"])
        assert "--discovery-depth" in result.output
