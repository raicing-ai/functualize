"""PanelRing — pure state machine for ordered panel navigation with wrapping.

Zero Textual imports. This module manages an ordered list of panel IDs
with modular index arithmetic for next/prev/first/last navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["PanelRing"]


@dataclass
class PanelRing:
    """Manages ordered panel list with wrapping navigation.

    Attributes:
        prefix: Category prefix for breadcrumb display ("R" for pre-flight, "E" for general).
        panel_ids: Ordered list of panel identifier strings.
    """

    prefix: str
    panel_ids: list[str] = field(default_factory=list)
    _index: int = field(default=0, repr=False)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_index(self) -> int:
        """Return the current panel index."""
        return self._index

    @property
    def current_id(self) -> str | None:
        """Return the current panel ID, or None if the ring is empty."""
        if not self.panel_ids:
            return None
        return self.panel_ids[self._index]

    @property
    def breadcrumb(self) -> str:
        """Format: ``[R:1/3] Config Table``.

        Returns empty string if the panel list is empty.
        """
        if not self.panel_ids:
            return ""
        count = len(self.panel_ids)
        title = self.panel_ids[self._index]
        return f"[{self.prefix}:{self._index + 1}/{count}] {title}"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next(self) -> int:
        """Advance index by one, wrapping from N-1 to 0.

        No-op if the panel list is empty. Returns the new index.
        """
        if not self.panel_ids:
            return self._index
        self._index = (self._index + 1) % len(self.panel_ids)
        return self._index

    def prev(self) -> int:
        """Decrement index by one, wrapping from 0 to N-1.

        No-op if the panel list is empty. Returns the new index.
        """
        if not self.panel_ids:
            return self._index
        self._index = (self._index - 1) % len(self.panel_ids)
        return self._index

    def first(self) -> int:
        """Jump to the first panel (index 0).

        No-op if the panel list is empty. Returns 0.
        """
        if not self.panel_ids:
            return self._index
        self._index = 0
        return self._index

    def last(self) -> int:
        """Jump to the last panel (index N-1).

        No-op if the panel list is empty. Returns N-1.
        """
        if not self.panel_ids:
            return self._index
        self._index = len(self.panel_ids) - 1
        return self._index

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def set_panels(self, panel_ids: list[str]) -> None:
        """Replace the panel list, clamping index if it exceeds the new length.

        If the new list is empty, index is reset to 0.
        If the current index exceeds (new length - 1), it is clamped to
        the last valid position.
        """
        self.panel_ids = panel_ids
        if not panel_ids:
            self._index = 0
        elif self._index >= len(panel_ids):
            self._index = len(panel_ids) - 1
