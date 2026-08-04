"""Integration tests for CLI --perf-report and --perf-filter flags.

Tests the CLI flag behavior for performance report output including:
- Default text format output
- JSON format output
- Invalid format error handling
- Filter pattern support
- No-data message when no marks are recorded
- Report printing after command failure

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


def _create_job_module(jobs_dir: Path, filename: str, code: str) -> Path:
    """Write a job module file into the given jobs directory."""
    job_file = jobs_dir / filename
    job_file.write_text(textwrap.dedent(code))
    return job_file


class TestPerfReportTextFormat:
    """Test --perf-report prints text summary by default."""

    def test_perf_report_flag_prints_text_summary(self, tmp_path):
        """--perf-report without format argument prints text summary."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "", "simple"])

        assert result.exit_code == 0
        assert "done" in result.output
        # Text summary should include "Total:" and phase durations
        assert "Total:" in result.output
        assert "ms" in result.output

    def test_perf_report_text_explicit_prints_text_summary(self, tmp_path):
        """--perf-report=text prints text summary."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "text", "simple"])

        assert result.exit_code == 0
        assert "done" in result.output
        assert "Total:" in result.output
        assert "ms" in result.output


class TestPerfReportJsonFormat:
    """Test --perf-report=json prints valid JSON."""

    def test_perf_report_json_prints_valid_json(self, tmp_path):
        """--perf-report=json prints valid JSON output."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "json", "simple"])

        assert result.exit_code == 0
        assert "done" in result.output

        # Extract JSON from output (after the command's own output)
        output_lines = result.output.strip().split("\n")
        # The JSON should be on the last line (after "done")
        json_line = output_lines[-1]
        data = json.loads(json_line)

        assert "total_ms" in data
        assert "phases" in data
        assert "marks" in data
        assert isinstance(data["total_ms"], int | float)
        assert isinstance(data["phases"], list)
        assert isinstance(data["marks"], list)
        # Boot marks should be present
        assert len(data["marks"]) > 0


class TestPerfReportInvalidFormat:
    """Test --perf-report=invalid exits with error."""

    def test_perf_report_invalid_format_exits_with_error(self, tmp_path):
        """--perf-report=invalid exits with code 1 and shows error."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "invalid", "simple"])

        assert result.exit_code == 1
        assert "Error" in result.output
        assert "text" in result.output
        assert "json" in result.output
        # The command should NOT have run
        assert "done" not in result.output

    def test_perf_report_csv_format_exits_with_error(self, tmp_path):
        """--perf-report=csv exits with code 1 (only text/json accepted)."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "csv", "simple"])

        assert result.exit_code == 1
        assert "Error" in result.output


class TestPerfReportFilter:
    """Test --perf-report --perf-filter filters output."""

    def test_perf_filter_narrows_text_output(self, tmp_path):
        """--perf-report --perf-filter=boot.plugins shows only matching phases."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            ["--perf-report", "text", "--perf-filter", "boot.plugins", "simple"],
        )

        assert result.exit_code == 0
        assert "done" in result.output
        # Output should contain "Total:" (report header)
        assert "Total:" in result.output
        # Should contain boot.plugins phase
        assert "boot.plugins" in result.output
        # Should NOT contain other boot phases (they are filtered out)
        assert "boot.observability" not in result.output
        assert "boot.children" not in result.output

    def test_perf_filter_narrows_json_output(self, tmp_path):
        """--perf-report=json --perf-filter=boot.plugins filters JSON output."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            ["--perf-report", "json", "--perf-filter", "boot.plugins", "simple"],
        )

        assert result.exit_code == 0

        output_lines = result.output.strip().split("\n")
        json_line = output_lines[-1]
        data = json.loads(json_line)

        # All phases should start with boot.plugins
        for phase in data["phases"]:
            assert phase["name"].startswith("boot.plugins"), (
                f"Phase '{phase['name']}' does not match filter 'boot.plugins'"
            )


class TestPerfReportNoData:
    """Test --perf-report with no marks prints no-data message."""

    def test_perf_report_no_marks_prints_no_data_message(self, tmp_path):
        """--perf-report with no recorded marks prints 'No performance data available.'"""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            from functualize._events.perf import perf_timeline

            def simple():
                '''A simple job that resets the timeline.'''
                perf_timeline.reset()
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "", "simple"])

        assert result.exit_code == 0
        assert "done" in result.output
        # After reset, no marks exist so the report should show no-data message
        assert "No performance data available." in result.output

    def test_perf_report_filter_no_match_prints_no_data(self, tmp_path):
        """--perf-report with filter that matches nothing prints no-data message."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''A simple job.'''
                print("done")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            [
                "--perf-report",
                "text",
                "--perf-filter",
                "nonexistent.phase.that.wont.match",
                "simple",
            ],
        )

        assert result.exit_code == 0
        assert "done" in result.output
        # With a filter that doesn't match any phase, summary returns no-data message
        assert "No performance data available." in result.output


class TestPerfReportWithFailingCommand:
    """Test --perf-report with failing command still prints report."""

    def test_perf_report_printed_after_failing_command(self, tmp_path):
        """--perf-report still prints report even when command fails."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "failing.py",
            """\
            def failing():
                '''A job that fails.'''
                raise RuntimeError("intentional failure")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--perf-report", "text", "failing"])

        # The command should have run (and failed), but report still prints
        # Note: Depending on how Typer handles exceptions + call_on_close,
        # the exit code may be non-zero but the report should still appear
        assert (
            "Total:" in result.output
            or "No performance data available." in result.output
        )
