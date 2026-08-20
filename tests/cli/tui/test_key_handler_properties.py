# Feature: tui-v3-integration, Property 7: Key dispatch is deterministic and complete
# Feature: tui-v3-integration, Property 8: NORMAL mode suppresses all unrecognized printable keys
# Feature: tui-v3-integration, Property 10: CommandPalette bypass is absolute
"""Property-based tests for KeyDispatcher.

Tests KeyDispatcher from functualize._cli.tui.key_handler:
- Property 7: Key dispatch is deterministic and complete
- Property 8: NORMAL mode suppresses all unrecognized printable keys
- Property 10: CommandPalette bypass is absolute

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 12.1, 12.2**
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.key_handler import KEYMAPS, KeyDispatcher

# =============================================================================
# Constants
# =============================================================================

# Keys that are in the NORMAL keymap — must be excluded from Property 8
_NORMAL_KEYMAP_KEYS: set[str] = set(KEYMAPS[FocusMode.NORMAL].keys())

# All printable ASCII characters (space through tilde)
_PRINTABLE_CHARS = [chr(c) for c in range(32, 127)]

# Printable chars NOT in the NORMAL keymap — the suppression targets
_SUPPRESSIBLE_CHARS = [c for c in _PRINTABLE_CHARS if c not in _NORMAL_KEYMAP_KEYS]

# All key strings used across all keymaps for generation
_ALL_KEYMAP_KEYS: set[str] = set()
for _km in KEYMAPS.values():
    _ALL_KEYMAP_KEYS.update(_km.keys())

# Representative key strings for Property 7 — mix of mapped, unmapped, and special
_REPRESENTATIVE_KEYS = sorted(
    _ALL_KEYMAP_KEYS | {"a", "b", "z", "0", "9", "!", "@", "ctrl+x"}
)


# =============================================================================
# Helpers
# =============================================================================


def _make_event(key: str) -> MagicMock:
    """Create a mock key event with .key, .prevent_default(), .stop()."""
    event = MagicMock()
    event.key = key
    event.prevent_default = MagicMock()
    event.stop = MagicMock()
    return event


def _make_app(
    *, palette_active: bool = False, autocomplete_visible: bool = False
) -> MagicMock:
    """Create a mock app with screen_stack and action methods.

    Args:
        palette_active: If True, simulate CommandPalette on screen_stack.
        autocomplete_visible: If True, is_autocomplete_visible() returns True.
    """
    app = MagicMock()

    if palette_active:
        # Simulate CommandPalette on screen_stack[1:]
        # We need to make _is_overlay_active() return True.
        # The real implementation does: isinstance(s, CommandPalette)
        # We mock the import path by making screen_stack contain a CommandPalette-like obj.

        # We'll patch the method directly on the dispatcher instead.
        # Actually, let's set up screen_stack with a mock that passes isinstance check.
        app.screen_stack = [MagicMock()]  # screen_stack[0] is base screen
    else:
        app.screen_stack = [MagicMock()]  # Only base screen

    app.is_autocomplete_visible = MagicMock(return_value=autocomplete_visible)
    app.active_panel = None
    return app


# =============================================================================
# Strategies
# =============================================================================

_focus_mode_strategy = st.sampled_from(list(FocusMode))
_focus_zone_strategy = st.sampled_from(list(FocusZone))
_key_strategy = st.sampled_from(_REPRESENTATIVE_KEYS)
_suppressible_char_strategy = st.sampled_from(_SUPPRESSIBLE_CHARS)


# =============================================================================
# Property 7: Key dispatch is deterministic and complete
# =============================================================================


@pytest.mark.slow
class TestKeyDispatchDeterministicAndComplete:
    """Property 7: Key dispatch is deterministic and complete.

    For any (mode, zone, key) triple with identical FocusState, dispatch
    produces the same result on every invocation. Every key is either
    handled (returns True) or passed through (returns False), with no
    third outcome.

    **Validates: Requirements 1.1, 1.2, 1.4**
    """

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_same_input_same_result(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """Dispatch with same (mode, zone, key) always returns the same boolean."""
        # First dispatch
        fs1 = FocusState()
        fs1.force(mode, zone)
        app1 = _make_app()
        dispatcher1 = KeyDispatcher(fs1, app1)
        event1 = _make_event(key)
        result1 = dispatcher1.dispatch(event1)

        # Second dispatch — same setup
        fs2 = FocusState()
        fs2.force(mode, zone)
        app2 = _make_app()
        dispatcher2 = KeyDispatcher(fs2, app2)
        event2 = _make_event(key)
        result2 = dispatcher2.dispatch(event2)

        assert result1 == result2, (
            f"Non-deterministic dispatch for ({mode.name}, {zone.name}, {key!r}): "
            f"first={result1}, second={result2}"
        )

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_result_is_boolean(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """Dispatch always returns a boolean — no third outcome."""
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        event = _make_event(key)

        result = dispatcher.dispatch(event)

        assert isinstance(result, bool), (
            f"Expected bool result for ({mode.name}, {zone.name}, {key!r}), "
            f"got {type(result).__name__}: {result!r}"
        )

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_handled_implies_event_stopped(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """If dispatch returns True, event.prevent_default() and event.stop() were called."""
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        event = _make_event(key)

        result = dispatcher.dispatch(event)

        if result is True:
            event.prevent_default.assert_called()
            event.stop.assert_called()


# =============================================================================
# Property 8: NORMAL mode suppresses all unrecognized printable keys
# =============================================================================


@pytest.mark.slow
class TestNormalModeSuppressesUnrecognizedPrintable:
    """Property 8: NORMAL mode suppresses all unrecognized printable keys.

    For any single printable character that is NOT in KEYMAPS[FocusMode.NORMAL],
    when dispatched in NORMAL mode, event.prevent_default() and event.stop()
    are called, and dispatch returns True.

    **Validates: Requirements 1.3**
    """

    @given(char=_suppressible_char_strategy, zone=_focus_zone_strategy)
    def test_unrecognized_printable_suppressed(
        self, char: str, zone: FocusZone
    ) -> None:
        """Unrecognized printable chars in NORMAL mode are suppressed."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        event = _make_event(char)

        result = dispatcher.dispatch(event)

        assert result is True, (
            f"Expected True (suppressed) for unrecognized printable {char!r} "
            f"in NORMAL mode, got {result}"
        )
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    @given(char=_suppressible_char_strategy, zone=_focus_zone_strategy)
    def test_unrecognized_printable_no_action_invoked(
        self, char: str, zone: FocusZone
    ) -> None:
        """Suppressed keys do not invoke any action method on app or panel."""
        fs = FocusState()
        fs.force(FocusMode.NORMAL, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        event = _make_event(char)

        dispatcher.dispatch(event)

        # No action_* methods should have been called on the app
        # (MagicMock tracks calls — we check no action_ method was called)
        for call_name, _, _ in app.method_calls:
            assert not call_name.startswith("action_"), (
                f"Unexpected action call {call_name} for suppressed key {char!r}"
            )


# =============================================================================
# Property 10: CommandPalette bypass is absolute
# =============================================================================


@pytest.mark.slow
class TestCommandPaletteBypassAbsolute:
    """Property 10: CommandPalette bypass is absolute.

    For any key event dispatched while the CommandPalette is on the
    screen_stack, the KeyDispatcher returns False without calling any
    action, prevent_default, or stop.

    **Validates: Requirements 1.5, 12.1, 12.2**
    """

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_palette_active_returns_false(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, dispatch always returns False."""
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app(palette_active=True)
        dispatcher = KeyDispatcher(fs, app)

        # Patch _is_overlay_active to return True
        # (avoids needing real CommandPalette import in test env)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        result = dispatcher.dispatch(event)

        assert result is False, (
            f"Expected False (bypass) for key {key!r} with palette active, got {result}"
        )

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_palette_active_no_prevent_default(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, event.prevent_default() is never called."""
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app(palette_active=True)
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        dispatcher.dispatch(event)

        event.prevent_default.assert_not_called()

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_palette_active_no_stop(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, event.stop() is never called."""
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app(palette_active=True)
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        dispatcher.dispatch(event)

        event.stop.assert_not_called()

    @given(mode=_focus_mode_strategy, zone=_focus_zone_strategy, key=_key_strategy)
    def test_palette_active_no_action_called(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, no action methods are invoked."""
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app(palette_active=True)
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        dispatcher.dispatch(event)

        # Verify no action_ methods called on app
        for call_name, _, _ in app.method_calls:
            assert not call_name.startswith("action_"), (
                f"Unexpected action call {call_name} with palette active"
            )
