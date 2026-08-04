"""Centralized focus state machine for the TUI.

Defines a Finite State Machine with 4 modes:
- COMMAND: SmartBar has focus (default home)
- NORMAL: Panel has focus, navigating with j/k
- INSERT: Editing a value within a panel
- FILTER: Filtering panel content with /

Transitions are explicit and validated — only defined transitions are allowed.

Also defines KEYMAPS — the single source of truth for ALL key bindings per mode.
The App's on_key reads the current mode and dispatches from this map.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from enum import Enum


class FocusMode(Enum):
    """The four interaction modes of the TUI."""

    COMMAND = "command"  # SmartBar focused
    NORMAL = "normal"  # Panel focused, navigating
    INSERT = "insert"  # Editing a cell value
    FILTER = "filter"  # Filtering/searching panel content


class FocusZone(Enum):
    """Physical location of focus."""

    SMARTBAR = "smartbar"
    DISPLAY = "display"
    PANEL = "panel"


# NOTE: The authoritative keymap lives in key_handler.py (KeyDispatcher).
# This copy is kept for reference and hint-generation only.
# Any keymap changes MUST be made in key_handler.py first.
KEYMAPS: dict[FocusMode, dict[str, str]] = {
    FocusMode.COMMAND: {
        "tab": "autocomplete_toggle",
        "ctrl+r": "panel_preflight_toggle",
        "ctrl+e": "panel_general_toggle",
        "ctrl+enter": "execute",
        "ctrl+q": "quit",
        "escape": "smartbar_clear",
        "ctrl+h": "ring_first",
        "ctrl+j": "ring_next",
        "ctrl+k": "ring_prev",
        "ctrl+l": "ring_last",
        "ctrl+u": "display_prev",
        "ctrl+i": "display_next",
        "shift+tab": "zone_cycle",
        "ctrl+s": "save_shortcut",
    },
    FocusMode.NORMAL: {
        "j": "cursor_down",
        "k": "cursor_up",
        "h": "cursor_left",
        "l": "cursor_right",
        "down": "cursor_down",
        "up": "cursor_up",
        "left": "cursor_left",
        "right": "cursor_right",
        "i": "enter_insert",
        "slash": "enter_filter",
        "enter": "drill_down",
        "ctrl+enter": "execute",
        "escape": "exit_panel",
        "ctrl+j": "ring_next",
        "ctrl+k": "ring_prev",
        "ctrl+h": "ring_first",
        "ctrl+l": "ring_last",
        "ctrl+r": "panel_preflight_toggle",
        "ctrl+e": "panel_general_toggle",
    },
    FocusMode.INSERT: {
        "escape": "exit_insert",
        "enter": "confirm_edit",
        "tab": "select_choice",
        "up": "choice_up",
        "down": "choice_down",
    },
    FocusMode.FILTER: {
        "escape": "exit_filter",
        "enter": "apply_filter",
    },
}


# Valid transitions: (from_mode, to_mode)
_VALID_TRANSITIONS: set[tuple[FocusMode, FocusMode]] = {
    (FocusMode.COMMAND, FocusMode.NORMAL),  # Ctrl+R/E/U/I → panel opens
    (FocusMode.NORMAL, FocusMode.COMMAND),  # Esc from panel → SmartBar
    (FocusMode.NORMAL, FocusMode.INSERT),  # 'i' in panel → edit mode
    (FocusMode.NORMAL, FocusMode.FILTER),  # '/' in panel → filter mode
    (FocusMode.INSERT, FocusMode.NORMAL),  # Esc/Enter from edit → back to navigate
    (FocusMode.FILTER, FocusMode.NORMAL),  # Esc/Enter from filter → back to navigate
    (FocusMode.COMMAND, FocusMode.COMMAND),  # Stay in command (no-op)
}


class FocusState:
    """Centralized focus state manager — single source of truth.

    All components read from this. Only the app mutates it via transition methods.
    Components subscribe to changes via the on_change callback.
    """

    def __init__(self) -> None:
        self._mode: FocusMode = FocusMode.COMMAND
        self._zone: FocusZone = FocusZone.SMARTBAR
        self._on_change: list[Callable[[FocusMode, FocusZone], None]] = []

    @property
    def mode(self) -> FocusMode:
        return self._mode

    @property
    def zone(self) -> FocusZone:
        return self._zone

    @property
    def mode_indicator(self) -> str:
        """For status bar: '-- NORMAL --', '-- INSERT --', etc. Empty for COMMAND."""
        if self._mode == FocusMode.COMMAND:
            return ""
        return f"-- {self._mode.value.upper()} --"

    def subscribe(self, callback: Callable[[FocusMode, FocusZone], None]) -> None:
        """Subscribe to mode/zone changes."""
        self._on_change.append(callback)

    def transition(self, to_mode: FocusMode, zone: FocusZone | None = None) -> bool:
        """Attempt a state transition.

        Returns True if the transition was valid and executed.
        Returns False if the transition is not allowed from the current state.
        """
        if (self._mode, to_mode) not in _VALID_TRANSITIONS:
            return False
        self._mode = to_mode
        if zone is not None:
            self._zone = zone
        elif to_mode == FocusMode.COMMAND:
            self._zone = FocusZone.SMARTBAR
        self._notify()
        return True

    def force(self, mode: FocusMode, zone: FocusZone) -> None:
        """Force a state (for initialization or recovery). No validation."""
        self._mode = mode
        self._zone = zone
        self._notify()

    def _notify(self) -> None:
        for cb in self._on_change:
            with contextlib.suppress(Exception):
                cb(self._mode, self._zone)

    # Convenience methods
    def enter_normal(self, zone: FocusZone = FocusZone.PANEL) -> bool:
        return self.transition(FocusMode.NORMAL, zone)

    def enter_insert(self) -> bool:
        return self.transition(FocusMode.INSERT)

    def enter_filter(self) -> bool:
        return self.transition(FocusMode.FILTER)

    def enter_command(self) -> bool:
        return self.transition(FocusMode.COMMAND, FocusZone.SMARTBAR)

    def exit_to_normal(self) -> bool:
        """From INSERT or FILTER → back to NORMAL."""
        if self._mode in (FocusMode.INSERT, FocusMode.FILTER):
            return self.transition(FocusMode.NORMAL)
        return False

    # Footer hints based on current mode
    def get_mode_actions(self) -> list[tuple[str, str]]:
        """Return mode-appropriate action hints for the status bar/footer."""
        if self._mode == FocusMode.COMMAND:
            return [
                ("Tab", "complete"),
                ("Ctrl+R", "pre-flight"),
                ("Ctrl+E", "general"),
                ("Ctrl+Q", "exit"),
            ]
        elif self._mode == FocusMode.NORMAL:
            return [
                ("Ctrl+Enter", "run"),
                ("j/k", "navigate"),
                ("i", "edit"),
                ("/", "filter"),
                ("Esc", "back"),
                ("Ctrl+J/K", "switch panel"),
            ]
        elif self._mode == FocusMode.INSERT:
            return [("Enter", "confirm"), ("Tab", "complete"), ("Esc", "cancel")]
        elif self._mode == FocusMode.FILTER:
            return [("Enter", "apply"), ("Esc", "clear")]
        return []
