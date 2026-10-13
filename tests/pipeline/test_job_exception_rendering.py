"""A job's own exception reaches the shell as one line, not a framework traceback.

A job that raised used to print the whole call stack — the console script,
`_cli/main.py`, click, the adapter, the executor — with the author's message as
the last of ~40 lines. Exit 1 was right; the output was a crash report for a
failure that was the job's to report.

**Driven through real processes, because nothing else can see it.** An
in-process runner hands back the exception object, not what the interpreter
prints, and `pitfalls.md` §25 records two earlier regressions of exactly this
shape that every in-process test passed. So each test here spawns the command
and reads its stderr.

Both doors (`func` and a project's own `main.py`), and the warm run as well as
the cold one: the warm run builds its command from the discovery cache and
imports the job module under a synthetic name, which is where the field report
saw `_functualize_sync_.<stem>_<id>.DemoError`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_JOB_RAISED = 1

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("demo", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = '''
class DemoError(Exception):
    """A domain error a job raises for an expected failure."""


def boom() -> None:
    """Raise a builtin exception."""
    raise RuntimeError("boom")


def err() -> None:
    """Raise the job's own exception class."""
    raise DemoError("bad input: row 3 has no id")
'''

#: What a framework frame looks like on stderr. A traceback names files, so
#: the absence of every one of these is the absence of the framework's stack.
_FRAMEWORK_MARKERS = (
    "Traceback",
    'File "',
    "click/",
    "functualize/app/adapters/",
    "functualize/_cli/",
    "functualize/_engine/",
    "_functualize_sync_",
)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    # `jobs_directories` is what makes `func` and `main.py` see the same jobs.
    (root / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (root / "main.py").write_text(_MAIN)
    (root / "jobs").mkdir()
    (root / "jobs" / "demo.py").write_text(_JOBS)
    return root


def _env(tmp_path: Path) -> dict[str, str]:
    """`HOME` and every XDG root inside the test (AGENTS.md, *Writing tests*).

    `func` writes an append-only install registry under the user's data
    directory, and the suite's autouse fake home is shared by every checkout.
    """
    home = tmp_path / "home"
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        XDG_STATE_HOME=str(home / ".local" / "state"),
    )
    return env


def _run(
    root: Path, env: dict[str, str], surface: str, *args: str
) -> subprocess.CompletedProcess[str]:
    """Run through the installed `func` console script or the project's `main.py`."""
    argv = (
        [str(Path(sys.executable).with_name("func")), *args]
        if surface == "func"
        else [sys.executable, "main.py", *args]
    )
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=str(root), env=env, timeout=120
    )


def _error_lines(stderr: str) -> list[str]:
    """The `Error:` lines — unrelated warnings (a slow plugin import) may surround them."""
    return [line for line in stderr.splitlines() if line.startswith("Error:")]


def _assert_no_framework_frames(stderr: str) -> None:
    for marker in _FRAMEWORK_MARKERS:
        assert marker not in stderr, f"{marker!r} reached stderr:\n{stderr}"


SURFACES = ["func", "app"]


@pytest.mark.parametrize("surface", SURFACES)
def test_a_raising_job_prints_one_line_and_no_frames(
    surface: str, tmp_path: Path
) -> None:
    """The defect as reported: `func boom` with `raise RuntimeError("boom")`."""
    root, env = _project(tmp_path), _env(tmp_path)

    result = _run(root, env, surface, "boom")

    assert result.returncode == _JOB_RAISED, result.stderr
    assert _error_lines(result.stderr) == ["Error: RuntimeError: boom"], result.stderr
    _assert_no_framework_frames(result.stderr)
    assert result.stdout == ""


@pytest.mark.parametrize("surface", SURFACES)
def test_the_warm_run_renders_the_same_line(surface: str, tmp_path: Path) -> None:
    """Cold and warm are different programs; they must say the same thing.

    The job's own exception class is used because the warm run imports the
    module under a synthetic name — the line must name the class, not that.
    """
    root, env = _project(tmp_path), _env(tmp_path)

    cold = _run(root, env, surface, "err")
    warm = _run(root, env, surface, "err")

    expected = ["Error: DemoError: bad input: row 3 has no id"]
    for run in (cold, warm):
        assert run.returncode == _JOB_RAISED, run.stderr
        assert _error_lines(run.stderr) == expected, run.stderr
        _assert_no_framework_frames(run.stderr)


@pytest.mark.parametrize("surface", SURFACES)
def test_log_level_debug_brings_the_traceback_back(
    surface: str, tmp_path: Path
) -> None:
    """The explicit opt-in: the full stack, down to the job's own frame."""
    root, env = _project(tmp_path), _env(tmp_path)

    result = _run(root, env, surface, "--log-level", "DEBUG", "boom")

    assert result.returncode == _JOB_RAISED, result.stderr
    assert "Traceback (most recent call last):" in result.stderr
    assert 'raise RuntimeError("boom")' in result.stderr
    assert "RuntimeError: boom" in result.stderr


@pytest.mark.parametrize("surface", SURFACES)
def test_emit_format_json_carries_the_same_line(surface: str, tmp_path: Path) -> None:
    """`--emit-format` governs stdout only; a failure adds nothing there."""
    root, env = _project(tmp_path), _env(tmp_path)

    result = _run(root, env, surface, "--emit-format", "json", "boom")

    assert result.returncode == _JOB_RAISED, result.stderr
    assert _error_lines(result.stderr) == ["Error: RuntimeError: boom"], result.stderr
    _assert_no_framework_frames(result.stderr)
    assert result.stdout == ""
