"""Integration tests verifying perf report output in direct-dispatch modes.

Tests exercise the real main() entry point via the cli_run fixture, verifying
that --perf-report correctly activates performance timeline recording and
outputs to stderr in JOB, BARE, and default-format scenarios.

Validates: Requirements 2.6, 2.7
"""

from __future__ import annotations

import json


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


class TestPerfReportDefaultWithJob:
    """func --perf-report <job> (no explicit format) uses default "text"."""

    def test_perf_report_default_with_job(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        # --perf-report followed by job name (not a valid format value)
        # should use default format "text" and route "hello" as the job
        result = cli_run(["--perf-report", "hello"], cwd=root)
        assert result.exit_code == 0
        # Job should execute
        assert "world" in result.stdout
        # Perf report in text format on stderr
        assert "Total:" in result.stderr
        assert "ms" in result.stderr


class TestPerfReportBareMode:
    """func --perf-report in bare mode (non-TTY) produces perf report on stderr."""

    def test_perf_report_bare_mode(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"hello.py": "def hello():\n    print('world')\n"})
        # --perf-report with no job name → BARE mode (cli_run is non-TTY)
        # Should list jobs AND print perf report on stderr
        result = cli_run(["--perf-report"], cwd=root)
        assert result.exit_code == 0
        # BARE mode lists discovered jobs on stdout
        assert "hello" in result.stdout
        # Perf report should appear on stderr
        assert "Total:" in result.stderr
        assert "ms" in result.stderr


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
