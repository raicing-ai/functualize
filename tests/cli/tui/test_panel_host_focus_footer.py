"""Unit tests for focus-aware PanelHost footer (update_chrome_with_focus).

Tests verify footer content for focused vs unfocused states, with/without
breadcrumb depth, and single vs multiple panels.

Validates: Requirements R6-AC1, R6-AC2, R6-AC3, R6-AC4
"""

from __future__ import annotations

from functualize._cli.tui.panel_host import PanelHost


class _FakeFooter:
    """Stub for DynamicFooterWidget — records update_actions calls."""

    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []

    def update_actions(self, actions: list[tuple[str, str]]) -> None:
        self.actions = list(actions)

    def clear_actions(self) -> None:
        self.actions = []


class _FakeBreadcrumb:
    """Stub for BreadcrumbHeader."""

    def __init__(self) -> None:
        self.state = None

    def update_state(self, state: object) -> None:
        self.state = state

    def clear_state(self) -> None:
        self.state = None


class _FakePanel:
    """Stub panel widget that implements get_available_actions."""

    def __init__(self, actions: list[tuple[str, str]] | None = None) -> None:
        self._actions = actions or [("j/k", "navigate"), ("Esc", "back")]

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        if not focused:
            return [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]
        return self._actions


class _FakePanelNoActions:
    """Stub panel widget WITHOUT get_available_actions (tests fallback)."""

    pass


def _make_panel_host(
    panels: list[tuple[str, object]] | None = None,
    breadcrumb_stack: list[str] | None = None,
) -> tuple[PanelHost, _FakeFooter, _FakeBreadcrumb]:
    """Create a PanelHost with stubbed query_one to return fake widgets."""
    host = PanelHost.__new__(PanelHost)
    host._type_prefix = "R"
    host._panels = panels or []
    host._current_index = 0
    host._breadcrumb_stack = breadcrumb_stack or []
    host._mounted = False
    host._focus_state = None
    host._view_stack = []

    fake_footer = _FakeFooter()
    fake_breadcrumb = _FakeBreadcrumb()

    def fake_query_one(selector: str, widget_type: type | None = None):
        if "footer" in selector:
            return fake_footer
        if "breadcrumb" in selector:
            return fake_breadcrumb
        raise ValueError(f"Unknown selector: {selector}")

    host.query_one = fake_query_one  # type: ignore[assignment]

    return host, fake_footer, fake_breadcrumb


# ===========================================================================
# R6-AC2: Unfocused footer
# ===========================================================================


class TestUnfocusedFooter:
    """When focused=False, panel footer shows 'how to get here' hints."""

    def test_unfocused_shows_focus_and_cycle(self) -> None:
        """R6-AC2: Unfocused footer shows Ctrl+R focus and Shift+Tab cycle."""
        panel = _FakePanel()
        host, footer, _ = _make_panel_host(panels=[("Config", panel)])

        host.update_chrome_with_focus(focused=False)

        assert footer.actions == [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

    def test_unfocused_with_multiple_panels(self) -> None:
        """R6-AC2: Unfocused footer is the same regardless of panel count."""
        panel1 = _FakePanel()
        panel2 = _FakePanel()
        host, footer, _ = _make_panel_host(
            panels=[("Config", panel1), ("Files", panel2)]
        )

        host.update_chrome_with_focus(focused=False)

        assert footer.actions == [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

    def test_unfocused_with_breadcrumb_depth(self) -> None:
        """R6-AC2: Unfocused footer is the same even with breadcrumb depth > 0."""
        panel = _FakePanel()
        host, footer, _ = _make_panel_host(
            panels=[("Config", panel)],
            breadcrumb_stack=["Detail: region"],
        )

        host.update_chrome_with_focus(focused=False)

        assert footer.actions == [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]


# ===========================================================================
# R6-AC1 + R6-AC4: Focused footer at depth 0
# ===========================================================================


class TestFocusedFooterDepthZero:
    """When focused=True and breadcrumb_depth == 0."""

    def test_focused_single_panel_no_ring_nav(self) -> None:
        """R6-AC4: With single panel, no ring nav hints are shown."""
        panel = _FakePanel(actions=[("j/k", "navigate"), ("Esc", "back")])
        host, footer, _ = _make_panel_host(panels=[("Config", panel)])

        host.update_chrome_with_focus(focused=True)

        # Should NOT include Ctrl+J/K since only one panel
        assert ("Ctrl+J/K", "switch") not in footer.actions
        assert footer.actions == [("j/k", "navigate"), ("Esc", "back")]

    def test_focused_multiple_panels_includes_ring_nav(self) -> None:
        """R6-AC4: With multiple panels at depth 0, ring nav hints are prepended."""
        panel1 = _FakePanel(actions=[("j/k", "navigate"), ("Esc", "back")])
        panel2 = _FakePanel()
        host, footer, _ = _make_panel_host(
            panels=[("Config", panel1), ("Files", panel2)]
        )

        host.update_chrome_with_focus(focused=True)

        # Ctrl+J/K should be first
        assert footer.actions[0] == ("Ctrl+J/K", "switch")
        # Panel-specific actions follow
        assert ("j/k", "navigate") in footer.actions
        assert ("Esc", "back") in footer.actions

    def test_focused_panel_actions_come_from_get_available_actions(self) -> None:
        """R6-AC1: Panel-specific actions from get_available_actions(focused=True)."""
        custom_actions = [("x", "delete"), ("q", "quit")]
        panel = _FakePanel(actions=custom_actions)
        host, footer, _ = _make_panel_host(panels=[("Custom", panel)])

        host.update_chrome_with_focus(focused=True)

        assert footer.actions == custom_actions


# ===========================================================================
# R6-AC3: Focused footer with breadcrumb_depth > 0
# ===========================================================================


class TestFocusedFooterWithBreadcrumb:
    """When focused=True and breadcrumb_depth > 0 (drill-down state)."""

    def test_breadcrumb_depth_no_ring_nav(self) -> None:
        """R6-AC3: With breadcrumb_depth > 0, ring nav hints are NOT shown."""
        panel = _FakePanel(actions=[("Esc", "back")])
        host, footer, _ = _make_panel_host(
            panels=[("Config", panel), ("Files", _FakePanel())],
            breadcrumb_stack=["Detail: region"],
        )

        host.update_chrome_with_focus(focused=True)

        # Should NOT have ring nav even with multiple panels
        assert ("Ctrl+J/K", "switch") not in footer.actions
        # Should have panel-specific actions only
        assert footer.actions == [("Esc", "back")]

    def test_breadcrumb_depth_2_no_ring_nav(self) -> None:
        """R6-AC3: Even at depth 2, ring nav is not shown."""
        panel = _FakePanel(actions=[("Esc", "back")])
        host, footer, _ = _make_panel_host(
            panels=[("Config", panel), ("Files", _FakePanel())],
            breadcrumb_stack=["Level 1", "Level 2"],
        )

        host.update_chrome_with_focus(focused=True)

        assert ("Ctrl+J/K", "switch") not in footer.actions


# ===========================================================================
# Fallback behavior for panels without get_available_actions
# ===========================================================================


class TestPanelWithoutGetAvailableActions:
    """Panels without get_available_actions fall back to [("Esc", "back")]."""

    def test_fallback_actions(self) -> None:
        """Panels without get_available_actions get the default fallback."""
        panel = _FakePanelNoActions()
        host, footer, _ = _make_panel_host(panels=[("Legacy", panel)])

        host.update_chrome_with_focus(focused=True)

        assert footer.actions == [("Esc", "back")]


# ===========================================================================
# _update_chrome maintains existing behavior
# ===========================================================================


class TestUpdateChromeBackcompat:
    """_update_chrome() still produces the same result as focused=True."""

    def test_update_chrome_delegates_to_focused_true(self) -> None:
        """_update_chrome calls update_chrome_with_focus(focused=True) internally."""
        panel = _FakePanel(actions=[("j/k", "navigate"), ("Esc", "back")])
        host, footer, _ = _make_panel_host(
            panels=[("Config", panel), ("Files", _FakePanel())]
        )

        host._update_chrome()

        # Should behave like focused=True at depth 0 with multiple panels
        assert footer.actions[0] == ("Ctrl+J/K", "switch")
        assert ("j/k", "navigate") in footer.actions

    def test_update_chrome_updates_breadcrumb(self) -> None:
        """_update_chrome also updates the breadcrumb header."""
        panel = _FakePanel()
        host, footer, breadcrumb = _make_panel_host(panels=[("Config", panel)])

        host._update_chrome()

        # Breadcrumb should have been updated
        assert breadcrumb.state is not None


# ===========================================================================
# Edge case: empty panels
# ===========================================================================


class TestEmptyPanels:
    """Edge case: no panels set."""

    def test_no_panels_focused_noop(self) -> None:
        """No-op when panels list is empty."""
        host, footer, _ = _make_panel_host(panels=[])

        host.update_chrome_with_focus(focused=True)

        # Footer should not have been touched (remains empty)
        assert footer.actions == []

    def test_no_panels_unfocused_noop(self) -> None:
        """No-op when panels list is empty."""
        host, footer, _ = _make_panel_host(panels=[])

        host.update_chrome_with_focus(focused=False)

        assert footer.actions == []
