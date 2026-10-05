"""Integration tests for early-parse flag combinations through real main() entry point.

Validates Requirements 1.7, 2.9, 2.10, 2.11 from the perf-report-flag-tui-fix spec.

These tests exercise the full CLI stack end-to-end using the `cli_run` fixture,
verifying that early-parse global flags interact correctly with positional
routing: a value-required flag consumes the token after it, and only what is
left is a command candidate.
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

    def test_perf_report_followed_by_job_name_is_a_usage_error(
        self, cli_run, project_tree
    ) -> None:
        """`func --perf-report forecast`: the job name is the flag's value.

        The flag is value-required, so "forecast" is consumed as its value —
        an invalid one — and no command lookup happens: exit 2 naming the
        accepted formats, never a run and never `Unknown command`.

        Validates: Requirements 1.7, 2.9 (one arity per pre-boot flag)
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--perf-report", "forecast"], cwd=root)
        assert result.exit_code == 2, (
            f"Expected exit 2 (usage error), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "--perf-report must be one of" in result.stderr
        assert "'forecast'" in result.stderr
        assert "rain-output" not in result.stdout

    def test_emit_format_followed_by_job_name_is_a_usage_error(
        self, cli_run, project_tree
    ) -> None:
        """`func --emit-format forecast`: the job name is the flag's value.

        The same rule as its --perf-report twin: the token after a
        value-required flag is its value, invalid here, and the run never
        starts.

        Validates: Requirements 1.7, 2.9 (one arity per pre-boot flag)
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--emit-format", "forecast"], cwd=root)
        assert result.exit_code == 2, (
            f"Expected exit 2 (usage error), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "--emit-format must be one of" in result.stderr
        assert "'forecast'" in result.stderr
        assert "rain-output" not in result.stdout

    def test_multiple_flags_with_job(self, cli_run, project_tree) -> None:
        """A known global flag after a value-required flag is a missing value.

        `func --log-level DEBUG --perf-report --no-dotenv forecast`
        - --log-level consumes "DEBUG"
        - --perf-report's value slot holds --no-dotenv, a pre-boot-owned
          token: the value is missing, and --no-dotenv is neither swallowed
          nor applied — exit 2, not a run of "forecast".

        Validates: Requirements 2.10
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(
            ["--log-level", "DEBUG", "--perf-report", "--no-dotenv", "forecast"],
            cwd=root,
        )
        assert result.exit_code == 2, (
            f"Expected exit 2 (missing value), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "--perf-report requires a value: one of {json, text}." in (result.stderr)
        assert "rain-output" not in result.stdout

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
        """Invalid --discovery-depth value exits with error code 2.

        `func --discovery-depth abc forecast` → exit 2, error on stderr. A
        wrong value is a usage error for every value-required flag, so the
        non-integer depth joins the selection-table flags at exit 2.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--discovery-depth", "abc", "forecast"], cwd=root)
        assert result.exit_code == 2, (
            f"Expected exit 2 (validation error), got {result.exit_code}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert (
            "discovery-depth" in result.stderr.lower()
            or "discovery" in result.stderr.lower()
        )

    def test_invalid_perf_format(self, cli_run, project_tree) -> None:
        """Invalid --perf-report format value exits with error code 2.

        `func --perf-report=yaml forecast` → exit 2, error on stderr — the
        same usage family as a missing value.

        Validates: Requirements 1.7, 2.9
        """
        root = project_tree(
            jobs={"forecast.py": "def forecast():\n    print('rain-output')\n"}
        )
        result = cli_run(["--perf-report=yaml", "forecast"], cwd=root)
        assert result.exit_code == 2, (
            f"Expected exit 2 (validation error), got {result.exit_code}.\n"
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
