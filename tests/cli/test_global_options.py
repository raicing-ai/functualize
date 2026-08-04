"""Unit tests for _extract_global_options in _cli/dispatch.py.

Validates Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import pytest

from functualize._cli.dispatch import _extract_global_options


class TestExtractGlobalOptionsLogLevel:
    """Tests for --log-level extraction."""

    def test_log_level_debug_before_positional(self) -> None:
        """--log-level DEBUG deploy extracts log_level=DEBUG, positional='deploy'."""
        opts, cli_flags = _extract_global_options(
            ["func", "--log-level", "DEBUG", "deploy"]
        )
        assert opts.log_level == "DEBUG"
        assert opts.first_positional_index == 2  # index in argv[1:] where "deploy" is

    def test_log_level_case_insensitive(self) -> None:
        """--log-level accepts lowercase and normalizes to uppercase."""
        opts, _ = _extract_global_options(["func", "--log-level", "info", "deploy"])
        assert opts.log_level == "INFO"

    def test_log_level_equals_syntax(self) -> None:
        """--log-level=WARNING style works."""
        opts, _ = _extract_global_options(["func", "--log-level=WARNING", "deploy"])
        assert opts.log_level == "WARNING"

    def test_invalid_log_level_raises_system_exit(self) -> None:
        """Invalid --log-level BOGUS triggers SystemExit (validation error)."""
        with pytest.raises(SystemExit) as exc_info:
            _extract_global_options(["func", "--log-level", "BOGUS", "deploy"])
        assert exc_info.value.code == 1

    def test_invalid_log_level_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Invalid --log-level prints descriptive error to stderr."""
        with pytest.raises(SystemExit):
            _extract_global_options(["func", "--log-level", "BOGUS", "deploy"])
        captured = capsys.readouterr()
        assert "BOGUS" in captured.err
        assert "--log-level" in captured.err


class TestExtractGlobalOptionsImportLibs:
    """Tests for --import-libs extraction."""

    def test_single_import_libs(self) -> None:
        """--import-libs ./vendor deploy extracts import_libs=['./vendor']."""
        opts, cli_flags = _extract_global_options(
            ["func", "--import-libs", "./vendor", "deploy"]
        )
        assert opts.import_libs == ["./vendor"]
        assert cli_flags["import_libs"] == ["./vendor"]

    def test_multiple_import_libs(self) -> None:
        """Multiple --import-libs accumulate into a list."""
        opts, cli_flags = _extract_global_options(
            ["func", "--import-libs", "./vendor", "--import-libs", "./lib", "deploy"]
        )
        assert opts.import_libs == ["./vendor", "./lib"]
        assert cli_flags["import_libs"] == ["./vendor", "./lib"]

    def test_import_libs_equals_syntax(self) -> None:
        """--import-libs=./vendor style works."""
        opts, _ = _extract_global_options(["func", "--import-libs=./vendor", "deploy"])
        assert opts.import_libs == ["./vendor"]


class TestExtractGlobalOptionsPassthrough:
    """Tests for unrecognized flags passing through (not consumed)."""

    def test_unrecognized_long_flag_stops_scanning(self) -> None:
        """Unrecognized --env flag is not consumed; treated as positional boundary."""
        opts, cli_flags = _extract_global_options(["func", "--env", "prod"])
        # --env is unrecognized, so scanning stops. first_positional_index
        # points to --env (index 0 in argv[1:])
        assert opts.first_positional_index == 0
        assert opts.log_level is None
        assert opts.import_libs is None

    def test_job_specific_flags_after_positional_not_consumed(self) -> None:
        """Flags after the positional argument are not consumed by global extraction."""
        opts, cli_flags = _extract_global_options(
            ["func", "--log-level", "DEBUG", "deploy", "--env", "prod"]
        )
        assert opts.log_level == "DEBUG"
        # "deploy" is at index 2 in argv[1:]
        assert opts.first_positional_index == 2
        # --env is after the positional, not touched

    def test_unrecognized_short_flag_stops_scanning(self) -> None:
        """Unrecognized short flag -v is not consumed."""
        opts, _ = _extract_global_options(["func", "-v", "deploy"])
        # -v is unrecognized, scanning stops at index 0
        assert opts.first_positional_index == 0


class TestExtractGlobalOptionsPositionalDetection:
    """Tests for correct positional argument detection."""

    def test_bare_invocation(self) -> None:
        """func with no args → first_positional_index=-1."""
        opts, cli_flags = _extract_global_options(["func"])
        assert opts.first_positional_index == -1
        assert cli_flags == {}

    def test_positional_only(self) -> None:
        """func deploy → first_positional_index=0 (deploy is at index 0 in argv[1:])."""
        opts, _ = _extract_global_options(["func", "deploy"])
        assert opts.first_positional_index == 0

    def test_global_options_then_positional(self) -> None:
        """func --no-dotenv --log-level INFO deploy → positional index reflects skipped options."""
        opts, _ = _extract_global_options(
            ["func", "--no-dotenv", "--log-level", "INFO", "deploy"]
        )
        assert opts.log_level == "INFO"
        assert opts.no_dotenv is True
        # --no-dotenv is index 0, --log-level is index 1, INFO is index 2, deploy is index 3
        assert opts.first_positional_index == 3

    def test_only_global_flags_no_positional(self) -> None:
        """func --no-dotenv --log-level INFO → scanning exhausts all args."""
        opts, _ = _extract_global_options(
            ["func", "--no-dotenv", "--log-level", "INFO"]
        )
        assert opts.log_level == "INFO"
        assert opts.no_dotenv is True
        # No positional found; first_positional_index remains -1
        assert opts.first_positional_index == -1


class TestExtractGlobalOptionsOtherFlags:
    """Tests for other supported global options."""

    def test_no_dotenv_flag(self) -> None:
        """--no-dotenv sets no_dotenv=True."""
        opts, cli_flags = _extract_global_options(["func", "--no-dotenv", "deploy"])
        assert opts.no_dotenv is True
        assert cli_flags.get("dotenv") is False

    def test_dotenv_file(self) -> None:
        """--dotenv-file .env.local extracts correctly."""
        opts, cli_flags = _extract_global_options(
            ["func", "--dotenv-file", ".env.local", "deploy"]
        )
        assert opts.dotenv_file == ".env.local"
        assert cli_flags["dotenv_path"] == ".env.local"

    def test_discovery_depth(self) -> None:
        """--discovery-depth 3 extracts as integer."""
        opts, cli_flags = _extract_global_options(
            ["func", "--discovery-depth", "3", "deploy"]
        )
        assert opts.discovery_depth == 3
        assert cli_flags["scan_depth"] == 3

    def test_exclude_accumulates(self) -> None:
        """Multiple --exclude flags accumulate."""
        opts, cli_flags = _extract_global_options(
            ["func", "--exclude", "__pycache__", "--exclude", ".git", "deploy"]
        )
        assert opts.exclude == ["__pycache__", ".git"]
        assert cli_flags["exclude_patterns"] == ["__pycache__", ".git"]

    def test_cli_flags_only_contains_non_none(self) -> None:
        """cli_flags dict only contains non-None overrides."""
        _, cli_flags = _extract_global_options(["func", "deploy"])
        assert cli_flags == {}

    def test_argv_not_mutated(self) -> None:
        """Original argv list is not mutated."""
        argv = ["func", "--log-level", "DEBUG", "deploy"]
        original = argv.copy()
        _extract_global_options(argv)
        assert argv == original
