"""Completion data extraction, and what it must never get wrong (T44a).

The extraction is the boot-once half of the direnv completion model: read the
app's descriptors and trie, produce partition-correct word lists, hand them to a
static shell script. The tests that matter are not "does it list `run`" — they
are the two ways a completion surface has historically leaked:

* the **injection point** (`opts: DeployOptions`) must not appear as a flag; it
  is settable nowhere, and every prior surface that leaked did so by mistaking
  it for a field;
* a **group option** (`--env`, declared on `deploy`) must appear on the leaf
  job that inherits it, because that is where a user types it — and its enum
  values must come with it, or `--env <TAB>` offers nothing.

Both are asserted against a fixture whose shape (group + group options + a job
with its own flags and an inherited enum) is the minimal reproduction of the
partition.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize._cli.completions.data import extract_completion_data
from functualize.app import FunctualizeApp
from functualize.app.utils import auto_discover

_DEPLOY = textwrap.dedent("""
    from enum import Enum
    from typing import Annotated
    from pydantic import BaseModel
    from functualize.job import job, GroupOptions, Option

    class Env(str, Enum):
        dev = "dev"
        prod = "prod"

    class DeployOptions(GroupOptions, group="deploy"):
        env: Annotated[Env, Option("-e")] = Env.dev
        dry_run: bool = False

    class RunConfig(BaseModel):
        image: str = "nginx"
        replicas: int = 1

    @job(group="deploy")
    def run(config: RunConfig, opts: DeployOptions = None):
        print(config.image)
""")


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jobs_dir = tmp_path / ".functualize" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "deploy.py").write_text(_DEPLOY)
    monkeypatch.chdir(tmp_path)
    AppState.reset()
    dr = auto_discover(tmp_path)
    app = FunctualizeApp(name="functualize", job_sources=dr.job_sources)
    result = extract_completion_data(app)
    AppState.reset()
    return result


class TestCommandStructure:
    def test_top_level_lists_groups_and_builtin(self, data) -> None:
        assert "deploy" in data.command_tree[""]
        assert "builtin" in data.command_tree[""]

    def test_a_group_lists_its_jobs(self, data) -> None:
        assert data.command_tree["deploy"] == ["run"]

    def test_builtin_lists_its_subcommands(self, data) -> None:
        assert "cache" in data.command_tree["builtin"]
        assert data.command_tree["builtin cache"] == [
            "show",
            "clear",
            "rebuild",
            "check",
        ]


class TestThePartition:
    def test_a_job_offers_its_own_flags(self, data) -> None:
        flags = data.command_tree["deploy run"]
        assert "--image" in flags
        assert "--replicas" in flags

    def test_a_job_offers_the_group_flags_it_inherits(self, data) -> None:
        """`--env` is declared on `deploy`, and `deploy run` inherits it — this
        is where the user types it."""
        flags = data.command_tree["deploy run"]
        assert "--env" in flags
        assert "-e" in flags
        assert "--dry-run" in flags

    def test_the_injection_point_is_never_a_flag(self, data) -> None:
        """`opts` is the parameter that *receives* the resolved group options;
        it is settable nowhere and must appear on no surface. Every prior
        completion leak was exactly this mistake."""
        flags = data.command_tree["deploy run"]
        assert "--opts" not in flags
        assert not any("opt" in f for f in flags)

    def test_an_enum_group_flag_carries_its_choices(self, data) -> None:
        assert data.flag_choices["deploy run"]["--env"] == ["dev", "prod"]


class TestNewJobsNeedNoCacheFile:
    def test_extraction_reflects_the_live_app_not_a_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A job added to the app is completable immediately — the data comes
        from the booted app's descriptors, not a written completion payload."""
        jobs_dir = tmp_path / ".functualize" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "solo.py").write_text("def solo():\n    print('hi')\n")
        monkeypatch.chdir(tmp_path)
        AppState.reset()
        dr = auto_discover(tmp_path)
        app = FunctualizeApp(name="functualize", job_sources=dr.job_sources)

        data = extract_completion_data(app)
        AppState.reset()

        assert "solo" in data.command_tree[""]
