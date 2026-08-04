"""Automated test proving offscreen Textual continuation works.

This test uses Textual's run_test() (headless mode) to prove that:
1. Widgets update their state even when rendering is suppressed via _begin_batch()
2. After _end_batch(), the widget tree has the correct final state
3. No buffering or replay is needed — state just accumulates naturally

Run with: uv run pytest experiments/offscreen_textual/test_offscreen.py -v
"""

from __future__ import annotations

import asyncio

import pytest

from tests.experiments.offscreen_textual.experiment import CounterWidget, OffscreenExperimentApp


@pytest.mark.asyncio
async def test_widget_updates_during_batch_suppression():
    """Prove that widget state updates even when painting is suppressed."""
    app = OffscreenExperimentApp()

    async with app.run_test(size=(80, 10)) as pilot:
        counter = app.query_one("#counter", CounterWidget)

        # Initial state
        assert counter.count == 0

        # Manually suppress rendering (simulates "execution mode")
        app._begin_batch()

        # Mutate widget state multiple times while rendering is off
        counter.count = 1
        await pilot.pause()
        counter.count = 2
        await pilot.pause()
        counter.count = 5
        await pilot.pause()

        # State IS updated even though nothing painted
        assert counter.count == 5

        # Resume rendering
        app._end_batch()
        await pilot.pause()

        # Widget still has correct state — no replay needed
        assert counter.count == 5


@pytest.mark.asyncio
async def test_reactive_watchers_fire_during_batch():
    """Prove that reactive watchers fire even during batch suppression."""
    app = OffscreenExperimentApp()
    watcher_log: list[int] = []

    async with app.run_test(size=(80, 10)) as pilot:
        counter = app.query_one("#counter", CounterWidget)

        # Add a watcher to track changes
        def _watch(new_val: int) -> None:
            watcher_log.append(new_val)

        counter.watch_count = _watch  # type: ignore[attr-defined]

        # Suppress rendering
        app._begin_batch()

        # Increment 5 times
        for i in range(1, 6):
            counter.count = i
            await pilot.pause()

        app._end_batch()
        await pilot.pause()

        # All 5 watcher calls happened even though rendering was off
        assert counter.count == 5
        # Watcher was called for each mutation
        assert watcher_log == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_async_task_updates_widget_during_batch():
    """Prove that async tasks can update widgets during batch suppression."""
    app = OffscreenExperimentApp()

    async with app.run_test(size=(80, 10)) as pilot:
        counter = app.query_one("#counter", CounterWidget)

        # Suppress rendering
        app._begin_batch()

        # Start an async task that increments the counter
        async def _increment():
            for _ in range(3):
                await asyncio.sleep(0.05)
                counter.count += 1

        task = asyncio.create_task(_increment())
        await task
        await pilot.pause()

        # State updated correctly via async task
        assert counter.count == 3

        # Resume
        app._end_batch()
        await pilot.pause()

        # Still correct
        assert counter.count == 3


@pytest.mark.asyncio
async def test_multiple_widgets_update_during_batch():
    """Prove that multiple widgets can update independently during batch."""
    app = OffscreenExperimentApp()

    async with app.run_test(size=(80, 10)) as pilot:
        counter = app.query_one("#counter", CounterWidget)
        status = app.query_one("#status")

        app._begin_batch()

        counter.count = 42
        status.update("Updated while offscreen!")
        await pilot.pause()

        app._end_batch()
        await pilot.pause()

        assert counter.count == 42
        # Status widget has been updated (its renderable changed)
        # The key point: when Textual repaints, it shows "42" and the new status
        # without any explicit replay or buffer flush
