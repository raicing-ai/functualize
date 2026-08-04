"""Unit tests for tui/integration.py — set_focus(None) pattern and helpers.

Validates that the integration helpers correctly wire the set_focus(None)
fix when transitioning to NORMAL mode, that the CommandPalette check
in KeyDispatcher remains the first guard in dispatch, and that
action_zone_cycle correctly cycles zones and focuses widgets.

**Validates: Requirements 1.5, 10.1, 10.2, 10.3, 10.4, 10.5, 12.1, 12.2, 12.3, 12.4**
"""

from __future__ import annotations

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.integration import (
    action_zone_cycle,
    enter_normal_mode,
    exit_to_command_mode,
)
from functualize._cli.tui.key_handler import KeyDispatcher

# =============================================================================
# Helpers
# =============================================================================


class FakeApp:
    """Minimal App stand-in for testing integration helpers."""

    def __init__(self) -> None:
        self.focus_cleared = False
        self.focused_widget: object | None = "something"

    def set_focus(self, widget: object | None) -> None:
        self.focused_widget = widget
        if widget is None:
            self.focus_cleared = True


class FakeSmartBar:
    """Minimal SmartBar stand-in for testing exit_to_command_mode."""

    def __init__(self) -> None:
        self.has_focus = False
        self.value = ""
        self.cursor_position = 0

    def focus(self) -> None:
        self.has_focus = True


# =============================================================================
# Tests: enter_normal_mode
# =============================================================================


class TestEnterNormalMode:
    """Tests for the enter_normal_mode integration helper."""

    def test_calls_set_focus_none_on_successful_transition(self) -> None:
        """Req 1.5: set_focus(None) is called when entering NORMAL mode."""
        fs = FocusState()  # starts at COMMAND
        app = FakeApp()

        result = enter_normal_mode(app, fs)

        assert result is True
        assert app.focus_cleared is True
        assert app.focused_widget is None
        assert fs.mode is FocusMode.NORMAL
        assert fs.zone is FocusZone.PANEL  # default zone

    def test_does_not_call_set_focus_on_failed_transition(self) -> None:
        """If transition is invalid, set_focus(None) is NOT called."""
        fs = FocusState()
        fs.force(FocusMode.INSERT, FocusZone.SMARTBAR)  # INSERT → NORMAL is valid
        # But INSERT → NORMAL is actually valid, let's use FILTER → COMMAND (invalid)
        fs.force(FocusMode.FILTER, FocusZone.PANEL)
        app = FakeApp()

        # FILTER can only go to NORMAL, not via enter_normal (which is valid)
        # Let's force to INSERT first and try to enter NORMAL — that IS valid.
        # Actually, we need an invalid transition. enter_normal from NORMAL is invalid.
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        # NORMAL → NORMAL is not in valid transitions
        result = enter_normal_mode(app, fs)

        assert result is False
        assert app.focus_cleared is False

    def test_uses_provided_zone(self) -> None:
        """Zone argument is passed through to FocusState."""
        fs = FocusState()
        app = FakeApp()

        enter_normal_mode(app, fs, zone=FocusZone.DISPLAY)

        assert fs.zone is FocusZone.DISPLAY

    def test_default_zone_is_panel(self) -> None:
        """Default zone for entering NORMAL is PANEL."""
        fs = FocusState()
        app = FakeApp()

        enter_normal_mode(app, fs)

        assert fs.zone is FocusZone.PANEL

    def test_works_without_set_focus_method(self) -> None:
        """Gracefully handles app objects without set_focus (no crash)."""
        fs = FocusState()
        app = object()  # no set_focus method

        result = enter_normal_mode(app, fs)

        assert result is True
        assert fs.mode is FocusMode.NORMAL


# =============================================================================
# Tests: exit_to_command_mode
# =============================================================================


class TestExitToCommandMode:
    """Tests for the exit_to_command_mode integration helper."""

    def test_transitions_to_command_and_focuses_smartbar(self) -> None:
        """Exiting to COMMAND focuses the SmartBar."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        app = FakeApp()
        bar = FakeSmartBar()

        result = exit_to_command_mode(app, fs, smartbar=bar)

        assert result is True
        assert fs.mode is FocusMode.COMMAND
        assert fs.zone is FocusZone.SMARTBAR
        assert bar.has_focus is True

    def test_transitions_without_smartbar(self) -> None:
        """Works without a SmartBar reference."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        app = FakeApp()

        result = exit_to_command_mode(app, fs, smartbar=None)

        assert result is True
        assert fs.mode is FocusMode.COMMAND

    def test_rejects_invalid_transition(self) -> None:
        """Cannot exit to COMMAND from INSERT (must go through NORMAL first)."""
        fs = FocusState()
        fs.force(FocusMode.INSERT, FocusZone.SMARTBAR)
        app = FakeApp()
        bar = FakeSmartBar()

        result = exit_to_command_mode(app, fs, smartbar=bar)

        assert result is False
        assert bar.has_focus is False


# =============================================================================
# Tests: CommandPalette check is first guard in dispatch
# =============================================================================


class TestCommandPaletteGuard:
    """Verify CommandPalette check is the first operation in KeyDispatcher.dispatch."""

    def test_command_palette_check_returns_false_immediately(self) -> None:
        """Req 12.1-12.4: CommandPalette active → returns False, no side effects."""
        fs = FocusState()
        app = FakeApp()
        dispatcher = KeyDispatcher(fs, app)
        # Monkey-patch to simulate CommandPalette active
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        class FakeEvent:
            def __init__(self) -> None:
                self.key = "j"
                self.prevented = False
                self.stopped = False

            def prevent_default(self) -> None:
                self.prevented = True

            def stop(self) -> None:
                self.stopped = True

        event = FakeEvent()
        result = dispatcher.dispatch(event)

        assert result is False
        assert event.prevented is False
        assert event.stopped is False

    def test_command_palette_check_preserves_focus_state(self) -> None:
        """Req 12.3: No FocusState transitions while palette is active."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        app = FakeApp()
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        class FakeEvent:
            def __init__(self) -> None:
                self.key = "escape"  # Would normally trigger exit_panel
                self.prevented = False
                self.stopped = False

            def prevent_default(self) -> None:
                self.prevented = True

            def stop(self) -> None:
                self.stopped = True

        event = FakeEvent()
        dispatcher.dispatch(event)

        # FocusState unchanged
        assert fs.mode is FocusMode.NORMAL
        assert fs.zone is FocusZone.PANEL


# =============================================================================
# Helpers for zone cycling tests
# =============================================================================


class FakeWidget:
    """Minimal focusable widget stand-in."""

    def __init__(self, name: str = "widget") -> None:
        self.name = name
        self.has_focus = False

    def focus(self) -> None:
        self.has_focus = True


# =============================================================================
# Tests: action_zone_cycle
# =============================================================================


class TestActionZoneCycle:
    """Tests for the action_zone_cycle integration helper.

    Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
    """

    def test_cycles_from_smartbar_to_display(self) -> None:
        """Req 10.1: Shift+Tab in COMMAND cycles SMARTBAR → DISPLAY."""
        fs = FocusState()  # starts at (COMMAND, SMARTBAR)
        app = FakeApp()
        display_widget = FakeWidget("display")

        widgets = {
            FocusZone.SMARTBAR: FakeWidget("smartbar"),
            FocusZone.DISPLAY: display_widget,
            FocusZone.PANEL: FakeWidget("panel"),
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {
                FocusZone.SMARTBAR,
                FocusZone.DISPLAY,
                FocusZone.PANEL,
            },
            get_zone_widget=lambda z: widgets.get(z),
        )

        assert fs.zone is FocusZone.DISPLAY
        assert display_widget.has_focus is True

    def test_cycles_from_display_to_panel(self) -> None:
        """Req 10.1: Continues cycling DISPLAY → PANEL."""
        fs = FocusState()
        fs.force(FocusMode.COMMAND, FocusZone.DISPLAY)
        app = FakeApp()
        panel_widget = FakeWidget("panel")

        widgets = {
            FocusZone.SMARTBAR: FakeWidget("smartbar"),
            FocusZone.DISPLAY: FakeWidget("display"),
            FocusZone.PANEL: panel_widget,
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {
                FocusZone.SMARTBAR,
                FocusZone.DISPLAY,
                FocusZone.PANEL,
            },
            get_zone_widget=lambda z: widgets.get(z),
        )

        assert fs.zone is FocusZone.PANEL
        assert panel_widget.has_focus is True

    def test_cycles_from_panel_wraps_to_smartbar(self) -> None:
        """Req 10.1: Wraps from PANEL back to SMARTBAR."""
        fs = FocusState()
        fs.force(FocusMode.COMMAND, FocusZone.PANEL)
        app = FakeApp()
        smartbar_widget = FakeWidget("smartbar")

        widgets = {
            FocusZone.SMARTBAR: smartbar_widget,
            FocusZone.DISPLAY: FakeWidget("display"),
            FocusZone.PANEL: FakeWidget("panel"),
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {
                FocusZone.SMARTBAR,
                FocusZone.DISPLAY,
                FocusZone.PANEL,
            },
            get_zone_widget=lambda z: widgets.get(z),
        )

        assert fs.zone is FocusZone.SMARTBAR
        assert smartbar_widget.has_focus is True

    def test_skips_display_when_not_visible(self) -> None:
        """Req 10.2: If DISPLAY not visible, skip it."""
        fs = FocusState()  # starts at (COMMAND, SMARTBAR)
        app = FakeApp()
        panel_widget = FakeWidget("panel")

        widgets = {
            FocusZone.SMARTBAR: FakeWidget("smartbar"),
            FocusZone.PANEL: panel_widget,
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {FocusZone.SMARTBAR, FocusZone.PANEL},
            get_zone_widget=lambda z: widgets.get(z),
        )

        # Should skip DISPLAY and go directly to PANEL
        assert fs.zone is FocusZone.PANEL
        assert panel_widget.has_focus is True

    def test_skips_panel_when_not_visible(self) -> None:
        """Req 10.3: If PANEL not visible, skip it."""
        fs = FocusState()  # starts at (COMMAND, SMARTBAR)
        app = FakeApp()
        display_widget = FakeWidget("display")

        widgets = {
            FocusZone.SMARTBAR: FakeWidget("smartbar"),
            FocusZone.DISPLAY: display_widget,
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {FocusZone.SMARTBAR, FocusZone.DISPLAY},
            get_zone_widget=lambda z: widgets.get(z),
        )

        assert fs.zone is FocusZone.DISPLAY
        assert display_widget.has_focus is True

    def test_remains_on_smartbar_when_only_zone(self) -> None:
        """Req 10.3: If no other zone visible, remain on SMARTBAR."""
        fs = FocusState()  # starts at (COMMAND, SMARTBAR)
        app = FakeApp()
        smartbar_widget = FakeWidget("smartbar")

        widgets = {FocusZone.SMARTBAR: smartbar_widget}

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {FocusZone.SMARTBAR},
            get_zone_widget=lambda z: widgets.get(z),
        )

        # Only one zone visible → stays on SMARTBAR
        assert fs.zone is FocusZone.SMARTBAR
        assert smartbar_widget.has_focus is True

    def test_focuses_target_widget(self) -> None:
        """Req 10.4: On zone transition, call focus() on target widget."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.SMARTBAR)
        app = FakeApp()
        display_widget = FakeWidget("display")

        widgets = {
            FocusZone.SMARTBAR: FakeWidget("smartbar"),
            FocusZone.DISPLAY: display_widget,
            FocusZone.PANEL: FakeWidget("panel"),
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {
                FocusZone.SMARTBAR,
                FocusZone.DISPLAY,
                FocusZone.PANEL,
            },
            get_zone_widget=lambda z: widgets.get(z),
        )

        assert display_widget.has_focus is True

    def test_works_in_normal_mode(self) -> None:
        """Req 10.1: Zone cycling works in NORMAL mode too."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        app = FakeApp()
        smartbar_widget = FakeWidget("smartbar")

        widgets = {
            FocusZone.SMARTBAR: smartbar_widget,
            FocusZone.DISPLAY: FakeWidget("display"),
            FocusZone.PANEL: FakeWidget("panel"),
        }

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {
                FocusZone.SMARTBAR,
                FocusZone.DISPLAY,
                FocusZone.PANEL,
            },
            get_zone_widget=lambda z: widgets.get(z),
        )

        assert fs.zone is FocusZone.SMARTBAR
        assert smartbar_widget.has_focus is True

    def test_no_crash_when_widget_is_none(self) -> None:
        """Gracefully handles None widget (no focus call, no crash)."""
        fs = FocusState()  # starts at (COMMAND, SMARTBAR)
        app = FakeApp()

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {
                FocusZone.SMARTBAR,
                FocusZone.DISPLAY,
                FocusZone.PANEL,
            },
            get_zone_widget=lambda z: None,  # No widget available
        )

        # Zone still advances even if widget is None
        assert fs.zone is FocusZone.DISPLAY

    def test_does_not_change_mode(self) -> None:
        """Req 10.1: Zone cycling does not change FocusMode."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.SMARTBAR)
        app = FakeApp()

        action_zone_cycle(
            app,
            fs,
            get_visible_zones=lambda: {FocusZone.SMARTBAR, FocusZone.PANEL},
            get_zone_widget=lambda z: FakeWidget("w"),
        )

        assert fs.mode is FocusMode.NORMAL  # Mode unchanged
