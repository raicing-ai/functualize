"""PanelRingController — pure state machine for panel ring navigation.

Manages ring index state per category (pre-flight / general), category
switching, modular wrapping navigation, and breadcrumb sub-panel stack.

This module has no Textual dependency and is testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

_MAX_BREADCRUMB_DEPTH = 3


class Category(Enum):
    """Panel ring category state."""

    HIDDEN = "hidden"
    PRE_FLIGHT = "pre-flight"
    GENERAL = "general"


@dataclass
class PanelRingController:
    """Manages ring navigation, category switching, and breadcrumb state."""

    active_category: Category = Category.HIDDEN
    _pre_flight_index: int = 0
    _general_index: int = 0
    _breadcrumb_stack: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Category activation
    # ------------------------------------------------------------------

    def activate_pre_flight(self, ring_size: int) -> int | None:
        """Activate the pre-flight ring. Returns panel index or None if empty."""
        if ring_size == 0:
            return None
        self.active_category = Category.PRE_FLIGHT
        self._pre_flight_index = self._clamp(self._pre_flight_index, ring_size)
        return self._pre_flight_index

    def activate_general(self, ring_size: int) -> int | None:
        """Activate the general ring. Returns panel index or None if empty."""
        if ring_size == 0:
            return None
        self.active_category = Category.GENERAL
        self._general_index = self._clamp(self._general_index, ring_size)
        return self._general_index

    def collapse(self) -> None:
        """Hide panel slot, return to HIDDEN. Clears breadcrumb stack."""
        self.active_category = Category.HIDDEN
        self._breadcrumb_stack.clear()

    # ------------------------------------------------------------------
    # Ring navigation
    # ------------------------------------------------------------------

    def next_panel(self, ring_size: int) -> int:
        """Advance index with modular wrapping. Returns new index."""
        if ring_size <= 1:
            return 0
        idx = (self._active_index + 1) % ring_size
        self._set_active_index(idx)
        return idx

    def prev_panel(self, ring_size: int) -> int:
        """Retreat index with modular wrapping. Returns new index."""
        if ring_size <= 1:
            return 0
        idx = (self._active_index - 1) % ring_size
        self._set_active_index(idx)
        return idx

    def first_panel(self) -> int:
        """Jump to index 0. Returns 0."""
        self._set_active_index(0)
        return 0

    def last_panel(self, ring_size: int) -> int:
        """Jump to ring_size - 1. Returns new index."""
        idx = 0 if ring_size <= 0 else ring_size - 1
        self._set_active_index(idx)
        return idx

    # ------------------------------------------------------------------
    # Breadcrumb stack
    # ------------------------------------------------------------------

    def push_breadcrumb(self, label: str) -> bool:
        """Push sub-panel label. Returns False if max depth reached."""
        if len(self._breadcrumb_stack) >= _MAX_BREADCRUMB_DEPTH:
            return False
        self._breadcrumb_stack.append(label)
        return True

    def pop_breadcrumb(self) -> str | None:
        """Pop sub-panel label. Returns popped label or None if at root."""
        if not self._breadcrumb_stack:
            return None
        return self._breadcrumb_stack.pop()

    @property
    def breadcrumb_depth(self) -> int:
        """Current breadcrumb stack depth."""
        return len(self._breadcrumb_stack)

    # ------------------------------------------------------------------
    # Index access
    # ------------------------------------------------------------------

    @property
    def current_index(self) -> int:
        """Return the current index for the active category."""
        return self._active_index

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _active_index(self) -> int:
        """Get the index for the active category."""
        if self.active_category == Category.PRE_FLIGHT:
            return self._pre_flight_index
        if self.active_category == Category.GENERAL:
            return self._general_index
        return 0

    def _set_active_index(self, idx: int) -> None:
        """Set the index for the active category."""
        if self.active_category == Category.PRE_FLIGHT:
            self._pre_flight_index = idx
        elif self.active_category == Category.GENERAL:
            self._general_index = idx

    @staticmethod
    def _clamp(index: int, ring_size: int) -> int:
        """Clamp index to valid range [0, ring_size - 1]."""
        if ring_size <= 0:
            return 0
        if index >= ring_size:
            return ring_size - 1
        if index < 0:
            return 0
        return index
