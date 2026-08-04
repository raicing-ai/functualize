"""Tests for INVOKE_FAILURE hook integration (Task 8.3).

Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6
"""

from __future__ import annotations

import textwrap

import pytest

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize._types.enums import RunStatus
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp


def _write_jobs(tmp_path, source: str) -> str:
    """Helper to write job files and return the directory path."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "test_jobs.py").write_text(textwrap.dedent(source))
    return str(jobs_dir)


@pytest.fixture(autouse=True)
def reset_app_state():
    """Reset AppState before each test."""
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


class TestInvokeFailureHook:
    """Tests for INVOKE_FAILURE hook firing on child failure (Req 21.2)."""

    def test_invoke_failure_fires_on_child_failure(self, tmp_path):
        """INVOKE_FAILURE fires with (rc, child_job_name, depth, result) on FAILURE."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                return rc.invoke("failing_job")

            def failing_job(rc: RunContext):
                raise ValueError("something broke")
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []

        def on_invoke_failure(rc, child_name, depth, result):
            received.append(
                {
                    "parent_name": rc.name,
                    "child_name": child_name,
                    "depth": depth,
                    "status": result.status,
                }
            )

        app.hook_registry.register_global(HookEvent.INVOKE_FAILURE, on_invoke_failure)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert len(received) == 1
        assert received[0]["parent_name"] == "parent-job"
        assert received[0]["child_name"] == "failing-job"
        assert received[0]["depth"] == 1
        assert received[0]["status"] == RunStatus.FAILURE

    def test_invoke_failure_not_fired_on_success(self, tmp_path):
        """INVOKE_FAILURE does NOT fire when child succeeds (Req 21.6)."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                return rc.invoke("child_job")

            def child_job(rc: RunContext):
                return "success"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []
        app.hook_registry.register_global(
            HookEvent.INVOKE_FAILURE,
            lambda rc, name, depth, result: received.append(name),
        )

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert received == []

    def test_invoke_failure_not_fired_on_timeout(self, tmp_path):
        """INVOKE_FAILURE does NOT fire when child times out (Req 21.6)."""
        source = """\
            import time
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                rc.invoke("slow_job", timeout=0.2)

            def slow_job(rc: RunContext):
                time.sleep(1)
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []
        app.hook_registry.register_global(
            HookEvent.INVOKE_FAILURE,
            lambda rc, name, depth, result: received.append(name),
        )

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert received == []


class TestInvokeFailureBeforeEnd:
    """Tests that INVOKE_FAILURE fires BEFORE INVOKE_END (Req 21.4)."""

    def test_invoke_failure_fires_before_invoke_end(self, tmp_path):
        """INVOKE_FAILURE fires before INVOKE_END on child failure."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                return rc.invoke("failing_job")

            def failing_job(rc: RunContext):
                raise RuntimeError("boom")
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        events = []

        def on_failure(rc, child_name, depth, result):
            events.append("INVOKE_FAILURE")

        def on_end(rc, child_name, depth, result):
            events.append("INVOKE_END")

        app.hook_registry.register_global(HookEvent.INVOKE_FAILURE, on_failure)
        app.hook_registry.register_global(HookEvent.INVOKE_END, on_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert events == ["INVOKE_FAILURE", "INVOKE_END"]


class TestInvokeFailureExceptionIsolation:
    """Tests that INVOKE_FAILURE hook exceptions don't prevent INVOKE_END (Req 21.5)."""

    def test_hook_exception_does_not_prevent_invoke_end(self, tmp_path):
        """If INVOKE_FAILURE hook raises, INVOKE_END still fires."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                return rc.invoke("failing_job")

            def failing_job(rc: RunContext):
                raise ValueError("job failed")
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        def bad_failure_hook(rc, child_name, depth, result):
            raise RuntimeError("failure hook exploded")

        end_received = []

        def on_end(rc, child_name, depth, result):
            end_received.append(result.status)

        app.hook_registry.register_global(HookEvent.INVOKE_FAILURE, bad_failure_hook)
        app.hook_registry.register_global(HookEvent.INVOKE_END, on_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        # INVOKE_END still fired despite INVOKE_FAILURE hook raising
        assert end_received == [RunStatus.FAILURE]
