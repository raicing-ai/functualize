"""Tests for breadcrumb depth guard on ring navigation.

Verifies that:
1. Ring navigation (Ctrl+J/K/H/L) is blocked when breadcrumb depth > 0
2. Ring navigation works normally when breadcrumb depth == 0
3. PanelHost.breadcrumb_depth property returns correct value

Requirements: R7-AC1, R7-AC2, R7-AC3
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from functualize._cli.tui.panel_host import PanelHost

# =============================================================================
# Test: PanelHost.breadcrumb_depth property
# =============================================================================


class TestBreadcrumbDepthProperty:
    """PanelHost.breadcrumb_depth returns len(_breadcrumb_stack)."""

    def test_depth_zero_at_init(self) -> None:
        """Breadcrumb depth is 0 when freshly constructed."""
        with patch.object(PanelHost, "__init_subclass__", lambda **kw: None):
            host = PanelHost.__new__(PanelHost)
            host._breadcrumb_stack = []
        assert host.breadcrumb_depth == 0

    def test_depth_one_after_push(self) -> None:
        """Breadcrumb depth is 1 after one push."""
        with patch.object(PanelHost, "__init_subclass__", lambda **kw: None):
            host = PanelHost.__new__(PanelHost)
            host._breadcrumb_stack = ["Detail: port"]
        assert host.breadcrumb_depth == 1

    def test_depth_two_after_two_pushes(self) -> None:
        """Breadcrumb depth is 2 after two pushes."""
        with patch.object(PanelHost, "__init_subclass__", lambda **kw: None):
            host = PanelHost.__new__(PanelHost)
            host._breadcrumb_stack = ["Detail: port", "Edit: value"]
        assert host.breadcrumb_depth == 2

    def test_depth_decreases_after_pop(self) -> None:
        """Breadcrumb depth decreases when stack is popped."""
        with patch.object(PanelHost, "__init_subclass__", lambda **kw: None):
            host = PanelHost.__new__(PanelHost)
            host._breadcrumb_stack = ["Detail: port"]
        assert host.breadcrumb_depth == 1
        host._breadcrumb_stack.pop()
        assert host.breadcrumb_depth == 0


# =============================================================================
# Test: Ring navigation blocked when breadcrumb depth > 0
# =============================================================================


class TestRingNavigationBlocked:
    """Ring navigation actions are no-ops when breadcrumb depth > 0 (R7-AC1)."""

    def _make_tui_with_active_panel_host(self, breadcrumb_depth: int = 0) -> MagicMock:
        """Create a mock TUI app with a panel host at given breadcrumb depth."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        # Set up mock panel host
        panel_host = MagicMock()
        panel_host.is_active = True
        panel_host.breadcrumb_depth = breadcrumb_depth
        tui._panel_host = panel_host
        # Real FocusState (COMMAND/SMARTBAR): the zone-aware active_panel
        # resolves through the panel host, as before the convergence.
        from functualize._cli.tui.focus import FocusState

        tui._focus_state = FocusState()
        return tui

    def test_ring_next_blocked_at_depth_1(self) -> None:
        """action_ring_next is a no-op when breadcrumb depth is 1."""
        tui = self._make_tui_with_active_panel_host(breadcrumb_depth=1)
        tui.action_ring_next()
        tui._panel_host.navigate_next.assert_not_called()

    def test_ring_prev_blocked_at_depth_1(self) -> None:
        """action_ring_prev is a no-op when breadcrumb depth is 1."""
        tui = self._make_tui_with_active_panel_host(breadcrumb_depth=1)
        tui.action_ring_prev()
        tui._panel_host.navigate_prev.assert_not_called()

    def test_ring_first_blocked_at_depth_1(self) -> None:
        """action_ring_first is a no-op when breadcrumb depth is 1."""
        tui = self._make_tui_with_active_panel_host(breadcrumb_depth=1)
        tui.action_ring_first()
        tui._panel_host.navigate_first.assert_not_called()

    def test_ring_last_blocked_at_depth_1(self) -> None:
        """action_ring_last is a no-op when breadcrumb depth is 1."""
        tui = self._make_tui_with_active_panel_host(breadcrumb_depth=1)
        tui.action_ring_last()
        tui._panel_host.navigate_last.assert_not_called()

    def test_ring_next_blocked_at_depth_2(self) -> None:
        """action_ring_next is a no-op when breadcrumb depth is 2."""
        tui = self._make_tui_with_active_panel_host(breadcrumb_depth=2)
        tui.action_ring_next()
        tui._panel_host.navigate_next.assert_not_called()

    def test_ring_prev_blocked_at_depth_2(self) -> None:
        """action_ring_prev is a no-op when breadcrumb depth is 2."""
        tui = self._make_tui_with_active_panel_host(breadcrumb_depth=2)
        tui.action_ring_prev()
        tui._panel_host.navigate_prev.assert_not_called()


# =============================================================================
# Test: Ring navigation works when breadcrumb depth == 0
# =============================================================================


class TestRingNavigationAllowed:
    """Ring navigation works normally when breadcrumb depth == 0 (R7-AC2)."""

    def _make_tui_with_active_panel_host(self) -> MagicMock:
        """Create a mock TUI app with panel host at depth 0."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        panel_host = MagicMock()
        panel_host.is_active = True
        panel_host.breadcrumb_depth = 0
        tui._panel_host = panel_host
        # Real FocusState (COMMAND/SMARTBAR): the zone-aware active_panel
        # resolves through the panel host, as before the convergence.
        from functualize._cli.tui.focus import FocusState

        tui._focus_state = FocusState()
        return tui

    def test_ring_next_works_at_depth_0(self) -> None:
        """action_ring_next navigates when breadcrumb depth is 0."""
        tui = self._make_tui_with_active_panel_host()
        tui.action_ring_next()
        tui._panel_host.navigate_next.assert_called_once()

    def test_ring_prev_works_at_depth_0(self) -> None:
        """action_ring_prev navigates when breadcrumb depth is 0."""
        tui = self._make_tui_with_active_panel_host()
        tui.action_ring_prev()
        tui._panel_host.navigate_prev.assert_called_once()

    def test_ring_first_works_at_depth_0(self) -> None:
        """action_ring_first navigates when breadcrumb depth is 0."""
        tui = self._make_tui_with_active_panel_host()
        tui.action_ring_first()
        tui._panel_host.navigate_first.assert_called_once()

    def test_ring_last_works_at_depth_0(self) -> None:
        """action_ring_last navigates when breadcrumb depth is 0."""
        tui = self._make_tui_with_active_panel_host()
        tui.action_ring_last()
        tui._panel_host.navigate_last.assert_called_once()


# =============================================================================
# Test: Ring navigation no-op when panel host is inactive
# =============================================================================


class TestRingNavigationInactive:
    """Ring navigation is a no-op when panel host is not active."""

    def test_ring_next_noop_when_inactive(self) -> None:
        """action_ring_next is a no-op when panel host is inactive."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        panel_host = MagicMock()
        panel_host.is_active = False
        panel_host.breadcrumb_depth = 0
        tui._panel_host = panel_host

        tui.action_ring_next()
        panel_host.navigate_next.assert_not_called()


# =============================================================================
# Test: Esc pops breadcrumb when depth > 0 (R7-AC3)
# =============================================================================


class TestEscPopsBreadcrumb:
    """Esc pops breadcrumb when depth > 0 rather than collapsing host."""

    def test_esc_pops_breadcrumb_at_depth_1(self) -> None:
        """handle_esc pops one level when depth is 1."""
        with patch.object(PanelHost, "__init_subclass__", lambda **kw: None):
            host = PanelHost.__new__(PanelHost)
            host._breadcrumb_stack = ["Detail: port"]
            host._panels = [("Config Table", MagicMock())]
            host._current_index = 0
            host._type_prefix = "R"
            host._view_stack = []
            # Mock methods needed for _update_chrome
            host.query_one = MagicMock()

        assert host.breadcrumb_depth == 1
        result = host.handle_esc()
        assert result is True
        assert host.breadcrumb_depth == 0

    def test_esc_collapses_at_depth_0(self) -> None:
        """handle_esc collapses the host when already at depth 0."""
        with patch.object(PanelHost, "__init_subclass__", lambda **kw: None):
            host = PanelHost.__new__(PanelHost)
            host._breadcrumb_stack = []
            host._panels = [("Config Table", MagicMock())]
            host._current_index = 0
            host._view_stack = []
            # Mock methods needed for collapse
            host.remove_class = MagicMock()
            host.query_one = MagicMock()

        assert host.breadcrumb_depth == 0
        result = host.handle_esc()
        assert result is True
        # Collapse clears the breadcrumb stack (which is already empty) and removes CSS class
        host.remove_class.assert_called_with("active")
