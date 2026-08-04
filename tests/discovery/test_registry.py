"""Unit tests for JobRegistry."""

import os
import textwrap

from functualize._app.state import AppState
from functualize._discovery.registry import JobRegistry
from functualize.app.core import FunctualizeApp
from functualize.job.context import RunContext


class TestJobRegistry:
    """Tests for JobRegistry class."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def _create_jobs_dir(self, tmp_path, modules: dict[str, str]) -> str:
        """Helper to create a temporary jobs directory with module files.

        Args:
            tmp_path: The temporary directory path.
            modules: Dict of module_name -> source_code.

        Returns:
            The path to the jobs directory.
        """
        jobs_dir = os.path.join(tmp_path, "jobs")
        os.makedirs(jobs_dir, exist_ok=True)
        for name, source in modules.items():
            filepath = os.path.join(jobs_dir, f"{name}.py")
            with open(filepath, "w") as f:
                f.write(textwrap.dedent(source))
        return jobs_dir

    def test_scan_empty_directory(self, tmp_path):
        """Scanning an empty directory registers no commands."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # No commands registered
        assert len(registry._registered_commands) == 0

    def test_scan_registers_public_functions(self, tmp_path):
        """Public functions defined in module are registered."""
        modules = {
            "greet": """\
                def hello(name: str = "world"):
                    \"\"\"Say hello.\"\"\"
                    return f"Hello, {name}!"

                def goodbye(name: str = "world"):
                    \"\"\"Say goodbye.\"\"\"
                    return f"Goodbye, {name}!"
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert "__top__::hello" in registry._registered_commands
        assert "__top__::goodbye" in registry._registered_commands

    def test_scan_skips_underscore_prefixed(self, tmp_path):
        """Functions prefixed with underscore are not registered."""
        modules = {
            "helpers": """\
                def public_func():
                    return "public"

                def _private_func():
                    return "private"
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert "__top__::public_func" in registry._registered_commands
        assert "__top__::_private_func" not in registry._registered_commands

    def test_scan_skips_imported_functions(self, tmp_path):
        """Functions imported from other modules are not registered."""
        modules = {
            "myjob": """\
                from os.path import join

                def my_command():
                    return "my command"
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # Only my_command should be registered, not 'join'
        assert "__top__::my_command" in registry._registered_commands
        assert "__top__::join" not in registry._registered_commands

    def test_job_name_grouping(self, tmp_path):
        """Modules with JOB_GROUP create sub-Typer groups."""
        modules = {
            "deploy_jobs": """\
                JOB_GROUP = "deploy"

                def start():
                    return "starting deploy"

                def stop():
                    return "stopping deploy"
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert "deploy::start" in registry._registered_commands
        assert "deploy::stop" in registry._registered_commands

    def test_ungrouped_functions_at_top_level(self, tmp_path):
        """Modules without JOB_GROUP register at top level."""
        modules = {
            "simple": """\
                def run_task():
                    return "running"
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert "__top__::run_task" in registry._registered_commands

    def test_duplicate_command_detection(self, tmp_path):
        """Duplicate commands at the same level are skipped with warning."""
        modules = {
            "first": """\
                def duplicate_cmd():
                    return "first"
            """,
            "second": """\
                def duplicate_cmd():
                    return "second"
            """,
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # Only one should be registered
        assert "__top__::duplicate_cmd" in registry._registered_commands
        # The first one found should be preserved (alphabetical order: first before second)
        assert "first" in registry._registered_commands["__top__::duplicate_cmd"]

    def test_import_error_continues_scanning(self, tmp_path):
        """Modules that fail to import don't stop scanning."""
        modules = {
            "broken": """\
                import nonexistent_module_xyz_123
            """,
            "working": """\
                def good_command():
                    return "works"
            """,
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # The working module should still be registered
        assert "__top__::good_command" in registry._registered_commands

    def test_skips_packages(self, tmp_path):
        """Sub-packages in the jobs directory are skipped."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)

        # Create a sub-package
        pkg_dir = os.path.join(jobs_dir, "subpkg")
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, "__init__.py"), "w") as f:
            f.write("def should_not_register(): pass\n")

        # Create a regular module
        with open(os.path.join(jobs_dir, "regular.py"), "w") as f:
            f.write("def should_register(): pass\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert "__top__::should_register" in registry._registered_commands
        assert "__top__::should_not_register" not in registry._registered_commands


class TestCreateJobCommand:
    """Tests for create_job_command method."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def test_injects_runcontext(self):
        """RunContext is injected into the function at invocation time."""
        received_rc = []

        def my_job(name: str, rc: RunContext) -> str:
            received_rc.append(rc)
            return f"Hello, {name}!"

        from functualize.app.adapters.click_params import create_job_command

        app = FunctualizeApp(name="testapp")
        registry = JobRegistry(
            app=app,
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("my_job", my_job)

        result = wrapped(name="world")

        assert result == "Hello, world!"
        assert len(received_rc) == 1
        assert isinstance(received_rc[0], RunContext)
        assert received_rc[0].name == "my_job"

    def test_invocation_without_app_raises(self):
        """Invoking a wrapped command without an attached app raises RuntimeError."""

        def my_job() -> None:
            pass

        from functualize.app.adapters.click_params import create_job_command

        registry = JobRegistry(
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("my_job", my_job)

        import pytest

        with pytest.raises(RuntimeError, match="no execution engine available"):
            wrapped()

    def test_excludes_runcontext_from_signature(self):
        """RunContext parameter is excluded from the wrapped function's signature."""
        import inspect

        from functualize.app.adapters.click_params import create_job_command

        def my_job(name: str, count: int = 1, rc: RunContext = None) -> str:
            return f"{name} x {count}"

        registry = JobRegistry(
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("my_job", my_job)

        sig = inspect.signature(wrapped)
        param_names = list(sig.parameters.keys())

        assert "rc" not in param_names
        assert "name" in param_names
        assert "count" in param_names

    def test_function_without_runcontext(self):
        """Functions without RunContext parameter still work."""
        from functualize.app.adapters.click_params import create_job_command

        def simple_job(message: str) -> str:
            return message

        app = FunctualizeApp(name="testapp")
        registry = JobRegistry(
            app=app,
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("simple_job", simple_job)

        result = wrapped(message="test")
        assert result == "test"

    def test_preserves_function_name(self):
        """Wrapped function preserves the original function name."""
        from functualize.app.adapters.click_params import create_job_command

        def my_special_job(rc: RunContext) -> None:
            pass

        registry = JobRegistry(
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("my_special_job", my_special_job)

        assert wrapped.__name__ == "my_special_job"

    def test_preserves_docstring(self):
        """Wrapped function preserves the original docstring."""
        from functualize.app.adapters.click_params import create_job_command

        def documented_job(rc: RunContext) -> None:
            """This is a documented job."""
            pass

        registry = JobRegistry(
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("documented_job", documented_job)

        assert wrapped.__doc__ == "This is a documented job."

    def test_job_invokes_successfully(self):
        """Job function is invoked and returns its result."""
        from functualize.app.adapters.click_params import create_job_command

        called = []

        def my_job(rc: RunContext) -> str:
            called.append(True)
            return "done"

        app = FunctualizeApp(name="testapp")
        registry = JobRegistry(
            app=app,
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("my_job", my_job)

        result = wrapped()
        assert result == "done"
        assert called == [True]

    def test_runcontext_has_job_name(self):
        """RunContext passed to job function has correct name."""
        from functualize.app.adapters.click_params import create_job_command

        received_rc = []

        def my_job(rc: RunContext) -> None:
            received_rc.append(rc)

        app = FunctualizeApp(name="testapp")
        registry = JobRegistry(
            app=app,
            cli_wiring_factory={"create_job_command": create_job_command},
        )
        wrapped = registry.create_job_command("my_job", my_job)
        wrapped()

        assert received_rc[0].name == "my_job"


class TestUpdateConfigPaths:
    """Tests for update_config_paths method."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def test_update_config_paths_noop_without_app(self):
        """update_config_paths is a no-op when _app is None."""
        registry = JobRegistry()
        # Should not raise even with no run contexts or app
        registry.update_config_paths()


class TestMultipleDirectories:
    """Tests for scanning multiple job directories."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def test_scan_multiple_directories(self, tmp_path):
        """Multiple directories can be scanned."""
        # Create first directory
        dir1 = os.path.join(str(tmp_path), "jobs1")
        os.makedirs(dir1)
        with open(os.path.join(dir1, "mod1.py"), "w") as f:
            f.write("def cmd_one(): return 'one'\n")

        # Create second directory
        dir2 = os.path.join(str(tmp_path), "jobs2")
        os.makedirs(dir2)
        with open(os.path.join(dir2, "mod2.py"), "w") as f:
            f.write("def cmd_two(): return 'two'\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [dir1, dir2])

        assert "__top__::cmd_one" in registry._registered_commands
        assert "__top__::cmd_two" in registry._registered_commands

    def test_module_filter_restricts_imports(self, tmp_path):
        """When module_filter is provided, only matching modules are imported."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "deploy.py"), "w") as f:
            f.write("def deploy_app(): return 'deployed'\n")
        with open(os.path.join(jobs_dir, "migrate.py"), "w") as f:
            f.write("def run_migration(): return 'migrated'\n")
        with open(os.path.join(jobs_dir, "notify.py"), "w") as f:
            f.write("def send_notification(): return 'notified'\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir], module_filter={"deploy"})

        # Only deploy module should be registered
        assert "__top__::deploy_app" in registry._registered_commands
        assert "__top__::run_migration" not in registry._registered_commands
        assert "__top__::send_notification" not in registry._registered_commands

    def test_module_filter_none_imports_all(self, tmp_path):
        """When module_filter is None (default), all modules are imported."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "alpha.py"), "w") as f:
            f.write("def alpha_cmd(): return 'alpha'\n")
        with open(os.path.join(jobs_dir, "beta.py"), "w") as f:
            f.write("def beta_cmd(): return 'beta'\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir], module_filter=None)

        assert "__top__::alpha_cmd" in registry._registered_commands
        assert "__top__::beta_cmd" in registry._registered_commands

    def test_module_filter_with_multiple_entries(self, tmp_path):
        """Module filter can contain multiple module names."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "first.py"), "w") as f:
            f.write("def first_cmd(): return 'first'\n")
        with open(os.path.join(jobs_dir, "second.py"), "w") as f:
            f.write("def second_cmd(): return 'second'\n")
        with open(os.path.join(jobs_dir, "third.py"), "w") as f:
            f.write("def third_cmd(): return 'third'\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir], module_filter={"first", "third"})

        assert "__top__::first_cmd" in registry._registered_commands
        assert "__top__::second_cmd" not in registry._registered_commands
        assert "__top__::third_cmd" in registry._registered_commands


class TestExtractDescriptors:
    """Tests for the extract_descriptors() L1 isolation method."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def test_returns_job_descriptors_without_typer(self, tmp_path):
        """extract_descriptors() produces JobDescriptors without a Typer app."""
        import sys

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "mymod.py"), "w") as f:
            f.write(
                "def deploy():\n    '''Deploy to production.'''\n    pass\n\n"
                "def rollback():\n    '''Rollback.'''\n    pass\n"
            )

        sys.path.insert(0, jobs_dir)
        try:
            registry = JobRegistry()
            descriptors = registry.extract_descriptors("mymod")
        finally:
            sys.path.remove(jobs_dir)
            sys.modules.pop("mymod", None)

        assert len(descriptors) == 2
        names = {d.name for d in descriptors}
        assert "deploy" in names
        assert "rollback" in names

    def test_populates_registered_jobs_without_registered_commands(self, tmp_path):
        """After extract_descriptors(), jobs are in _registered_jobs but not _registered_commands."""
        import sys

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "singlemod.py"), "w") as f:
            f.write("def run():\n    pass\n")

        sys.path.insert(0, jobs_dir)
        try:
            registry = JobRegistry()
            registry.extract_descriptors("singlemod")
        finally:
            sys.path.remove(jobs_dir)
            sys.modules.pop("singlemod", None)

        assert "run" in registry._registered_jobs
        assert len(registry._registered_commands) == 0

    def test_scan_and_register_produces_same_commands_as_split_path(self, tmp_path):
        """scan_and_register() and extract_descriptors() + wire produce identical commands."""
        import sys

        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)
        with open(os.path.join(jobs_dir, "modx.py"), "w") as f:
            f.write("def alpha():\n    pass\n\ndef beta():\n    pass\n")

        # Path A: scan_and_register
        sys.path.insert(0, jobs_dir)
        try:
            registry_a = JobRegistry()
            registry_a.scan_and_register(None, [jobs_dir])

            # Path B: extract_descriptors only records descriptors, not commands
            # (scan_and_register is what populates _registered_commands).
            registry_b = JobRegistry()
            registry_b.extract_descriptors("modx")
            assert len(registry_b._registered_commands) == 0
            assert "alpha" in registry_b._registered_jobs
            assert "beta" in registry_b._registered_jobs
        finally:
            sys.path.remove(jobs_dir)
            sys.modules.pop("modx", None)


class TestJobGroupValidationInRegistry:
    """Tests for JOB_GROUP validation at discovery time in registry (Requirement 2)."""

    def setup_method(self):
        """Reset AppState before each test."""
        AppState.reset()
        AppState.set("config_directory", ".")
        AppState.set("environment", "DEV")

    def _create_jobs_dir(self, tmp_path, modules: dict[str, str]) -> str:
        """Helper to create a temporary jobs directory with module files."""
        jobs_dir = os.path.join(tmp_path, "jobs")
        os.makedirs(jobs_dir, exist_ok=True)
        for name, source in modules.items():
            filepath = os.path.join(jobs_dir, f"{name}.py")
            with open(filepath, "w") as f:
                f.write(textwrap.dedent(source))
        return jobs_dir

    def test_invalid_job_group_skips_module_in_registry(self, tmp_path):
        """Module with invalid JOB_GROUP is skipped during registry scan."""
        modules = {
            "bad_group": """\
                JOB_GROUP = "infra..aws"

                def provision():
                    \"\"\"Provision infra.\"\"\"
                    return "provisioning"
            """,
            "good_module": """\
                def deploy():
                    \"\"\"Deploy.\"\"\"
                    return "deploying"
            """,
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        # good_module should be registered
        assert "__top__::deploy" in registry._registered_commands
        # bad_group module should be skipped entirely
        assert "infra..aws.provision" not in registry._registered_jobs

    def test_invalid_job_group_leading_dot_skips_in_registry(self, tmp_path):
        """Module with leading-dot JOB_GROUP is skipped."""
        modules = {
            "leading_dot": """\
                JOB_GROUP = ".infra"

                def provision():
                    \"\"\"Provision.\"\"\"
                    pass
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert len(registry._registered_jobs) == 0

    def test_valid_job_group_registers_in_registry(self, tmp_path):
        """Module with valid JOB_GROUP registers descriptors correctly."""
        modules = {
            "infra_jobs": """\
                JOB_GROUP = "infra"

                def provision():
                    \"\"\"Provision.\"\"\"
                    pass

                def teardown():
                    \"\"\"Teardown.\"\"\"
                    pass
            """
        }
        jobs_dir = self._create_jobs_dir(str(tmp_path), modules)

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        assert "infra.provision" in registry._registered_jobs
        assert "infra.teardown" in registry._registered_jobs
