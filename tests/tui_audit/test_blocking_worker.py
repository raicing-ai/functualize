"""Proof: a sync call inside an async worker freezes the whole TUI.

``run_worker(coroutine)`` schedules the coroutine on the app's event
loop — it is "background" only in the sense that it doesn't block the
caller. Any synchronous code inside it still monopolizes the loop:
timers stop firing, keys queue up, and RichLog output written before
the call does not render until the call returns.

This was exactly the shape of ``job_execution.execute_job_async`` prior
to the fix: it called the synchronous
``FunctualizeApp.execute(...)`` directly inside an async worker. A job
that took 30s would freeze the TUI for 30s and the "live" log output
would appear only after completion.

The fix shape (also proven here): run the sync work in a thread worker
(``thread=True``) and marshal UI updates via ``call_from_thread``. The
two tests below (``test_sync_call_in_async_worker_freezes_event_loop``
and ``test_thread_worker_keeps_event_loop_responsive``) exercise this
pattern in isolation via the toy ``HeartbeatApp`` and remain as general
proofs of *why* the pattern is dangerous and why the fix works — they
are not deleted by the fix landing.

``test_real_job_execution_stays_responsive`` below is the
inversion: it exercises the REAL ``job_execution.run_job`` code path
(post-fix) end-to-end and asserts responsiveness, documenting that the
actual fix is applied in production code, not just proven in the toy
model.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.widgets import RichLog

if TYPE_CHECKING:
    import pytest

BLOCK_SECONDS = 0.4
TICK_INTERVAL = 0.05
# A responsive loop fits many ticks into BLOCK_SECONDS; a frozen loop fits ~0.
RESPONSIVE_THRESHOLD = 3


class HeartbeatApp(App[None]):
    """Counts timer ticks — a proxy for 'is the UI responsive'."""

    def __init__(self) -> None:
        super().__init__()
        self.ticks_during_work = 0
        self._working = False

    def compose(self) -> ComposeResult:
        yield RichLog()

    def on_mount(self) -> None:
        self.set_interval(TICK_INTERVAL, self._tick)

    def _tick(self) -> None:
        if self._working:
            self.ticks_during_work += 1

    # --- the bug pattern: sync call inside an async worker -------------
    async def _blocking_async_job(self) -> None:
        self._working = True
        self.query_one(RichLog).write("starting (you should see this live)")
        time.sleep(BLOCK_SECONDS)  # stand-in for sync FunctualizeApp.execute()
        self._working = False

    # --- the fix pattern: sync work in a thread worker ------------------
    def _blocking_thread_job(self) -> None:
        self._working = True
        self.call_from_thread(self.query_one(RichLog).write, "starting (renders live)")
        time.sleep(BLOCK_SECONDS)
        self._working = False


async def test_sync_call_in_async_worker_freezes_event_loop() -> None:
    """The pattern used by job_execution.py starves timers (and rendering)."""
    app = HeartbeatApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        worker = app.run_worker(app._blocking_async_job(), exclusive=True)
        await worker.wait()
        await pilot.pause()
    assert app.ticks_during_work < RESPONSIVE_THRESHOLD, (
        f"expected a frozen loop, got {app.ticks_during_work} ticks — "
        "if this fails, Textual changed how async workers are scheduled"
    )


async def test_thread_worker_keeps_event_loop_responsive() -> None:
    """Same blocking work via thread=True — the UI keeps ticking."""
    app = HeartbeatApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        worker = app.run_worker(app._blocking_thread_job, thread=True)
        # Let the loop run while the thread blocks.
        deadline = time.monotonic() + BLOCK_SECONDS + 1.0
        while worker.is_running and time.monotonic() < deadline:
            await asyncio.sleep(TICK_INTERVAL)
        await pilot.pause()
    assert app.ticks_during_work >= RESPONSIVE_THRESHOLD, (
        f"thread worker should leave the loop responsive, "
        f"got only {app.ticks_during_work} ticks"
    )


# --- inversion: the real code path, post-fix -----------------


async def test_real_job_execution_stays_responsive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual ``job_execution.run_job`` stays responsive during a job.

    Unlike the two proofs above (which use the toy ``HeartbeatApp``),
    this drives the real ``FunctualizeInlineTUI`` + ``run_job`` code path
    end-to-end, proving the R1 thread-worker migration
    is actually applied in production code.
    """
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize.app.core import FunctualizeApp

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="blockingproofapp")

    def slow_job() -> None:
        time.sleep(BLOCK_SECONDS)

    func_app.register_dynamic_job("slowjob", slow_job)
    tui_app = FunctualizeInlineTUI(func_app)

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "slowjob"
        await pilot.pause()
        tui_app.action_execute()
        await pilot.pause()

        ticks = 0
        deadline = time.monotonic() + BLOCK_SECONDS + 1.0
        while tui_app.workers and time.monotonic() < deadline:
            await asyncio.sleep(TICK_INTERVAL)
            ticks += 1

        await tui_app.workers.wait_for_complete()
        await pilot.pause()

    assert ticks >= RESPONSIVE_THRESHOLD, (
        f"expected the real job_execution.run_job path to leave the "
        f"loop responsive, got only {ticks} polls — the R1 fix may have "
        "regressed"
    )
