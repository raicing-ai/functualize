"""Integration tests verifying perf report output in direct-dispatch modes.

Tests exercise the real main() entry point via the cli_run fixture, verifying
that --perf-report correctly activates performance timeline recording and
outputs to stderr in JOB, BARE, and default-format scenarios.

Validates: Requirements 2.6, 2.7
"""

from __future__ import annotations

import json

from tests.conftest import surfaces

# `func`-only: `--perf-report` is a pre-command global parsed by `func`'s
# pre-boot layer; click has no equivalent on an app's own tree, so there is
# no second surface for these to run on.
#
# One more face of the dispatch-layer divergence recorded in `.spec/STATE.md`.
pytestmark = surfaces("func")


class TestPerfReportTextWithJob:
    """func --perf-report text <job> produces text perf report on stderr."""

    def test_perf_report_text_with_job(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        result = cli_run(["--perf-report", "text", "hello"], cwd=root)
        assert result.exit_code == 0
        # Job should still produce its stdout output
        assert "world" in result.stdout
        # Perf report should be on stderr with timing data
        assert "Total:" in result.stderr
        assert "ms" in result.stderr


class TestPerfReportJsonWithJob:
    """func --perf-report json <job> produces JSON perf report on stderr."""

    def test_perf_report_json_with_job(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        result = cli_run(["--perf-report", "json", "hello"], cwd=root)
        assert result.exit_code == 0
        # Job should still produce its stdout output
        assert "world" in result.stdout
        # Perf report should be valid JSON on stderr
        perf_data = json.loads(result.stderr)
        assert "total_ms" in perf_data
        assert "phases" in perf_data
        assert "marks" in perf_data


class TestPerfReportRequiresItsValue:
    """A bare --perf-report is a missing value, in both spellings."""

    def test_perf_report_followed_by_job_name_is_a_usage_error(
        self, cli_run, project_tree
    ) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        # The job name is the flag's value — an invalid one — so the run
        # never starts and the sentence names the accepted formats.
        result = cli_run(["--perf-report", "hello"], cwd=root)
        assert result.exit_code == 2
        assert "--perf-report must be one of {json, text}, got 'hello'." in (
            result.stderr
        )
        assert "world" not in result.stdout

    def test_perf_report_alone_is_a_missing_value(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        # Nothing follows the flag: exit 2 with the missing-value sentence,
        # not a bare-mode listing with a default-format report.
        result = cli_run(["--perf-report"], cwd=root)
        assert result.exit_code == 2
        assert "--perf-report requires a value: one of {json, text}." in (result.stderr)
        assert "hello" not in result.stdout


class TestPerfReportJsonStructure:
    """Verify JSON perf report contains expected structure."""

    def test_perf_report_json_structure(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        result = cli_run(["--perf-report", "json", "hello"], cwd=root)
        assert result.exit_code == 0

        perf_data = json.loads(result.stderr)

        # Top-level structure
        assert isinstance(perf_data["total_ms"], (int, float))
        assert perf_data["total_ms"] > 0

        # Phases should be a list of dicts with name and duration_ms
        assert isinstance(perf_data["phases"], list)
        if perf_data["phases"]:
            phase = perf_data["phases"][0]
            assert "name" in phase
            assert "duration_ms" in phase
            assert isinstance(phase["duration_ms"], (int, float))

        # Marks should be a list of dicts with name and timestamp_ns
        assert isinstance(perf_data["marks"], list)
        if perf_data["marks"]:
            mark = perf_data["marks"][0]
            assert "name" in mark
            assert "timestamp_ns" in mark


class TestNoPerfReportWithoutFlag:
    """func <job> without --perf-report does NOT produce perf output on stderr."""

    def test_no_perf_report_without_flag(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        result = cli_run(["hello"], cwd=root)
        assert result.exit_code == 0
        assert "world" in result.stdout
        # No perf report — stderr should NOT contain timing data
        assert "Total:" not in result.stderr
        assert "total_ms" not in result.stderr
