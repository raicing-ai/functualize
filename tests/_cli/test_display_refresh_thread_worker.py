"""Tests for the DisplaySlot refresh threading contract (steering §2.5).

``DisplayProvider.refresh()`` is arbitrary user code that may do I/O, so it
must never run on the event-loop thread. These tests exercise the real
``DisplaySlot`` inside a real ``FunctualizeInlineTUI``:

- a slow refresh must not freeze the loop (the item-4 freeze bug),
- a *hung* refresh must be abandoned on timeout and must not starve peers,
- a raising refresh still logs-and-skips,
- a minimal (5-attribute) provider must not crash the timer loop (item 5c).
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.app.core import FunctualizeApp

TICK_INTERVAL = 0.02
BLOCK_SECONDS = 0.4
RESPONSIVE_THRESHOLD = 3


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    """A real inline TUI over a minimal app, isolated from $HOME/cwd."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    return FunctualizeInlineTUI(FunctualizeApp(name="displayapp"))


class _SlowDisplay:
    """A display whose refresh blocks — the shape that used to freeze the TUI."""

    display_id = "slow"
    display_title = "Slow"
    display_priority = 10
    refresh_interval = 0.5
    linked_jobs = None
    linked_groups = None

    def __init__(self, block: float = BLOCK_SECONDS) -> None:
        self._block = block
        self.calls = 0
        self.thread_names: list[str] = []

    def should_show(self, cwd: Path, app: object) -> bool:
        return True

    def compose_display(self):  # type: ignore[no-untyped-def]
        from textual.widgets import Static

        yield Static("slow")

    def refresh(self) -> None:
        self.calls += 1
        self.thread_names.append(threading.current_thread().name)
        time.sleep(self._block)


class _HungDisplay(_SlowDisplay):
    """A display that never returns from refresh()."""

    display_id = "hung"
    display_title = "Hung"
    refresh_interval = 0.5
    refresh_timeout = 0.2

    def __init__(self) -> None:
        super().__init__(block=0.0)
        self.released = threading.Event()

    def refresh(self) -> None:
        self.calls += 1
        # Blocks until the test releases it, well past refresh_timeout.
        self.released.wait(timeout=10.0)


class _FastDisplay(_SlowDisplay):
    display_id = "fast"
    display_title = "Fast"
    display_priority = 20
    refresh_interval = 0.5

    def __init__(self) -> None:
        super().__init__(block=0.0)


class _MinimalDisplay:
    """Only the five attributes discovery actually requires (item 5c).

    No ``refresh_interval``, no ``refresh``, no ``linked_jobs``/
    ``linked_groups`` — reading any of those unguarded crashed the timer loop.
    """

    display_id = "minimal"
    display_title = "Minimal"
    display_priority = 5

    def should_show(self, cwd: Path, app: object) -> bool:
        return True

    def compose_display(self):  # type: ignore[no-untyped-def]
        from textual.widgets import Static

        yield Static("minimal")


class _RaisingDisplay(_SlowDisplay):
    display_id = "raising"
    display_title = "Raising"
    refresh_interval = 0.5

    def __init__(self) -> None:
        super().__init__(block=0.0)

    def refresh(self) -> None:
        self.calls += 1
        raise RuntimeError("boom")


async def test_slow_refresh_does_not_freeze_the_loop(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """A blocking refresh() runs off-loop, leaving the UI responsive.

    This is the item-4 regression guard: with ``refresh()`` called inline
    from the timer callback, the poll loop below starves almost entirely.
    """
    display = _SlowDisplay()

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(display)
        await pilot.pause()

        ticks = 0
        deadline = time.monotonic() + BLOCK_SECONDS + 1.0
        while display.calls == 0 and time.monotonic() < deadline:
            await asyncio.sleep(TICK_INTERVAL)
        # Poll while the (already dispatched) refresh is blocking.
        inner_deadline = time.monotonic() + BLOCK_SECONDS
        while time.monotonic() < inner_deadline:
            await asyncio.sleep(TICK_INTERVAL)
            ticks += 1

        await pilot.pause()

    assert display.calls >= 1, "registration should trigger an immediate refresh"
    assert ticks >= RESPONSIVE_THRESHOLD, (
        f"expected a responsive event loop, got only {ticks} polls while "
        "refresh() blocked — refresh is still running on the loop thread"
    )
    assert all(name != "MainThread" for name in display.thread_names), (
        f"refresh() must run off the main thread, saw {display.thread_names}"
    )


async def test_hung_display_does_not_starve_a_healthy_one(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """A provider that never returns is abandoned; its peers keep refreshing."""
    hung = _HungDisplay()
    fast = _FastDisplay()

    try:
        async with tui_app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            tui_app._display_slot.register_display(hung)
            tui_app._display_slot.register_display(fast)
            await pilot.pause()

            deadline = time.monotonic() + 3.0
            while fast.calls < 2 and time.monotonic() < deadline:
                await asyncio.sleep(TICK_INTERVAL)

            await pilot.pause()

        assert fast.calls >= 2, (
            f"the healthy display should keep refreshing while a peer hangs, "
            f"got {fast.calls} refreshes"
        )
        # The hung provider is retried after its timeout abandons a cycle,
        # but must never stack up unboundedly.
        assert hung.calls <= fast.calls + 1
    finally:
        hung.released.set()


async def test_raising_refresh_logs_and_skips(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """A provider that raises must not crash the timer loop."""
    display = _RaisingDisplay()

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(display)
        await pilot.pause()

        deadline = time.monotonic() + 2.0
        while display.calls < 2 and time.monotonic() < deadline:
            await asyncio.sleep(TICK_INTERVAL)
        await pilot.pause()

    assert display.calls >= 2, (
        "a raising refresh() should be retried on the next cycle, not kill the timer"
    )


async def test_minimal_provider_does_not_crash_timer_loop(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """A 5-attribute provider registers and survives a timer sync (item 5c)."""
    display = _MinimalDisplay()

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(display)
        await pilot.pause()
        # Force the paths that used to read optional attributes unguarded.
        tui_app._display_slot.update_job("some.job")
        tui_app._display_slot.update_cwd(Path.cwd())
        await pilot.pause()

    assert tui_app._display_slot.has_visible_displays


def test_display_base_class_supplies_defaults() -> None:
    """``functualize.ui.Display`` fills in every optional hook (item 5c)."""
    from functualize.ui import Display

    class Bare(Display):
        display_id = "bare"

        def compose_display(self):  # type: ignore[no-untyped-def]
            yield from ()

    bare = Bare()
    assert bare.refresh_interval is None
    assert bare.linked_jobs is None
    assert bare.linked_groups is None
    assert bare.display_priority == 100
    assert bare.refresh_timeout > 0
    assert bare.get_available_actions(focused=True) == []
    assert bare.refresh() is None
    assert bare.should_show(Path.cwd(), object()) is True  # type: ignore[arg-type]


def test_display_base_class_is_not_itself_discovered() -> None:
    """`from functualize.ui import Display` must not register a phantom display.

    The base satisfies every required attribute by design, so a module that
    imports it would otherwise have the base discovered alongside the real
    subclasses — registering a display whose compose_display() raises.
    """
    from functualize._cli.tui.display_provider_discovery import (
        find_display_providers,
        is_display_provider,
    )
    from functualize.ui import Display

    assert is_display_provider(Display) is False

    class _Module:
        pass

    module = _Module()
    module.Display = Display  # type: ignore[attr-defined]
    module.Real = _MinimalDisplay  # type: ignore[attr-defined]

    found = find_display_providers(module)

    assert found == [_MinimalDisplay]
