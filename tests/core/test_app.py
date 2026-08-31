"""Unit tests for FunctualizeApp class and CLI bootstrap."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import DEFAULT_CONFIG_FILE_REGEX, FunctualizeApp
from functualize.types import ConfigFileRole, EnvironmentSource

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary config directory with a base config file."""
    config_file = tmp_path / "config.base.toml"
    config_file.write_text('[general]\napp_name = "test"\n')
    return tmp_path


@pytest.fixture
def dotenv_file(tmp_path):
    """Create a temporary .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_VAR=hello\nANOTHER_VAR=world\n")
    return env_file


class TestFunctualizeAppInit:
    """Tests for FunctualizeApp initialization."""

    def test_creates_cli_command(self, config_dir):
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))
        assert app.cli_command is not None
        assert app.name == "testapp"

    def test_stores_jobs_directories(self, config_dir):
        dirs = [str(config_dir / "jobs")]
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=dirs))
        assert app._jobs_directories == dirs

    def test_default_plugin_group(self):
        app = FunctualizeApp(name="testapp")
        assert app.plugin_loader._group == "functualize.plugins"

    def test_custom_plugin_group(self):
        app = FunctualizeApp(
            name="testapp",
            plugin_sources=PluginSources(entry_point_group="myapp.plugins"),
        )
        assert app.plugin_loader._group == "myapp.plugins"

    def test_default_config_file_regex(self):
        app = FunctualizeApp(name="testapp")
        assert app._config_file_regex == DEFAULT_CONFIG_FILE_REGEX

    def test_custom_config_file_regex(self):
        custom_regex = r"^settings\.(\w+)\.toml$"
        app = FunctualizeApp(
            name="testapp",
            config_sources=ConfigSources(file_pattern=custom_regex),
        )
        assert app._config_file_regex == custom_regex

    def test_sets_appstate_config_directory(self):
        FunctualizeApp(name="testapp")
        assert AppState.get("config_directory") is not None

    def test_resolves_environment_from_env_var(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "STAGING"}):
            app = FunctualizeApp(name="testapp")
            assert app.active_environment() == "STAGING"
            assert app.environment_source() is EnvironmentSource.ENVIRONMENT

    def test_environment_defaults_to_dev(self):
        env = {k: v for k, v in os.environ.items()}
        for var in ("FUNCTUALIZE_ENV", "ENVIRONMENT", "ENV"):
            env.pop(var, None)
        with patch.dict(os.environ, env, clear=True):
            app = FunctualizeApp(name="testapp")
            assert app.active_environment() == "DEV"
            # Defaulted, not chosen — the distinction the TUI footer shows.
            assert app.environment_source() is EnvironmentSource.DEFAULT


class TestConfigDiscovery:
    """Tests for config directory discovery."""

    def test_discovers_config_from_cwd(self, tmp_path):
        """When config files exist in CWD, uses that directory."""
        config_file = tmp_path / "config.base.toml"
        config_file.write_text('[general]\nkey = "value"\n')

        with patch("os.getcwd", return_value=str(tmp_path)):
            app = FunctualizeApp(name="testapp")
            assert app._config_path == str(tmp_path)

    def test_discovers_config_from_parent(self, tmp_path):
        """When config files exist in a parent directory, finds them."""
        config_file = tmp_path / "config.base.toml"
        config_file.write_text('[general]\nkey = "value"\n')

        child_dir = tmp_path / "subdir" / "deep"
        child_dir.mkdir(parents=True)

        with patch("os.getcwd", return_value=str(child_dir)):
            app = FunctualizeApp(name="testapp")
            assert app._config_path == str(tmp_path)

    def test_falls_back_to_app_dir_when_no_config(self, tmp_path):
        """When no config files found, falls back to OS app dir."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        # Use a directory that won't have config files in its tree
        with (
            patch("os.getcwd", return_value=str(empty_dir)),
            patch("os.path.expanduser", return_value=str(tmp_path)),
        ):
            app = FunctualizeApp(name="testapp")
            # Should fall back to typer.get_app_dir
            # The actual path depends on OS, just verify it's not the empty dir
            assert app._config_path != str(empty_dir)


class TestGlobalOptions:
    """Tests for CLI global options (--log-level, --dotenv-file, --config-directory)."""

    def test_log_level_default_info(self):
        app = FunctualizeApp(name="testapp")
        result = runner.invoke(app.cli_command, ["--help"])
        assert result.exit_code == 0

    def test_log_level_option_accepted(self):
        app = FunctualizeApp(name="testapp")
        result = runner.invoke(app.cli_command, ["--log-level", "DEBUG"])
        assert result.exit_code == 0

    def test_dotenv_file_loads_env_vars(self, dotenv_file):
        app = FunctualizeApp(name="testapp")
        result = runner.invoke(app.cli_command, ["--dotenv-file", str(dotenv_file)])
        assert result.exit_code == 0
        assert AppState.get("dotenv_path") == str(dotenv_file)

    def test_dotenv_file_not_found_exits_nonzero(self, tmp_path):
        app = FunctualizeApp(name="testapp")
        nonexistent = str(tmp_path / "nonexistent.env")
        result = runner.invoke(app.cli_command, ["--dotenv-file", nonexistent])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_config_directory_option_sets_appstate(self, config_dir):
        app = FunctualizeApp(name="testapp")
        result = runner.invoke(app.cli_command, ["--config-directory", str(config_dir)])
        assert result.exit_code == 0
        assert AppState.get("config_directory") == str(config_dir)

    def test_config_directory_not_found_exits_nonzero(self, tmp_path):
        app = FunctualizeApp(name="testapp")
        nonexistent = str(tmp_path / "nonexistent_dir")
        result = runner.invoke(app.cli_command, ["--config-directory", nonexistent])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_invoke_without_command_shows_help(self):
        """Callback with invoke_without_command=True should work without subcommand."""
        app = FunctualizeApp(name="testapp")
        result = runner.invoke(app.cli_command, [])
        # Should not error - invoke_without_command=True means it's OK to call with no subcommand
        assert result.exit_code == 0


class TestComponentWiring:
    """Tests for component wiring (JobRegistry, PluginLoader, HookRegistry)."""

    def test_job_registry_initialized(self):
        app = FunctualizeApp(name="testapp")
        assert app.job_registry is not None

    def test_plugin_loader_initialized(self):
        app = FunctualizeApp(name="testapp")
        assert app.plugin_loader is not None

    def test_hook_registry_initialized(self):
        app = FunctualizeApp(name="testapp")
        assert app.hook_registry is not None

    def test_jobs_scanned_when_directories_provided(self, tmp_path):
        """When jobs_directories are provided, scan_and_register is called."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create a simple job module
        job_file = jobs_dir / "sample_job.py"
        job_file.write_text("def hello():\n    '''Say hello.'''\n    print('hello')\n")

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        # The job should be registered
        result = runner.invoke(app.cli_command, ["hello", "--help"])
        assert result.exit_code == 0
        assert "Say hello" in result.output

    def test_jobs_not_scanned_when_no_directories(self):
        """When no jobs_directories, no scanning occurs."""
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))
        # Should still work, just no job commands
        result = runner.invoke(app.cli_command, ["--help"])
        assert result.exit_code == 0


class TestConfigFiles:
    """Tests for config_files() — per-file provenance for delivery layers."""

    @staticmethod
    def _app_in(tmp_path, monkeypatch, environment="dev"):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ENVIRONMENT", environment)
        app = FunctualizeApp(name="testapp")

        def serve(port: int = 1, debug: bool = False, workers: int = 1) -> None:
            pass

        app.register_dynamic_job("serve", serve)
        return app

    def _by_name(self, app, job_name="serve"):
        return {Path(i.path).name: i for i in app.config_files(job_name)}

    def test_reports_each_file_contribution(self, tmp_path, monkeypatch):
        """Each file keeps its own values, not the merged view."""
        (tmp_path / "config.base.toml").write_text("[serve]\nport = 80\nworkers = 1\n")
        (tmp_path / "config.dev.toml").write_text(
            "[serve]\nport = 8080\ndebug = true\n"
        )

        files = self._by_name(self._app_in(tmp_path, monkeypatch))

        assert files["config.base.toml"].values == {"port": 80, "workers": 1}
        assert files["config.dev.toml"].values == {"port": 8080, "debug": True}

    def test_overlay_outranks_base(self, tmp_path, monkeypatch):
        """The active overlay wins — the whole point of the feature."""
        (tmp_path / "config.base.toml").write_text("[serve]\nport = 80\n")
        (tmp_path / "config.dev.toml").write_text("[serve]\nport = 8080\n")

        app = self._app_in(tmp_path, monkeypatch)
        files = self._by_name(app)

        assert files["config.base.toml"].role is ConfigFileRole.BASE
        assert files["config.dev.toml"].role is ConfigFileRole.OVERLAY
        # Lower precedence rank wins.
        assert (
            files["config.dev.toml"].precedence < files["config.base.toml"].precedence
        )

    def test_other_environments_are_inert_not_absent(self, tmp_path, monkeypatch):
        """A prod file under ENVIRONMENT=dev exists but must not contribute.

        Reporting it (rather than omitting it) is what lets a delivery layer
        explain why a file that plainly exists is not taking effect.
        """
        (tmp_path / "config.dev.toml").write_text("[serve]\nport = 8080\n")
        (tmp_path / "config.prod.toml").write_text("[serve]\nport = 9999\n")

        app = self._app_in(tmp_path, monkeypatch)
        files = self._by_name(app)

        assert files["config.prod.toml"].role is ConfigFileRole.INERT
        assert files["config.prod.toml"].precedence is None
        assert files["config.prod.toml"].is_active is False
        # It still reports what it *would* have said.
        assert files["config.prod.toml"].values == {"port": 9999}

    def test_job_name_narrows_values_to_the_section(self, tmp_path, monkeypatch):
        (tmp_path / "config.dev.toml").write_text(
            "[serve]\nport = 8080\n\n[other]\nx = 1\n"
        )

        app = self._app_in(tmp_path, monkeypatch)

        assert self._by_name(app)["config.dev.toml"].values == {"port": 8080}
        # Without a job name, the file's full contents come back.
        full = {Path(i.path).name: i for i in app.config_files()}
        assert full["config.dev.toml"].values == {
            "serve": {"port": 8080},
            "other": {"x": 1},
        }

    def test_returns_empty_when_no_files_discovered(self, tmp_path, monkeypatch):
        assert self._app_in(tmp_path, monkeypatch).config_files("serve") == []


class TestRunMethod:
    """Tests for the run() entry point method."""

    def test_run_invokes_cli_command(self):
        """run() should invoke the Typer app."""
        app = FunctualizeApp(name="testapp")
        # We can't easily test run() directly since it calls sys.exit,
        # but we can verify it exists and is callable
        assert callable(app.run)

    def test_run_method_exists(self):
        app = FunctualizeApp(name="testapp")
        assert hasattr(app, "run")
