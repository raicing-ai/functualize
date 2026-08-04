"""Extension protocols for TUI architecture v2.

Defines @runtime_checkable protocols for all extension points.
Plugin authors implement these protocols to contribute panels, displays,
themes, header/status bar items, and post-run stamps to the TUI.

All protocols are importable from ``functualize.plugin``.

Usage:
    from functualize.plugin import DisplayProvider, PanelProvider, ThemeProvider
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from functualize._cli.data.pending_execution import PendingExecution
    from functualize.app.core import FunctualizeApp


# ---------------------------------------------------------------------------
# Forward-reference type stubs for protocols that reference types not yet
# defined in the codebase. These are declared here so the protocols can use
# them in TYPE_CHECKING without hard imports.
# ---------------------------------------------------------------------------


class SessionState:
    """Placeholder for runtime session state (to be implemented)."""

    ...


# ---------------------------------------------------------------------------
# Extension Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class SignatureProvider(Protocol):
    """Provides content for the signature slot above display panels.

    Implementations render a single-line signature string shown at the
    top of the TUI. Multiple providers are stacked by priority (lower first).
    """

    priority: int

    def render_signature(self, app: FunctualizeApp) -> str | None:
        """Render signature text, or None to skip this provider."""
        ...


@runtime_checkable
class InteractiveContent(Protocol):
    """The one interaction contract shared by every key-receiving widget.

    Whether a widget lives in the PanelHost ring, a drill-down sub-view, or
    the display slot, it becomes interactive the same way (the PanelHost
    idiom — there is no second key-routing mechanism):

    - ``can_focus = True`` so zone focus can land on it,
    - ``action_*`` methods (``action_cursor_down``, ``action_drill_down``, …)
      reached via ``KEYMAPS[mode] → KeyDispatcher._resolve_target``,
    - :meth:`get_available_actions` for the dynamic footer,
    - drill-down via a namespaced ``Message`` the app routes to the host's
      ``push_view``.

    Implementing this protocol is opt-in: hosts fall back gracefully
    (footer default, keys inert) when a widget omits it.
    """

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return (key, label) tuples for the dynamic footer."""
        ...


@runtime_checkable
class DisplayProvider(Protocol):
    """Provides an above-header display panel with CWD-contextual visibility.

    Display panels show ambient situational awareness (Docker services,
    Git status, etc.) and support auto-refresh and job-linking.

    The widgets yielded by :meth:`compose_display` may satisfy
    :class:`InteractiveContent` (plus ``can_focus``/``action_*``) to become
    interactive when the DISPLAY zone is focused — same contract as PanelHost
    panels.
    """

    display_id: str
    display_title: str
    display_priority: int
    refresh_interval: float | None  # min 0.5s when set
    linked_jobs: list[str] | None
    linked_groups: list[str] | None

    def should_show(self, cwd: Path, app: FunctualizeApp) -> bool:
        """Return True if this display should be visible for the given CWD."""
        ...

    def compose_display(self) -> ComposeResult:
        """Compose the display widget tree."""
        ...

    def refresh(self) -> None:
        """Called at refresh_interval to update display content."""
        ...

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return (key, label) tuples for the dynamic footer."""
        ...


@runtime_checkable
class PanelProvider(Protocol):
    """Provides a panel for the pre-flight or general ring.

    Panels are shown in the Panel Slot below the SmartBar, navigable
    via Ctrl+H/J/K/L within their ring.
    """

    panel_id: str
    panel_title: str
    panel_priority: int
    panel_category: str  # "pre-flight" | "general"

    def should_show(self, pending: PendingExecution | None) -> bool:
        """Return True if this panel should appear in the ring."""
        ...

    def compose_panel(self) -> ComposeResult:
        """Compose the panel widget tree."""
        ...

    def on_activate(self, pending: PendingExecution | None) -> None:
        """Called when this panel becomes the active panel in the ring."""
        ...

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Return (key, label) tuples for the dynamic footer."""
        ...


@runtime_checkable
class HeaderItemProvider(Protocol):
    """Provides an item rendered in the header bar.

    Items are collected, filtered (None skipped), sorted by priority,
    and joined with double-space separator.
    """

    item_id: str
    item_priority: int

    def render_item(self, app: FunctualizeApp) -> str | None:
        """Render header item text, or None to skip."""
        ...


@runtime_checkable
class StatusBarItemProvider(Protocol):
    """Provides an item rendered in the status bar.

    Items are collected, filtered (None skipped), sorted by priority,
    and joined with double-space separator.
    """

    item_id: str
    item_priority: int

    def render_item(self, app: FunctualizeApp, state: SessionState) -> str | None:
        """Render status bar item text, or None to skip."""
        ...


@runtime_checkable
class BarRenderer(Protocol):
    """Overrides default header or status bar rendering.

    When registered, replaces the default "join with double-space"
    rendering for the specified bar type. Last registered wins.
    """

    bar_type: str  # "header" | "status"

    def render(self, items: list[tuple[str, str]], context: dict[str, object]) -> str:
        """Render the bar from collected (id, text) pairs and context."""
        ...


@runtime_checkable
class ThemeProvider(Protocol):
    """Provides a CSS-based color theme for the TUI.

    Themes are registered by theme_id. The active theme's CSS is loaded
    at startup and can be hot-switched via settings.
    """

    theme_id: str
    theme_name: str

    def get_css(self) -> str:
        """Return the CSS string for this theme."""
        ...


@runtime_checkable
class PostRunStampProvider(Protocol):
    """Provides output printed to stdout on TUI exit.

    Stamps are rendered after the TUI unmounts, giving plugins a chance
    to print summary information to the terminal.
    """

    def render_stamp(self, session: SessionState) -> str | None:
        """Render stamp text, or None to skip."""
        ...


# ---------------------------------------------------------------------------
# ID Validation Utility
# ---------------------------------------------------------------------------

_EXTENSION_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")
_EXTENSION_ID_MAX_LENGTH = 64


def validate_extension_id(extension_id: str) -> bool:
    """Validate an extension ID string.

    Valid IDs are:
    - Non-empty
    - Lowercase alphanumeric, hyphens, and underscores only
    - Maximum 64 characters

    Args:
        extension_id: The ID string to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not extension_id:
        return False
    if len(extension_id) > _EXTENSION_ID_MAX_LENGTH:
        return False
    return _EXTENSION_ID_PATTERN.match(extension_id) is not None


__all__ = [
    "BarRenderer",
    "DisplayProvider",
    "HeaderItemProvider",
    "PanelProvider",
    "PostRunStampProvider",
    "SessionState",
    "SignatureProvider",
    "StatusBarItemProvider",
    "ThemeProvider",
    "validate_extension_id",
]
