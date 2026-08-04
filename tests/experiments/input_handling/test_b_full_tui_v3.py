"""Tests for Full TUI v3: cell nav, bar states, drill-down.

Run:
    uv run pytest experiments/input_handling/test_b_full_tui_v3.py -v --tb=short
"""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, Input

from tests.experiments.input_handling.experiment_b_full_tui_v3 import (
    FocusZone, FullTuiV3App,
)


@pytest.mark.asyncio
async def test_bar_state_grey_pending_ready():
    """Bar transitions: grey → pending → ready based on job + fields."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        assert app._bar_state == "grey"

        # Type "deploy" — all required fields have defaults → ready
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        assert app._bar_state == "ready"
        assert app.query_one("#smart-bar", Input).has_class("ready")


@pytest.mark.asyncio
async def test_cell_navigation_h_l():
    """h/l moves between columns in NORMAL panel mode."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        table = app.query_one("#panel-table", DataTable)
        assert table.cursor_column == 0  # Start at Setting

        await pilot.press("l")
        await pilot.pause()
        assert table.cursor_column == 1  # Value

        await pilot.press("l")
        await pilot.pause()
        assert table.cursor_column == 2  # Source

        await pilot.press("h")
        await pilot.pause()
        assert table.cursor_column == 1  # Back to Value


@pytest.mark.asyncio
async def test_i_on_value_column_enters_insert():
    """Pressing i on the Value column enters INSERT mode."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        # Move to Value column
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        assert app._mode == "insert"
        bar = app.query_one("#smart-bar", Input)
        assert bar.has_class("editing")
        assert "region" in bar.placeholder


@pytest.mark.asyncio
async def test_i_on_source_column_shows_picker():
    """Pressing i on the Source column shows target picker (choosing mode)."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        # Move to Source column
        await pilot.press("l", "l")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        assert app._mode == "choosing"
        from textual.widgets import OptionList
        ol = app.query_one("#choices-list", OptionList)
        assert ol.has_class("visible")
        assert ol.option_count > 0  # Shows persist targets


@pytest.mark.asyncio
async def test_i_on_setting_column_jumps_to_value():
    """Pressing i on Setting (non-editable) jumps cursor to Value column."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        table = app.query_one("#panel-table", DataTable)
        assert table.cursor_column == 0  # Setting

        await pilot.press("i")
        await pilot.pause()

        # Should jump to Value column and enter insert
        assert app._mode == "insert"
        assert table.cursor_column == 1


@pytest.mark.asyncio
async def test_drill_down_shows_resolution_chain():
    """Enter shows field detail with resolution chain."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        # Breadcrumb should show detail
        assert len(app._sub_breadcrumbs) == 1
        assert "Detail: region" in app._sub_breadcrumbs[0]

        # Detail view should be visible
        from textual.widgets import Static
        detail = app.query_one("#detail-view", Static)
        assert detail.has_class("visible")


@pytest.mark.asyncio
async def test_escape_pops_detail_then_collapses():
    """Esc from detail → back to table. Esc again → collapse."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("enter")  # Drill down
        await pilot.pause()
        assert len(app._sub_breadcrumbs) == 1

        await pilot.press("escape")  # Pop detail
        await pilot.pause()
        assert len(app._sub_breadcrumbs) == 0
        assert app._active_ring is not None

        await pilot.press("escape")  # Collapse
        await pilot.pause()
        assert app._active_ring is None
        assert app._zone == FocusZone.SMARTBAR


@pytest.mark.asyncio
async def test_choices_shown_for_enum_field():
    """Editing an enum field shows the choices OptionList."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d", "e", "p", "l", "o", "y")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        # Move to Value column and edit (region has choices)
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        from textual.widgets import OptionList
        ol = app.query_one("#choices-list", OptionList)
        assert ol.has_class("visible")
        assert ol.option_count >= 1  # At least 1 choice visible (filtering may narrow)


@pytest.mark.asyncio
async def test_ctrl_r_requires_job():
    """Ctrl+R without a job shows warning."""
    app = FullTuiV3App()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app._active_ring is None
