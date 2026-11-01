"""Pilot tests for the R1 thread-worker migration of job_execution.py.

Exercises the REAL ``run_job``/``execute_job_async`` code path (not the
toy ``HeartbeatApp``) through a real ``FunctualizeInlineTUI`` instance,
per the TUI audit rules.

Technique: mirrors ``tests/tui_audit/test_blocking_worker.py``'s
``HeartbeatApp`` approach — instead of a timer callback, we poll the
running worker while it executes a slow synchronous job and count how
many times the event loop got to run in between. A responsive loop
(thread worker) accumulates many polls; a frozen loop (async worker
calling sync code directly) accumulates ~0.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.job_execution import _job_worker_running
from functualize.app.core import FunctualizeApp
from tests._responsiveness import count_polls, responsive_floor

BLOCK_SECONDS = 0.4
TICK_INTERVAL = 0.02


@pytest.fixture()
def job_started() -> threading.Event:
    """Set by the slow job's own body, the moment it begins executing.

    The responsiveness test needs to know *exactly* when its measurement
    window opens. Worker state is the wrong signal for that: a worker sits in
    PENDING for an unbounded time on a loaded runner, so any deadline waiting
    for RUNNING is a guess about the machine — which is the class of assertion
    `tests/_responsiveness.py` exists to get away from. The job telling us it
    has started is not a guess.
    """
    return threading.Event()


@pytest.fixture()
def tui_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_started: threading.Event
) -> FunctualizeInlineTUI:
    """A real FunctualizeInlineTUI over a minimal app, isolated from $HOME/cwd."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="jobexecapp")

    def slow_job() -> None:
        job_started.set()
        time.sleep(BLOCK_SECONDS)

    func_app.register_dynamic_job("slowjob", slow_job)

    def fast_job() -> None:
        pass

    func_app.register_dynamic_job("fastjob", fast_job)

    return FunctualizeInlineTUI(func_app)


async def test_ui_stays_responsive_while_job_executes(
    tui_app: FunctualizeInlineTUI,
    job_started: threading.Event,
) -> None:
    """the event loop keeps ticking during job execution.

    Runs a slow synchronous job through the real ``run_job`` entry point
    and polls the loop while the worker is active. A frozen loop (the
    pre-fix async-worker-calling-sync-code pattern) starves this poll
    loop almost entirely; a thread-worker migration leaves it responsive.

    The measurement window must *contain* the job. It opens on the job's
    own started-event and closes on the job worker's liveness (never the
    shared ``tui_app.workers`` set, whose emptiness cannot distinguish
    "never started" from "already finished"), and a window that misses the
    job fails with its own wording instead of the blocked-loop verdict.
    This matters because `Pilot.pause()` -- `wait_for_idle(0)` -- can run
    to its one-second cap under load and outlast the whole 0.4s job: the
    third occurrence of this test failing (two runs, `STATUS.md` #33) was
    exactly that, reported as a blocked loop that never happened.
    """
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        # This machine's ceiling for the poll pattern below, measured on the
        # same idle loop right before the job starts.
        idle_polls = await count_polls(BLOCK_SECONDS, TICK_INTERVAL)

        tui_app._smart_bar.value = "slowjob"
        await pilot.pause()

        tui_app.action_execute()

        # Open the window on the job's own started-event, polled with plain
        # asyncio.sleep ticks -- NOT `pilot.pause()`. `pause(delay=None)` is
        # `await wait_for_idle(0)` (textual/pilot.py), and `wait_for_idle`
        # (textual/_wait.py) only breaks early when the process CPU is quiet;
        # under load it runs to its one-second cap -- 2.5x the entire job --
        # and the test resumed after the job had already finished. That
        # produced `ticks == 0`, `elapsed == 0.000s`, which the window below
        # then reported as "the sync call is still blocking the event loop" --
        # arithmetically impossible for a genuinely blocked loop, which always
        # completes at least one tick before its deadline. The event (set by
        # the job body's first line) says the job started; the worker running
        # below says it is still going; nothing here depends on the idle
        # heuristic that used to outlast the job.
        start_deadline = time.monotonic() + 10.0
        while not job_started.is_set():
            if time.monotonic() > start_deadline:
                pytest.fail(
                    "the slow job never began executing — it did not run in a "
                    "worker at all, which is the pre-migration defect"
                )
            await asyncio.sleep(TICK_INTERVAL)

        # A job that finished before the window could open is a *missed
        # measurement*, and the old `tui_app.workers` window could not tell
        # that apart from a blocked loop: both look like an empty worker set
        # and zero ticks. `Worker._start` sets state RUNNING synchronously at
        # dispatch (textual/worker.py) and the job body keeps it there, so
        # "job started but worker not running" can only mean the job already
        # ended. Fail with what actually happened -- never the responsiveness
        # verdict below.
        if not _job_worker_running(tui_app):
            pytest.fail(
                "the slow job finished before the measurement window opened "
                "— the measurement missed the job entirely, which says "
                "nothing about event-loop responsiveness"
            )

        ticks = 0
        started = time.monotonic()
        deadline = started + BLOCK_SECONDS + 1.0
        while _job_worker_running(tui_app) and time.monotonic() < deadline:
            await asyncio.sleep(TICK_INTERVAL)
            ticks += 1
        elapsed = time.monotonic() - started

        await tui_app.workers.wait_for_complete()
        await pilot.pause()

    # A window that saw less than half the job's own runtime measured only
    # its tail, not the loop's behaviour during it: the rate scaling below
    # floors the ceiling at 1-2 ticks for such a window (`max(1, ...)`),
    # which even a healthy loop cannot reach for a job it barely saw. A
    # window that opened late is a *missed measurement* -- report it with
    # its own wording, never as a blocked loop. (A genuinely blocked loop
    # keeps the worker alive past its freeze, so its window is long: it
    # reaches the responsiveness assertion below, which is where it fails.)
    if elapsed < BLOCK_SECONDS / 2:
        pytest.fail(
            f"the measurement window opened too late: it saw only "
            f"{elapsed:.3f}s of the {BLOCK_SECONDS}s job — a missed "
            "window, not a blocked event loop"
        )

    # Compare *rates*, not counts. `idle_polls` was measured over the full
    # BLOCK_SECONDS, but the window actually polled starts once the worker is
    # running and ends when it finishes -- shorter, and by a margin that varies
    # with how fast the machine got the thread going. Comparing a short window's
    # count against a full window's ceiling asks the loop to do more work in
    # less time, which is how a responsive run reported 3 polls against a floor
    # of 6 on a loaded CI runner.
    scaled_ceiling = max(1, round(idle_polls * (elapsed / BLOCK_SECONDS)))
    floor = responsive_floor(scaled_ceiling)
    assert ticks >= floor, (
        f"expected a responsive event loop (thread worker): got {ticks} "
        f"polls in {elapsed:.3f}s against an idle ceiling of {idle_polls} "
        f"per {BLOCK_SECONDS}s (scaled to {scaled_ceiling}, floor {floor}) — "
        "the sync call is still blocking the event loop"
    )


async def test_reentry_guard_ignores_second_trigger_while_running(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """a second execute trigger while a worker is active is ignored.

    Also verifies ``_snapshot_store.record``/``.flush`` are
    called exactly once per execution even under a rapid double-trigger,
    proving single-writer access is preserved by the re-entry guard.

    **The second trigger has to be a real re-entry.** The guard asks
    ``worker.is_running``, and a single ``pilot.pause()`` yields one loop
    iteration — which is not a guarantee that Textual has transitioned the
    thread worker into RUNNING yet. When it has not, the second trigger sees no
    running worker, correctly starts a second execution, and ``record`` is
    called twice: a correct system failing a test that assumed a scheduling
    order it never established.

    That is not hypothetical. It failed twice on the 3.11 matrix leg while 3.12
    and 3.13 passed in the same runs (`STATUS.md` follow-up #23), in two pull
    requests that changed nothing this test reaches. So the wait below is the
    fix rather than a rerun: it *establishes* the precondition the docstring
    names instead of racing it.
    """
    tui_app._snapshot_store.record = MagicMock(wraps=tui_app._snapshot_store.record)  # type: ignore[method-assign]
    tui_app._snapshot_store.flush = MagicMock(wraps=tui_app._snapshot_store.flush)  # type: ignore[method-assign]

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        tui_app._smart_bar.value = "slowjob"
        await pilot.pause()

        tui_app.action_execute()

        # Wait for the guard's precondition rather than assuming it: the job
        # sleeps for BLOCK_SECONDS once running, so there is ample room to
        # re-trigger after this returns.
        for _ in range(500):
            if _job_worker_running(tui_app):
                break
            await pilot.pause()
        else:  # pragma: no cover - only on a pathologically stalled loop
            pytest.fail("the first job worker never reached RUNNING")

        # Now genuinely a re-entry: a second trigger while the first is active.
        tui_app.action_execute()
        await pilot.pause()

        await tui_app.workers.wait_for_complete()
        await pilot.pause()

    assert tui_app._snapshot_store.record.call_count == 1, (
        "record() should be called exactly once — a second trigger while "
        "a job worker is active must be ignored, not queued or run "
        "concurrently"
    )
    assert tui_app._snapshot_store.flush.call_count == 1
