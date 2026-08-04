"""Unit tests for focus-aware display footer and simplified status bar.

Tests verify:
- R7-AC1: Display footer shows nav actions when DISPLAY zone focused (multi/single display)
- R7-AC2: Display footer shows 'focus display' hint when DISPLAY zone NOT focused
- R8-AC1: Status bar displays mode + zone + readiness
- R8-AC3: Status bar format is: {MODE}  {Zone}  {readiness_indicator}
- R8-AC4: Mode indicators have correct Rich markup
- R8-AC5: Zone names are SmartBar, Display, Panel
- R8-AC6: Readiness indicators: Ready (green), Pending (yellow), empty for GREY

Feature: tui-preflight-and-footer-polish, Task 7
"""

from __future__ import annotations

from unittest.mock import MagicMock

from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize.types import EnvironmentSource

# The status bar always carries the active environment. These stubs report a
# defaulted DEV, which renders dim.
_ENV = "  [dim]ENV:DEV[/dim]"

# =============================================================================
# Tests: _MODE_STYLES dict (R8-AC4)
# =============================================================================


class TestModeStyles:
    """Test _MODE_STYLES mapping (R8-AC4)."""

    def test_command_mode_is_dim(self) -> None:
        from functualize._cli.tui.app import _MODE_STYLES

        assert _MODE_STYLES[FocusMode.COMMAND] == "[dim]COMMAND[/dim]"

    def test_normal_mode_is_bold_cyan(self) -> None:
        from functualize._cli.tui.app import _MODE_STYLES

        assert _MODE_STYLES[FocusMode.NORMAL] == "[bold cyan]NORMAL[/bold cyan]"

    def test_insert_mode_is_bold_green(self) -> None:
        from functualize._cli.tui.app import _MODE_STYLES

        assert _MODE_STYLES[FocusMode.INSERT] == "[bold green]INSERT[/bold green]"

    def test_filter_mode_is_bold_yellow(self) -> None:
        from functualize._cli.tui.app import _MODE_STYLES

        assert _MODE_STYLES[FocusMode.FILTER] == "[bold yellow]FILTER[/bold yellow]"

    def test_all_modes_covered(self) -> None:
        from functualize._cli.tui.app import _MODE_STYLES

        for mode in FocusMode:
            assert mode in _MODE_STYLES, f"Missing style for {mode.name}"


# =============================================================================
# Tests: _ZONE_NAMES dict (R8-AC5)
# =============================================================================


class TestZoneNames:
    """Test _ZONE_NAMES mapping (R8-AC5)."""

    def test_smartbar_name(self) -> None:
        from functualize._cli.tui.app import _ZONE_NAMES

        assert _ZONE_NAMES[FocusZone.SMARTBAR] == "SmartBar"

    def test_display_name(self) -> None:
        from functualize._cli.tui.app import _ZONE_NAMES

        assert _ZONE_NAMES[FocusZone.DISPLAY] == "Display"

    def test_panel_name(self) -> None:
        from functualize._cli.tui.app import _ZONE_NAMES

        assert _ZONE_NAMES[FocusZone.PANEL] == "Panel"

    def test_all_zones_covered(self) -> None:
        from functualize._cli.tui.app import _ZONE_NAMES

        for zone in FocusZone:
            assert zone in _ZONE_NAMES, f"Missing name for {zone.name}"


# =============================================================================
# Tests: _readiness_indicator() helper (R8-AC6)
# =============================================================================


class TestReadinessIndicator:
    """Test _readiness_indicator() returns correct strings (R8-AC6)."""

    def _make_tui_stub(self, readiness: BarReadiness) -> MagicMock:
        """Create a minimal TUI stub with smart bar readiness."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        stub = MagicMock(spec=FunctualizeInlineTUI)
        stub._smart_bar = MagicMock()
        stub._smart_bar.readiness = readiness
        # Bind the real method to our stub
        stub._readiness_indicator = FunctualizeInlineTUI._readiness_indicator.__get__(
            stub
        )
        return stub

    def test_ready_returns_green_indicator(self) -> None:
        stub = self._make_tui_stub(BarReadiness.READY)
        result = stub._readiness_indicator()
        assert result == "[bold green]● Ready[/bold green]"

    def test_pending_returns_yellow_indicator(self) -> None:
        stub = self._make_tui_stub(BarReadiness.PENDING)
        result = stub._readiness_indicator()
        assert result == "[bold yellow]◐ Pending[/bold yellow]"

    def test_grey_returns_empty(self) -> None:
        stub = self._make_tui_stub(BarReadiness.GREY)
        result = stub._readiness_indicator()
        assert result == ""

    def test_editing_returns_empty(self) -> None:
        stub = self._make_tui_stub(BarReadiness.EDITING)
        result = stub._readiness_indicator()
        assert result == ""

    def test_invalid_returns_empty(self) -> None:
        stub = self._make_tui_stub(BarReadiness.INVALID)
        result = stub._readiness_indicator()
        assert result == ""


# =============================================================================
# Tests: _update_display_footer() (R7-AC1, R7-AC2)
# =============================================================================


class TestUpdateDisplayFooter:
    """Test _update_display_footer for different zone states (R7-AC1, R7-AC2)."""

    def _make_tui_stub(
        self, has_visible: bool = True, visible_count: int = 2
    ) -> MagicMock:
        """Create a minimal TUI stub for display footer testing."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        stub = MagicMock(spec=FunctualizeInlineTUI)
        stub._display_slot = MagicMock()
        stub._display_slot.has_visible_displays = has_visible
        stub._display_slot.visible_count = visible_count
        # Default: a legacy non-interactive display, no drill-down pushed.
        stub._display_slot.current_interactive_widget = None
        stub._display_slot.view_depth = 0

        # Mock query_one to return a Static-like object
        footer_mock = MagicMock()
        stub.query_one = MagicMock(return_value=footer_mock)

        # Bind the real method
        stub._update_display_footer = (
            FunctualizeInlineTUI._update_display_footer.__get__(stub)
        )
        return stub

    def test_display_focused_multiple_displays_shows_nav(self) -> None:
        """R7-AC1: Multiple displays + DISPLAY zone → show cycle hints."""
        stub = self._make_tui_stub(has_visible=True, visible_count=3)
        stub._update_display_footer(FocusZone.DISPLAY)

        footer_mock = stub.query_one.return_value
        footer_mock.update.assert_called_once_with(
            " Ctrl+U/O cycle  Shift+Tab cycle zone"
        )

    def test_display_focused_single_display_shows_unfocus_only(self) -> None:
        """R7-AC1: Single display + DISPLAY zone → show only Shift+Tab cycle."""
        stub = self._make_tui_stub(has_visible=True, visible_count=1)
        stub._update_display_footer(FocusZone.DISPLAY)

        footer_mock = stub.query_one.return_value
        footer_mock.update.assert_called_once_with(" Shift+Tab cycle zone")

    def test_display_focused_interactive_widget_actions_lead(self) -> None:
        """An interactive display's own hints come first in the footer."""
        stub = self._make_tui_stub(has_visible=True, visible_count=1)

        widget = MagicMock()
        widget.get_available_actions.return_value = [("j/k", "scroll")]
        stub._display_slot.current_interactive_widget = widget
        stub._update_display_footer(FocusZone.DISPLAY)

        footer_mock = stub.query_one.return_value
        footer_mock.update.assert_called_once_with(" j/k scroll  Shift+Tab cycle zone")

    def test_display_focused_drill_down_shows_back(self) -> None:
        """A pushed sub-view advertises Esc back instead of display cycling."""
        stub = self._make_tui_stub(has_visible=True, visible_count=3)
        stub._display_slot.view_depth = 1
        stub._update_display_footer(FocusZone.DISPLAY)

        footer_mock = stub.query_one.return_value
        footer_mock.update.assert_called_once_with(" Esc back  Shift+Tab cycle zone")

    def test_display_not_focused_shows_focus_hint(self) -> None:
        """R7-AC2: Non-DISPLAY zone → show how to focus display."""
        stub = self._make_tui_stub(has_visible=True, visible_count=2)
        stub._update_display_footer(FocusZone.PANEL)

        footer_mock = stub.query_one.return_value
        footer_mock.update.assert_called_once_with(
            " Shift+Tab focus display  Ctrl+U/O cycle"
        )

    def test_display_not_focused_smartbar_zone(self) -> None:
        """R7-AC2: SMARTBAR zone → show how to focus display."""
        stub = self._make_tui_stub(has_visible=True, visible_count=1)
        stub._update_display_footer(FocusZone.SMARTBAR)

        footer_mock = stub.query_one.return_value
        footer_mock.update.assert_called_once_with(
            " Shift+Tab focus display  Ctrl+U/O cycle"
        )

    def test_no_visible_displays_does_nothing(self) -> None:
        """When no displays visible, footer is not updated."""
        stub = self._make_tui_stub(has_visible=False, visible_count=0)
        stub._update_display_footer(FocusZone.DISPLAY)

        stub.query_one.assert_not_called()


# =============================================================================
# Tests: _update_status_bar() format (R8-AC1, R8-AC3)
# =============================================================================


class TestUpdateStatusBar:
    """Test _update_status_bar produces correct format (R8-AC1, R8-AC3)."""

    def _make_tui_stub(self, readiness: BarReadiness = BarReadiness.GREY) -> MagicMock:
        """Create a minimal TUI stub for status bar testing."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        stub = MagicMock(spec=FunctualizeInlineTUI)
        stub._smart_bar = MagicMock()
        stub._smart_bar.readiness = readiness
        stub._func_app = MagicMock()
        # The environment is always on the bar; default to the "nothing set
        # it" case so these tests exercise the ordinary rendering.
        stub._func_app.active_environment = MagicMock(return_value="DEV")
        stub._func_app.environment_source = MagicMock(
            return_value=EnvironmentSource.DEFAULT
        )
        # No plugin bar items — status text stays base-only
        stub._plugin_instances = MagicMock(return_value=[])

        # Mock query_one to return a Static-like object
        status_mock = MagicMock()
        stub.query_one = MagicMock(return_value=status_mock)

        # Bind the real methods
        stub._readiness_indicator = FunctualizeInlineTUI._readiness_indicator.__get__(
            stub
        )
        stub._environment_indicator = (
            FunctualizeInlineTUI._environment_indicator.__get__(stub)
        )
        stub._update_status_bar = FunctualizeInlineTUI._update_status_bar.__get__(stub)
        return stub

    def test_command_smartbar_grey(self) -> None:
        """COMMAND mode + SmartBar zone + GREY readiness."""
        stub = self._make_tui_stub(BarReadiness.GREY)
        stub._update_status_bar(FocusMode.COMMAND, FocusZone.SMARTBAR)

        status_mock = stub.query_one.return_value
        expected = " [dim]COMMAND[/dim]  SmartBar  " + _ENV
        status_mock.update.assert_called_once_with(expected)

    def test_normal_panel_ready(self) -> None:
        """NORMAL mode + Panel zone + READY readiness."""
        stub = self._make_tui_stub(BarReadiness.READY)
        stub._update_status_bar(FocusMode.NORMAL, FocusZone.PANEL)

        status_mock = stub.query_one.return_value
        expected = (
            " [bold cyan]NORMAL[/bold cyan]  Panel  "
            "[bold green]● Ready[/bold green]" + _ENV
        )
        status_mock.update.assert_called_once_with(expected)

    def test_insert_panel_pending(self) -> None:
        """INSERT mode + Panel zone + PENDING readiness."""
        stub = self._make_tui_stub(BarReadiness.PENDING)
        stub._update_status_bar(FocusMode.INSERT, FocusZone.PANEL)

        status_mock = stub.query_one.return_value
        expected = (
            " [bold green]INSERT[/bold green]  Panel  "
            "[bold yellow]◐ Pending[/bold yellow]" + _ENV
        )
        status_mock.update.assert_called_once_with(expected)

    def test_filter_display_grey(self) -> None:
        """FILTER mode + Display zone + GREY readiness (empty indicator)."""
        stub = self._make_tui_stub(BarReadiness.GREY)
        stub._update_status_bar(FocusMode.FILTER, FocusZone.DISPLAY)

        status_mock = stub.query_one.return_value
        expected = " [bold yellow]FILTER[/bold yellow]  Display  " + _ENV
        status_mock.update.assert_called_once_with(expected)

    def test_status_bar_no_panel_hints(self) -> None:
        """Status bar never contains panel action hints (R8-AC2)."""
        stub = self._make_tui_stub(BarReadiness.READY)
        stub._update_status_bar(FocusMode.NORMAL, FocusZone.PANEL)

        status_mock = stub.query_one.return_value
        call_args = status_mock.update.call_args[0][0]

        # These are panel-specific hints that must NOT be in the status bar
        panel_hints = ["j/k", "h/l", "i edit", "r reset", "Esc back"]
        for hint in panel_hints:
            assert hint not in call_args, f"Status bar contains panel hint: {hint!r}"
