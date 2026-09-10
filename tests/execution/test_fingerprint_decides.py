"""``Fingerprint(decides=True)`` moves the skip decision from the engine to the job.

The assertion that matters most is the default, and it is the first test here:
a job that declares nothing new must behave *exactly* as it did — same status,
same exit code, same history entry. A new declaration field is the easiest way
to change a behaviour nobody asked to change.

Everything else runs a real job through the public entry point twice, so "the
body ran" and "the framework skipped" are observed facts rather than a claim
about an ``if``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp, request_for
from functualize.app.utils import StateStore
from functualize.job import (
    Fingerprint,
    Freshness,
    FreshnessVerdict,
    Guards,
    Precondition,
    RunStatus,
    job,
)
from functualize.types import ExitCode, RunRequest, exit_code_for_status
from functualize.workflow import END, Edge, Gate, Step, workflow

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _app(**jobs: object) -> FunctualizeApp:
    app = FunctualizeApp(name="decides")
    for name, fn in jobs.items():
        app.register_dynamic_job(name, fn)
    return app


def _history() -> list[dict[str, object]]:
    """This project's run ring, newest first."""
    return list(reversed(StateStore.for_project(Path.cwd()).get_history()))


def test_a_job_that_does_not_opt_in_is_still_skipped() -> None:
    """AC-3 — the default is untouched, down to the history entry.

    Written before the engine change, so it is a regression gate rather than a
    description of what the new code happens to do.
    """
    Path("input.txt").write_text("v1")
    ran: list[str] = []

    @job(cache=Fingerprint(sources=["input.txt"]))
    def build() -> str:
        ran.append("build")
        return "built"

    app = _app(build=build)
    first = app.execute(request_for("build"))
    second = app.execute(request_for("build"))

    assert first.status is RunStatus.SUCCESS, first.exception
    assert second.status is RunStatus.SKIPPED
    assert ran == ["build"], "the job re-ran despite unchanged inputs"
    # A skipped run still has an answer: it is the recorded value.
    assert second.return_value == "built"
    assert second.metadata["skip_reason"]
    assert exit_code_for_status(second.status) == ExitCode.OK, "a skip exits 0"
    assert [r["status"] for r in _history()] == ["success", "skipped"]


def test_an_opted_in_job_enters_its_body_and_reads_the_fresh_verdict() -> None:
    """AC-4 — the declaration is what enters the body, and the body can read why."""
    Path("input.txt").write_text("v1")
    seen: list[FreshnessVerdict | None] = []

    @job(cache=Fingerprint(sources=["input.txt"], decides=True))
    def build(fresh: Freshness) -> str:
        seen.append(fresh.verdict())
        return "reused"

    app = _app(build=build)
    app.execute(request_for("build"))
    seen.clear()

    second = app.execute(request_for("build"))

    assert second.status is RunStatus.SUCCESS, second.exception
    assert len(seen) == 1, "the body was not entered — decides did not reach the engine"
    verdict = seen[0]
    assert verdict is not None, "the verdict never arrived"
    assert verdict.is_fresh is True
    assert second.return_value == "reused"


def test_an_opted_in_run_is_recorded_as_having_run() -> None:
    """§3.3 — "the framework skipped me" and "I ran and did nothing" stay apart.

    A job that opts in and then declines to rebuild still *ran*: it read the
    verdict, it decided. Recording that as SKIPPED would make CI unable to tell
    the two, and would make an opted-in job indistinguishable from one that
    never had the option.
    """
    Path("input.txt").write_text("v1")

    @job(cache=Fingerprint(sources=["input.txt"], decides=True))
    def build() -> str:
        return "reused"

    app = _app(build=build)
    app.execute(request_for("build"))
    second = app.execute(request_for("build"))

    assert second.status is RunStatus.SUCCESS
    assert [r["status"] for r in _history()] == ["success", "success"]


def test_opting_in_does_not_bypass_a_failing_precondition() -> None:
    """AC-5 — ``decides`` affects SKIP_FRESH and nothing else.

    A failing precondition says the declared conditions for running this job
    were not met. Wanting to decide its own freshness is not a reason to run it
    somewhere its author told us it does not belong — the same boundary
    ``force_fresh`` respects (exit 3, not a body).
    """
    ran: list[str] = []

    @job(
        cache=Fingerprint(sources=["input.txt"], decides=True),
        guards=Guards(preconditions=[Precondition("exit 1", "not here yet")]),
    )
    def build() -> None:
        ran.append("build")

    result = _app(build=build).execute(request_for("build"))

    assert result.status is RunStatus.REFUSED
    assert exit_code_for_status(result.status) == ExitCode.REFUSED
    assert ran == [], "a refused job must not enter its body"


def test_opting_in_does_not_bypass_a_satisfied_status_guard() -> None:
    """AC-5 — SKIP_SATISFIED is a different claim, and is not overridden.

    A satisfied ``status`` guard is the author's own external "already done"
    check. ``decides`` speaks only for the freshness verdict, so a job whose
    verdict is SKIP_SATISFIED is skipped exactly as it was before.
    """
    Path("input.txt").write_text("v1")
    ran: list[str] = []

    @job(
        cache=Fingerprint(sources=["input.txt"], decides=True),
        guards=Guards(status=["test -f done.marker"]),
    )
    def build() -> None:
        ran.append("build")

    app = _app(build=build)
    app.execute(request_for("build"))
    ran.clear()
    Path("done.marker").write_text("")

    second = app.execute(request_for("build"))

    assert second.status is RunStatus.SKIPPED
    assert second.metadata["skip_reason"]
    assert ran == [], "a satisfied status guard must still refuse the body"


def test_opting_in_does_not_bypass_a_blocking_gate() -> None:
    """AC-5 — a gate awaiting input still blocks (exit 5, not a body).

    The walk stops before the body is reached at all, so `decides` has no
    standing here: a paused run is resumable, and running the epilogue early
    would spend the approval it is waiting for.
    """

    class Approval(BaseModel):
        approved: bool

    ran: list[str] = []

    @job
    def seed() -> str:
        return "seeded"

    @workflow(
        steps=[Step("seed"), Gate(name="approve", awaits=Approval)],
        edges=[Edge("seed", "approve"), Edge("approve", END)],
    )
    @job(cache=Fingerprint(sources=["input.txt"], decides=True))
    def release() -> str:
        ran.append("release")
        return "shipped"

    app = _app(seed=seed, release=release)
    result = app.execute(
        RunRequest(
            job_name="release",
            surface="app.execute",
            workflow_scope_id="decides-gate",
        )
    )

    assert result.status is RunStatus.BLOCKED
    assert exit_code_for_status(result.status) == ExitCode.BLOCKED
    assert ran == [], "a blocked gate must not run the body it is waiting for"


# --- The warm boot, in its own process --------------------------------------

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("d", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from functualize.job import Fingerprint, Freshness, job

JOB_GROUP = "d"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["input.txt"], decides=True))
def build(fresh: Freshness) -> None:
    verdict = fresh.verdict()
    print(f"BODY FRESH {None if verdict is None else verdict.is_fresh}")
"""


def test_the_declaration_survives_a_warm_boot(tmp_path: Path) -> None:
    """The second invocation builds its declaration from the discovery cache.

    On a cold boot `decides` is read off the live function; on every later one
    it is read off the serialized declaration. A field that does not
    round-trip is invisible on the first run and silently reverts to the
    default afterwards — the job would build once and then skip forever, which
    is exactly the cold/warm divergence class this repository has paid for
    before.
    """
    project = tmp_path / "warm"
    (project / ".functualize").mkdir(parents=True)
    (project / "input.txt").write_text("v1")
    (project / "main.py").write_text(_MAIN)
    (project / "config.base.toml").write_text('[general]\napp_name = "d"\n')
    jobs = project / "jobs"
    jobs.mkdir()
    (jobs / "d.py").write_text(_JOBS)

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(PROJECT_ROOT),
                "python",
                "main.py",
                "d",
                "build",
            ],
            capture_output=True,
            text=True,
            cwd=str(project),
            timeout=120,
        )

    cold = run()
    assert cold.returncode == 0, cold.stderr
    assert "BODY FRESH False" in cold.stdout, "setup: a cold boot runs the body"

    from functualize._primitives.cache_format import resolve_cache_path

    assert resolve_cache_path(project).exists(), "setup: the cold boot wrote a cache"

    warm = run()
    assert warm.returncode == 0, warm.stderr
    assert "BODY FRESH True" in warm.stdout, (
        "the warm boot skipped the body — `decides` did not survive the cache"
    )
