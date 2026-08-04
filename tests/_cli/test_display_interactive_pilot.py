"""Interactive display slot — real-app Pilot coverage (convergence, item 3).

Displays are now mounted for real inside ``#display-section`` and speak the
same interaction contract as PanelHost panels: Shift+Tab focuses the DISPLAY
zone in NORMAL mode, ``KeyDispatcher._resolve_target`` routes j/k/Enter to
the display's focusable widget through the zone-aware ``active_panel``,
Enter drill-downs push a sub-view (``Display.DrillDown`` → ``push_view``),
and Esc pops back / leaves the zone. Legacy 5-attr displays render
non-interactively with keys inert — the graceful-degradation contract.
"""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Static

from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize.ui import Display
from tests._cli._tui_fixtures import tui_app

__all__ = ["tui_app"]


class _InteractiveBody(Widget):
    """Display body implementing the converged interaction contract."""

    can_focus = True

    DEFAULT_CSS = """
    _InteractiveBody {
        height: auto;
        min-height: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.cursor = 0

    def render(self) -> str:
        return f"cursor={self.cursor}"

    def action_cursor_down(self) -> None:
        self.cursor += 1

    def action_cursor_up(self) -> None:
        self.cursor -= 1

    def action_drill_down(self) -> None:
        self.post_message(
            Display.DrillDown(Static("detail body", id="detail-view"), "Detail")
        )

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        return [("j/k", "move"), ("Enter", "detail")]


class _InteractiveDisplay:
    display_id = "inter"
    display_title = "Inter"
    display_priority = 1

    def should_show(self, cwd, app) -> bool:
        return True

    def compose_display(self):
        yield _InteractiveBody()


class _LegacyDisplay:
    """Minimal 5-attr duck-typed display — must stay working, non-interactive."""

    display_id = "legacy"
    display_title = "Legacy"
    display_priority = 5

    def should_show(self, cwd, app) -> bool:
        return True

    def compose_display(self):
        yield Static("legacy content")


async def test_shift_tab_enters_display_and_keys_route(tui_app) -> None:
    """Shift+Tab → NORMAL/DISPLAY; j/k dispatch to the display widget."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(_InteractiveDisplay())
        await pilot.pause()

        await pilot.press("shift+tab")
        await pilot.pause()

        assert tui_app._focus_state.zone is FocusZone.DISPLAY
        assert tui_app._focus_state.mode is FocusMode.NORMAL

        body = tui_app.active_panel
        assert isinstance(body, _InteractiveBody), (
            "active_panel must resolve to the display's interactive widget "
            "while the DISPLAY zone is focused in NORMAL mode"
        )

        await pilot.press("j")
        await pilot.press("j")
        await pilot.press("k")
        await pilot.pause()
        assert body.cursor == 1, "j/j/k should have dispatched to the widget"


async def test_enter_drill_down_and_escape_back(tui_app) -> None:
    """Enter pushes a sub-view (breadcrumb sub-level); Esc pops; Esc leaves."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(_InteractiveDisplay())
        await pilot.pause()

        await pilot.press("shift+tab")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert tui_app._display_slot.view_depth == 1
        assert tui_app._display_slot.current_view_title == "Detail"
        bc = tui_app.query_one("#display-bc", Static)
        assert "› Detail" in str(bc.content)

        await pilot.press("escape")
        await pilot.pause()
        assert tui_app._display_slot.view_depth == 0
        assert tui_app._focus_state.zone is FocusZone.DISPLAY
        assert tui_app._focus_state.mode is FocusMode.NORMAL

        await pilot.press("escape")
        await pilot.pause()
        assert tui_app._focus_state.mode is FocusMode.COMMAND
        assert tui_app._focus_state.zone is FocusZone.SMARTBAR
        # The display stays visible — Esc leaves the zone, it doesn't hide it.
        assert tui_app._display_slot.has_visible_displays


async def test_legacy_display_renders_but_keys_inert(tui_app) -> None:
    """A 5-attr display mounts and renders; focus falls back to the chrome
    container; keys neither dispatch nor crash."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(_LegacyDisplay())
        await pilot.pause()

        assert tui_app._display_slot.current_interactive_widget is None

        await pilot.press("shift+tab")
        await pilot.pause()
        assert tui_app._focus_state.zone is FocusZone.DISPLAY
        # No interactive widget → mode stays COMMAND, keys stay inert.
        assert tui_app._focus_state.mode is FocusMode.COMMAND

        await pilot.press("j")
        await pilot.pause()  # nothing to assert beyond "did not crash"

        # The legacy content is really mounted (not chrome-extracted).
        statics = tui_app.query("#display-slot-content Static")
        assert any("legacy content" in str(s.content) for s in statics)


async def test_ctrl_u_o_cycles_mounted_displays(tui_app) -> None:
    """Ctrl+U/O cycle the (now mounted) slot — the pre-guard crash path."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(_InteractiveDisplay())
        tui_app._display_slot.register_display(_LegacyDisplay())
        await pilot.pause()

        first = tui_app._display_slot.current_display_id
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert tui_app._display_slot.current_display_id != first

        await pilot.press("ctrl+u")
        await pilot.pause()
        assert tui_app._display_slot.current_display_id == first


async def test_active_panel_is_zone_aware(tui_app) -> None:
    """active_panel returns the display widget only in NORMAL/DISPLAY."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._display_slot.register_display(_InteractiveDisplay())
        await pilot.pause()

        # COMMAND/SMARTBAR: panel-host resolution (no display routing).
        assert not isinstance(tui_app.active_panel, _InteractiveBody)

        await pilot.press("shift+tab")
        await pilot.pause()
        assert isinstance(tui_app.active_panel, _InteractiveBody)

        # Leaving the zone flips resolution back.
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(tui_app.active_panel, _InteractiveBody)
