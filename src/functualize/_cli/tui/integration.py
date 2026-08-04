"""Integration helpers — patterns for wiring KeyDispatcher into a Textual App.

This module documents and provides utilities for integrating the v3 key
dispatch system into a Textual App. The key patterns are:

1. **set_focus(None) on NORMAL mode entry**: When transitioning from COMMAND
   to NORMAL mode, the App MUST call ``self.set_focus(None)`` to remove DOM
   focus from widgets (particularly the SmartBar Input). Without this, a
   focused Input widget consumes key events before they reach the App's
   ``on_key`` handler, meaning the KeyDispatcher never sees them.

2. **CommandPalette bypass**: The KeyDispatcher already implements this
   (Req 12.1–12.4) as its first guard in ``dispatch()``. No additional
   wiring is needed — the dispatcher checks ``screen_stack`` for
   ``CommandPalette`` and returns False (pass-through) when active.

3. **on_key wiring**: The App's ``on_key(event)`` method should simply
   delegate to ``self._key_dispatcher.dispatch(event)``.

Usage in future tui/app.py
--------------------------

.. code-block:: python

    from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
    from functualize._cli.tui.key_handler import KeyDispatcher
    from functualize._cli.tui.integration import enter_normal_mode

    class FunctualizeInlineTUI(App[int]):
        def __init__(self):
            super().__init__()
            self._focus_state = FocusState()
            self._key_dispatcher = KeyDispatcher(self._focus_state, self)

        def on_key(self, event):
            self._key_dispatcher.dispatch(event)

        def action_panel_command_toggle(self):
            # ... activate panel ...
            enter_normal_mode(self, self._focus_state, FocusZone.PANEL)

        def action_panel_general_toggle(self):
            # ... activate panel ...
            enter_normal_mode(self, self._focus_state, FocusZone.PANEL)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from functualize._cli.tui.focus import FocusState, FocusZone

__all__ = ["action_zone_cycle", "enter_normal_mode", "exit_to_command_mode"]


def enter_normal_mode(
    app: Any,
    focus_state: FocusState,
    zone: FocusZone = FocusZone.PANEL,
) -> bool:
    """Transition to NORMAL mode with the set_focus(None) fix applied.

    This ensures the Textual App's ``on_key`` handler receives all key
    events by removing DOM focus from any widget (particularly Input
    widgets that would otherwise consume keys before on_key fires).

    Args:
        app: The Textual App instance (must have ``set_focus`` method).
        focus_state: The FocusState FSM instance.
        zone: The target zone (defaults to PANEL).

    Returns:
        True if the transition succeeded, False if it was rejected by the FSM.

    Requirement References:
        - Req 1.5: NORMAL mode receives all keys via on_key
        - Req 12.1–12.4: CommandPalette protection (handled by KeyDispatcher)
    """
    success = focus_state.enter_normal(zone)
    if success:
        # Critical: remove DOM focus so on_key receives all keys
        # Without this, a focused Input widget consumes key events
        # before they bubble up to the App's on_key handler.
        set_focus = getattr(app, "set_focus", None)
        if set_focus is not None:
            set_focus(None)
    return success


def exit_to_command_mode(
    app: Any,
    focus_state: FocusState,
    smartbar: Any | None = None,
) -> bool:
    """Transition back to COMMAND mode and optionally focus the SmartBar.

    When exiting NORMAL mode back to COMMAND, the SmartBar should regain
    focus so the user can type commands. Positions cursor at the end
    to avoid selecting all text.

    Args:
        app: The Textual App instance.
        focus_state: The FocusState FSM instance.
        smartbar: Optional SmartBar widget to receive focus.

    Returns:
        True if the transition succeeded, False if rejected.
    """
    success = focus_state.enter_command()
    if success and smartbar is not None:
        focus_method = getattr(smartbar, "focus", None)
        if focus_method is not None:
            focus_method()
            # Move cursor to end to prevent select-all on focus
            smartbar.cursor_position = len(smartbar.value)
    return success


def action_zone_cycle(
    app: Any,
    focus_state: FocusState,
    get_visible_zones: Callable[[], set[FocusZone]],
    get_zone_widget: Callable[[FocusZone], Any | None],
) -> None:
    """Execute zone cycling: advance to next visible zone and focus its widget.

    Called when Shift+Tab is pressed in COMMAND or NORMAL mode. Determines
    which zones are currently visible, cycles to the next one in fixed order
    (SMARTBAR → DISPLAY → PANEL → wrap), and calls focus() on the target
    zone's primary widget.

    Args:
        app: The Textual App instance (unused directly, available for future use).
        focus_state: The FocusState FSM instance — owns the current zone.
        get_visible_zones: Callback returning the set of currently visible zones.
            Zones not visible (e.g., no display widget mounted, no panel ring
            active) should be excluded. SMARTBAR is always included.
        get_zone_widget: Callback mapping a FocusZone to its primary widget.
            Returns None if the zone has no focusable widget.

    Requirement References:
        - Req 10.1: COMMAND/NORMAL + Shift+Tab → cycle to next visible zone
        - Req 10.2: If DISPLAY not visible → skip it
        - Req 10.3: If PANEL not visible → skip, remain on SMARTBAR if no other zone
        - Req 10.4: On zone transition, call focus() on target zone's primary widget
        - Req 10.5: INSERT/FILTER → don't handle (handled by keymap — no mapping)
    """
    visible = get_visible_zones()
    new_zone = focus_state.cycle_zone(visible)
    widget = get_zone_widget(new_zone)
    if widget is not None:
        focus_method = getattr(widget, "focus", None)
        if focus_method is not None:
            focus_method()
