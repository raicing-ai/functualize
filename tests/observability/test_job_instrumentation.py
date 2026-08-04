"""Unit tests for job lifecycle instrumentation points (task 11.1).

Verifies that job.execute and job.teardown events are emitted correctly
at the appropriate lifecycle boundaries during job execution.
"""

from __future__ import annotations

import os
import textwrap
from unittest.mock import MagicMock

import click
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._discovery.registry import JobRegistry
from functualize._engine.executor import JobExecutionEngine
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._events.middleware_stack import MiddlewareStack
from functualize.job._middleware import MiddlewareRegistry


def _build_cli(app_mock, registry: JobRegistry) -> click.Group:
    """Build a click.Group wiring every discovered job as a command.

    Replaces the old scan_and_register→Typer wiring: discovery records job
    identity, and delivery-layer command construction is the adapter's job, so
    the test builds the click commands directly from the registered functions.
    """
    from functualize.app.adapters.click_params import create_job_click_command

    group = click.Group(name="func")
    for prefix, entry in registry._registered_jobs.items():
        if entry.function is None:
            continue
        command = create_job_click_command(
            prefix, entry.function, entry.config_class, app=app_mock
        )
        group.add_command(command, name=prefix)
    return group


class TestJobExecuteInstrumentation:
    """Tests for job.execute instrumentation points."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def _create_jobs_dir(self, tmp_path, modules: dict[str, str]) -> str:
        jobs_dir = os.path.join(tmp_path, "jobs")
        os.makedirs(jobs_dir, exist_ok=True)
        for name, source in modules.items():
            filepath = os.path.join(jobs_dir, f"{name}.py")
            with open(filepath, "w") as f:
                f.write(textwrap.dedent(source))
        return jobs_dir

    def _create_app_mock(self) -> MagicMock:
        """Create a mock app with event_bus, middleware, and a real execution engine."""
        app_mock = MagicMock()
        app_mock.event_bus = EventBus()
        app_mock.middleware = MiddlewareStack()
        app_mock._resolution_chain = ResolutionChain([])
        app_mock.plugin_config_registry = MagicMock()
        app_mock.plugin_config_registry.get_all.return_value = {}
        engine = JobExecutionEngine(
            di_registry=app_mock._di_registry,
            event_bus=app_mock.event_bus,
            hook_registry=HookRegistry(),
            middleware_chain=MiddlewareRegistry(),
        )
        app_mock._execution_engine = engine
        app_mock.execution_engine = engine
        return app_mock

    def test_job_execute_emits_start_and_end_on_success(self, tmp_path):
        """Successful job emits job.execute.start and job.execute.end events."""
        modules = {
            "simple": """\
                def hello(name: str = "world"):
                    \"\"\"A simple job.\"\"\"
                    print(f"Hello, {name}!")
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        app_mock = self._create_app_mock()
        registry = JobRegistry(app=app_mock)
        registry.scan_and_register(None, [jobs_dir])

        # Subscribe to events
        events: list = []
        app_mock.event_bus.subscribe("*", lambda e: events.append(e))

        # Invoke the command
        result = CliRunner().invoke(
            _build_cli(app_mock, registry), ["hello", "--name", "test"]
        )
        assert result.exit_code == 0

        # Verify events were emitted
        event_names = [e.event_name for e in events]
        assert "job.execute.start" in event_names
        assert "job.execute.end" in event_names
        assert "job.execute.error" not in event_names

        # Verify start event payload
        start_event = next(e for e in events if e.event_name == "job.execute.start")
        assert start_event.resource == "hello"
        assert start_event.payload["job_name"] == "hello"

        # Verify end event payload
        end_event = next(e for e in events if e.event_name == "job.execute.end")
        assert end_event.resource == "hello"
        assert end_event.payload["job_name"] == "hello"
        assert "duration_ms" in end_event.payload
        assert end_event.payload["duration_ms"] >= 0

    def test_job_execute_emits_start_and_error_on_failure(self, tmp_path):
        """Failing job emits job.execute.start and job.execute.error events."""
        modules = {
            "failing": """\
                def fail_job():
                    \"\"\"A job that raises.\"\"\"
                    raise ValueError("Something went wrong")
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        app_mock = self._create_app_mock()
        registry = JobRegistry(app=app_mock)
        registry.scan_and_register(None, [jobs_dir])

        # Subscribe to events
        events: list = []
        app_mock.event_bus.subscribe("*", lambda e: events.append(e))

        # Invoke the command (will fail)
        result = CliRunner().invoke(_build_cli(app_mock, registry), ["fail-job"])
        assert result.exit_code != 0

        # Verify events were emitted
        event_names = [e.event_name for e in events]
        assert "job.execute.start" in event_names
        # Engine emits job.execute.end with status='failure' (not a separate error event)
        assert "job.execute.end" in event_names

        # Verify end event payload contains failure info
        end_event = next(e for e in events if e.event_name == "job.execute.end")
        assert end_event.resource == "fail-job"
        assert end_event.payload["job_name"] == "fail-job"
        assert end_event.payload["status"] == "failure"
        assert "duration_ms" in end_event.payload
        assert end_event.payload["duration_ms"] >= 0


class TestJobTeardownInstrumentation:
    """Tests for job.teardown instrumentation points."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def _create_jobs_dir(self, tmp_path, modules: dict[str, str]) -> str:
        jobs_dir = os.path.join(tmp_path, "jobs")
        os.makedirs(jobs_dir, exist_ok=True)
        for name, source in modules.items():
            filepath = os.path.join(jobs_dir, f"{name}.py")
            with open(filepath, "w") as f:
                f.write(textwrap.dedent(source))
        return jobs_dir

    def _create_app_mock(self) -> MagicMock:
        """Create a mock app with event_bus, middleware, and a real execution engine."""
        app_mock = MagicMock()
        app_mock.event_bus = EventBus()
        app_mock.middleware = MiddlewareStack()
        app_mock._resolution_chain = ResolutionChain([])
        app_mock.plugin_config_registry = MagicMock()
        app_mock.plugin_config_registry.get_all.return_value = {}
        engine = JobExecutionEngine(
            di_registry=app_mock._di_registry,
            event_bus=app_mock.event_bus,
            hook_registry=HookRegistry(),
            middleware_chain=MiddlewareRegistry(),
        )
        app_mock._execution_engine = engine
        app_mock.execution_engine = engine
        return app_mock

    def test_job_teardown_emits_start_and_end_on_success(self, tmp_path):
        """Successful job emits job.teardown.start and job.teardown.end events."""
        modules = {
            "simple": """\
                def hello():
                    \"\"\"A simple job.\"\"\"
                    print("hello")
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        app_mock = self._create_app_mock()
        registry = JobRegistry(app=app_mock)
        registry.scan_and_register(None, [jobs_dir])

        # Subscribe to events
        events: list = []
        app_mock.event_bus.subscribe("*", lambda e: events.append(e))

        # Invoke the command
        result = CliRunner().invoke(_build_cli(app_mock, registry), ["hello"])
        assert result.exit_code == 0

        # Verify teardown events were emitted
        event_names = [e.event_name for e in events]
        assert "job.teardown.start" in event_names
        assert "job.teardown.end" in event_names

        # Verify teardown start event
        teardown_start = next(e for e in events if e.event_name == "job.teardown.start")
        assert teardown_start.resource == "hello"
        assert teardown_start.payload["job_name"] == "hello"

        # Verify teardown end event
        teardown_end = next(e for e in events if e.event_name == "job.teardown.end")
        assert teardown_end.resource == "hello"
        assert teardown_end.payload["job_name"] == "hello"
        assert "duration_ms" in teardown_end.payload
        assert teardown_end.payload["duration_ms"] >= 0

    def test_job_teardown_emits_on_failure(self, tmp_path):
        """Failing job still emits teardown events."""
        modules = {
            "failing": """\
                def fail_job():
                    \"\"\"A job that raises.\"\"\"
                    raise RuntimeError("oops")
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        app_mock = self._create_app_mock()
        registry = JobRegistry(app=app_mock)
        registry.scan_and_register(None, [jobs_dir])

        # Subscribe to events
        events: list = []
        app_mock.event_bus.subscribe("*", lambda e: events.append(e))

        # Invoke (will fail)
        result = CliRunner().invoke(_build_cli(app_mock, registry), ["fail-job"])
        assert result.exit_code != 0

        # Verify teardown events still fire after failure
        event_names = [e.event_name for e in events]
        assert "job.teardown.start" in event_names
        assert "job.teardown.end" in event_names


class TestInstrumentationFaultTolerance:
    """Tests for fault-tolerant instrumentation (emit failures don't break jobs)."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def _create_jobs_dir(self, tmp_path, modules: dict[str, str]) -> str:
        jobs_dir = os.path.join(tmp_path, "jobs")
        os.makedirs(jobs_dir, exist_ok=True)
        for name, source in modules.items():
            filepath = os.path.join(jobs_dir, f"{name}.py")
            with open(filepath, "w") as f:
                f.write(textwrap.dedent(source))
        return jobs_dir

    def test_invocation_without_app_raises_runtime_error(self, tmp_path):
        """Invoking a job without an attached app raises RuntimeError."""
        modules = {
            "noapp": """\
                def basic():
                    \"\"\"A basic job.\"\"\"
                    print("works")
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        # No app reference — invocation must raise RuntimeError
        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        result = CliRunner().invoke(_build_cli(None, registry), ["basic"])
        assert result.exit_code != 0
        assert result.exception is not None
        assert isinstance(result.exception, RuntimeError)
