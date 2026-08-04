"""Focus state machine — single source of truth for mode + zone.

Pure Python, no Textual imports. Implements observer pattern for
change notification and validated (mode, zone) transitions.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

__all__ = ["FocusMode", "FocusZone", "FocusState"]


class FocusMode(Enum):
    """Vim-style mode for key dispatch."""

    COMMAND = "command"
    NORMAL = "normal"
    INSERT = "insert"
    FILTER = "filter"


class FocusZone(Enum):
    """Logical UI region that can receive focus."""

    SMARTBAR = "smartbar"
    DISPLAY = "display"
    PANEL = "panel"


class FocusState:
    """Validated state machine with (mode, zone) transitions.

    Enforces that only specific (from_mode → to_mode) pairs are allowed.
    Notifies subscribers on successful transitions. Initializes to
    (COMMAND, SMARTBAR) with no notifications fired.
    """

    _VALID_TRANSITIONS: set[tuple[FocusMode, FocusMode]] = {
        (FocusMode.COMMAND, FocusMode.NORMAL),
        (FocusMode.NORMAL, FocusMode.COMMAND),
        (FocusMode.NORMAL, FocusMode.INSERT),
        (FocusMode.NORMAL, FocusMode.FILTER),
        (FocusMode.INSERT, FocusMode.NORMAL),
        (FocusMode.FILTER, FocusMode.NORMAL),
        (FocusMode.COMMAND, FocusMode.COMMAND),
    }

    def __init__(self) -> None:
        self._mode: FocusMode = FocusMode.COMMAND
        self._zone: FocusZone = FocusZone.SMARTBAR
        self._subscribers: list[Callable[[FocusMode, FocusZone], None]] = []

    # --- Properties ---

    @property
    def mode(self) -> FocusMode:
        """Current focus mode."""
        return self._mode

    @property
    def zone(self) -> FocusZone:
        """Current focus zone."""
        return self._zone

    @property
    def mode_indicator(self) -> str:
        """Status bar indicator: empty for COMMAND, '-- MODE --' otherwise."""
        if self._mode is FocusMode.COMMAND:
            return ""
        return f"-- {self._mode.name} --"

    # --- Observer ---

    def subscribe(self, cb: Callable[[FocusMode, FocusZone], None]) -> None:
        """Register a callback invoked on every successful transition."""
        self._subscribers.append(cb)

    def _notify(self) -> None:
        """Invoke all subscribers with current (mode, zone)."""
        for cb in self._subscribers:
            cb(self._mode, self._zone)

    # --- Transitions ---

    def transition(self, to_mode: FocusMode, zone: FocusZone | None = None) -> bool:
        """Attempt a validated mode transition.

        Returns True if the transition succeeded, False if rejected.
        On success, updates mode/zone and notifies subscribers.

        Zone behavior:
        - If zone is provided: use it.
        - If zone is None and target is COMMAND: set zone to SMARTBAR.
        - If zone is None and target is not COMMAND: retain current zone.
        """
        if (self._mode, to_mode) not in self._VALID_TRANSITIONS:
            return False

        self._mode = to_mode

        if zone is not None:
            self._zone = zone
        elif to_mode is FocusMode.COMMAND:
            self._zone = FocusZone.SMARTBAR

        self._notify()
        return True

    def force(self, mode: FocusMode, zone: FocusZone) -> None:
        """Unchecked state set — for internal/testing use only.

        Sets mode and zone without validation or notification.
        """
        self._mode = mode
        self._zone = zone

    # --- Convenience shortcuts ---

    def enter_normal(self, zone: FocusZone = FocusZone.PANEL) -> bool:
        """Transition to NORMAL mode (from COMMAND or INSERT/FILTER)."""
        return self.transition(FocusMode.NORMAL, zone)

    def enter_insert(self) -> bool:
        """Transition to INSERT mode (only valid from NORMAL)."""
        return self.transition(FocusMode.INSERT)

    def enter_command(self) -> bool:
        """Transition to COMMAND mode (only valid from NORMAL)."""
        return self.transition(FocusMode.COMMAND)

    def exit_to_normal(self) -> bool:
        """Exit INSERT or FILTER back to NORMAL mode."""
        return self.transition(FocusMode.NORMAL)

    # --- Zone cycling ---

    def cycle_zone(self, visible_zones: set[FocusZone]) -> FocusZone:
        """Advance to next zone in fixed order, skipping invisible ones.

        Order: SMARTBAR → DISPLAY → PANEL → (wrap).
        If only one zone is visible, returns SMARTBAR without changing.
        Notifies subscribers so footers update on zone change.
        """
        cycle_order = [FocusZone.SMARTBAR, FocusZone.DISPLAY, FocusZone.PANEL]
        visible_cycle = [z for z in cycle_order if z in visible_zones]

        if len(visible_cycle) <= 1:
            return FocusZone.SMARTBAR

        try:
            current_idx = visible_cycle.index(self._zone)
        except ValueError:
            current_idx = 0

        next_idx = (current_idx + 1) % len(visible_cycle)
        new_zone = visible_cycle[next_idx]
        self._zone = new_zone
        self._notify()
        return new_zone
