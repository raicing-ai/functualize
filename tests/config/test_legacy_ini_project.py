"""A project whose config the framework can no longer read must say so.

ADR-007 made TOML the only format registered at boot. For a project that
already had `config.base.ini`, the result was not an error — it was silence.
The file failed the extension check in `discover_config_path`, so it never
anchored a directory, never entered `FileSource._discovered_paths`, and never
reached `ConfigFileInfo.parsed` either. The job ran on its model defaults, exit
code 0, and `func builtin info` reported "No config files found".

That is the same failure the branch removed the bare-`FIELD` environment
fallback for: a wrong value, silently, with the correct one unreachable. The
gap that let it ship is that every test written for ADR-007 started from a TOML
project. Nothing asked what the *pre-migration* state looks like, so the one
user population the change was breaking was the one population untested.

These tests are that fixture.
"""

from __future__ import annotations

import pytest


def _packed(output: str) -> str:
    """Rich output with wrapping removed, for asserting on long strings.

    The unreadable-file report is a panel titled with the file's absolute
    path, and a temp path is always long enough for Rich to wrap it — so a
    plain substring check fails on layout rather than on behaviour. Asserting
    on the packed form keeps the test measuring the diagnostic, not the
    terminal width it happened to be rendered at.
    """
    return "".join(ch for ch in output if not ch.isspace() and ch not in "│─╭╮╰╯┃━┏┓┗┛")


PYPROJECT = """\
[project]
name = "legacy-ini-project"
version = "0.1.0"
"""

INI_CONFIG = """\
[sync]
api_url = https://from-the-ini-file.example.com
"""

JOB = """
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job


class SyncConfig(BaseModel):
    api_url: str = Field(default="THE-MODEL-DEFAULT")


@job(extra_description="Sync with the remote API")
def sync(config: SyncConfig, rc: RunContext) -> str:
    print(f"api_url={config.api_url}")
    return "ok"
"""


@pytest.fixture()
def legacy_project(project_tree):
    """A project whose only configuration is an `.ini` file."""
    return project_tree(
        pyproject=PYPROJECT,
        jobs={"job_sync.py": JOB},
        extra_files={"config.base.ini": INI_CONFIG},
    )


class TestTheFileIsNotIgnoredInSilence:
    def test_running_a_job_warns_about_the_unreadable_file(
        self, cli_run, legacy_project
    ):
        """The operator who needs this most is not running a diagnostic command.

        They are running the job, getting the model default, and have no reason
        to suspect the config file they wrote is being ignored.
        """
        result = cli_run(["sync"], cwd=legacy_project)

        combined = result.stdout + result.stderr
        assert "config.base.ini" in _packed(combined), (
            "a config file the framework cannot read was ignored without a "
            f"word:\n{combined}"
        )

    def test_the_warning_names_the_way_out(self, cli_run, legacy_project):
        """Naming a problem without naming its fix is half a diagnostic.

        Both remedies must be named, because they answer different questions:
        convert, for a project that is willing to move; register a provider
        from a plugin, for one that is not. The second is the one with a trap
        in it — registering on ``app.config_registry`` after boot is too late —
        so the warning says when plugins load.
        """
        result = cli_run(["sync"], cwd=legacy_project)

        packed = _packed(result.stdout + result.stderr)
        assert "ConvertittoTOML" in packed
        assert "plugin" in packed

    def test_builtin_info_reports_the_file(self, cli_run, legacy_project):
        """`info` is the command for "what config is in effect?".

        It used to answer "No config files found" while the file sat in the
        project root.
        """
        result = cli_run(["builtin", "info"], cwd=legacy_project)

        assert "config.base.ini" in _packed(result.stdout), (
            f"the unreadable config file was not reported:\n{result.stdout}"
        )
        assert "No config files found" not in result.stdout


class TestTheWayOutClosesTheLoop:
    """Following the warning must actually work.

    A conversion *command* used to stand here. It was removed — pre-1.0 there
    is no user population to carry across the break, and a command that exists
    only to serve one is the ``migrate_ini_to_toml``-with-no-callers shape it
    was built to fix, one level up. What must still hold is that the remedy
    the warning names produces a project that resolves.
    """

    def test_converting_the_file_makes_the_value_resolve(self, cli_run, legacy_project):
        """The first remedy: convert, and the value the INI held comes back."""
        (legacy_project / "config.base.ini").unlink()
        (legacy_project / "config.base.toml").write_text(
            '[sync]\napi_url = "https://from-the-ini-file.example.com"\n'
        )

        run = cli_run(["sync"], cwd=legacy_project)
        assert "api_url=https://from-the-ini-file.example.com" in run.stdout, (
            "the converted file does not resolve — the fix the warning names "
            f"does not work:\n{run.stdout}\n{run.stderr}"
        )

    def test_a_toml_project_warns_about_nothing(self, cli_run, project_tree):
        """Guard the guard: the warning must not fire for a healthy project."""
        root = project_tree(
            pyproject=PYPROJECT,
            jobs={"job_sync.py": JOB},
            extra_files={
                "config.base.toml": '[sync]\napi_url = "https://from-toml.example.com"\n'
            },
        )
        result = cli_run(["sync"], cwd=root)

        assert "api_url=https://from-toml.example.com" in result.stdout
        assert "no config format provider" not in (result.stdout + result.stderr)
