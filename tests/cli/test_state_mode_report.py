"""The state store says where it is, and which of the two modes that is (D-5).

`resolve_state_path` has always done the right thing: walk upward for a
`.functualize/` directory and put `state.json` inside it when one exists,
falling back to `$XDG_CACHE_HOME/functualize/<project-id>/` only in standalone
mode. That is the correct design and the reason is good — `func` is meant to run
over loose scripts anywhere on the filesystem, and littering a `.functualize/`
beside every one of them would be worse than a keyed cache directory.

**What was missing is that nothing said which mode you were in, or that
`mkdir .functualize` is the switch.** The audit that found this is the
cautionary example: its own `demo.sh` imports `_primitives.locator` and deletes
a hashed directory by hand to get a cold run, because the unit had no
`.functualize/` and nothing told it so.

The store does not move. This is reporting, plus documentation in
`docs/guides/task-runner.md` beside `Fingerprint`, where somebody reasoning
about freshness will look.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("m", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from functualize.job import job

JOB_GROUP = "m"


@job(group=JOB_GROUP)
def noop() -> None:
    print("RAN noop")
"""


def _project(tmp_path: Path, *, declared: bool) -> Path:
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "m"\n')
    if declared:
        (tmp_path / ".functualize").mkdir()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "m.py").write_text(_JOBS)
    return tmp_path


def _run(project: Path, surface: str, *args: str) -> subprocess.CompletedProcess[str]:
    argv = (
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args]
        if surface == "func"
        else ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args]
    )
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=str(project), timeout=120
    )


SURFACES = ["func", "app"]


@pytest.mark.parametrize("surface", SURFACES)
def test_a_declared_project_reports_project_mode(surface: str, tmp_path: Path) -> None:
    project = _project(tmp_path, declared=True)

    out = _run(project, surface, "builtin", "state", "show").stdout

    assert "Mode:" in out, out
    assert "project" in out, out
    # It names the directory that decided it, so "why is it there?" is answered
    # in the same line as "where is it?".
    assert ".functualize/ found at" in out, out
    assert str(project / ".functualize" / "state.json") in out, out


@pytest.mark.parametrize("surface", SURFACES)
def test_an_undeclared_project_reports_standalone_and_names_the_switch(
    surface: str, tmp_path: Path
) -> None:
    """Standalone is the fallback, not the failure — and it says how to leave.

    Reporting the mode without naming the switch would leave the reader exactly
    where the audit was: knowing the file is somewhere else, not knowing that
    one `mkdir` moves it.
    """
    project = _project(tmp_path, declared=False)

    out = _run(project, surface, "builtin", "state", "show").stdout

    assert "standalone" in out, out
    assert "create one to keep state in the project" in out, out
    assert str(project / ".functualize" / "state.json") not in out, out


@pytest.mark.parametrize("surface", SURFACES)
def test_builtin_info_reports_the_same_two_facts(surface: str, tmp_path: Path) -> None:
    """`builtin info` is where someone looks first, so it must not disagree."""
    project = _project(tmp_path, declared=True)

    out = _run(project, surface, "builtin", "info").stdout

    assert "Runtime State" in out, out
    assert "State path:" in out, out
    assert "project (.functualize/ found at" in out, out


def test_the_reported_path_is_the_one_the_engine_writes(tmp_path: Path) -> None:
    """Reporting a path the run does not use would be worse than silence.

    Both come from `resolve_state_location`, which is now the single upward
    walk — `resolve_state_path` is a thin wrapper on it. Two walks can disagree;
    one cannot.
    """
    project = _project(tmp_path, declared=True)

    assert "RAN noop" in _run(project, "app", "m", "noop").stdout
    reported = [
        line.split("State path:", 1)[1].strip()
        for line in _run(project, "app", "builtin", "state", "show").stdout.splitlines()
        if "State path:" in line
    ]

    assert reported, "no State path line"
    assert Path(reported[0]).exists(), reported[0]
