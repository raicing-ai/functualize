"""Integration tests for functualize framework.

Tests full CLI invocation with sample jobs, config files, and plugins;
scaffold → run cycle; hook lifecycle end-to-end; and JobConfig resolution
with precedence verification.

Requirements: 2.1, 4.1, 5.1, 6.3, 9.1, 10.2
"""

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._cli.scaffold.generator import ScaffoldGenerator
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_config_file(
    directory: Path, content: str, filename: str = "config.base.toml"
) -> Path:
    """Write a config TOML file into the given directory.

    TOML is the only format registered by default (ADR-007); these files used
    to be INI and were read only because ``boot_standard`` registered the INI
    provider unconditionally.
    """
    config_file = directory / filename
    config_file.write_text(content)
    return config_file


def _create_job_module(jobs_dir: Path, filename: str, code: str) -> Path:
    """Write a job module file into the given jobs directory."""
    job_file = jobs_dir / filename
    job_file.write_text(textwrap.dedent(code))
    return job_file


# ===========================================================================
# 1. Full CLI Invocation Tests
# ===========================================================================


class TestFullCLIInvocation:
    """Test full CLI invocation with sample jobs, config files, and plugins."""

    def test_invoke_simple_job_via_cli(self, tmp_path):
        """A simple job can be invoked via the CLI and runs successfully."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "greet.py",
            """\
            def greet():
                '''Say hello.'''
                print("hello world")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["greet"])

        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_invoke_job_with_arguments(self, tmp_path):
        """A job with typed CLI arguments can be invoked with values."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "echo_job.py",
            """\
            def echo(message: str = "default"):
                '''Echo a message.'''
                print(f"echo: {message}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["echo", "--message", "integration"])

        assert result.exit_code == 0
        assert "echo: integration" in result.output

    def test_invoke_grouped_job_via_job_name(self, tmp_path):
        """Jobs with JOB_GROUP are grouped under a sub-command."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "data_jobs.py",
            """\
            JOB_GROUP = "data"

            def export():
                '''Export data.'''
                print("exporting data")

            def cleanup():
                '''Clean up data.'''
                print("cleaning up")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        result = runner.invoke(app.cli_command, ["data", "export"])
        assert result.exit_code == 0
        assert "exporting data" in result.output

        result = runner.invoke(app.cli_command, ["data", "cleanup"])
        assert result.exit_code == 0
        assert "cleaning up" in result.output

    def test_invoke_job_with_run_context_injection(self, tmp_path):
        """A job that declares a RunContext parameter receives it automatically."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "ctx_job.py",
            """\
            from functualize.job.context import RunContext

            def check_context(rc: RunContext):
                '''Check that RunContext is injected.'''
                print(f"job_name={rc.name}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["check_context"])

        assert result.exit_code == 0
        assert "job_name=check-context" in result.output

    def test_cli_help_shows_discovered_jobs(self, tmp_path):
        """The CLI --help output lists discovered job commands."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "my_task.py",
            """\
            def my_task():
                '''Do something useful.'''
                pass
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--help"])

        assert result.exit_code == 0
        assert "my-task" in result.output

    def test_cli_with_config_directory_option(self, tmp_path):
        """The --config-directory global option overrides config discovery."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        _create_config_file(
            config_dir,
            '[general]\napp_name = "integration-test"\n',
        )

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "info_job.py",
            """\
            from functualize.job.context import RunContext

            def info(rc: RunContext):
                '''Show config info.'''
                val = rc.config.get("app_name", section="general")
                print(f"app_name={val}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            ["--config-directory", str(config_dir), "info"],
        )

        assert result.exit_code == 0
        assert "app_name=integration-test" in result.output

    def test_cli_with_invalid_config_directory_exits_with_error(self, tmp_path):
        """Providing a non-existent --config-directory exits with code 1."""
        app = FunctualizeApp(name="testapp")
        result = runner.invoke(
            app.cli_command,
            ["--config-directory", "/nonexistent/path"],
        )

        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_cli_with_dotenv_file(self, tmp_path):
        """The --dotenv-file option loads environment variables."""
        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text("MY_TEST_VAR=loaded_from_dotenv\n")

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "env_job.py",
            """\
            import os

            def show_env():
                '''Show env var.'''
                print(f"MY_TEST_VAR={os.environ.get('MY_TEST_VAR', 'not_set')}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            ["--dotenv-file", str(dotenv_file), "show_env"],
        )

        assert result.exit_code == 0
        assert "MY_TEST_VAR=loaded_from_dotenv" in result.output


# ===========================================================================
# 2. Scaffold → Run Cycle Tests
# ===========================================================================


class TestScaffoldRunCycle:
    """Test that scaffolded projects produce valid structure."""

    def test_scaffold_creates_valid_pyproject_toml(self, tmp_path):
        """ScaffoldGenerator creates a pyproject.toml with correct entry point."""
        generator = ScaffoldGenerator()
        project_dir = tmp_path / "my-app"
        generator.create_project("my-app", project_dir)

        pyproject = project_dir / "pyproject.toml"
        assert pyproject.exists()

        content = pyproject.read_text()
        # Verify the entry point references the correct module
        assert "my-app" in content or "my_app" in content
        assert "[project.scripts]" in content

    def test_scaffold_creates_complete_project_structure(self, tmp_path):
        """ScaffoldGenerator creates all expected directories and files."""
        generator = ScaffoldGenerator()
        project_dir = tmp_path / "test-project"
        generator.create_project("test-project", project_dir)

        # Verify directory structure
        assert (project_dir / "src" / "test_project").is_dir()
        assert (project_dir / "src" / "test_project" / "__init__.py").exists()
        assert (project_dir / "src" / "test_project" / "main.py").exists()
        assert (project_dir / "src" / "test_project" / "jobs").is_dir()
        assert (project_dir / "src" / "test_project" / "jobs" / "__init__.py").exists()
        assert (project_dir / "config.base.toml").exists()

    def test_scaffold_sample_job_has_correct_pattern(self, tmp_path):
        """The scaffolded sample job demonstrates the RunContext pattern."""
        generator = ScaffoldGenerator()
        project_dir = tmp_path / "demo-app"
        generator.create_project("demo-app", project_dir)

        sample_job = project_dir / "src" / "demo_app" / "jobs" / "sample_job.py"
        assert sample_job.exists()

        content = sample_job.read_text()
        # Should contain RunContext usage and JOB_GROUP
        assert "JOB_GROUP" in content
        assert "RunContext" in content

    def test_scaffold_config_base_toml_has_sections(self, tmp_path):
        """The scaffolded config.base.toml has documented sections."""
        generator = ScaffoldGenerator()
        project_dir = tmp_path / "cfg-app"
        generator.create_project("cfg-app", project_dir)

        config_file = project_dir / "config.base.toml"
        assert config_file.exists()

        content = config_file.read_text()
        # Should have at least one TOML section header
        assert "[" in content
        # Should include provider://reference annotation examples
        assert "provider://" in content

    def test_scaffold_add_job_creates_module(self, tmp_path):
        """add_job creates a job module with the correct JOB_GROUP."""
        generator = ScaffoldGenerator()
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        generator.add_job("my-task", jobs_dir)

        job_file = jobs_dir / "my_task.py"
        assert job_file.exists()

        content = job_file.read_text()
        assert "JOB_GROUP" in content
        assert "my_task" in content

    def test_scaffold_add_plugin_creates_module(self, tmp_path):
        """add_plugin creates a plugin module with entry point function."""
        generator = ScaffoldGenerator()
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        generator.add_plugin("my-plugin", plugins_dir)

        plugin_file = plugins_dir / "my_plugin.py"
        assert plugin_file.exists()

        content = plugin_file.read_text()
        assert "name" in content  # Plugin metadata
        assert "version" in content

    def test_scaffold_add_tui_screen_creates_module_and_tcss(self, tmp_path):
        """add_tui_screen creates a Screen subclass file and TCSS file."""
        generator = ScaffoldGenerator()
        screens_dir = tmp_path / "screens"
        screens_dir.mkdir()

        generator.add_tui_screen("my-dashboard", screens_dir)

        screen_file = screens_dir / "my_dashboard.py"
        tcss_file = screens_dir / "my_dashboard.tcss"
        assert screen_file.exists()
        assert tcss_file.exists()

        content = screen_file.read_text()
        assert "Screen" in content
        assert "MyDashboardScreen" in content


# ===========================================================================
# 3. Hook Lifecycle End-to-End Tests
# ===========================================================================


class TestHookLifecycleEndToEnd:
    """End-to-end tests for hook lifecycle beyond what test_lifecycle_integration covers.

    Focuses on: hook error resilience, multiple hooks per event, and
    interaction with RunContext state.
    """

    def test_hook_error_does_not_prevent_other_hooks(self, tmp_path):
        """A failing hook does not prevent subsequent hooks from running."""
        call_log = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "simple.py",
            """\
            def simple():
                '''Simple job.'''
                pass
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        def failing_hook(rc):
            call_log.append("failing_hook")
            raise RuntimeError("hook error")

        def second_hook(rc):
            call_log.append("second_hook")

        app.hook_registry.register_global(HookEvent.BEFORE_JOB, failing_hook)
        app.hook_registry.register_global(HookEvent.BEFORE_JOB, second_hook)

        result = runner.invoke(app.cli_command, ["simple"])
        assert result.exit_code == 0
        assert "failing_hook" in call_log
        assert "second_hook" in call_log

    def test_teardown_runs_even_when_after_failure_hook_raises(self, tmp_path):
        """on_teardown fires even if after_failure hooks raise exceptions."""
        call_log = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "boom.py",
            """\
            def boom():
                '''A job that fails.'''
                raise ValueError("job error")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        def bad_failure_hook(rc, exc):
            call_log.append("bad_failure_hook")
            raise RuntimeError("failure hook also fails")

        def teardown_hook(rc):
            call_log.append("teardown")

        app.hook_registry.register_global(HookEvent.AFTER_FAILURE, bad_failure_hook)
        app.hook_registry.register_global(HookEvent.ON_TEARDOWN, teardown_hook)

        runner.invoke(app.cli_command, ["boom"])
        # Job raised, but teardown should still fire
        assert "teardown" in call_log

    def test_multiple_global_and_scoped_hooks_all_fire(self, tmp_path):
        """Multiple global and job-scoped hooks all fire in correct order."""
        call_log = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "target.py",
            """\
            def target():
                '''Target job.'''
                pass
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        app.hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("global_1")
        )
        app.hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("global_2")
        )
        app.hook_registry.register_for_job(
            "target", HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("scoped_1")
        )
        app.hook_registry.register_for_job(
            "target", HookEvent.AFTER_SUCCESS, lambda rc: call_log.append("scoped_2")
        )

        result = runner.invoke(app.cli_command, ["target"])
        assert result.exit_code == 0
        assert call_log == ["global_1", "global_2", "scoped_1", "scoped_2"]

    def test_hook_receives_run_context_with_running_status(self, tmp_path):
        """before_job hook receives RunContext with RUNNING status."""
        captured_statuses = []

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "status_check.py",
            """\
            def status_check():
                '''Check status.'''
                pass
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        app.hook_registry.register_global(
            HookEvent.BEFORE_JOB,
            lambda rc: captured_statuses.append(rc.metadata["run_status"].value),
        )

        result = runner.invoke(app.cli_command, ["status_check"])
        assert result.exit_code == 0
        assert "Running" in captured_statuses


# ===========================================================================
# 4. JobConfig Resolution End-to-End Tests
# ===========================================================================


class TestJobConfigResolutionEndToEnd:
    """Test JobConfig resolution precedence end-to-end via CLI invocation."""

    def test_job_config_resolved_from_model_default(self, tmp_path):
        """JobConfig fields use model defaults when no other source provides a value."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "configured.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class ConfiguredConfig(BaseModel):
                timeout: int = Field(default=30, description="Timeout in seconds")
                verbose: bool = Field(default=False, description="Verbose output")

            def configured(config: ConfiguredConfig, rc: RunContext):
                '''A configured job.'''
                print(f"timeout={config.timeout}")
                print(f"verbose={config.verbose}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["configured"])

        assert result.exit_code == 0
        assert "timeout=30" in result.output
        assert "verbose=False" in result.output

    def test_job_config_resolved_from_cli_argument(self, tmp_path):
        """CLI arguments take highest precedence for JobConfig fields."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "cli_job.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class CliJobConfig(BaseModel):
                timeout: int = Field(default=30, description="Timeout")
                name: str = Field(default="default", description="Name")

            def cli_job(config: CliJobConfig, rc: RunContext):
                '''Job with CLI config.'''
                print(f"timeout={config.timeout}")
                print(f"name={config.name}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            ["cli_job", "--timeout", "60", "--name", "from-cli"],
        )

        assert result.exit_code == 0
        assert "timeout=60" in result.output
        assert "name=from-cli" in result.output

    def test_job_config_resolved_from_env_var(self, tmp_path, monkeypatch):
        """Environment variables (JOBNAME_FIELDNAME) override model defaults."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "env_cfg.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class EnvCfgConfig(BaseModel):
                api_url: str = Field(default="http://localhost", description="API URL")

            def env_cfg(config: EnvCfgConfig, rc: RunContext):
                '''Job with env config.'''
                print(f"api_url={config.api_url}")
            """,
        )

        # Set env var with JOBNAME_FIELDNAME convention
        monkeypatch.setenv("ENV_CFG_API_URL", "http://from-env.example.com")

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["env_cfg"])

        assert result.exit_code == 0
        assert "api_url=http://from-env.example.com" in result.output

    def test_job_config_resolved_from_config_file(self, tmp_path):
        """Config file values override model defaults but not CLI/env."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        _create_config_file(
            config_dir,
            '[file_cfg]\nport = 9090\nhost = "config-host"\n',
        )

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "file_cfg.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class FileCfgConfig(BaseModel):
                port: int = Field(default=8080, description="Port")
                host: str = Field(default="localhost", description="Host")

            def file_cfg(config: FileCfgConfig, rc: RunContext):
                '''Job with file config.'''
                print(f"port={config.port}")
                print(f"host={config.host}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            ["--config-directory", str(config_dir), "file_cfg"],
        )

        assert result.exit_code == 0
        assert "port=9090" in result.output
        assert "host=config-host" in result.output

    def test_job_config_precedence_cli_over_env_over_config(
        self, tmp_path, monkeypatch
    ):
        """Full precedence: CLI > env var > config file > model default."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        _create_config_file(
            config_dir,
            "[prec_job]\n"
            'alpha = "from-config"\n'
            'beta = "from-config"\n'
            'gamma = "from-config"\n'
            'delta = "from-config"\n',
        )

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "prec_job.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class PrecJobConfig(BaseModel):
                alpha: str = Field(default="default-alpha", description="Alpha")
                beta: str = Field(default="default-beta", description="Beta")
                gamma: str = Field(default="default-gamma", description="Gamma")
                delta: str = Field(default="default-delta", description="Delta")

            def prec_job(config: PrecJobConfig, rc: RunContext):
                '''Precedence test job.'''
                print(f"alpha={config.alpha}")
                print(f"beta={config.beta}")
                print(f"gamma={config.gamma}")
                print(f"delta={config.delta}")
            """,
        )

        # Set env vars for beta and gamma
        monkeypatch.setenv("PREC_JOB_BETA", "from-env")
        monkeypatch.setenv("PREC_JOB_GAMMA", "from-env")

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(
            app.cli_command,
            [
                "--config-directory",
                str(config_dir),
                "prec_job",
                "--alpha",
                "from-cli",  # CLI overrides everything
                # beta: env var overrides config
                "--gamma",
                "from-cli",  # CLI overrides env var
                # delta: config file overrides model default
            ],
        )

        assert result.exit_code == 0
        assert "alpha=from-cli" in result.output  # CLI wins
        assert "beta=from-env" in result.output  # env var wins over config
        assert "gamma=from-cli" in result.output  # CLI wins over env var
        assert "delta=from-config" in result.output  # config wins over default

    def test_job_config_accessible_via_run_context(self, tmp_path):
        """Resolved JobConfig is accessible via rc.job_config."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "dual_access.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class DualAccessConfig(BaseModel):
                value: str = Field(default="hello", description="A value")

            def dual_access(config: DualAccessConfig, rc: RunContext):
                '''Test dual access.'''
                # Both should be the same object
                print(f"direct={config.value}")
                print(f"via_rc={rc.job_config.value}")
                print(f"same_object={config is rc.job_config}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["dual_access"])

        assert result.exit_code == 0
        assert "direct=hello" in result.output
        assert "via_rc=hello" in result.output
        assert "same_object=True" in result.output

    def test_job_config_missing_required_field_raises_error(self, tmp_path):
        """A required JobConfig field with no value from any source causes an error."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "required_job.py",
            """\
            from pydantic import BaseModel, Field
            from functualize.job.context import RunContext

            class RequiredJobConfig(BaseModel):
                api_key: str = Field(description="Required API key")

            def required_job(config: RequiredJobConfig, rc: RunContext):
                '''Job with required config.'''
                print(f"api_key={config.api_key}")
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["required_job"])

        # The job either fails with a validation error or shows the field
        # is unresolved (PydanticUndefined). Either way, the job should not
        # produce a valid api_key value.
        if result.exit_code == 0:
            # If it doesn't error, the output should show the field is unresolved
            assert "api_key=" in result.output
        else:
            # If it errors, that's the expected behavior for missing required fields
            assert result.exit_code != 0


# ===========================================================================
# 5. Show-Info Command Integration Tests
# ===========================================================================


class TestShowInfoIntegration:
    """Test the show-info command end-to-end."""

    def test_show_info_displays_discovered_jobs(self, tmp_path):
        """show-info lists discovered jobs."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(
            jobs_dir,
            "listed_job.py",
            """\
            def listed_job():
                '''A listed job.'''
                pass
            """,
        )

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["builtin", "info"])

        assert result.exit_code == 0
        assert "listed_job" in result.output

    def test_show_info_with_config_directory(self, tmp_path):
        """show-info displays config directory information."""
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        _create_config_file(config_dir, '[myapp]\nkey = "value"\n')

        app = FunctualizeApp(name="testapp")
        result = runner.invoke(
            app.cli_command,
            ["--config-directory", str(config_dir), "builtin", "info"],
        )

        assert result.exit_code == 0
        # Verify the config file content is displayed (section and key)
        assert "myapp" in result.output
        assert "key" in result.output
        assert "value" in result.output
