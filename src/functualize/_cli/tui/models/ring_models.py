"""Core data models for the multi-panel ring-based TUI architecture.

This module defines the pure data structures used by the PanelRingController,
FocusZoneManager, and related components. All models use dataclasses and have
no Textual dependency — they are testable in isolation.

This module is in the ``_cli/`` layer — it uses only stdlib and references
protocol types from ``functualize.plugin`` under TYPE_CHECKING.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp

    # Protocol types will be defined by task 1.1 in functualize.plugin.
    # Once created, replace Any with the actual protocol imports:
    #   from functualize.plugin import DisplayProvider, PanelProvider, ThemeProvider
    DisplayProvider = Any
    PanelProvider = Any
    ThemeProvider = Any


# ---------------------------------------------------------------------------
# PanelRingController state (serializable)
# ---------------------------------------------------------------------------


@dataclass
class PanelRingState:
    """Serializable state for PanelRingController.

    Captures the minimal state needed to persist and restore the controller
    between sessions or across reactive updates.
    """

    active_category: str = "hidden"  # "hidden" | "pre-flight" | "general"
    pre_flight_index: int = 0
    general_index: int = 0
    breadcrumb_stack: list[str] = field(default_factory=list)  # max 3 items


# ---------------------------------------------------------------------------
# Ring registration models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredPanel:
    """A panel registered in a ring.

    Frozen so it can be used as a stable reference; mutation happens at
    the ring level (insertion/removal), not on individual registrations.
    """

    provider: PanelProvider
    panel_id: str
    priority: int
    category: str  # "pre-flight" | "general"


@dataclass
class PanelRing:
    """An ordered ring of panels within a single category.

    Maintains sorted order by priority, respecting anchors for first/last
    positions. Anchored panels are pinned regardless of priority values.
    """

    category: str  # "pre-flight" | "general"
    _panels: list[RegisteredPanel] = field(default_factory=list)
    _anchors: dict[str, str] = field(default_factory=dict)  # "first"|"last" -> panel_id

    @property
    def size(self) -> int:
        """Return the number of panels in this ring."""
        return len(self._panels)

    def get_panel_at(self, index: int) -> RegisteredPanel | None:
        """Return the panel at the given index, or None if out of bounds."""
        if 0 <= index < len(self._panels):
            return self._panels[index]
        return None

    def set_anchor(self, position: str, panel_id: str) -> None:
        """Set an anchor position ("first" or "last") for a panel_id."""
        self._anchors[position] = panel_id

    def insert_panel(self, panel: RegisteredPanel) -> None:
        """Insert a panel sorted by priority, respecting anchors.

        Anchored panels:
        - "first" anchor is always at index 0.
        - "last" anchor is always at the final index.
        - Non-anchored panels are inserted between anchors, sorted ascending
          by priority.

        Tie-breaking depends on the ring category:
        - "pre-flight": ties broken alphabetically by panel_id.
        - "general": ties broken by registration order (appended after
          existing panels with the same priority).
        """
        # If this panel is the "first" anchor, always insert at position 0
        if self._anchors.get("first") == panel.panel_id:
            self._panels.insert(0, panel)
            return

        # If this panel is the "last" anchor, always append at end
        if self._anchors.get("last") == panel.panel_id:
            self._panels.append(panel)
            return

        # Determine insertion boundaries based on existing anchors
        start = 0
        end = len(self._panels)

        # If there's a "first" anchor already in the list, start after it
        if "first" in self._anchors:
            for i, p in enumerate(self._panels):
                if p.panel_id == self._anchors["first"]:
                    start = i + 1
                    break

        # If there's a "last" anchor already in the list, end before it
        if "last" in self._anchors:
            for i, p in enumerate(self._panels):
                if p.panel_id == self._anchors["last"]:
                    end = i
                    break

        # Find insertion point within [start, end) sorted by priority.
        # Tie-breaking strategy differs by category:
        # - pre-flight: alphabetical by panel_id (deterministic ordering)
        # - general: registration order (insert after same-priority panels)
        insert_at = end
        if self.category == "pre-flight":
            # Ties broken alphabetically by panel_id
            for i in range(start, end):
                existing = self._panels[i]
                if (panel.priority, panel.panel_id) < (
                    existing.priority,
                    existing.panel_id,
                ):
                    insert_at = i
                    break
        else:
            # General ring: ties broken by registration order
            # (insert after all existing panels with the same priority)
            for i in range(start, end):
                existing = self._panels[i]
                if panel.priority < existing.priority:
                    insert_at = i
                    break

        self._panels.insert(insert_at, panel)

    def remove_panel(self, panel_id: str) -> int | None:
        """Remove a panel by ID. Returns new ring size, or None if not found."""
        for i, p in enumerate(self._panels):
            if p.panel_id == panel_id:
                self._panels.pop(i)
                # Clean up anchors if we removed an anchored panel
                for position, anchored_id in list(self._anchors.items()):
                    if anchored_id == panel_id:
                        del self._anchors[position]
                return len(self._panels)
        return None


# ---------------------------------------------------------------------------
# Display ring models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredDisplay:
    """A display panel registered in the display ring."""

    provider: DisplayProvider
    display_id: str
    priority: int


@dataclass
class DisplayRing:
    """Ordered ring of display panels, filtered by visibility.

    Displays are ordered by priority (lower = first). Only displays whose
    provider returns ``should_show(cwd, app) == True`` are considered visible.
    """

    _displays: list[RegisteredDisplay] = field(default_factory=list)
    _current_index: int = 0

    def visible_displays(
        self, cwd: Path, app: FunctualizeApp
    ) -> list[RegisteredDisplay]:
        """Filter to only displays where should_show() is True."""
        return [d for d in self._displays if d.provider.should_show(cwd, app)]

    def insert_display(self, display: RegisteredDisplay) -> None:
        """Insert a display sorted by priority (ascending).

        Ties are broken by registration order (append after same-priority).
        """
        insert_at = len(self._displays)
        for i, existing in enumerate(self._displays):
            if display.priority < existing.priority:
                insert_at = i
                break
        self._displays.insert(insert_at, display)

    def next_display(self) -> int:
        """Advance to the next display. Returns the new index."""
        if not self._displays:
            return 0
        self._current_index = (self._current_index + 1) % len(self._displays)
        return self._current_index

    def prev_display(self) -> int:
        """Move to the previous display. Returns the new index."""
        if not self._displays:
            return 0
        self._current_index = (self._current_index - 1) % len(self._displays)
        return self._current_index

    @property
    def current_index(self) -> int:
        """Return the current display index."""
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        """Set the current display index."""
        self._current_index = value


# ---------------------------------------------------------------------------
# Theme state
# ---------------------------------------------------------------------------


@dataclass
class ThemeState:
    """Runtime state for the theming system.

    Tracks the active theme, all registered theme providers, and the
    resolved semantic variable mappings.
    """

    active_theme_id: str = "transparent"
    registered_themes: dict[str, ThemeProvider] = field(default_factory=dict)
    semantic_variables: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Breadcrumb state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BreadcrumbState:
    """Immutable breadcrumb state for rendering.

    Represents the current panel position and navigation depth for
    display in the BreadcrumbHeader widget.
    """

    type_prefix: str  # "D" | "R" | "E"
    position: int  # 1-based
    total: int
    title: str
    sub_levels: tuple[str, ...] = ()  # max 2 items

    def render(self) -> str:
        """Render as '[R:1/3] Config Table > Field Detail: region'.

        Format: [TYPE:N/M] Title [> SubLevel1 [> SubLevel2]]
        """
        base = f"[{self.type_prefix}:{self.position}/{self.total}] {self.title}"
        if self.sub_levels:
            return base + " > " + " > ".join(self.sub_levels)
        return base
