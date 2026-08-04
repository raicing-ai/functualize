"""Integration tests for lifecycle hook wiring in FunctualizeApp.

Verifies that lifecycle hooks fire correctly around job execution:
before_job → job → after_success/after_failure → on_teardown
"""

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def jobs_dir(tmp_path):
    """Create a temporary jobs directory with a simple job module."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    return jobs


@pytest.fixture
def successful_job_module(jobs_dir):
    """Create a job module that succeeds."""
    job_file = jobs_dir / "success_job.py"
    job_file.write_text(
        "def succeed():\n    '''A job that succeeds.'''\n    return 'ok'\n"
    )
    return jobs_dir


@pytest.fixture
def failing_job_module(jobs_dir):
    """Create a job module that raises an exception."""
    job_file = jobs_dir / "fail_job.py"
    job_file.write_text(
        "def fail_hard():\n"
        "    '''A job that fails.'''\n"
        "    raise ValueError('something went wrong')\n"
    )
    return jobs_dir


class TestLifecycleHooksOnSuccess:
    """Tests that lifecycle hooks fire correctly when a job succeeds."""

    def test_before_job_fires_before_execution(self, successful_job_module):
        """before_job hook is invoked before the job runs."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(successful_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: call_log.append("before_job")
        )

        result = runner.invoke(app.cli_command, ["succeed"])
        assert result.exit_code == 0
        assert "before_job" in call_log

    def test_after_success_fires_on_success(self, successful_job_module):
        """after_success hook is invoked when the job completes without error."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(successful_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("after_success")
        )

        result = runner.invoke(app.cli_command, ["succeed"])
        assert result.exit_code == 0
        assert "after_success" in call_log

    def test_on_teardown_fires_on_success(self, successful_job_module):
        """on_teardown hook is invoked after a successful job."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(successful_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.ON_TEARDOWN, lambda rc: call_log.append("on_teardown")
        )

        result = runner.invoke(app.cli_command, ["succeed"])
        assert result.exit_code == 0
        assert "on_teardown" in call_log

    def test_after_failure_does_not_fire_on_success(self, successful_job_module):
        """after_failure hook is NOT invoked when the job succeeds."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(successful_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_FAILURE, lambda rc, exc: call_log.append("after_failure")
        )

        result = runner.invoke(app.cli_command, ["succeed"])
        assert result.exit_code == 0
        assert "after_failure" not in call_log

    def test_hook_order_on_success(self, successful_job_module):
        """Hooks fire in order: before_job → after_success → on_teardown."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(successful_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: call_log.append("before_job")
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("after_success")
        )
        app.hook_registry.register_global(
            HookEvent.ON_TEARDOWN, lambda rc: call_log.append("on_teardown")
        )

        result = runner.invoke(app.cli_command, ["succeed"])
        assert result.exit_code == 0
        assert call_log == ["before_job", "after_success", "on_teardown"]


class TestLifecycleHooksOnFailure:
    """Tests that lifecycle hooks fire correctly when a job fails."""

    def test_before_job_fires_before_failing_job(self, failing_job_module):
        """before_job hook is invoked even when the job will fail."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(failing_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: call_log.append("before_job")
        )

        runner.invoke(app.cli_command, ["fail_hard"])
        assert "before_job" in call_log

    def test_after_failure_fires_on_exception(self, failing_job_module):
        """after_failure hook is invoked when the job raises an exception."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(failing_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_FAILURE,
            lambda rc, exc: call_log.append(f"after_failure:{type(exc).__name__}"),
        )

        runner.invoke(app.cli_command, ["fail_hard"])
        assert "after_failure:ValueError" in call_log

    def test_on_teardown_fires_on_failure(self, failing_job_module):
        """on_teardown hook is invoked even when the job fails."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(failing_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.ON_TEARDOWN, lambda rc: call_log.append("on_teardown")
        )

        runner.invoke(app.cli_command, ["fail_hard"])
        assert "on_teardown" in call_log

    def test_after_success_does_not_fire_on_failure(self, failing_job_module):
        """after_success hook is NOT invoked when the job fails."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(failing_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("after_success")
        )

        runner.invoke(app.cli_command, ["fail_hard"])
        assert "after_success" not in call_log

    def test_hook_order_on_failure(self, failing_job_module):
        """Hooks fire in order: before_job → after_failure → on_teardown."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(failing_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: call_log.append("before_job")
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_FAILURE,
            lambda rc, exc: call_log.append("after_failure"),
        )
        app.hook_registry.register_global(
            HookEvent.ON_TEARDOWN, lambda rc: call_log.append("on_teardown")
        )

        runner.invoke(app.cli_command, ["fail_hard"])
        assert call_log == ["before_job", "after_failure", "on_teardown"]


class TestJobScopedHooks:
    """Tests that job-scoped hooks fire only for the correct job."""

    def test_job_scoped_hook_fires_for_matching_job(self, tmp_path):
        """A hook registered for a specific job fires when that job runs."""
        call_log = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "alpha.py").write_text(
            "def alpha():\n    '''Alpha job.'''\n    pass\n"
        )
        (jobs_dir / "beta.py").write_text(
            "def beta():\n    '''Beta job.'''\n    pass\n"
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        # Register a hook scoped to "alpha" only
        app.hook_registry.register_for_job(
            "alpha", HookEvent.BEFORE_JOB, lambda rc: call_log.append("alpha_before")
        )

        result = runner.invoke(app.cli_command, ["alpha"])
        assert result.exit_code == 0
        assert "alpha_before" in call_log

    def test_job_scoped_hook_does_not_fire_for_other_job(self, tmp_path):
        """A hook registered for a specific job does NOT fire for other jobs."""
        call_log = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "alpha.py").write_text(
            "def alpha():\n    '''Alpha job.'''\n    pass\n"
        )
        (jobs_dir / "beta.py").write_text(
            "def beta():\n    '''Beta job.'''\n    pass\n"
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        # Register a hook scoped to "alpha" only
        app.hook_registry.register_for_job(
            "alpha", HookEvent.BEFORE_JOB, lambda rc: call_log.append("alpha_before")
        )

        result = runner.invoke(app.cli_command, ["beta"])
        assert result.exit_code == 0
        assert "alpha_before" not in call_log

    def test_global_hooks_fire_before_job_scoped(self, tmp_path):
        """Global hooks fire first, then job-scoped hooks."""
        call_log = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "myjob.py").write_text(
            "def myjob():\n    '''My job.'''\n    pass\n"
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: call_log.append("global_before")
        )
        app.hook_registry.register_for_job(
            "myjob", HookEvent.BEFORE_JOB, lambda rc: call_log.append("scoped_before")
        )

        result = runner.invoke(app.cli_command, ["myjob"])
        assert result.exit_code == 0
        assert call_log == ["global_before", "scoped_before"]


class TestHookRegistryWiring:
    """Tests that FunctualizeApp correctly wires HookRegistry to JobRegistry."""

    def test_app_hook_registry_is_same_as_job_registry_hook_registry(self):
        """The app's hook_registry is the same HookRegistry used by the job_registry.

        After the SignalBus merge, app.hook_registry returns the HookRegistry
        instance directly — the same instance that the job_registry uses.
        """
        app = FunctualizeApp(name="testapp")
        # The HookRegistry is the same instance used by job_registry
        assert app.hook_registry is app.job_registry._hook_registry

    def test_hooks_registered_after_init_still_fire(self, successful_job_module):
        """Hooks registered after app init still fire because they share the same registry."""
        call_log = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(successful_job_module)]),
        )
        # Register hook AFTER app initialization
        app.hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("late_hook")
        )

        result = runner.invoke(app.cli_command, ["succeed"])
        assert result.exit_code == 0
        assert "late_hook" in call_log


class TestRunContextInHooks:
    """Tests that hooks receive a valid RunContext."""

    def test_before_job_receives_run_context_with_job_name(self, tmp_path):
        """before_job hook receives a RunContext with the correct job name."""
        captured_names = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "greet.py").write_text("def greet():\n    '''Greet.'''\n    pass\n")

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB, lambda rc: captured_names.append(rc.name)
        )

        result = runner.invoke(app.cli_command, ["greet"])
        assert result.exit_code == 0
        assert "greet" in captured_names

    def test_after_failure_receives_exception(self, failing_job_module):
        """after_failure hook receives the actual exception that was raised."""
        captured_exceptions = []

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(failing_job_module)]),
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_FAILURE,
            lambda rc, exc: captured_exceptions.append(exc),
        )

        runner.invoke(app.cli_command, ["fail_hard"])
        assert len(captured_exceptions) == 1
        assert isinstance(captured_exceptions[0], ValueError)
        assert "something went wrong" in str(captured_exceptions[0])
