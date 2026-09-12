"""A declared notification fires once across a real crash.

`workflow-graph-semantics`/T6. Spec AC-13. Decision **N8**.

**A real `kill -9`, for `test_crash_and_resume`'s reason.** A unit test can fake
crash-and-resume by walking the same scope twice, and such a test passes whether
or not the mark and the delivery are ordered — it never exercises the window
where a process dies between two writes.
`tests/workflow/test_notify.py::TestItFiresAtMostOnce` holds the half that can be
unit-tested; this file holds the half that cannot.

The evidence is a **file the notifier appends to**. Its line count is how many
times somebody was told, which no amount of record-keeping can fake: the first
runner is killed with the notification already sent, and the resumed walk
re-reaches the same blocked state and must stay quiet.

The asymmetry is deliberate and runs this way round. The mark is committed
*before* the provider is called, so a crash inside the delivery loses a
notification rather than repeating it — a resumed workflow must not page the
on-call again for a failure they have already seen.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


#: A workflow that blocks at a gate, with a notifier that tells the parent it
#: has delivered and then waits to be killed.
#:
#: Blocking rather than failing, because a blocked scope is the one a resume
#: genuinely re-enters: the second runner replays to the same gate, reaches the
#: same `blocked` status, and is therefore in exactly the position to send the
#: notification a second time.
_WORKFLOW = """
import sys, time
from pathlib import Path

from pydantic import BaseModel

from functualize._engine.notify import NotifierRegistry
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.scope_store import ScopeStore
from functualize._types.workflow import (
    END, Edge, Gate, Notify, Step, WorkflowDeclaration,
)

MARKER = Path(sys.argv[1])
HANG = Path(sys.argv[2])
WAIT = sys.argv[3] == "yes"


class Ask(BaseModel):
    text: str


class FileNotifier:
    name = "file"

    def deliver(self, notification):
        with Path(notification.to).open("a") as fh:
            fh.write(f"{notification.status}\\n")
        if WAIT:
            # Announce that somebody has been told, then wait to be killed. The
            # parent kills on seeing this, so the crash lands *after* the
            # delivery and after the record that it happened.
            HANG.write_text("ready")
            time.sleep(60)


declaration = WorkflowDeclaration(
    nodes=(Step("work"), Gate(name="approval", awaits=Ask)),
    edges=(Edge(source="work", target="approval"), Edge(source="approval", target=END)),
    notify=(Notify(on="blocked", to=str(MARKER), provider="file"),),
)

registry = NotifierRegistry()
registry.register(FileNotifier())

store = ScopeStore.for_project(Path.cwd())
WorkflowWalker(
    declaration, store, "notify-scope", run_step=lambda name: name,
    workflow_name="flow", notifiers=registry,
).run()
"""


def _write_runner(project: Path) -> Path:
    (project / ".functualize").mkdir(parents=True, exist_ok=True)
    runner = project / "runner.py"
    runner.write_text(textwrap.dedent(_WORKFLOW))
    return runner


def _spawn(runner: Path, marker: Path, hang: Path, *, wait: bool) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(runner), str(marker), str(hang), "yes" if wait else "no"],
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
    """SIGKILL. Not `terminate()` — a handler could still flush on SIGTERM."""
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def _expire_the_dead_runners_lease(project: Path) -> None:
    """Fast-forward past the crashed runner's lease. **Only the clock is faked.**

    The crash stays a real SIGKILL. What is simulated is the *waiting*: a killed
    runner's lease is live for its full duration because nothing can tell
    "crashed" from "slow", and waiting 300 s in a test is absurd. The expiry
    path itself is covered by `tests/workflow/test_abandoned_and_reclaim.py`.
    """
    from datetime import UTC, datetime, timedelta

    from functualize._primitives.scope_store import ScopeStore

    store = ScopeStore.for_project(project)
    scope = store.get_scope("notify-scope")
    assert scope and scope.get("lease"), "the crashed runner left no lease"
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    lease = {**scope["lease"], "expires_at": past}
    store._mutate(  # noqa: SLF001
        lambda env: env["scopes"]["notify-scope"].__setitem__("lease", lease)
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "proj"


class TestANotificationSurvivesACrashWithoutRepeating:
    def test_it_is_not_sent_again_after_a_kill_and_a_resume(
        self, project: Path
    ) -> None:
        """AC-13, through a real SIGKILL.

        The first runner blocks at the gate, notifies, and hangs inside the
        notifier. It is killed with no chance to clean up. A second runner
        replays to the same gate, reaches the same `blocked` status — and must
        stay quiet, because the record committed before the first delivery says
        somebody has already been told.
        """
        runner = _write_runner(project)
        marker, hang = project / "notified.log", project / "ready"

        first = _spawn(runner, marker, hang, wait=True)
        assert _wait_for(hang), "the first runner never delivered the notification"
        _kill_hard(first)

        assert marker.read_text().count("blocked") == 1, "setup: notified once"

        from functualize._primitives.scope_store import ScopeStore
        from functualize.app._workflow_control import reclaim_scope

        _expire_the_dead_runners_lease(project)
        store = ScopeStore.for_project(project)
        assert reclaim_scope(store, "notify-scope")["status"] == "reclaimed"

        second = _spawn(runner, marker, hang, wait=False)
        out, err = second.communicate(timeout=60)
        assert second.returncode == 0, (
            f"the resumed runner failed\nstdout: {out.decode()[-2000:]}\n"
            f"stderr: {err.decode()[-2000:]}"
        )

        assert marker.read_text().count("blocked") == 1, (
            "the notification was sent twice across the crash — the record that "
            "it fired did not stop the resume from repeating it"
        )

    def test_the_resumed_walk_really_reached_the_same_state(
        self, project: Path
    ) -> None:
        """The guard on the test above.

        "Notified once" would also be true of a second runner that crashed on
        startup, or blocked somewhere else, or never ran the gate at all — so
        silence is only evidence when the walk was in a position to speak.
        """
        runner = _write_runner(project)
        marker, hang = project / "notified.log", project / "ready"

        first = _spawn(runner, marker, hang, wait=True)
        assert _wait_for(hang)
        _kill_hard(first)

        from functualize._primitives.scope_store import ScopeStore
        from functualize.app._workflow_control import reclaim_scope

        _expire_the_dead_runners_lease(project)
        reclaim_scope(ScopeStore.for_project(project), "notify-scope")

        second = _spawn(runner, marker, hang, wait=False)
        second.communicate(timeout=60)

        scope = ScopeStore.for_project(project).get_scope("notify-scope")
        assert scope is not None
        assert scope["status"] == "blocked"
        assert scope["position"] == "approval"

    def test_a_fresh_scope_is_notified(self, project: Path) -> None:
        """The other guard: the mechanism must be able to say anything at all.

        Without this, a notifier that never fired would pass every assertion
        above — which is the shape of a test that cannot fail.
        """
        runner = _write_runner(project)
        marker, hang = project / "notified.log", project / "ready"

        proc = _spawn(runner, marker, hang, wait=False)
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err.decode()[-2000:]

        assert marker.read_text().count("blocked") == 1
