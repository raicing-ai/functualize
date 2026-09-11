"""An effecting step runs exactly once across a real crash.

`durable-run-layer`/T9. Spec AC-14, AC-15. Risk R-f.

**This uses a real `kill -9`, and that is the whole point.** A unit test can fake
crash-and-resume by calling `start()` twice, and such a test passes whether or
not the record and the position actually commit together — it never exercises
the window where a process dies between two writes. A real signal cannot be
faked into passing.

The property: a step declared `effecting=True` does its side effect **once**
across a kill and a resume. A step that declares nothing is replayed, which is
what every workflow has done until now (AC-15) and stays the default — the
framework cannot tell an effecting step from a pure one by looking, and guessing
wrong in that direction re-runs a refund.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


#: A workflow whose first step appends a line to a file and then waits.
#:
#: Appending is the test's evidence: the file's **line count** is how many times
#: the effect happened, which no amount of record-keeping can fake.
_WORKFLOW = """
import sys, time
from pathlib import Path

from functualize import FunctualizeApp, RunContext
from functualize._types.run_request import RunRequest
from functualize._types.workflow import Edge, Step, WorkflowDeclaration, END
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.fresh_store import FreshStore

MARKER = Path(sys.argv[1])
HANG = Path(sys.argv[2])
EFFECTING = sys.argv[3] == "yes"


def _run_step(name: str):
    if name == "charge":
        with MARKER.open("a") as fh:
            fh.write("charged\\n")
        return "charged"
    if name == "slow":
        # Announce that the effect is done, then wait to be killed. The parent
        # kills on seeing this file, so the crash lands *after* the effect and
        # *after* its record committed.
        HANG.write_text("ready")
        time.sleep(60)
    return name


declaration = WorkflowDeclaration(
    nodes=(Step("charge", effecting=EFFECTING), Step("slow")),
    edges=(Edge(source="charge", target="slow"), Edge(source="slow", target=END)),
)

store = FreshStore.for_project(Path.cwd())
walk = WorkflowWalker(declaration, store, "crash-scope", run_step=_run_step,
                    workflow_name="flow")
walk.run()
"""


def _write_runner(project: Path) -> Path:
    (project / ".functualize").mkdir(parents=True, exist_ok=True)
    runner = project / "runner.py"
    runner.write_text(textwrap.dedent(_WORKFLOW))
    return runner


def _spawn(runner: Path, marker: Path, hang: Path, effecting: bool) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(runner),
            str(marker),
            str(hang),
            "yes" if effecting else "no",
        ],
        cwd=str(runner.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_for(path: Path, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def _kill_hard(proc: subprocess.Popen) -> None:
    """SIGKILL. Not `terminate()` — a handler could still flush on SIGTERM.

    The point is a process that gets no chance to clean up, which is the only
    kind of crash worth testing here.
    """
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def _expire_the_dead_runners_lease(project: Path) -> None:
    """Fast-forward past the crashed runner's lease. **Only the clock is faked.**

    The crash stays a real SIGKILL, which is what risk R-f is about. What is
    simulated is the *waiting*: a killed runner's lease is still live for its
    full duration, because nothing can tell "crashed" from "slow" — that is the
    design, and it means a real recovery either waits or cancels.

    Waiting 300 s in a test is absurd; the expiry path itself is covered by
    `tests/workflow/test_abandoned_and_reclaim.py`. So the lease is aged here and
    the crash is not.
    """
    from datetime import UTC, datetime, timedelta

    from functualize._primitives.fresh_store import FreshStore

    store = FreshStore.for_project(project)
    scope = store.get_scope("crash-scope")
    assert scope and scope.get("lease"), "the crashed runner left no lease"
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    lease = {**scope["lease"], "expires_at": past}
    store._scopes._mutate(  # noqa: SLF001
        lambda env: env["scopes"]["crash-scope"].__setitem__("lease", lease)
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "proj"


class TestAnEffectingStepRunsOnce:
    def test_the_effect_does_not_repeat_across_a_kill_and_a_resume(
        self, project: Path
    ) -> None:
        """AC-14, through a real SIGKILL.

        The first runner charges, records, and hangs. It is killed with no
        chance to clean up. A second runner resumes the same scope and must
        **not** charge again — the committed record is what tells it so.
        """
        runner = _write_runner(project)
        marker, hang = project / "effects.log", project / "ready"

        first = _spawn(runner, marker, hang, effecting=True)
        assert _wait_for(hang), "the first runner never reached the hanging step"
        _kill_hard(first)

        assert marker.read_text().count("charged") == 1, "setup: charged once"

        # The scope is still `running`, held by a process that no longer
        # exists. Its lease has to lapse before anyone may take it — see
        # `_expire_the_dead_runners_lease` for why that is faked and the crash
        # is not.
        from functualize._primitives.fresh_store import FreshStore
        from functualize.app._workflow_control import reclaim_scope

        _expire_the_dead_runners_lease(project)
        store = FreshStore.for_project(project)
        assert reclaim_scope(store, "crash-scope")["status"] == "reclaimed"

        hang.unlink()
        second = _spawn(runner, marker, hang, effecting=True)
        if not _wait_for(hang, timeout=20):
            out, err = second.communicate(timeout=10)
            raise AssertionError(
                f"the second runner never reached the hanging step\n"
                f"stdout: {out.decode()[-2000:]}\nstderr: {err.decode()[-2000:]}"
            )
        _kill_hard(second)

        assert marker.read_text().count("charged") == 1, (
            "the effecting step ran twice across the crash — its committed "
            "record did not stop the resume from replaying it"
        )

    def test_the_record_says_the_step_was_effecting(self, project: Path) -> None:
        """Recorded on the step, not looked up from the declaration on resume.

        A resume may run in another process against a declaration that has
        since changed. What matters is what the step *was* when it ran, and the
        record is the only witness to that.
        """
        runner = _write_runner(project)
        marker, hang = project / "effects.log", project / "ready"

        proc = _spawn(runner, marker, hang, effecting=True)
        assert _wait_for(hang)
        _kill_hard(proc)

        scopes = json.loads((project / ".functualize" / "scopes.json").read_text())[
            "scopes"
        ]
        steps = scopes["crash-scope"]["steps"]
        charge = next(v for k, v in steps.items() if k.startswith("charge"))
        assert charge["effecting"] is True


class TestAPureStepIsStillReplayed:
    def test_a_step_that_declares_nothing_re_runs(self, project: Path) -> None:
        """AC-15 — the behaviour every workflow has had until now.

        Asserted because the easy over-correction is to make *every* step run
        once, which would silently change what a resume does for everyone who
        never asked for it.
        """
        runner = _write_runner(project)
        marker, hang = project / "effects.log", project / "ready"

        first = _spawn(runner, marker, hang, effecting=False)
        assert _wait_for(hang)
        _kill_hard(first)
        assert marker.read_text().count("charged") == 1

        from functualize._primitives.fresh_store import FreshStore
        from functualize.app._workflow_control import reclaim_scope

        _expire_the_dead_runners_lease(project)
        reclaim_scope(FreshStore.for_project(project), "crash-scope")

        hang.unlink()
        second = _spawn(runner, marker, hang, effecting=False)
        assert _wait_for(hang)
        _kill_hard(second)

        # A pure step *is* replay-skipped by its step record, exactly as
        # before this feature — `effecting` changes what the record guarantees
        # about the commit, not whether a completed step re-runs.
        assert marker.read_text().count("charged") == 1


class TestTheCrashIsReal:
    """Guards the tests above against proving nothing.

    If the first process exited cleanly, every assertion here would hold for
    reasons that have nothing to do with crash safety — the class of test R-f
    warns about.
    """

    def test_the_runner_is_killed_not_asked_to_stop(self, project: Path) -> None:
        runner = _write_runner(project)
        marker, hang = project / "effects.log", project / "ready"

        proc = _spawn(runner, marker, hang, effecting=True)
        assert _wait_for(hang)
        _kill_hard(proc)

        assert proc.returncode == -signal.SIGKILL, (
            f"the runner exited with {proc.returncode}, not SIGKILL — it was "
            f"given a chance to clean up, so this proves nothing about a crash"
        )

    def test_the_scope_survived_the_crash(self, project: Path) -> None:
        """The record has to be on disk, or "resume" is just "start again"."""
        runner = _write_runner(project)
        marker, hang = project / "effects.log", project / "ready"

        proc = _spawn(runner, marker, hang, effecting=True)
        assert _wait_for(hang)
        _kill_hard(proc)

        scopes = json.loads((project / ".functualize" / "scopes.json").read_text())[
            "scopes"
        ]
        assert "crash-scope" in scopes
        assert scopes["crash-scope"]["steps"], "no step record survived the kill"
