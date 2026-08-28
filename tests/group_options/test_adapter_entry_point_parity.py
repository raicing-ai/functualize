"""The surface `tests/group_options/` could not see: an app's own entry point.

Every other probe in this package drives `functualize._cli.main` — the `func`
command. A standalone app does not go through it. `CliAdapter` builds a real
nested ``click.Group`` tree and click owns the parse, so mid-path flags never
reach ``walk_group_path`` at all:

    func deploy --env prod web run v1.2   →  env = prod
    glab deploy --env prod web run v1.2   →  Error: No such option '--env'

Nothing caught it because "CLI parity" was six probes over one CLI. The
adapter is a *second* CLI, and `examples/standalone/group_options_lab/`
ships a `glab` script whose README says the two are interchangeable.

The probes here run the adapter directly rather than the console script, so
they need no install step — the tree under test is the one
``register_discovered_jobs`` builds either way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

_GROUP_MODULE = """\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    env: Annotated[str, Option("-e")] = "staging"
    dry_run: Annotated[bool, Option("--dry-run")] = False


class WebOptions(GroupOptions, group="deploy.web"):
    region: str = "us-east-1"
"""

_WEB_JOB = '''\
from typing import Annotated

from functualize.job import Arg, job

from _group import DeployOptions, WebOptions

JOB_GROUP = "deploy.web"


@job
def run(
    image: Annotated[str, Arg()],
    replicas: int = 1,
    opts: DeployOptions = None,
    web: WebOptions = None,
):
    """Deploy the web tier."""
    print(f"image={image} replicas={replicas} env={opts.env} region={web.region}")
    return image
'''

_CONFIG = """\
[deploy]
env = "from-file"

[deploy.web]
region = "region-from-file"
"""


@pytest.fixture()
def app_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An app built the way a standalone project builds one, plus a runner."""
    from functualize.app import FunctualizeApp, JobSources
    from functualize.app.adapters import CliAdapter

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "_group.py").write_text(_GROUP_MODULE, encoding="utf-8")
    (jobs / "web.py").write_text(_WEB_JOB, encoding="utf-8")
    (tmp_path / "config.base.toml").write_text(_CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    app = FunctualizeApp(
        name="glab", job_sources=JobSources(directories=[str(jobs)], lazy=True)
    )
    adapter = CliAdapter()
    adapter(app)

    def run(args: list[str]):
        return CliRunner().invoke(adapter._cli_group, args, catch_exceptions=False)

    return run


class TestMidPathFlagsReachAnAppsOwnEntryPoint:
    def test_the_outer_groups_flag_is_accepted_mid_path(self, app_cli) -> None:
        result = app_cli(["deploy", "--env", "prod", "web", "run", "v1.2"])
        assert result.exit_code == 0, result.output
        assert "env=prod" in result.output

    def test_both_levels_in_one_invocation(self, app_cli) -> None:
        result = app_cli(
            ["deploy", "--env", "prod", "web", "--region", "eu-west-1", "run", "v1.2"]
        )
        assert result.exit_code == 0, result.output
        assert "env=prod" in result.output
        assert "region=eu-west-1" in result.output

    def test_a_bool_presence_flag_does_not_eat_the_next_segment(self, app_cli) -> None:
        """`--dry-run web` must not bind `web` as the flag's value."""
        result = app_cli(["deploy", "--dry-run", "web", "run", "v1"])
        assert result.exit_code == 0, result.output
        assert "image=v1" in result.output


class TestTheGroupsDefaultDoesNotOutrankItsConfigFile:
    """The trap in giving a group real click params.

    ``group_option_values`` is handed to the engine as the **CLI layer**, which
    outranks the group's config file. click fills every unsupplied option with
    its declared default, so depositing the whole kwargs dict would silently
    replace `[deploy] env = "from-file"` with `"staging"` — a regression with
    no error and no obviously guilty line. Only values click reports as coming
    from the command line are deposited.
    """

    def test_an_unsupplied_flag_leaves_the_file_winning(self, app_cli) -> None:
        result = app_cli(["deploy", "web", "run", "v1.2"])
        assert result.exit_code == 0, result.output
        assert "env=from-file" in result.output
        assert "region=region-from-file" in result.output

    def test_a_supplied_flag_still_beats_the_file(self, app_cli) -> None:
        result = app_cli(["deploy", "--env", "cli-wins", "web", "run", "v1.2"])
        assert result.exit_code == 0, result.output
        assert "env=cli-wins" in result.output


class TestARefusalIsStillARefusal:
    def test_a_deeper_groups_flag_is_refused_at_the_shallower_one(
        self, app_cli
    ) -> None:
        """`--region` belongs to `deploy.web`; `deploy` must not accept it."""
        result = app_cli(["deploy", "--region", "eu-west-1", "web", "run", "v1.2"])
        assert result.exit_code != 0
        assert "No such option" in result.output

    def test_an_undeclared_flag_is_refused(self, app_cli) -> None:
        result = app_cli(["deploy", "--nonsense", "x", "web", "run", "v1.2"])
        assert result.exit_code != 0
        assert "No such option" in result.output
