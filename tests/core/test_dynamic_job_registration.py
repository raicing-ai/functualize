"""Unit tests for JobDescriptor retention and dynamic job registration."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import pytest

from functualize._app.state import AppState
from functualize._discovery.registry import JobRegistry
from functualize._events.hooks import HookEvent
from functualize._types.descriptors import JobDescriptor
from functualize.app.core import FunctualizeApp

if TYPE_CHECKING:
    from functualize.job.context import RunContext


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    """Create a minimal FunctualizeApp for testing."""
    return FunctualizeApp(name="testapp")


class TestJobDescriptorRetention:
    """Tests for get_descriptors() and get_descriptor() on JobRegistry."""

    def test_get_descriptors_empty_initially(self) -> None:
        """get_descriptors() returns empty list when no jobs registered."""
        registry = JobRegistry()
        assert registry.get_descriptors() == []

    def test_get_descriptors_after_scan(self, tmp_path: Any) -> None:
        """get_descriptors() returns descriptors after scan_and_register."""
        import os

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "mymod.py"), "w") as f:
            f.write(
                "def deploy():\n    '''Deploy.'''\n    pass\n\n"
                "def rollback():\n    '''Rollback.'''\n    pass\n"
            )

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        descriptors = registry.get_descriptors()
        assert len(descriptors) == 2
        names = {d.name for d in descriptors}
        assert "deploy" in names
        assert "rollback" in names

    def test_get_descriptors_returns_copy(self, tmp_path: Any) -> None:
        """get_descriptors() returns a new list (not the internal reference)."""
        import os

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "simple.py"), "w") as f:
            f.write("def my_job():\n    pass\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        list1 = registry.get_descriptors()
        list2 = registry.get_descriptors()
        assert list1 is not list2
        assert list1 == list2

    def test_get_descriptor_by_name(self, tmp_path: Any) -> None:
        """get_descriptor(name) returns the matching descriptor."""
        import os

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "tasks.py"), "w") as f:
            f.write(
                "def build():\n    '''Build project.'''\n    pass\n\n"
                "def test():\n    '''Run tests.'''\n    pass\n"
            )

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        descriptor = registry.get_descriptor("build")
        assert descriptor.name == "build"
        assert descriptor.docstring == "Build project."

    def test_get_descriptor_raises_key_error_on_miss(self) -> None:
        """get_descriptor(name) raises KeyError when name not found."""
        registry = JobRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get_descriptor("nonexistent")

    def test_get_descriptor_key_error_message(self) -> None:
        """KeyError message indicates the unmatched name."""
        registry = JobRegistry()
        with pytest.raises(
            KeyError, match="No JobDescriptor found for job name 'missing-job'"
        ):
            registry.get_descriptor("missing-job")

    def test_descriptors_are_job_descriptor_instances(self, tmp_path: Any) -> None:
        """All items in get_descriptors() are JobDescriptor instances."""
        import os

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "basic.py"), "w") as f:
            f.write("def run():\n    pass\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        for descriptor in registry.get_descriptors():
            assert isinstance(descriptor, JobDescriptor)


class TestDynamicJobRegistration:
    """Tests for FunctualizeApp.register_dynamic_job()."""

    def test_register_dynamic_job_basic(self, app: FunctualizeApp) -> None:
        """A dynamically registered job is accessible via the registry."""

        def my_dynamic_job(rc: RunContext) -> str:
            return "dynamic result"

        app.register_dynamic_job("my-dynamic", my_dynamic_job)

        # Job should be in registered jobs
        registered = app.job_registry.get_job("my-dynamic")
        assert registered.name == "my-dynamic"
        assert registered.function is my_dynamic_job

    def test_register_dynamic_job_creates_descriptor(self, app: FunctualizeApp) -> None:
        """register_dynamic_job creates and retains a JobDescriptor."""

        def job_fn() -> None:
            """A test job."""
            pass

        app.register_dynamic_job("test-job", job_fn)

        descriptor = app.job_registry.get_descriptor("test-job")
        assert descriptor.name == "test-job"
        assert descriptor.docstring == "A test job."

    def test_register_dynamic_job_with_group(self, app: FunctualizeApp) -> None:
        """Dynamic job can be registered with a group."""

        def job_fn() -> None:
            pass

        app.register_dynamic_job("start", job_fn, group="server")

        registered = app.job_registry.get_job("start")
        assert registered.group == "server"

        descriptor = app.job_registry.get_descriptor("start")
        assert descriptor.group == "server"

    def test_register_dynamic_job_with_config_class(self, app: FunctualizeApp) -> None:
        """Dynamic job can be registered with a config_class."""
        from pydantic import BaseModel

        class MyConfig(BaseModel):
            host: str = "localhost"
            port: int = 8080

        def job_fn() -> None:
            pass

        app.register_dynamic_job("configured-job", job_fn, config_class=MyConfig)

        registered = app.job_registry.get_job("configured-job")
        assert registered.config_class is MyConfig

    def test_register_dynamic_job_duplicate_raises_value_error(
        self, app: FunctualizeApp
    ) -> None:
        """Registering a job with a duplicate name raises ValueError."""

        def job_a() -> None:
            pass

        def job_b() -> None:
            pass

        app.register_dynamic_job("unique-name", job_a)
        with pytest.raises(ValueError, match="already exists"):
            app.register_dynamic_job("unique-name", job_b)

    def test_register_dynamic_job_fires_job_registered_event(
        self, app: FunctualizeApp
    ) -> None:
        """Registering a dynamic job fires JOB_REGISTERED hook."""
        received_metadata: list[dict[str, Any]] = []

        def on_registered(metadata: dict[str, Any]) -> None:
            received_metadata.append(metadata)

        app.hook_registry.register_global(HookEvent.JOB_REGISTERED, on_registered)

        def my_job() -> None:
            """My dynamic job docstring."""
            pass

        app.register_dynamic_job("event-job", my_job, group="tools")

        assert len(received_metadata) == 1
        meta = received_metadata[0]
        assert meta["name"] == "event-job"
        assert meta["group"] == "tools"
        assert meta["docstring"] == "My dynamic job docstring."
        assert meta["config_schema"] is None

    def test_register_dynamic_job_executable_via_engine(
        self, app: FunctualizeApp
    ) -> None:
        """A dynamically registered job can be executed via the engine."""
        called_with: list[str] = []

        def my_job(rc: RunContext) -> str:
            called_with.append(rc.name)
            return "executed"

        app.register_dynamic_job("exec-job", my_job)

        # Execute via engine
        registered = app.job_registry.get_job("exec-job")
        result = app.execution_engine.execute(
            job_name="exec-job",
            function=registered.function,
            config_class=registered.config_class,
            kwargs={},
        )

        assert result.return_value == "executed"
        assert called_with == ["exec-job"]

    def test_register_dynamic_job_descriptor_in_get_descriptors(
        self, app: FunctualizeApp
    ) -> None:
        """Dynamic job descriptor appears in get_descriptors() list."""

        def job_fn() -> None:
            pass

        app.register_dynamic_job("listed-job", job_fn)

        descriptors = app.job_registry.get_descriptors()
        names = {d.name for d in descriptors}
        assert "listed-job" in names

    def test_register_dynamic_job_no_docstring(self, app: FunctualizeApp) -> None:
        """Dynamic job with no docstring stores None."""

        def job_fn():
            pass

        app.register_dynamic_job("no-doc", job_fn)

        descriptor = app.job_registry.get_descriptor("no-doc")
        assert descriptor.docstring is None

    def test_duplicate_check_against_scan_registered_jobs(
        self, tmp_path: Any, app: FunctualizeApp
    ) -> None:
        """Duplicate check works against jobs registered via scan_and_register."""
        import os

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "existing.py"), "w") as f:
            f.write("def my_existing_job():\n    pass\n")

        app.job_registry.scan_and_register(app.cli_command, [jobs_dir])

        # Now trying to register a dynamic job with the same name should fail
        def dynamic_fn() -> None:
            pass

        with pytest.raises(ValueError, match="already exists"):
            app.register_dynamic_job("my_existing_job", dynamic_fn)

    def test_register_dynamic_job_invocable_via_rc_invoke(
        self, app: FunctualizeApp
    ) -> None:
        """A dynamically registered job can be invoked via rc.invoke()."""
        child_calls: list[str] = []

        def child_job(rc: RunContext) -> str:
            child_calls.append("called")
            return "child result"

        def parent_job(rc: RunContext) -> str:
            result = rc.invoke("child-job")
            return result.return_value

        app.register_dynamic_job("child-job", child_job)
        app.register_dynamic_job("parent-job", parent_job)

        # Execute parent, which invokes child
        registered = app.job_registry.get_job("parent-job")
        result = app.execution_engine.execute(
            job_name="parent-job",
            function=registered.function,
            config_class=registered.config_class,
            kwargs={},
        )

        assert result.return_value == "child result"
        assert child_calls == ["called"]
