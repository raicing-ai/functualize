# Feature: tui-v3-integration, Property 1: Mode transitions are always valid
# Feature: tui-v3-integration, Property 5: Zone cycling visits all visible zones exactly once per full cycle
"""Property-based tests for FocusState FSM.

Tests FocusState from functualize._cli.tui.focus:
- Property 1: Mode transitions are always valid
- Property 5: Zone cycling visits all visible zones exactly once per full cycle

**Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 10.1, 10.2, 10.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone

# =============================================================================
# Constants
# =============================================================================

# The complete set of valid transitions per Requirement 2.1
_VALID_TRANSITIONS: set[tuple[FocusMode, FocusMode]] = {
    (FocusMode.COMMAND, FocusMode.NORMAL),
    (FocusMode.NORMAL, FocusMode.COMMAND),
    (FocusMode.NORMAL, FocusMode.INSERT),
    (FocusMode.NORMAL, FocusMode.FILTER),
    (FocusMode.INSERT, FocusMode.NORMAL),
    (FocusMode.FILTER, FocusMode.NORMAL),
    (FocusMode.COMMAND, FocusMode.COMMAND),
}

# Fixed cycle order per Requirement 2.5
_CYCLE_ORDER = [FocusZone.SMARTBAR, FocusZone.DISPLAY, FocusZone.PANEL]

# =============================================================================
# Strategies
# =============================================================================

_focus_mode_strategy = st.sampled_from(list(FocusMode))
_focus_zone_strategy = st.sampled_from(list(FocusZone))


@st.composite
def _visible_zones_with_smartbar(draw: st.DrawFn) -> set[FocusZone]:
    """Generate a visible zone set that always includes SMARTBAR (Req 2.7).

    Returns subsets of {SMARTBAR, DISPLAY, PANEL} that always contain SMARTBAR.
    """
    optional = draw(
        st.sets(st.sampled_from([FocusZone.DISPLAY, FocusZone.PANEL]), max_size=2)
    )
    return {FocusZone.SMARTBAR} | optional


# =============================================================================
# Property 1: Mode transitions are always valid
# =============================================================================


@pytest.mark.slow
class TestModeTransitionsAlwaysValid:
    """Property 1: Mode transitions are always valid.

    For every (from_mode, to_mode) pair:
    - If the pair is in _VALID_TRANSITIONS, transition() returns True,
      mode updates to to_mode, and subscribers are notified.
    - If the pair is NOT in _VALID_TRANSITIONS, transition() returns False,
      mode and zone remain unchanged, and no subscriber is notified.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """

    @given(from_mode=_focus_mode_strategy, to_mode=_focus_mode_strategy)
    @settings(max_examples=100)
    def test_valid_transitions_succeed(
        self, from_mode: FocusMode, to_mode: FocusMode
    ) -> None:
        """Valid (from_mode, to_mode) pairs succeed with state update and notification."""
        if (from_mode, to_mode) not in _VALID_TRANSITIONS:
            return  # Skip invalid pairs — tested below

        fs = FocusState()
        # Force to the from_mode with a known zone
        fs.force(from_mode, FocusZone.PANEL)

        notifications: list[tuple[FocusMode, FocusZone]] = []
        fs.subscribe(lambda m, z: notifications.append((m, z)))

        result = fs.transition(to_mode)

        assert result is True, (
            f"Expected transition({from_mode.name} -> {to_mode.name}) to succeed"
        )
        assert fs.mode is to_mode, f"Expected mode={to_mode.name}, got {fs.mode.name}"
        assert len(notifications) == 1, (
            f"Expected exactly 1 notification, got {len(notifications)}"
        )
        # Verify notification contains correct mode
        assert notifications[0][0] is to_mode

    @given(from_mode=_focus_mode_strategy, to_mode=_focus_mode_strategy)
    @settings(max_examples=100)
    def test_invalid_transitions_fail(
        self, from_mode: FocusMode, to_mode: FocusMode
    ) -> None:
        """Invalid (from_mode, to_mode) pairs return False with no state change (Req 2.3)."""
        if (from_mode, to_mode) in _VALID_TRANSITIONS:
            return  # Skip valid pairs — tested above

        fs = FocusState()
        original_zone = FocusZone.DISPLAY
        fs.force(from_mode, original_zone)

        notifications: list[tuple[FocusMode, FocusZone]] = []
        fs.subscribe(lambda m, z: notifications.append((m, z)))

        result = fs.transition(to_mode)

        assert result is False, (
            f"Expected transition({from_mode.name} -> {to_mode.name}) to be rejected"
        )
        assert fs.mode is from_mode, (
            f"Expected mode unchanged at {from_mode.name}, got {fs.mode.name}"
        )
        assert fs.zone is original_zone, (
            f"Expected zone unchanged at {original_zone.name}, got {fs.zone.name}"
        )
        assert len(notifications) == 0, (
            f"Expected no notifications on rejected transition, got {len(notifications)}"
        )

    @given(
        from_mode=_focus_mode_strategy,
        to_mode=_focus_mode_strategy,
        zone=_focus_zone_strategy,
    )
    @settings(max_examples=100)
    def test_zone_behavior_on_success(
        self, from_mode: FocusMode, to_mode: FocusMode, zone: FocusZone
    ) -> None:
        """On success with zone arg: update zone (Req 2.2)."""
        if (from_mode, to_mode) not in _VALID_TRANSITIONS:
            return

        fs = FocusState()
        fs.force(from_mode, FocusZone.PANEL)

        result = fs.transition(to_mode, zone=zone)

        assert result is True
        assert fs.zone is zone, (
            f"Expected zone={zone.name} when zone arg provided, got {fs.zone.name}"
        )

    @given(from_mode=_focus_mode_strategy, to_mode=_focus_mode_strategy)
    @settings(max_examples=100)
    def test_zone_defaults_to_smartbar_for_command(
        self, from_mode: FocusMode, to_mode: FocusMode
    ) -> None:
        """Without zone arg and target is COMMAND: zone becomes SMARTBAR (Req 2.2)."""
        if (from_mode, to_mode) not in _VALID_TRANSITIONS:
            return
        if to_mode is not FocusMode.COMMAND:
            return

        fs = FocusState()
        fs.force(from_mode, FocusZone.DISPLAY)

        result = fs.transition(to_mode)

        assert result is True
        assert fs.zone is FocusZone.SMARTBAR, (
            f"Expected zone=SMARTBAR when transitioning to COMMAND without zone arg, "
            f"got {fs.zone.name}"
        )

    @given(from_mode=_focus_mode_strategy, to_mode=_focus_mode_strategy)
    @settings(max_examples=100)
    def test_zone_retained_for_non_command(
        self, from_mode: FocusMode, to_mode: FocusMode
    ) -> None:
        """Without zone arg and target is NOT COMMAND: retain current zone (Req 2.2)."""
        if (from_mode, to_mode) not in _VALID_TRANSITIONS:
            return
        if to_mode is FocusMode.COMMAND:
            return

        fs = FocusState()
        original_zone = FocusZone.DISPLAY
        fs.force(from_mode, original_zone)

        result = fs.transition(to_mode)

        assert result is True
        assert fs.zone is original_zone, (
            f"Expected zone retained as {original_zone.name}, got {fs.zone.name}"
        )


# =============================================================================
# Property 5: Zone cycling visits all visible zones exactly once per full cycle
# =============================================================================


@pytest.mark.slow
class TestZoneCyclingVisitsAllVisibleZones:
    """Property 5: Zone cycling visits all visible zones exactly once per full cycle.

    For any visible zone set (always including SMARTBAR) and any starting zone
    within that set, calling cycle_zone() N times (N = len(visible_zones))
    returns to the starting zone, and each zone in the visible set is visited
    exactly once during the full cycle.

    **Validates: Requirements 2.5, 2.6, 10.1, 10.2, 10.3**
    """

    @given(
        visible_zones=_visible_zones_with_smartbar(),
        start_zone_idx=st.integers(min_value=0, max_value=2),
    )
    @settings(max_examples=100)
    def test_full_cycle_returns_to_start(
        self, visible_zones: set[FocusZone], start_zone_idx: int
    ) -> None:
        """N calls to cycle_zone() return to the starting zone."""
        # Determine the visible cycle in fixed order
        visible_cycle = [z for z in _CYCLE_ORDER if z in visible_zones]
        n = len(visible_cycle)

        if n <= 1:
            return  # Single-zone case tested separately below

        # Pick a valid starting zone from the visible set
        start_zone = visible_cycle[start_zone_idx % n]

        fs = FocusState()
        fs.force(FocusMode.COMMAND, start_zone)

        # Cycle N times
        for _ in range(n):
            fs.cycle_zone(visible_zones)

        # After N cycles, should be back to start
        assert fs.zone is start_zone, (
            f"After {n} cycles starting from {start_zone.name}, "
            f"expected to return to {start_zone.name}, got {fs.zone.name}"
        )

    @given(
        visible_zones=_visible_zones_with_smartbar(),
        start_zone_idx=st.integers(min_value=0, max_value=2),
    )
    @settings(max_examples=100)
    def test_each_zone_visited_exactly_once(
        self, visible_zones: set[FocusZone], start_zone_idx: int
    ) -> None:
        """Each visible zone is visited exactly once per full cycle."""
        visible_cycle = [z for z in _CYCLE_ORDER if z in visible_zones]
        n = len(visible_cycle)

        if n <= 1:
            return  # Single-zone case tested separately below

        start_zone = visible_cycle[start_zone_idx % n]

        fs = FocusState()
        fs.force(FocusMode.COMMAND, start_zone)

        visited: list[FocusZone] = []
        for _ in range(n):
            result = fs.cycle_zone(visible_zones)
            visited.append(result)

        # All visible zones should appear exactly once
        assert set(visited) == visible_zones, (
            f"Expected to visit all zones in {visible_zones}, "
            f"but visited {set(visited)}"
        )
        assert len(visited) == len(set(visited)), (
            f"Expected each zone visited exactly once, but got duplicates: {visited}"
        )

    @given(visible_zones=_visible_zones_with_smartbar())
    @settings(max_examples=100)
    def test_single_zone_returns_smartbar_unchanged(
        self, visible_zones: set[FocusZone]
    ) -> None:
        """If only one zone visible, return SMARTBAR without changing zone (Req 2.6)."""
        if len(visible_zones) > 1:
            return  # Only test single-zone case here

        fs = FocusState()
        original_zone = FocusZone.SMARTBAR
        fs.force(FocusMode.COMMAND, original_zone)

        result = fs.cycle_zone(visible_zones)

        assert result is FocusZone.SMARTBAR, (
            f"Expected SMARTBAR returned for single visible zone, got {result.name}"
        )
        # Zone should not change
        assert fs.zone is original_zone, (
            f"Expected zone unchanged at {original_zone.name}, got {fs.zone.name}"
        )
