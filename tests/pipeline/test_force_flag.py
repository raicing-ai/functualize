"""`--force` runs a job that is up to date (D-5).

There was no way to say "run anyway". The only workarounds were touching a
source file or deleting a state directory whose location was reported nowhere —
and in standalone mode that is a hashed directory under `$XDG_CACHE_HOME`. Make
has `-B`, Taskfile has `-f`.

**What it does not override is the point of these tests.** `--force` says "run
anyway"; it does not say "the world is fine". A failing `Precondition` still
refuses (exit 3) and a gate still blocks (exit 5), because those report that the
declared conditions for running were not met, and a flag cannot change what is
true about the world. Getting that boundary wrong would turn a deliberate
refusal into a false clean — the exact class this branch exists to close.

Both surfaces, because there are two CLIs and only one of them had the flag
plumbing to copy from.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("f", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from pathlib import Path

from functualize.job import Fingerprint, Guards, Precondition, job

JOB_GROUP = "f"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["src/*.py"]))
def cached() -> None:
    print("RAN cached")


@job(group=JOB_GROUP, guards=Guards(status=[lambda: Path("done.flag").exists()]))
def guarded() -> None:
    print("RAN guarded")
    Path("done.flag").write_text("done\\n")


@job(
    group=JOB_GROUP,
    guards=Guards(preconditions=[Precondition("test -f missing.txt", msg="no world")]),
)
def gated() -> None:
    print("RAN gated")
"""


def _project(tmp_path: Path) -> Path:
    # `jobs_directories` in `.functualize.toml` is what makes the bare `func`
    # CLI and the app's own entry point see the same jobs. Without it `func`
    # walks for `.functualize/jobs` and answers `Unknown command 'f'`, so a
    # "both surfaces" test would quietly be a one-surface test.
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "f"\n')
    (tmp_path / ".functualize").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print(1)\n")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "f.py").write_text(_JOBS)
    return tmp_path


def _run(project: Path, surface: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke through `func` or through the app's own entry point."""
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
def test_force_reruns_a_job_that_is_up_to_date(surface: str, tmp_path: Path) -> None:
    """Cold, warm, then forced — the third run is the one under test."""
    project = _project(tmp_path)

    first = _run(project, surface, "f", "cached")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "RAN cached" in first.stdout

    second = _run(project, surface, "f", "cached")
    assert "RAN cached" not in second.stdout, "expected the second run to be fresh"

    forced = _run(project, surface, "--force", "f", "cached")
    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert "RAN cached" in forced.stdout, forced.stdout + forced.stderr


@pytest.mark.parametrize("surface", SURFACES)
def test_force_overrides_a_satisfied_status_guard(surface: str, tmp_path: Path) -> None:
    """A `status` guard says "already done"; `--force` says "do it anyway".

    Taskfile's `-f` skips `status:` for the same reason. This is the one place
    `--force` is deliberately wider than the engine's existing `force_fresh`,
    which is produced by the workflow walker for a `FromJob` dependent and
    stays narrow on purpose.
    """
    project = _project(tmp_path)

    assert "RAN guarded" in _run(project, surface, "f", "guarded").stdout
    assert "RAN guarded" not in _run(project, surface, "f", "guarded").stdout

    forced = _run(project, surface, "--force", "f", "guarded")
    assert "RAN guarded" in forced.stdout, forced.stdout + forced.stderr


@pytest.mark.parametrize("surface", SURFACES)
def test_force_does_not_override_a_failing_precondition(
    surface: str, tmp_path: Path
) -> None:
    """Still exit 3, forced or not.

    A refusal says the declared conditions for running were not met. `--force`
    is a statement about *wanting* the work done, not about the world, and
    letting it through here would let a stage run — and report success — in an
    environment its own declaration says it must not run in.
    """
    project = _project(tmp_path)

    plain = _run(project, surface, "f", "gated")
    assert plain.returncode == 3, plain.stdout + plain.stderr

    forced = _run(project, surface, "--force", "f", "gated")
    assert forced.returncode == 3, forced.stdout + forced.stderr
    assert "RAN gated" not in forced.stdout
