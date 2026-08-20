# Feature: tui-v3-wiring, Property 4: CommandPalette blocks all dispatch
# Feature: tui-v3-wiring, Property 5: NORMAL mode suppresses unrecognized printable keys
"""Property-based tests for KeyDispatcher guard and NORMAL mode suppression.

Tests KeyDispatcher from functualize._cli.tui.key_handler:
- Property 4: CommandPalette blocks all dispatch
- Property 5: NORMAL mode suppresses unrecognized printable keys

**Validates: Requirements 10.4, 10.5, 15.3, 17.1, 17.2**
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

# Keys that are in the NORMAL keymap — must be excluded from Property 5
_NORMAL_KEYMAP_KEYS: set[str] = set(KEYMAPS[FocusMode.NORMAL].keys())


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


def _make_app(*, autocomplete_visible: bool = False) -> MagicMock:
    """Create a mock app with screen_stack and action methods.

    Args:
        autocomplete_visible: If True, is_autocomplete_visible() returns True.
    """
    app = MagicMock()
    app.screen_stack = [MagicMock()]  # Only base screen (no CommandPalette)
    app.is_autocomplete_visible = MagicMock(return_value=autocomplete_visible)
    app.active_panel = None
    return app


# =============================================================================
# Strategies
# =============================================================================

_focus_mode_strategy = st.sampled_from(list(FocusMode))
_focus_zone_strategy = st.sampled_from(list(FocusZone))

# Broad key strategy: random text strings to stress-test CommandPalette guard
_random_key_strategy = st.text(min_size=1, max_size=10, alphabet=st.characters())

# Printable characters using Unicode categories: Letter, Number, Punctuation, Symbol
_printable_char_strategy = st.characters(
    whitelist_categories=("L", "N", "P", "S")
).filter(lambda c: c not in _NORMAL_KEYMAP_KEYS)


# =============================================================================
# Property 4: CommandPalette blocks all dispatch
# =============================================================================


@pytest.mark.slow
class TestCommandPaletteBlocksAllDispatch:
    """Property 4: CommandPalette blocks all dispatch.

    For any key event dispatched while the CommandPalette is on the
    screen_stack, the KeyDispatcher returns False without calling any
    action, prevent_default, or stop, and without triggering any
    FocusState transition.

    **Validates: Requirements 10.4, 17.1, 17.2**
    """

    @given(
        mode=_focus_mode_strategy,
        zone=_focus_zone_strategy,
        key=_random_key_strategy,
    )
    def test_palette_active_returns_false(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, dispatch always returns False.

        **Validates: Requirements 10.4, 17.1**
        """
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        # Mock _is_overlay_active to return True
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        result = dispatcher.dispatch(event)

        assert result is False, (
            f"Expected False (bypass) for key {key!r} with palette active, got {result}"
        )

    @given(
        mode=_focus_mode_strategy,
        zone=_focus_zone_strategy,
        key=_random_key_strategy,
    )
    def test_palette_active_no_action_called(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, no action methods are invoked.

        **Validates: Requirements 17.1**
        """
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        dispatcher.dispatch(event)

        # Verify no action_ methods called on app
        for call_name, _, _ in app.method_calls:
            assert not call_name.startswith("action_"), (
                f"Unexpected action call {call_name} with palette active"
            )

    @given(
        mode=_focus_mode_strategy,
        zone=_focus_zone_strategy,
        key=_random_key_strategy,
    )
    def test_palette_active_no_event_suppression(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, prevent_default() and stop() are never called.

        **Validates: Requirements 10.4**
        """
        fs = FocusState()
        fs.force(mode, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        dispatcher.dispatch(event)

        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()

    @given(
        mode=_focus_mode_strategy,
        zone=_focus_zone_strategy,
        key=_random_key_strategy,
    )
    def test_palette_active_no_focus_state_transition(
        self, mode: FocusMode, zone: FocusZone, key: str
    ) -> None:
        """With CommandPalette active, no FocusState transition occurs.

        **Validates: Requirements 17.2**
        """
        fs = FocusState()
        fs.force(mode, zone)
        # Track transitions via subscriber
        transitions: list[tuple[FocusMode, FocusZone]] = []
        fs.subscribe(lambda m, z: transitions.append((m, z)))

        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        dispatcher._is_overlay_active = lambda: True  # type: ignore[method-assign]

        event = _make_event(key)
        dispatcher.dispatch(event)

        assert transitions == [], (
            f"FocusState transitioned to {transitions} while palette was active"
        )
        # Also verify mode and zone are unchanged
        assert fs.mode == mode, f"Mode changed from {mode} to {fs.mode}"
        assert fs.zone == zone, f"Zone changed from {zone} to {fs.zone}"


# =============================================================================
# Property 5: NORMAL mode suppresses unrecognized printable keys
# =============================================================================


@pytest.mark.slow
class TestNormalModeSuppressesUnrecognizedPrintable:
    """Property 5: NORMAL mode suppresses unrecognized printable keys.

    For any single printable character that is NOT in KEYMAPS[FocusMode.NORMAL],
    when dispatched in NORMAL mode, event.prevent_default() and event.stop()
    are called, dispatch returns True, and no action method is invoked.

    **Validates: Requirements 10.5, 15.3**
    """

    @given(char=_printable_char_strategy, zone=_focus_zone_strategy)
    def test_unrecognized_printable_suppressed(
        self, char: str, zone: FocusZone
    ) -> None:
        """Unrecognized printable chars in NORMAL mode are suppressed (returns True).

        **Validates: Requirements 10.5**
        """
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

    @given(char=_printable_char_strategy, zone=_focus_zone_strategy)
    def test_unrecognized_printable_event_stopped(
        self, char: str, zone: FocusZone
    ) -> None:
        """Suppressed keys have prevent_default() and stop() called.

        **Validates: Requirements 10.5, 15.3**
        """
        fs = FocusState()
        fs.force(FocusMode.NORMAL, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        event = _make_event(char)

        dispatcher.dispatch(event)

        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    @given(char=_printable_char_strategy, zone=_focus_zone_strategy)
    def test_unrecognized_printable_no_action_invoked(
        self, char: str, zone: FocusZone
    ) -> None:
        """Suppressed keys do not invoke any action method on app or panel.

        **Validates: Requirements 15.3**
        """
        fs = FocusState()
        fs.force(FocusMode.NORMAL, zone)
        app = _make_app()
        dispatcher = KeyDispatcher(fs, app)
        event = _make_event(char)

        dispatcher.dispatch(event)

        # No action_* methods should have been called on the app
        for call_name, _, _ in app.method_calls:
            assert not call_name.startswith("action_"), (
                f"Unexpected action call {call_name} for suppressed key {char!r}"
            )
