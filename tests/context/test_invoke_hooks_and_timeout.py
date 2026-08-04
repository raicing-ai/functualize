"""Tests for INVOKE_START/INVOKE_END hooks and invoke timeout (Task 6.5).

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 17.1, 17.2, 17.3, 17.4
"""

from __future__ import annotations

import textwrap

import pytest

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize._types.enums import RunStatus
from functualize.app.config import ExecutionConfig, JobSources
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


class TestInvokeStartHook:
    """Tests for INVOKE_START hook firing behavior (Req 14.2)."""

    def test_invoke_start_fires_before_child_execution(self, tmp_path):
        """INVOKE_START fires with (parent_rc, child_job_name, kwargs, depth)."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                return rc.invoke("child_job", x=42)

            def child_job(rc: RunContext):
                return "child_result"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []

        def on_invoke_start(rc, child_name, kwargs, depth):
            received.append(
                {
                    "parent_name": rc.name,
                    "child_name": child_name,
                    "kwargs": kwargs,
                    "depth": depth,
                }
            )

        app.hook_registry.register_global(HookEvent.INVOKE_START, on_invoke_start)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert len(received) == 1
        assert received[0]["parent_name"] == "parent-job"
        assert received[0]["child_name"] == "child-job"
        assert received[0]["kwargs"] == {"x": 42}
        assert received[0]["depth"] == 1

    def test_invoke_start_not_fired_on_job_not_found(self, tmp_path):
        """INVOKE_START is NOT fired when job doesn't exist (Req 14.4)."""
        source = """\
            from functualize.job.context import RunContext
            from functualize._engine.errors import JobNotFoundError

            def parent_job(rc: RunContext):
                try:
                    rc.invoke("nonexistent_job")
                except JobNotFoundError:
                    pass
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []
        app.hook_registry.register_global(
            HookEvent.INVOKE_START,
            lambda rc, name, kwargs, depth: received.append(name),
        )

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert received == []

    def test_invoke_start_not_fired_on_recursion_limit(self, tmp_path):
        """INVOKE_START is NOT fired when recursion limit is hit (Req 14.4)."""
        source = """\
            from functualize.job.context import RunContext
            from functualize._engine.errors import RecursionLimitError

            def recursive_job(rc: RunContext):
                try:
                    rc.invoke("recursive_job")
                except RecursionLimitError:
                    pass
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[jobs_dir]),
            execution=ExecutionConfig(max_invoke_depth=1),
        )

        received = []
        app.hook_registry.register_global(
            HookEvent.INVOKE_START,
            lambda rc, name, kwargs, depth: received.append(depth),
        )

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["recursive_job"])

        # Only the first invoke should fire (depth=1), not the recursive one
        # because recursive_job is at depth 0 initially, then at depth 1
        # when it tries to invoke itself again, it hits the limit (1 >= 1)
        assert received == [1]


class TestInvokeEndHook:
    """Tests for INVOKE_END hook firing behavior (Req 14.3)."""

    def test_invoke_end_fires_after_child_success(self, tmp_path):
        """INVOKE_END fires with (parent_rc, child_job_name, depth, result)."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                return rc.invoke("child_job")

            def child_job(rc: RunContext):
                return "done"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []

        def on_invoke_end(rc, child_name, depth, result):
            received.append(
                {
                    "parent_name": rc.name,
                    "child_name": child_name,
                    "depth": depth,
                    "status": result.status,
                    "return_value": result.return_value,
                }
            )

        app.hook_registry.register_global(HookEvent.INVOKE_END, on_invoke_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert len(received) == 1
        assert received[0]["parent_name"] == "parent-job"
        assert received[0]["child_name"] == "child-job"
        assert received[0]["depth"] == 1
        assert received[0]["status"] == RunStatus.SUCCESS
        assert received[0]["return_value"] == "done"

    def test_invoke_end_fires_after_child_failure(self, tmp_path):
        """INVOKE_END fires even when child job fails (Req 14.3)."""
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

        def on_invoke_end(rc, child_name, depth, result):
            received.append(
                {
                    "status": result.status,
                    "exception_type": type(result.exception).__name__,
                }
            )

        app.hook_registry.register_global(HookEvent.INVOKE_END, on_invoke_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert len(received) == 1
        assert received[0]["status"] == RunStatus.FAILURE
        assert received[0]["exception_type"] == "ValueError"

    def test_invoke_end_not_fired_on_job_not_found(self, tmp_path):
        """INVOKE_END is NOT fired when job doesn't exist (Req 14.4)."""
        source = """\
            from functualize.job.context import RunContext
            from functualize._engine.errors import JobNotFoundError

            def parent_job(rc: RunContext):
                try:
                    rc.invoke("nonexistent_job")
                except JobNotFoundError:
                    pass
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        received = []
        app.hook_registry.register_global(
            HookEvent.INVOKE_END,
            lambda rc, name, depth, result: received.append(name),
        )

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert received == []


class TestInvokeNestedHooks:
    """Tests for nested invocation hook pairing (Req 14.5)."""

    def test_nested_invocations_fire_matched_pairs(self, tmp_path):
        """Each nesting level fires its own INVOKE_START/INVOKE_END pair."""
        source = """\
            from functualize.job.context import RunContext

            def top_job(rc: RunContext):
                return rc.invoke("mid_job")

            def mid_job(rc: RunContext):
                return rc.invoke("leaf_job")

            def leaf_job(rc: RunContext):
                return "leaf"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        events = []

        def on_start(rc, child_name, kwargs, depth):
            events.append(("START", child_name, depth))

        def on_end(rc, child_name, depth, result):
            events.append(("END", child_name, depth))

        app.hook_registry.register_global(HookEvent.INVOKE_START, on_start)
        app.hook_registry.register_global(HookEvent.INVOKE_END, on_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["top_job"])

        # Expected order: start mid(1), start leaf(2), end leaf(2), end mid(1)
        assert events == [
            ("START", "mid-job", 1),
            ("START", "leaf-job", 2),
            ("END", "leaf-job", 2),
            ("END", "mid-job", 1),
        ]


class TestInvokeStartHookExceptionIsolation:
    """Tests that INVOKE_START hook exceptions don't prevent execution."""

    def test_hook_exception_does_not_prevent_execution(self, tmp_path):
        """If INVOKE_START hook raises, execution still proceeds."""
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

        def bad_hook(rc, child_name, kwargs, depth):
            raise RuntimeError("hook exploded")

        end_received = []

        def on_end(rc, child_name, depth, result):
            end_received.append(result.return_value)

        app.hook_registry.register_global(HookEvent.INVOKE_START, bad_hook)
        app.hook_registry.register_global(HookEvent.INVOKE_END, on_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        # Child still executed successfully despite hook error
        assert end_received == ["success"]


class TestInvokeTimeout:
    """Tests for the timeout parameter on rc.invoke() (Req 17)."""

    def test_timeout_below_minimum_raises_value_error(self, tmp_path):
        """timeout < 0.1 raises ValueError (Req 17.4)."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                rc.invoke("child_job", timeout=0.05)

            def child_job(rc: RunContext):
                return "done"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        # The ValueError should propagate as job failure
        assert result.exit_code != 0 or result.exception is not None

    def test_timeout_exactly_minimum_does_not_raise(self, tmp_path):
        """timeout = 0.1 is accepted without error (Req 17.1)."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                result = rc.invoke("child_job", timeout=0.1)
                return result.return_value

            def child_job(rc: RunContext):
                return "quick"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code == 0

    def test_timeout_returns_timeout_result_on_expiry(self, tmp_path):
        """Exceeded timeout returns JobResult(TIMEOUT) (Req 17.2)."""
        source = """\
            import time
            from functualize.job.context import RunContext
            from functualize._types.enums import RunStatus

            def parent_job(rc: RunContext):
                result = rc.invoke("slow_job", timeout=0.2)
                assert result.status == RunStatus.TIMEOUT
                assert isinstance(result.exception, TimeoutError)
                assert result.duration_ms > 0

            def slow_job(rc: RunContext):
                time.sleep(1)
                return "never"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code == 0

    def test_timeout_none_allows_indefinite_execution(self, tmp_path):
        """No timeout (None) allows child to run without limit (Req 17.3)."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                result = rc.invoke("child_job")
                return result.return_value

            def child_job(rc: RunContext):
                return "completed"
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code == 0

    def test_timeout_fires_invoke_end_on_expiry(self, tmp_path):
        """INVOKE_END still fires with TIMEOUT result when timeout expires."""
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

        end_events = []

        def on_invoke_end(rc, child_name, depth, result):
            end_events.append(
                {
                    "child_name": child_name,
                    "status": result.status,
                }
            )

        app.hook_registry.register_global(HookEvent.INVOKE_END, on_invoke_end)

        import click.testing

        runner = click.testing.CliRunner()
        runner.invoke(app.cli_command, ["parent_job"])

        assert len(end_events) == 1
        assert end_events[0]["child_name"] == "slow-job"
        assert end_events[0]["status"] == RunStatus.TIMEOUT

    def test_timeout_zero_raises_value_error(self, tmp_path):
        """timeout=0 raises ValueError."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                rc.invoke("child_job", timeout=0)

            def child_job(rc: RunContext):
                pass
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code != 0 or result.exception is not None

    def test_timeout_negative_raises_value_error(self, tmp_path):
        """timeout=-1.0 raises ValueError."""
        source = """\
            from functualize.job.context import RunContext

            def parent_job(rc: RunContext):
                rc.invoke("child_job", timeout=-1.0)

            def child_job(rc: RunContext):
                pass
        """
        jobs_dir = _write_jobs(tmp_path, source)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[jobs_dir])
        )

        import click.testing

        runner = click.testing.CliRunner()
        result = runner.invoke(app.cli_command, ["parent_job"])
        assert result.exit_code != 0 or result.exception is not None
