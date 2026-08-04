"""Tests for the full TUI architecture experiment.

Run:
    uv run pytest experiments/input_handling/test_b_full_tui.py -v --tb=short
"""

from __future__ import annotations

import pytest

from tests.experiments.input_handling.experiment_b_full_tui import (
    FocusZone,
    FullTuiApp,
)


# ─── Panel Ring Toggle Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ctrl_r_opens_preflight_ring():
    """Ctrl+R opens the pre-flight panel ring."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        assert app._mode == "command"
        assert app._active_ring is None

        await pilot.press("ctrl+r")
        await pilot.pause()

        assert app._active_ring is app._preflight_ring
        assert app._mode == "normal"
        assert app._zone == FocusZone.PANEL


@pytest.mark.asyncio
async def test_ctrl_e_opens_general_ring():
    """Ctrl+E opens the general panel ring."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert app._active_ring is app._general_ring
        assert app._mode == "normal"
        assert app._zone == FocusZone.PANEL


@pytest.mark.asyncio
async def test_ctrl_r_again_collapses():
    """Pressing Ctrl+R twice collapses the pre-flight ring."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app._active_ring is app._preflight_ring

        await pilot.press("ctrl+r")
        await pilot.pause()

        assert app._active_ring is None
        assert app._mode == "command"
        assert app._zone == FocusZone.SMARTBAR


@pytest.mark.asyncio
async def test_switching_rings():
    """Pressing Ctrl+E while pre-flight is open switches to general."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app._active_ring is app._preflight_ring

        await pilot.press("ctrl+e")
        await pilot.pause()
        assert app._active_ring is app._general_ring
        assert app._mode == "normal"


# ─── Ring Navigation (Ctrl+H/J/K/L) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ring_navigation_next_prev():
    """Ctrl+J/K navigates within the panel ring."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")  # General ring (4 panels)
        await pilot.pause()

        assert app._general_ring.index == 0
        assert app._general_ring.current.title == "Job Browser"

        await pilot.press("ctrl+j")
        await pilot.pause()
        assert app._general_ring.index == 1
        assert app._general_ring.current.title == "History"

        await pilot.press("ctrl+j")
        await pilot.pause()
        assert app._general_ring.index == 2
        assert app._general_ring.current.title == "Shortcuts"

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert app._general_ring.index == 1
        assert app._general_ring.current.title == "History"


@pytest.mark.asyncio
async def test_ring_navigation_first_last():
    """Ctrl+H jumps to first, Ctrl+L to last."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        await pilot.press("ctrl+l")
        await pilot.pause()
        assert app._general_ring.index == 3
        assert app._general_ring.current.title == "Settings"

        await pilot.press("ctrl+h")
        await pilot.pause()
        assert app._general_ring.index == 0
        assert app._general_ring.current.title == "Job Browser"


# ─── Focus Zone Cycling ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shift_tab_cycles_zones():
    """Shift+Tab cycles through visible zones."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Start at SmartBar with display visible
        assert app._zone == FocusZone.SMARTBAR

        # Open a panel so all zones are visible
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app._zone == FocusZone.PANEL

        # Cycle: Panel → SmartBar
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app._zone == FocusZone.SMARTBAR

        # Cycle: SmartBar → Display
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app._zone == FocusZone.DISPLAY

        # Cycle: Display → Panel
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app._zone == FocusZone.PANEL


# ─── Breadcrumb Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_breadcrumb_shows_position():
    """Breadcrumb shows [R:1/2] or [E:2/4] format."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()

        bc = app._preflight_ring.breadcrumb
        assert "[R:1/2]" in bc
        assert "Config Table" in bc

        await pilot.press("ctrl+j")
        await pilot.pause()
        bc = app._preflight_ring.breadcrumb
        assert "[R:2/2]" in bc
        assert "Diff View" in bc


@pytest.mark.asyncio
async def test_breadcrumb_sub_levels():
    """Enter adds sub-breadcrumb, Esc pops it."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()

        assert app._sub_breadcrumbs == []

        # Drill into first row
        await pilot.press("enter")
        await pilot.pause()
        assert len(app._sub_breadcrumbs) == 1
        assert "Detail: region" in app._sub_breadcrumbs[0]

        # Esc pops the breadcrumb (not collapse)
        await pilot.press("escape")
        await pilot.pause()
        assert app._sub_breadcrumbs == []
        assert app._active_ring is not None  # Still open


# ─── Escape Layered Behavior ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escape_layered():
    """Esc: pop breadcrumb → collapse → SmartBar."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()

        # Add a breadcrumb
        await pilot.press("enter")
        await pilot.pause()
        assert len(app._sub_breadcrumbs) == 1

        # First Esc: pop breadcrumb
        await pilot.press("escape")
        await pilot.pause()
        assert app._sub_breadcrumbs == []
        assert app._active_ring is not None

        # Second Esc: collapse panel
        await pilot.press("escape")
        await pilot.pause()
        assert app._active_ring is None
        assert app._zone == FocusZone.SMARTBAR
        assert app._mode == "command"


# ─── INSERT Mode (Option B) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_mode_in_panel():
    """Pressing 'i' enters INSERT mode, typing works, Enter confirms."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()

        # Edit first row (region)
        await pilot.press("i")
        await pilot.pause()
        assert app._mode == "insert"

        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        assert bar.has_class("editing")
        assert "region" in bar.placeholder

        # Type new value
        await pilot.press("backspace", "backspace", "backspace", "backspace",
                          "backspace", "backspace", "backspace", "backspace", "backspace")
        await pilot.press("e", "u", "-", "w", "e", "s", "t", "-", "1")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert app._mode == "normal"
        # Data should be updated
        assert app._preflight_ring.panels[0].rows[0][1][1] == "eu-west-1"


@pytest.mark.asyncio
async def test_insert_escape_cancels():
    """Escape in INSERT cancels without changing data."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        await pilot.press("x", "y", "z")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert app._mode == "normal"
        # Original value unchanged
        assert app._preflight_ring.panels[0].rows[0][1][1] == "us-east-1"


# ─── Display Panel ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_display_navigation():
    """Ctrl+U/I navigates display panels."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # First Ctrl+U focuses display
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert app._zone == FocusZone.DISPLAY
        assert app._display_ring.index == 0

        # Second Ctrl+U navigates prev (wraps to last)
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert app._display_ring.index == 1  # Wrapped to "Git Status"


# ─── Bug Fix Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escape_from_display_returns_to_smartbar():
    """Esc from Display zone returns focus to SmartBar."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Focus display zone
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert app._zone == FocusZone.DISPLAY
        assert app._mode == "normal"

        # Esc should return to SmartBar
        await pilot.press("escape")
        await pilot.pause()
        assert app._zone == FocusZone.SMARTBAR
        assert app._mode == "command"


@pytest.mark.asyncio
async def test_jk_only_moves_panel_when_panel_focused():
    """j/k should NOT move panel cursor when Display zone is focused."""
    app = FullTuiApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Open pre-flight panel first
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app._zone == FocusZone.PANEL

        from textual.widgets import DataTable

        table = app.query_one("#panel-table", DataTable)
        initial_row = table.cursor_row

        # Now switch to display zone
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert app._zone == FocusZone.DISPLAY

        # j/k should NOT move the panel table cursor
        await pilot.press("j")
        await pilot.pause()
        assert table.cursor_row == initial_row

        await pilot.press("k")
        await pilot.pause()
        assert table.cursor_row == initial_row
