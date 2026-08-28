"""Unit tests for the builtin info command."""

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp

runner = CliRunner()


def _invoke(app, args):
    """Invoke through the app's click tree.

    Since B2b the adapter mounts the reserved ``builtin`` subtree on
    ``app.cli_command``, so ``builtin info`` is reachable without registering
    anything by hand.
    """
    return runner.invoke(app.cli_command, args)


def _packed(output: str) -> str:
    """Rich output with wrapping removed, for asserting on long strings.

    A panel wraps a temp path across lines and pads each with box-drawing
    characters, so a plain substring check for a path fails on layout rather
    than on behaviour.
    """
    return "".join(ch for ch in output if not ch.isspace() and ch not in "│─╭╮╰╯┃━┏┓┗┛")


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary config directory with base and dev config files.

    TOML, because TOML is what the framework reads (ADR-007). These were `.ini`
    until 2026-08-28 and the tests still passed, because `builtin info` parsed
    config files itself with `configparser` instead of asking the registered
    providers — so it displayed the contents of files the resolver ignored.
    """
    base_config = tmp_path / "config.base.toml"
    base_config.write_text(
        "[general]\n"
        'app_name = "testapp"\n'
        "debug = false\n\n"
        "[server]\n"
        'host = "localhost"\n'
        "port = 8080\n"
    )
    dev_config = tmp_path / "config.dev.toml"
    dev_config.write_text('[server]\nhost = "0.0.0.0"\nport = 9090\n')
    return tmp_path


@pytest.fixture
def dotenv_file(tmp_path):
    """Create a temporary .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("MY_VAR=hello\nSECRET=world\n")
    return env_file


@pytest.fixture
def jobs_dir(tmp_path):
    """Create a temporary jobs directory with sample job modules."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()

    # Simple job without JOB_GROUP
    simple_job = jobs / "simple_job.py"
    simple_job.write_text(
        "def greet():\n    '''Greet the user.'''\n    print('hello')\n"
    )

    # Grouped job with JOB_GROUP
    grouped_job = jobs / "data_job.py"
    grouped_job.write_text(
        "JOB_GROUP = 'data'\n\n"
        "def fetch():\n"
        "    '''Fetch data.'''\n"
        "    print('fetching')\n\n"
        "def transform():\n"
        "    '''Transform data.'''\n"
        "    print('transforming')\n"
    )

    return jobs


@pytest.fixture
def jobs_dir_with_config(tmp_path):
    """Create a jobs directory with a job that has a JobConfig."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()

    job_file = jobs / "configured_job.py"
    job_file.write_text(
        "from pydantic import BaseModel, Field\n"
        "from functualize.job.context import RunContext\n\n"
        "class MyConfig(BaseModel):\n"
        "    api_url: str = Field(default='http://localhost', description='API URL')\n"
        "    timeout: int = Field(default=30, description='Timeout in seconds')\n"
        "    verbose: bool = Field(default=False, description='Verbose output')\n\n"
        "def process(config: MyConfig, rc: RunContext):\n"
        "    '''Process with config.'''\n"
        "    pass\n"
    )

    return jobs


class TestShowInfoBasic:
    """Tests for basic builtin info command output."""

    def test_show_info_command_exists(self):
        app = FunctualizeApp(name="testapp")
        result = _invoke(app, ["builtin", "info", "--help"])
        assert result.exit_code == 0
        assert "Show current CLI configuration" in result.output

    def test_show_info_displays_log_level(self):
        app = FunctualizeApp(name="testapp")
        result = _invoke(app, ["builtin", "info"])
        assert result.exit_code == 0
        assert "Log Level" in result.output

    def test_show_info_displays_environment(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "STAGING"}):
            app = FunctualizeApp(name="testapp")
            result = _invoke(app, ["builtin", "info"])
            assert result.exit_code == 0
            assert "STAGING" in result.output

    def test_show_info_displays_config_directory(self, config_dir):
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        # Rich may truncate long paths; check that "Config Directory" label is present
        assert "Config Directory" in result.output

    def test_show_info_no_config_files_message(self, tmp_path):
        """When no config files exist, shows appropriate message."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        app = FunctualizeApp(name="testapp")
        result = _invoke(app, ["--config-directory", str(empty_dir), "builtin", "info"])
        assert result.exit_code == 0
        assert "No config files found" in result.output


class TestShowInfoConfigFiles:
    """Tests for config file display in builtin info."""

    def test_displays_config_file_contents(self, config_dir):
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        # Should show interpolated config values
        assert "app_name" in result.output
        assert "host" in result.output
        assert "port" in result.output

    def test_displays_section_headers_and_values(self, config_dir):
        """The panel shows what the providers parsed, section by section.

        This was `test_displays_interpolated_values`: the panel ran every value
        through `configparser.ExtendedInterpolation` over `os.environ`, so
        `${VAR}` in a config file was expanded *and printed*. That was removed
        rather than kept — a display surface that reads the environment and
        echoes the result is a leak, and nothing in the resolver interpolates,
        so the panel was showing values no run would ever use.
        """
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "general" in result.output
        assert "app_name" in result.output
        assert "localhost" in result.output

    def test_reports_a_file_no_provider_can_read(self, tmp_path):
        """A config-shaped file the framework cannot parse must still be named.

        Asserted against the output with whitespace stripped: Rich wraps a long
        path across lines, and a temp path is always long.
        """
        (tmp_path / "config.base.ini").write_text("[general]\napp_name = legacy\n")

        app = FunctualizeApp(name="testapp")
        result = _invoke(app, ["--config-directory", str(tmp_path), "builtin", "info"])

        assert result.exit_code == 0
        packed = _packed(result.output)
        assert "config.base.ini" in packed, (
            f"the unreadable config file was not reported:\n{result.output}"
        )
        assert "ConvertittoTOML" in packed, "the report does not name the way out"
        assert "No config files found" not in result.output


class TestShowInfoJobs:
    """Tests for discovered jobs display in builtin info."""

    def test_displays_discovered_jobs(self, jobs_dir, config_dir):
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "greet" in result.output

    def test_displays_job_name_grouping(self, jobs_dir, config_dir):
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "data" in result.output
        assert "fetch" in result.output
        assert "transform" in result.output

    def test_displays_module_path(self, jobs_dir, config_dir):
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "simple_job" in result.output
        assert "data_job" in result.output

    def test_no_jobs_message(self, config_dir):
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "No jobs discovered" in result.output


class TestShowInfoJobOption:
    """Tests for --job option in builtin info."""

    def test_job_not_found_shows_error(self, jobs_dir, config_dir):
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = _invoke(
            app,
            [
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
                "--job",
                "nonexistent",
            ],
        )
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_job_not_found_lists_available(self, jobs_dir, config_dir):
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = _invoke(
            app,
            [
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
                "--job",
                "nonexistent",
            ],
        )
        assert result.exit_code == 0
        assert "Available jobs" in result.output

    def test_job_with_config_shows_fields(self, jobs_dir_with_config, config_dir):
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(jobs_dir_with_config)]),
        )
        result = _invoke(
            app,
            [
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
                "--job",
                "process",
            ],
        )
        assert result.exit_code == 0
        assert "api_url" in result.output
        assert "timeout" in result.output
        assert "verbose" in result.output

    def test_job_with_config_shows_source(self, jobs_dir_with_config, config_dir):
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[str(jobs_dir_with_config)]),
        )
        result = _invoke(
            app,
            [
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
                "--job",
                "process",
            ],
        )
        assert result.exit_code == 0
        assert "model default" in result.output

    def test_job_without_config_shows_message(self, jobs_dir, config_dir):
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = _invoke(
            app,
            [
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
                "--job",
                "greet",
            ],
        )
        assert result.exit_code == 0
        assert "no JobConfig declared" in result.output


class TestShowInfoDotenv:
    """Tests for dotenv display in builtin info."""

    def test_no_dotenv_shows_message(self, config_dir):
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "No dotenv file loaded" in result.output

    def test_dotenv_loaded_shows_path(self, dotenv_file, config_dir):
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app,
            [
                "--dotenv-file",
                str(dotenv_file),
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
            ],
        )
        assert result.exit_code == 0
        # Rich may wrap long paths across lines; check that "Dotenv File" panel is shown
        # and that the .env filename appears somewhere in the output
        assert "Dotenv File" in result.output
        assert ".env" in result.output

    def test_dotenv_loaded_shows_contents(self, dotenv_file, config_dir):
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app,
            [
                "--dotenv-file",
                str(dotenv_file),
                "--config-directory",
                str(config_dir),
                "builtin",
                "info",
            ],
        )
        assert result.exit_code == 0
        assert "MY_VAR" in result.output


class TestShowInfoEnvVars:
    """Tests for --show-env-vars flag in builtin info."""

    def test_env_vars_not_shown_by_default(self, config_dir):
        app = FunctualizeApp(name="testapp")
        result = _invoke(
            app, ["--config-directory", str(config_dir), "builtin", "info"]
        )
        assert result.exit_code == 0
        assert "Environment Variables" not in result.output

    def test_env_vars_shown_with_flag(self, config_dir):
        app = FunctualizeApp(name="testapp")
        with patch.dict(os.environ, {"TEST_SHOW_VAR": "visible"}):
            result = _invoke(
                app,
                [
                    "--config-directory",
                    str(config_dir),
                    "builtin",
                    "info",
                    "--show-env-vars",
                ],
            )
            assert result.exit_code == 0
            assert "Environment Variables" in result.output
            assert "TEST_SHOW_VAR" in result.output
