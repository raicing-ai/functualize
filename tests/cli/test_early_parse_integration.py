"""Integration tests for early-parse flag combinations through real main() entry point.

Validates Requirements 1.7, 2.9, 2.10, 2.11 from the perf-report-flag-tui-fix spec.

These tests exercise the full CLI stack end-to-end using the `cli_run` fixture,
verifying that early-parse global flags interact correctly with positional routing
after the Bug A fix (optional-value flag lookahead).
"""

from __future__ import annotations

from tests.conftest import surfaces

# `func`-only: this exercises the **pre-boot dispatch layer**
# (`_cli/dispatch.py` + `_cli/main.py`), which resolves the command, renders
# listings and errors, and handles pre-command global flags before an app is
# ever built. An app entry point has no such layer — click owns its tree — so
# there is no second surface for these to run on.
#
# The underlying divergence is real and recorded in `.spec/STATE.md`: the two
# surfaces disagree about listings, unknown commands and their exit codes.
# Nothing in this cycle decided to close it.
pytestmark = surfaces("func")


class TestEarlyParseFlagIntegration:
    """Integration tests for early-parse flag combinations with job/builtin routing."""

    def test_perf_report_followed_by_job_name_routes_to_job(
        self, cli_run, project_tree
    ) -> None:
        """Bug A fix: `func --perf-report forecast` routes to JOB, not BARE.

        --perf-report without an explicit format value should default to "text"
        and leave "forecast" as the positional argument for mode detection.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--perf-report", "forecast"], cwd=root)
        assert result.exit_code == 0, (
            f"Expected exit 0 (job ran), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "rain-output" in result.stdout

    def test_output_followed_by_job_name_routes_to_job(
        self, cli_run, project_tree
    ) -> None:
        """Bug A fix: `func --output forecast` routes to JOB, not BARE.

        Since "forecast" is not in {"json", "text", "none"}, --output defaults
        to "none" and "forecast" remains a positional.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--output", "forecast"], cwd=root)
        assert result.exit_code == 0, (
            f"Expected exit 0 (job ran), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "rain-output" in result.stdout

    def test_multiple_flags_with_job(self, cli_run, project_tree) -> None:
        """Multiple early-parse flags combined still route positional to JOB.

        `func --log-level DEBUG --perf-report --no-dotenv forecast`
        - --log-level consumes "DEBUG"
        - --perf-report with no valid format next (--no-dotenv starts with -)
          defaults to "text"
        - --no-dotenv is a boolean flag
        - "forecast" is the first positional → Mode.JOB

        Validates: Requirements 2.10
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(
            ["--log-level", "DEBUG", "--perf-report", "--no-dotenv", "forecast"],
            cwd=root,
        )
        assert result.exit_code == 0, (
            f"Expected exit 0 (job ran), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "rain-output" in result.stdout

    def test_flags_with_builtin(self, cli_run) -> None:
        """Early-parse flags combined with builtin command route to BUILTIN.

        ``func --log-level DEBUG builtin version`` → Mode.BUILTIN

        Validates: Requirements 2.11
        """
        result = cli_run(["--log-level", "DEBUG", "builtin", "version"])
        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "functualize" in result.stdout.lower()

    def test_perf_report_equals_syntax(self, cli_run, project_tree) -> None:
        """Equals-syntax `func --perf-report=json forecast` works correctly.

        The `=`-style syntax should parse the format value and route
        "forecast" to Mode.JOB.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--perf-report=json", "forecast"], cwd=root)
        assert result.exit_code == 0, (
            f"Expected exit 0 (job ran), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "rain-output" in result.stdout

    def test_invalid_discovery_depth(self, cli_run, project_tree) -> None:
        """Invalid --discovery-depth value exits with error code 1.

        `func --discovery-depth abc forecast` → exit 1, error on stderr.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--discovery-depth", "abc", "forecast"], cwd=root)
        assert result.exit_code == 1, (
            f"Expected exit 1 (validation error), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert (
            "discovery-depth" in result.stderr.lower()
            or "discovery" in result.stderr.lower()
        )

    def test_invalid_perf_format(self, cli_run, project_tree) -> None:
        """Invalid --perf-report format value exits with error code 1.

        `func --perf-report=yaml forecast` → exit 1, error on stderr.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--perf-report=yaml", "forecast"], cwd=root)
        assert result.exit_code == 1, (
            f"Expected exit 1 (validation error), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "perf-report" in result.stderr.lower() or "perf" in result.stderr.lower()

    def test_perf_report_explicit_text_with_job(self, cli_run, project_tree) -> None:
        """Explicit format value: `func --perf-report text forecast` routes to JOB.

        "text" is consumed as the format value for --perf-report, and "forecast"
        remains as the positional → Mode.JOB.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--perf-report", "text", "forecast"], cwd=root)
        assert result.exit_code == 0, (
            f"Expected exit 0 (job ran), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "rain-output" in result.stdout
