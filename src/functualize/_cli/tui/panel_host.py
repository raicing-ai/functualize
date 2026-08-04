"""Unified PanelHost widget — provides consistent panel chrome and ring navigation.

PanelHost composes a BreadcrumbHeader, content area (ContentSwitcher), and
DynamicFooter to give every panel ring type (pre-flight, general) the same
chrome and keyboard navigation (Ctrl+H/J/K/L ring nav, Esc collapse).

The app drives PanelHost via methods — it emits no messages of its own.

This module is in the ``_cli/`` layer — it imports Textual at runtime.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, cast

try:
    from textual.containers import Vertical
    from textual.widget import Widget
except ImportError as _exc:
    raise ImportError(
        "PanelHost requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.tui.breadcrumb_header_widget import BreadcrumbHeader
from functualize._cli.tui.dynamic_footer_widget import DynamicFooterWidget
from functualize._cli.tui.models.ring_models import BreadcrumbState

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from functualize._cli.tui.focus import FocusState


class PanelHost(Widget):
    """Unified panel chrome and navigation for any panel ring type.

    Composes: BreadcrumbHeader (top) + content container + DynamicFooter (bottom).
    Manages a ring of panel widgets (ordered list) and handles ring navigation
    by showing/hiding panel widgets directly (no ContentSwitcher — it causes
    height issues in inline mode).

    Hidden by default (display: none). Shows when activated via activate().
    """

    can_focus = False  # Focus goes to the active panel widget, not the host

    DEFAULT_CSS = """
    PanelHost {
        height: auto;
        min-height: 0;
        display: none;
    }
    PanelHost.active {
        display: block;
    }
    PanelHost .panel-host-breadcrumb {
        height: 1;
        background: $surface;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    PanelHost .panel-host-footer {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    PanelHost .panel-host-content {
        height: auto;
        min-height: 1;
        max-height: 16;
        overflow-y: auto;
    }
    PanelHost .panel-host-content > * {
        display: none;
    }
    PanelHost .panel-host-content > .panel-visible {
        display: block;
    }
    """

    def __init__(
        self,
        type_prefix: str,
        *,
        id: str | None = None,
        focus_state: FocusState | None = None,
    ) -> None:
        super().__init__(id=id)
        self._type_prefix = type_prefix
        self._panels: list[tuple[str, Widget]] = []
        self._current_index: int = 0
        self._breadcrumb_stack: list[str] = []
        self._mounted: bool = False
        self._focus_state = focus_state
        # Sub-views pushed on top of the ring panel (drill-downs), kept in
        # lockstep with _breadcrumb_stack. See push_view().
        self._view_stack: list[tuple[str, Widget]] = []

    def compose(self) -> ComposeResult:
        """Compose: breadcrumb header, content area, dynamic footer."""
        yield BreadcrumbHeader("", classes="panel-host-breadcrumb")
        yield Vertical(classes="panel-host-content")
        yield DynamicFooterWidget("", classes="panel-host-footer")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_panels(self, panels: list[tuple[str, Widget]]) -> None:
        """Set the ordered list of (title, widget) pairs in the ring.

        Uses mount-once semantics: new panels are mounted into the content
        container. Previously mounted panels from other rings remain hidden
        via CSS (display: none). This avoids async mount/unmount races.
        """
        if not panels:
            return

        # Skip if already set with this exact panels list
        if self._panels is panels and self._mounted:
            return

        self._panels = panels
        self._current_index = 0
        self._breadcrumb_stack = []
        self.clear_views()

        # Mount new panels alongside any existing hidden ones.
        # Old panels from previous rings stay in the DOM (hidden via CSS)
        # until garbage collected — no remove_children() race.
        content = self.query_one(".panel-host-content", Vertical)

        # Hide ALL existing children (previous ring's panels)
        for child in content.children:
            child.remove_class("panel-visible")

        # Mount the new panels (they have unique IDs from _panel_id_seq)
        for _title, widget in panels:
            widget.remove_class("panel-visible")
            # Only mount if not already in this container
            if widget not in content._nodes:
                content.mount(widget)

        self._mounted = True
        self._show_current_panel()

    def activate(self, start_index: int = 0) -> None:
        """Show the host, display panel at start_index, update chrome, focus panel.

        Args:
            start_index: Which panel to show initially (0-based). Defaults to 0.
        """
        if not self._panels:
            return

        self.add_class("active")
        self._breadcrumb_stack = []
        self.clear_views()
        self._current_index = max(0, min(start_index, len(self._panels) - 1))
        self._show_current_panel()
        self._update_chrome()
        # Focus the current panel widget
        current = self.current_panel_widget
        if current and hasattr(current, "focus"):
            current.focus()

    def collapse(self) -> None:
        """Hide the host, drop any sub-views, clear chrome."""
        self.remove_class("active")
        self._breadcrumb_stack = []
        self.clear_views()
        self._clear_chrome()

    @property
    def is_active(self) -> bool:
        """Whether the panel host is currently visible/active."""
        return self.has_class("active")

    def set_type_prefix(self, type_prefix: str) -> None:
        """Public setter for the ring's breadcrumb type-prefix."""
        self._type_prefix = type_prefix

    @property
    def current_index(self) -> int:
        """Public accessor for the ring's current panel index."""
        return self._current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        self._current_index = value

    def navigate_next(self) -> None:
        """Advance to the next panel in the ring (wraps)."""
        if len(self._panels) <= 1:
            return
        self._current_index = (self._current_index + 1) % len(self._panels)
        self._show_current_panel()
        self._update_chrome()
        current = self.current_panel_widget
        if current and hasattr(current, "focus"):
            current.focus()

    def navigate_prev(self) -> None:
        """Move to the previous panel in the ring (wraps)."""
        if len(self._panels) <= 1:
            return
        self._current_index = (self._current_index - 1) % len(self._panels)
        self._show_current_panel()
        self._update_chrome()
        current = self.current_panel_widget
        if current and hasattr(current, "focus"):
            current.focus()

    def navigate_first(self) -> None:
        """Jump to the first panel in the ring."""
        if not self._panels:
            return
        self._current_index = 0
        self._show_current_panel()
        self._update_chrome()
        current = self.current_panel_widget
        if current and hasattr(current, "focus"):
            current.focus()

    def navigate_last(self) -> None:
        """Jump to the last panel in the ring."""
        if not self._panels:
            return
        self._current_index = len(self._panels) - 1
        self._show_current_panel()
        self._update_chrome()
        current = self.current_panel_widget
        if current and hasattr(current, "focus"):
            current.focus()

    @property
    def breadcrumb_depth(self) -> int:
        """Return the current breadcrumb depth (0 = root level)."""
        return len(self._breadcrumb_stack)

    def push_breadcrumb(self, sub_title: str) -> None:
        """Push a sub-level onto the breadcrumb stack (max 2 sub-levels)."""
        if len(self._breadcrumb_stack) < 2:
            self._breadcrumb_stack.append(sub_title)
            self._update_chrome()

    def pop_breadcrumb(self) -> bool:
        """Pop one sub-level. Returns True if popped, False if at root."""
        if self._breadcrumb_stack:
            self._breadcrumb_stack.pop()
            self._update_chrome()
            return True
        return False

    def handle_esc(self) -> bool:
        """Handle Esc. Returns True if handled (popped view/breadcrumb or collapsed)."""
        if self._view_stack:
            self.pop_view()
            return True
        if self._breadcrumb_stack:
            self._breadcrumb_stack.pop()
            self._update_chrome()
            return True
        # At root level — collapse
        self.collapse()
        return True

    # ------------------------------------------------------------------
    # View stack — drill-down sub-views
    # ------------------------------------------------------------------

    def push_view(self, widget: Widget, sub_title: str) -> None:
        """Push a sub-view on top of the current ring panel.

        This is what makes a drill-down's keys work. ``current_panel_widget``
        (and therefore the app's ``active_panel``, and therefore
        ``KeyDispatcher._resolve_target``) returns the top of this stack, so
        j/k/i/Enter route to the sub-view through the existing dispatch path
        with no second key-routing mechanism.

        The alternative — leaving the list panel active and giving it an
        ``in_detail`` mode flag — is what left the file detail view with
        every key dead except Esc: the keys still resolved to the list panel
        and moved its hidden cursor.

        Pushes a matching breadcrumb level, so the two stacks stay aligned.
        No-op past the breadcrumb's 2-sub-level budget.
        """
        if len(self._breadcrumb_stack) >= 2:
            return

        content = self.query_one(".panel-host-content", Vertical)
        if widget not in content._nodes:
            content.mount(widget)

        self._view_stack.append((sub_title, widget))
        self._breadcrumb_stack.append(sub_title)
        self._show_current_panel()
        self._update_chrome()
        if hasattr(widget, "focus"):
            widget.focus()

    def pop_view(self) -> bool:
        """Pop the top sub-view, revealing what is underneath.

        Returns True if a view was popped, False if the stack was empty.
        """
        if not self._view_stack:
            return False

        _title, widget = self._view_stack.pop()
        if self._breadcrumb_stack:
            self._breadcrumb_stack.pop()

        widget.remove_class("panel-visible")
        with contextlib.suppress(Exception):
            widget.remove()

        self._show_current_panel()
        self._update_chrome()
        current = self.current_panel_widget
        if current and hasattr(current, "focus"):
            current.focus()
        return True

    def clear_views(self) -> None:
        """Drop every sub-view — used when the ring is rebuilt or collapsed."""
        while self._view_stack:
            _title, widget = self._view_stack.pop()
            widget.remove_class("panel-visible")
            with contextlib.suppress(Exception):
                widget.remove()

    @property
    def view_depth(self) -> int:
        """How many sub-views are stacked on the ring panel."""
        return len(self._view_stack)

    @property
    def current_panel_widget(self) -> Widget | None:
        """Return the widget that currently owns the screen and the keys.

        The top sub-view if one is pushed, otherwise the ring's current panel.
        """
        if self._view_stack:
            return self._view_stack[-1][1]
        if not self._panels or self._current_index >= len(self._panels):
            return None
        return self._panels[self._current_index][1]

    @property
    def current_title(self) -> str:
        """Return the title of the currently displayed panel."""
        if not self._panels or self._current_index >= len(self._panels):
            return ""
        return self._panels[self._current_index][0]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _show_current_panel(self) -> None:
        """Show only the widget that currently owns the screen, hide the rest.

        With a sub-view pushed, every ring panel is hidden and the top view
        is shown in its place.
        """
        top_view = self._view_stack[-1][1] if self._view_stack else None

        for i, (_title, widget) in enumerate(self._panels):
            if top_view is None and i == self._current_index:
                widget.add_class("panel-visible")
            else:
                widget.remove_class("panel-visible")

        for _title, widget in self._view_stack:
            if widget is top_view:
                widget.add_class("panel-visible")
            else:
                widget.remove_class("panel-visible")

    def _update_chrome(self) -> None:
        """Update breadcrumb header and dynamic footer for the current panel.

        Delegates to update_chrome_with_focus(focused=True) for the footer,
        maintaining existing behavior for all callers (navigate_next/prev,
        activate, push/pop_breadcrumb).
        """
        self._update_breadcrumb_only()
        self.update_chrome_with_focus(focused=True)

    def _update_breadcrumb_only(self) -> None:
        """Update only the breadcrumb header (independent of focus state)."""
        if not self._panels:
            return

        title = self._panels[self._current_index][0]

        state = BreadcrumbState(
            type_prefix=self._type_prefix,
            position=self._current_index + 1,
            total=len(self._panels),
            title=title,
            sub_levels=tuple(self._breadcrumb_stack),
        )
        breadcrumb = self.query_one(".panel-host-breadcrumb", BreadcrumbHeader)
        breadcrumb.update_state(state)

    def update_chrome_with_focus(self, focused: bool) -> None:
        """Update footer with focus-awareness.

        When focused=True: shows ring nav hints (if at depth 0 with multiple
        panels) followed by panel-specific actions.
        When focused=False: shows generic "how to get here" hints.

        Also updates the breadcrumb (unchanged behavior).
        """
        if not self._panels:
            return
        # Read hints off whatever owns the keys — with a sub-view pushed the
        # ring panel's hints would be a lie.
        widget = self.current_panel_widget
        if widget is None:
            return

        actions: list[tuple[str, str]] = []
        if focused:
            # Ring nav only at depth 0 with multiple panels
            if self.breadcrumb_depth == 0 and len(self._panels) > 1:
                actions.append(("Ctrl+J/K", "switch"))
            panel_actions = self._get_panel_actions(widget, focused=True)
            actions.extend(panel_actions)
        else:
            actions = [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

        footer = self.query_one(".panel-host-footer", DynamicFooterWidget)
        footer.update_actions(actions)

        # Also update breadcrumb (unchanged behavior)
        self._update_breadcrumb_only()

    def _clear_chrome(self) -> None:
        """Clear breadcrumb header and footer content."""
        with contextlib.suppress(Exception):
            self.query_one(".panel-host-breadcrumb", BreadcrumbHeader).clear_state()
        with contextlib.suppress(Exception):
            self.query_one(".panel-host-footer", DynamicFooterWidget).clear_actions()

    def _get_panel_actions(
        self, widget: Widget, focused: bool
    ) -> list[tuple[str, str]]:
        """Get available actions from a panel widget.

        Falls back to [("Esc", "back")] if widget doesn't implement
        get_available_actions.
        """
        if hasattr(widget, "get_available_actions") and callable(
            widget.get_available_actions
        ):
            try:
                return cast(
                    "list[tuple[str, str]]", widget.get_available_actions(focused)
                )
            except Exception as exc:
                # get_available_actions is implemented per-panel; a bug in
                # one panel's implementation should not crash the footer —
                # log it and fall back to the default action set.
                self.log.warning(
                    f"_get_panel_actions: {type(widget).__name__}"
                    f".get_available_actions() raised "
                    f"({type(exc).__name__}): {exc}"
                )
        return [("Esc", "back")]
