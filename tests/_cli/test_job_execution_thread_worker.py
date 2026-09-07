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
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    """A real FunctualizeInlineTUI over a minimal app, isolated from $HOME/cwd."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="jobexecapp")

    def slow_job() -> None:
        time.sleep(BLOCK_SECONDS)

    func_app.register_dynamic_job("slowjob", slow_job)

    def fast_job() -> None:
        pass

    func_app.register_dynamic_job("fastjob", fast_job)

    return FunctualizeInlineTUI(func_app)


async def test_ui_stays_responsive_while_job_executes(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """the event loop keeps ticking during job execution.

    Runs a slow synchronous job through the real ``run_job`` entry point
    and polls the loop while the worker is active. A frozen loop (the
    pre-fix async-worker-calling-sync-code pattern) starves this poll
    loop almost entirely; a thread-worker migration leaves it responsive.
    """
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        # This machine's ceiling for the poll pattern below, measured on the
        # same idle loop right before the job starts.
        idle_polls = await count_polls(BLOCK_SECONDS, TICK_INTERVAL)

        tui_app._smart_bar.value = "slowjob"
        await pilot.pause()

        tui_app.action_execute()
        await pilot.pause()

        # Wait until the worker is genuinely RUNNING before counting anything.
        # Without this the poll loop can be reached after the job has already
        # finished -- `tui_app.workers` is then falsy, the loop never iterates,
        # and zero ticks is reported as "the sync call blocked the loop". That
        # is the *same* observation a frozen loop produces, so the failure was
        # indistinguishable from the defect the test exists to catch.
        # `test_reentry_guard_ignores_second_trigger_while_running` below
        # already waits this way; this test did not.
        start_deadline = time.monotonic() + BLOCK_SECONDS
        while not _job_worker_running(tui_app):
            if time.monotonic() > start_deadline:
                pytest.fail(
                    "the job worker never reached RUNNING — the job did not "
                    "run in a worker at all, which is the pre-migration defect"
                )
            await pilot.pause()

        ticks = 0
        started = time.monotonic()
        deadline = started + BLOCK_SECONDS + 1.0
        while tui_app.workers and time.monotonic() < deadline:
            await asyncio.sleep(TICK_INTERVAL)
            ticks += 1
        elapsed = time.monotonic() - started

        await tui_app.workers.wait_for_complete()
        await pilot.pause()

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
