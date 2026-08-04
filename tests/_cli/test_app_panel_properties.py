# Feature: tui-v3-wiring, Property 6: Panel toggle is involutory (toggling twice restores state)
# Feature: tui-v3-wiring, Property 7: Breadcrumb format matches ring state
"""Property-based tests for panel toggle involution and breadcrumb format.

Property 6: Panel toggle is involutory — toggling twice restores state.
Property 7: Breadcrumb format matches ring state.

**Validates: Requirements 12.1, 12.2, 8.2**
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.integration import enter_normal_mode, exit_to_command_mode
from functualize._cli.tui.models.ring_models import BreadcrumbState

# =============================================================================
# Strategies
# =============================================================================

# Strategy: which ring type to toggle
_ring_type = st.sampled_from(["preflight", "general"])

# Strategy: initial panel host active state
_initial_active = st.booleans()

# Strategy for BreadcrumbState generation
_panel_count = st.integers(min_value=1, max_value=10)
_panel_index = st.integers(min_value=0, max_value=9)  # filtered in test
_prefix = st.text(
    min_size=1,
    max_size=5,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)
_title = st.text(
    min_size=1,
    max_size=5,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)


# =============================================================================
# Helpers for Property 6
# =============================================================================


class PanelToggleState:
    """Simulates the panel toggle pattern from app.py without Textual.

    Tracks: panel_host.is_active, _active_ring, FocusState (mode, zone).
    """

    def __init__(
        self, *, is_active: bool, active_ring: str | None, focus_state: FocusState
    ) -> None:
        self.is_active = is_active
        self.active_ring = active_ring
        self.focus_state = focus_state
        # Mock SmartBar for exit_to_command_mode
        self.smartbar = MagicMock()
        self.smartbar.focus = MagicMock()
        # Mock app for set_focus(None)
        self.app = MagicMock()
        self.app.set_focus = MagicMock()

    def toggle(self, ring: str) -> None:
        """Simulate the toggle logic from app.py.

        Toggle ON (when not active or different ring):
            panel_host.activate() → is_active = True
            active_ring = ring
            enter_normal_mode(app, focus_state, FocusZone.PANEL)

        Toggle OFF (when active and same ring):
            panel_host.collapse() → is_active = False
            active_ring = None
            exit_to_command_mode(app, focus_state, smartbar)
        """
        if self.is_active and self.active_ring == ring:
            # Toggle OFF
            self.is_active = False
            self.active_ring = None
            exit_to_command_mode(self.app, self.focus_state, self.smartbar)
        else:
            # Toggle ON
            self.is_active = True
            self.active_ring = ring
            enter_normal_mode(self.app, self.focus_state, FocusZone.PANEL)

    def snapshot(self) -> tuple[bool, str | None, FocusMode]:
        """Capture the observable state for comparison."""
        return (self.is_active, self.active_ring, self.focus_state.mode)


# =============================================================================
# Property 6: Panel toggle is involutory (toggling twice restores state)
# =============================================================================


@pytest.mark.slow
class TestPanelToggleIsInvolutory:
    """Property 6: Panel toggle is involutory (toggling twice restores state).

    For any initial PanelHost visibility state (active or inactive), invoking
    the same panel toggle action twice in succession SHALL return the PanelHost
    to its original visibility state and restore the original FocusMode.

    **Validates: Requirements 12.1, 12.2**
    """

    @given(ring=_ring_type, initial_active=_initial_active)
    @settings(max_examples=100)
    def test_toggle_twice_restores_state(self, ring: str, initial_active: bool) -> None:
        """Toggling the same ring twice restores visibility and FocusMode.

        **Validates: Requirements 12.1, 12.2**
        """
        # Set up initial state.
        # If initially active, we need NORMAL mode (panels are shown in NORMAL).
        # If initially inactive, we're in COMMAND mode.
        focus_state = FocusState()
        if initial_active:
            # Simulate: panel was already toggled ON → NORMAL mode + PANEL zone
            focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)
            active_ring: str | None = ring
        else:
            # Initial state: COMMAND mode, no active ring
            focus_state.force(FocusMode.COMMAND, FocusZone.SMARTBAR)
            active_ring = None

        state = PanelToggleState(
            is_active=initial_active,
            active_ring=active_ring,
            focus_state=focus_state,
        )

        # Capture initial snapshot
        before = state.snapshot()

        # Toggle twice with the same ring
        state.toggle(ring)
        state.toggle(ring)

        # Capture final snapshot
        after = state.snapshot()

        assert before == after, (
            f"Toggle({ring}) twice did not restore state.\n"
            f"  Before: {before}\n"
            f"  After:  {after}"
        )

    @given(ring=_ring_type)
    @settings(max_examples=100)
    def test_toggle_on_then_off_returns_to_command(self, ring: str) -> None:
        """Starting inactive: toggle ON → NORMAL+PANEL, toggle OFF → COMMAND.

        **Validates: Requirements 12.1, 12.2**
        """
        focus_state = FocusState()
        focus_state.force(FocusMode.COMMAND, FocusZone.SMARTBAR)

        state = PanelToggleState(
            is_active=False,
            active_ring=None,
            focus_state=focus_state,
        )

        # Toggle ON
        state.toggle(ring)
        assert state.is_active is True
        assert state.active_ring == ring
        assert state.focus_state.mode == FocusMode.NORMAL

        # Toggle OFF
        state.toggle(ring)
        assert state.is_active is False
        assert state.active_ring is None
        assert state.focus_state.mode == FocusMode.COMMAND

    @given(ring=_ring_type)
    @settings(max_examples=100)
    def test_toggle_off_then_on_returns_to_normal(self, ring: str) -> None:
        """Starting active: toggle OFF → COMMAND, toggle ON → NORMAL+PANEL.

        **Validates: Requirements 12.1, 12.2**
        """
        focus_state = FocusState()
        focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)

        state = PanelToggleState(
            is_active=True,
            active_ring=ring,
            focus_state=focus_state,
        )

        # Toggle OFF
        state.toggle(ring)
        assert state.is_active is False
        assert state.active_ring is None
        assert state.focus_state.mode == FocusMode.COMMAND

        # Toggle ON
        state.toggle(ring)
        assert state.is_active is True
        assert state.active_ring == ring
        assert state.focus_state.mode == FocusMode.NORMAL


# =============================================================================
# Property 7: Breadcrumb format matches ring state
# =============================================================================


@pytest.mark.slow
class TestBreadcrumbFormatMatchesRingState:
    """Property 7: Breadcrumb format matches ring state.

    For any PanelRing with N panels (N > 0) at current index I with prefix P
    and title T, the BreadcrumbHeader SHALL display the text
    [{P}:{I+1}/{N}] {T}.

    **Validates: Requirements 8.2**
    """

    @given(
        count=_panel_count,
        prefix=_prefix,
        title=_title,
    )
    @settings(max_examples=100)
    def test_breadcrumb_render_matches_expected_format(
        self, count: int, prefix: str, title: str
    ) -> None:
        """BreadcrumbState.render() matches [{prefix}:{index+1}/{count}] {title}.

        **Validates: Requirements 8.2**
        """
        state = BreadcrumbState(
            type_prefix=prefix,
            position=1,  # 1-based
            total=count,
            title=title,
        )

        rendered = state.render()
        expected = f"[{prefix}:1/{count}] {title}"

        assert rendered == expected, (
            f"Breadcrumb format mismatch.\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {rendered!r}"
        )

    @given(
        count=_panel_count,
        prefix=_prefix,
        title=_title,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_breadcrumb_render_arbitrary_index(
        self, count: int, prefix: str, title: str, data: st.DataObject
    ) -> None:
        """BreadcrumbState.render() works for any valid index within [1, count].

        **Validates: Requirements 8.2**
        """
        # Draw a valid position (1-based) for the given count
        position = data.draw(st.integers(min_value=1, max_value=count))

        state = BreadcrumbState(
            type_prefix=prefix,
            position=position,
            total=count,
            title=title,
        )

        rendered = state.render()
        expected = f"[{prefix}:{position}/{count}] {title}"

        assert rendered == expected, (
            f"Breadcrumb format mismatch at position {position}/{count}.\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {rendered!r}"
        )

    @given(
        count=_panel_count,
        prefix=_prefix,
        title=_title,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_breadcrumb_render_with_sub_levels(
        self, count: int, prefix: str, title: str, data: st.DataObject
    ) -> None:
        """BreadcrumbState.render() appends sub-levels with ' > ' separator.

        **Validates: Requirements 8.2**
        """
        position = data.draw(st.integers(min_value=1, max_value=count))
        # Generate 1-2 sub-level strings
        sub_level_count = data.draw(st.integers(min_value=1, max_value=2))
        sub_levels = tuple(
            data.draw(
                st.text(
                    min_size=1,
                    max_size=5,
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                )
            )
            for _ in range(sub_level_count)
        )

        state = BreadcrumbState(
            type_prefix=prefix,
            position=position,
            total=count,
            title=title,
            sub_levels=sub_levels,
        )

        rendered = state.render()
        base_expected = f"[{prefix}:{position}/{count}] {title}"
        expected = base_expected + " > " + " > ".join(sub_levels)

        assert rendered == expected, (
            f"Breadcrumb format mismatch with sub-levels.\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {rendered!r}"
        )
