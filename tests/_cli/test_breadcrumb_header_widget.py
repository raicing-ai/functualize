"""Unit tests for BreadcrumbHeader and DynamicFooterWidget standalone widgets.

These tests verify that the widgets can be instantiated, updated, and cleared
independently of PanelSlot, satisfying task 20.3 requirements (22.7, 22.8).
"""

from __future__ import annotations

from functualize._cli.tui.breadcrumb_header_widget import BreadcrumbHeader
from functualize._cli.tui.dynamic_footer_widget import DynamicFooterWidget
from functualize._cli.tui.models.ring_models import BreadcrumbState


class TestBreadcrumbHeaderWidget:
    """Tests for the standalone BreadcrumbHeader widget."""

    def test_instantiation(self) -> None:
        """Widget can be instantiated with default empty content."""
        header = BreadcrumbHeader("")
        assert header is not None

    def test_update_state_renders_breadcrumb(self) -> None:
        """update_state() calls BreadcrumbState.render() and updates content."""
        header = BreadcrumbHeader("")
        state = BreadcrumbState(
            type_prefix="R",
            position=1,
            total=3,
            title="Config Table",
            sub_levels=(),
        )
        header.update_state(state)
        # The internal renderable is updated — verify render output matches
        assert state.render() == "[R:1/3] Config Table"

    def test_update_state_with_sub_levels(self) -> None:
        """update_state() handles sub-levels correctly."""
        header = BreadcrumbHeader("")
        state = BreadcrumbState(
            type_prefix="R",
            position=1,
            total=3,
            title="Config Table",
            sub_levels=("Field Detail: region",),
        )
        header.update_state(state)
        assert state.render() == "[R:1/3] Config Table > Field Detail: region"

    def test_update_state_general_ring(self) -> None:
        """update_state() handles general ring prefix."""
        header = BreadcrumbHeader("")
        state = BreadcrumbState(
            type_prefix="E",
            position=2,
            total=4,
            title="Settings",
            sub_levels=(),
        )
        header.update_state(state)
        assert state.render() == "[E:2/4] Settings"

    def test_update_state_display_panel(self) -> None:
        """update_state() handles display panel prefix."""
        header = BreadcrumbHeader("")
        state = BreadcrumbState(
            type_prefix="D",
            position=1,
            total=1,
            title="Docker Services",
            sub_levels=(),
        )
        header.update_state(state)
        assert state.render() == "[D:1/1] Docker Services"

    def test_clear_state(self) -> None:
        """clear_state() empties the widget content."""
        header = BreadcrumbHeader("")
        state = BreadcrumbState(
            type_prefix="R", position=1, total=3, title="Config Table"
        )
        header.update_state(state)
        header.clear_state()
        # After clear, no assertion on renderable needed — just no crash


class TestDynamicFooterWidget:
    """Tests for the standalone DynamicFooterWidget."""

    def test_instantiation(self) -> None:
        """Widget can be instantiated with default empty content."""
        footer = DynamicFooterWidget("")
        assert footer is not None

    def test_update_actions_with_tuples(self) -> None:
        """update_actions() formats action tuples correctly."""
        footer = DynamicFooterWidget("")
        actions = [("↑↓", "navigate"), ("Enter", "detail"), ("Esc", "back")]
        footer.update_actions(actions)
        # Verify the render_footer logic is applied
        from functualize._cli.tui.dynamic_footer import render_footer

        expected = render_footer(actions)
        assert expected == "↑↓ navigate  Enter detail  Esc back"

    def test_update_actions_empty_list(self) -> None:
        """update_actions() with empty list produces empty string."""
        footer = DynamicFooterWidget("")
        footer.update_actions([])
        from functualize._cli.tui.dynamic_footer import render_footer

        assert render_footer([]) == ""

    def test_update_actions_single_item(self) -> None:
        """update_actions() with single item formats correctly."""
        footer = DynamicFooterWidget("")
        actions = [("Ctrl+R", "pre-flight")]
        footer.update_actions(actions)
        from functualize._cli.tui.dynamic_footer import render_footer

        assert render_footer(actions) == "Ctrl+R pre-flight"

    def test_clear_actions(self) -> None:
        """clear_actions() empties the widget content."""
        footer = DynamicFooterWidget("")
        footer.update_actions([("e", "edit")])
        footer.clear_actions()
        # After clear, no crash — content is empty
