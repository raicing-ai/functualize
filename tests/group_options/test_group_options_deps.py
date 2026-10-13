"""A `Deps` upstream resolves the group-CLI layer the invocation typed.

`func demo --target b report`: the invoked job read ``target="b"`` while its
declared dependency resolved ``target`` from default/config/env — two values
in one run, silently, because the dependency's request was rebuilt without
the option map (``nested_request`` resets ``group_option_values`` and nothing
at the dependency seam said otherwise). ``--log-level DEBUG``'s
``Group options consumed mid-path`` line printed once, at the top, so the
debug output claimed one value while the run used two.

A dependency inherits the layer because it is part of *fulfilling* the
request that carried the flag — the engine schedules it before the
dependent's pre-flight, under the same command line. A workflow step and an
``rc.invoke`` child keep the documented boundary
(`docs/guides/group-options.md` → "Steering a whole run from code"); the
tests pinning that boundary are untouched by this feature and still hold.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import pytest

from functualize._app.state import AppState
from functualize._cli.main import _handle_group
from functualize.app.core import FunctualizeApp
from functualize.job import Deps, GroupOptions, Option, RunStatus, job
from functualize.types import RunRequest

if TYPE_CHECKING:
    from functualize._types import JobResult


class DemoOptions(GroupOptions, group="demo"):
    """The `demo` group's flags — the group the repro types at."""

    target: Annotated[str, Option("--target", help="Which target to build")] = "a"


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _app_with_deps(seen: list[tuple[str, str]]) -> FunctualizeApp:
    """``report → build → prepare``, every job reading the group's `target`.

    The chain is the repro's shape with one more hop than the report: the
    invoked job's direct dep (``build``) and that dep's own dep (``prepare``)
    are scheduled by the same run, so both must resolve the flag the
    invocation typed.
    """
    app = FunctualizeApp(name="deps-group-options")

    @job
    def prepare(opts: DemoOptions = None) -> str:
        seen.append(("prepare", opts.target))
        return "prepare"

    @job(deps=Deps("prepare"))
    def build(opts: DemoOptions = None) -> str:
        seen.append(("build", opts.target))
        return "build"

    @job(deps=Deps("build"))
    def report(opts: DemoOptions = None) -> str:
        seen.append(("report", opts.target))
        return "report"

    app.register_dynamic_job("prepare", prepare)
    app.register_dynamic_job("build", build)
    app.register_dynamic_job("report", report)
    return app


def _run(
    app: FunctualizeApp, job_name: str, *, group_options: dict[str, str] | None = None
) -> JobResult:
    """Through the engine with a group-CLI layer, as the dispatcher does.

    The mid-path walk lives in the CLI; the field it hands the engine is
    exactly this one, so this is the hop the report broke — minus the
    terminal. The CLI door itself is exercised further down.
    """
    return app._execution_engine.run(
        RunRequest(
            job_name=job_name,
            surface="app.execute",
            group_option_values=group_options,
        )
    )


class TestTheDependencyResolvesTheCliValue:
    """The repro: `func demo --target b report` — one run, one value."""

    def test_the_dependency_resolves_the_flag(self) -> None:
        seen: list[tuple[str, str]] = []
        result = _run(_app_with_deps(seen), "report", group_options={"target": "b"})

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        # The invoked job and its dependency agree. Before the fix these two
        # rows disagreed — `report` read b, `build` read a — and no output
        # said so.
        assert ("report", "b") in seen
        assert ("build", "b") in seen

    def test_every_depth_of_the_graph_resolves_it(self) -> None:
        """`build`'s own upstream is scheduled by the same run — the scheduler
        builds each node's request from the dependent's request, so depth is
        not a way back to the default."""
        seen: list[tuple[str, str]] = []
        result = _run(_app_with_deps(seen), "report", group_options={"target": "b"})

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        assert seen == [("prepare", "b"), ("build", "b"), ("report", "b")]


class TestPrecedenceIsUnchanged:
    """default < config file < vault < env < group-CLI — at the dependency too."""

    def test_the_flag_beats_the_environment_at_the_hop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEMO__TARGET", "fromenv")
        AppState.reset()

        seen: list[tuple[str, str]] = []
        result = _run(_app_with_deps(seen), "report", group_options={"target": "b"})

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        assert ("build", "b") in seen

    def test_no_flag_keeps_today_env_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run that typed no group flag changes nothing: the dependency
        resolves from its own env/file/default layers, exactly as before."""
        monkeypatch.setenv("DEMO__TARGET", "fromenv")
        AppState.reset()

        seen: list[tuple[str, str]] = []
        result = _run(_app_with_deps(seen), "report")

        assert result.status is RunStatus.SUCCESS, repr(result.exception)
        assert seen == [
            ("prepare", "fromenv"),
            ("build", "fromenv"),
            ("report", "fromenv"),
        ]


_GROUP_MODULE = """\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DemoOptions(GroupOptions, group="demo"):
    \"\"\"The demo group's flags.\"\"\"

    target: Annotated[str, Option("--target", help="Which target to build")] = "a"
"""

_DEMO_JOBS_MODULE = """\
from _group import DemoOptions

from functualize.job import Deps, job

JOB_GROUP = "demo"


@job
def prepare(opts: DemoOptions = None) -> None:
    print(f"prepare target={opts.target}")


@job(deps=Deps("demo.prepare"))
def build(opts: DemoOptions = None) -> None:
    print(f"build target={opts.target}")


@job(deps=Deps("demo.build"))
def report(opts: DemoOptions = None) -> None:
    print(f"report target={opts.target}")
"""


class TestTheReproThroughTheCliDoor:
    """`func demo --target b report` — boot, mid-path walk, dispatch, deps."""

    def test_the_mid_path_flag_reaches_the_dependency(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = []\n',
            encoding="utf-8",
        )
        (tmp_path / ".functualize.toml").write_text(
            'jobs_directories = ["jobs"]\n', encoding="utf-8"
        )
        (jobs / "_group.py").write_text(_GROUP_MODULE, encoding="utf-8")
        (jobs / "demo_jobs.py").write_text(_DEMO_JOBS_MODULE, encoding="utf-8")
        # The dispatcher reads the group-option specs from the discovery
        # cache, which is resolved from the process cwd — the same reason the
        # subprocess e2e suite runs with cwd=project.
        monkeypatch.chdir(tmp_path)

        with caplog.at_level("DEBUG", logger="functualize._cli.main"):
            exit_code = _handle_group(
                args=["demo", "--target", "b", "report"],
                anchor=tmp_path,
                merged_config={},
                effective={"jobs_directories": [str(jobs)], "import_libs": []},
                cli_flags={},
                group_names={"demo"},
            )

        captured = capsys.readouterr()
        assert exit_code == 0, captured.err
        assert "report target=b" in captured.out
        # The line the report broke: the dependency under the same command
        # line used to resolve the default while the invoked job read the
        # flag.
        assert "build target=b" in captured.out
        assert "prepare target=b" in captured.out
        assert "Group options consumed mid-path: {'target': 'b'}" in caplog.text
