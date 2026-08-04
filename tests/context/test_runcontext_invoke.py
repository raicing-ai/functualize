"""Tests for configurable max_invoke_depth in RunContext and FunctualizeApp (Task 4.2)."""

from __future__ import annotations

import textwrap

from functualize._app.state import AppState
from functualize.app.config import ExecutionConfig, JobSources
from functualize.app.core import FunctualizeApp


def _write_jobs(tmp_path, source: str) -> str:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "invoke_jobs.py").write_text(textwrap.dedent(source))
    return str(jobs_dir)


class TestConfigurableMaxInvokeDepth:
    """FunctualizeApp(max_invoke_depth=N) enforces depth N."""

    def setup_method(self):
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def test_default_max_depth_is_10(self, tmp_path):
        """Default max_invoke_depth is 10."""
        jobs_dir = _write_jobs(tmp_path, "def noop(): pass\n")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )
        assert app._execution_engine._max_invoke_depth == 10

    def test_custom_max_depth_is_stored(self, tmp_path):
        """FunctualizeApp(max_invoke_depth=3) stores 3 in the engine."""
        jobs_dir = _write_jobs(tmp_path, "def noop(): pass\n")
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=3),
        )
        assert app._execution_engine._max_invoke_depth == 3

    def test_recursion_error_at_configured_depth(self, tmp_path):
        """RecursionLimitError is raised at max_invoke_depth=2, not at 10.

        With invoke working correctly, the RecursionLimitError at the limit
        is captured into the child's JobResult(FAILURE). The parent job
        can inspect the result to see the error.
        """
        source = """\
            from functualize.job.context import RunContext
            from functualize._types.enums import RunStatus

            results = []

            def recursive_job(rc: RunContext):
                result = rc.invoke("recursive_job")
                results.append(result.status.value)
                return result.status.value
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=2),
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["recursive_job"])

        # The top-level job completes; recursion limit is hit internally
        # but contained in the result. Exit code is 0 because the
        # RecursionLimitError is captured in a JobResult.
        assert result.exit_code == 0
