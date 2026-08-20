# Feature: tui-architecture-v2, Property 1: Ring navigation wraps correctly
# Feature: tui-architecture-v2, Property 4: Index clamping on ring resize
"""Property-based tests for PanelRingController.

Tests PanelRingController from functualize._cli.tui.models.panel_ring_controller:
- Property 1: Ring navigation wraps correctly
- Property 4: Index clamping on ring resize

**Validates: Requirements 1.1, 1.2, 2.6**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.models.panel_ring_controller import (
    Category,
    PanelRingController,
)

# =============================================================================
# Strategies
# =============================================================================

# Ring size: at least 1, capped at 100 for practical testing
_ring_size_strategy = st.integers(min_value=1, max_value=100)


@st.composite
def _ring_size_and_start_index(draw: st.DrawFn) -> tuple[int, int]:
    """Generate a valid (ring_size, starting_index) pair."""
    ring_size = draw(_ring_size_strategy)
    start_index = draw(st.integers(min_value=0, max_value=ring_size - 1))
    return ring_size, start_index


# Category to activate (only PRE_FLIGHT and GENERAL support navigation)
_active_category_strategy = st.sampled_from([Category.PRE_FLIGHT, Category.GENERAL])


# =============================================================================
# Property 1: Ring navigation wraps correctly
# =============================================================================


@pytest.mark.slow
class TestRingNavigationWrapsCorrectly:
    """Property 1: Ring navigation wraps correctly.

    For any ring of size N >= 1 and any starting index in [0, N-1],
    calling next_panel should produce (index + 1) % N and calling
    prev_panel should produce (index - 1) % N, ensuring the ring
    always wraps without going out of bounds.

    **Validates: Requirements 1.1, 1.2**
    """

    @given(data=_ring_size_and_start_index(), category=_active_category_strategy)
    def test_next_panel_wraps_modularly(
        self, data: tuple[int, int], category: Category
    ) -> None:
        """next_panel produces (index + 1) % N (Req 1.1)."""
        ring_size, start_index = data
        ctrl = PanelRingController()

        # Activate the chosen category so navigation operates on it
        if category == Category.PRE_FLIGHT:
            ctrl.activate_pre_flight(ring_size)
            ctrl._pre_flight_index = start_index
        else:
            ctrl.activate_general(ring_size)
            ctrl._general_index = start_index

        result = ctrl.next_panel(ring_size)
        expected = (start_index + 1) % ring_size
        assert result == expected, (
            f"next_panel({ring_size}) from index {start_index}: "
            f"got {result}, expected {expected}"
        )

    @given(data=_ring_size_and_start_index(), category=_active_category_strategy)
    def test_prev_panel_wraps_modularly(
        self, data: tuple[int, int], category: Category
    ) -> None:
        """prev_panel produces (index - 1) % N (Req 1.2)."""
        ring_size, start_index = data
        ctrl = PanelRingController()

        # Activate the chosen category so navigation operates on it
        if category == Category.PRE_FLIGHT:
            ctrl.activate_pre_flight(ring_size)
            ctrl._pre_flight_index = start_index
        else:
            ctrl.activate_general(ring_size)
            ctrl._general_index = start_index

        result = ctrl.prev_panel(ring_size)
        expected = (start_index - 1) % ring_size
        assert result == expected, (
            f"prev_panel({ring_size}) from index {start_index}: "
            f"got {result}, expected {expected}"
        )

    @given(data=_ring_size_and_start_index(), category=_active_category_strategy)
    def test_next_panel_result_in_bounds(
        self, data: tuple[int, int], category: Category
    ) -> None:
        """next_panel result is always in [0, N-1] (Req 1.1)."""
        ring_size, start_index = data
        ctrl = PanelRingController()

        if category == Category.PRE_FLIGHT:
            ctrl.activate_pre_flight(ring_size)
            ctrl._pre_flight_index = start_index
        else:
            ctrl.activate_general(ring_size)
            ctrl._general_index = start_index

        result = ctrl.next_panel(ring_size)
        assert 0 <= result < ring_size, (
            f"next_panel({ring_size}) returned {result}, out of bounds [0, {ring_size - 1}]"
        )

    @given(data=_ring_size_and_start_index(), category=_active_category_strategy)
    def test_prev_panel_result_in_bounds(
        self, data: tuple[int, int], category: Category
    ) -> None:
        """prev_panel result is always in [0, N-1] (Req 1.2)."""
        ring_size, start_index = data
        ctrl = PanelRingController()

        if category == Category.PRE_FLIGHT:
            ctrl.activate_pre_flight(ring_size)
            ctrl._pre_flight_index = start_index
        else:
            ctrl.activate_general(ring_size)
            ctrl._general_index = start_index

        result = ctrl.prev_panel(ring_size)
        assert 0 <= result < ring_size, (
            f"prev_panel({ring_size}) returned {result}, out of bounds [0, {ring_size - 1}]"
        )

    @given(data=_ring_size_and_start_index(), category=_active_category_strategy)
    def test_next_then_prev_returns_to_start(
        self, data: tuple[int, int], category: Category
    ) -> None:
        """Calling next_panel then prev_panel returns to the original index."""
        ring_size, start_index = data
        ctrl = PanelRingController()

        if category == Category.PRE_FLIGHT:
            ctrl.activate_pre_flight(ring_size)
            ctrl._pre_flight_index = start_index
        else:
            ctrl.activate_general(ring_size)
            ctrl._general_index = start_index

        ctrl.next_panel(ring_size)
        result = ctrl.prev_panel(ring_size)
        assert result == start_index, (
            f"next then prev from {start_index} with ring_size={ring_size}: "
            f"got {result}, expected {start_index}"
        )


# =============================================================================
# Property 4: Index clamping on ring resize
# =============================================================================


@pytest.mark.slow
class TestIndexClampingOnRingResize:
    """Property 4: Index clamping on ring resize.

    For any ring with current index I and a new ring size M where M < I + 1,
    the controller should clamp the index to M - 1 (the new last valid position),
    ensuring the index never exceeds the ring bounds after a panel removal.

    **Validates: Requirements 2.6**
    """

    @given(
        initial_ring_size=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    def test_pre_flight_clamping_when_index_out_of_bounds(
        self, initial_ring_size: int, data: st.DataObject
    ) -> None:
        """When ring shrinks below current index, pre-flight index clamps to M-1."""
        ctrl = PanelRingController()

        # Activate pre-flight with initial size and navigate to a starting index
        ctrl.activate_pre_flight(initial_ring_size)
        starting_index = data.draw(
            st.integers(min_value=1, max_value=initial_ring_size - 1),
            label="starting_index",
        )
        # Navigate to the starting index
        for _ in range(starting_index):
            ctrl.next_panel(initial_ring_size)

        assert ctrl.current_index == starting_index

        # Generate a new ring size that makes the current index out of bounds
        # M < I + 1  →  M ≤ I  →  M in [1, starting_index]
        new_ring_size = data.draw(
            st.integers(min_value=1, max_value=starting_index),
            label="new_ring_size",
        )

        # Re-activate with smaller ring size (simulates panel removal)
        result = ctrl.activate_pre_flight(new_ring_size)

        # Index should be clamped to M - 1 (last valid position)
        assert result == new_ring_size - 1
        assert ctrl.current_index == new_ring_size - 1

    @given(
        initial_ring_size=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    def test_general_clamping_when_index_out_of_bounds(
        self, initial_ring_size: int, data: st.DataObject
    ) -> None:
        """When ring shrinks below current index, general index clamps to M-1."""
        ctrl = PanelRingController()

        # Activate general with initial size and navigate to a starting index
        ctrl.activate_general(initial_ring_size)
        starting_index = data.draw(
            st.integers(min_value=1, max_value=initial_ring_size - 1),
            label="starting_index",
        )
        # Navigate to the starting index
        for _ in range(starting_index):
            ctrl.next_panel(initial_ring_size)

        assert ctrl.current_index == starting_index

        # Generate a new ring size that makes the current index out of bounds
        new_ring_size = data.draw(
            st.integers(min_value=1, max_value=starting_index),
            label="new_ring_size",
        )

        # Re-activate with smaller ring size (simulates panel removal)
        result = ctrl.activate_general(new_ring_size)

        # Index should be clamped to M - 1 (last valid position)
        assert result == new_ring_size - 1
        assert ctrl.current_index == new_ring_size - 1

    @given(
        initial_ring_size=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    def test_pre_flight_no_clamping_when_index_in_bounds(
        self, initial_ring_size: int, data: st.DataObject
    ) -> None:
        """When ring size >= index + 1, pre-flight index stays unchanged."""
        ctrl = PanelRingController()

        # Activate pre-flight and navigate to a starting index
        ctrl.activate_pre_flight(initial_ring_size)
        starting_index = data.draw(
            st.integers(min_value=0, max_value=initial_ring_size - 1),
            label="starting_index",
        )
        # Navigate to the starting index
        for _ in range(starting_index):
            ctrl.next_panel(initial_ring_size)

        assert ctrl.current_index == starting_index

        # Generate a new ring size where M >= I + 1 (index stays valid)
        new_ring_size = data.draw(
            st.integers(min_value=starting_index + 1, max_value=100),
            label="new_ring_size",
        )

        # Re-activate with same or larger ring size
        result = ctrl.activate_pre_flight(new_ring_size)

        # Index should stay at the same position (no clamping needed)
        assert result == starting_index
        assert ctrl.current_index == starting_index

    @given(
        initial_ring_size=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    def test_general_no_clamping_when_index_in_bounds(
        self, initial_ring_size: int, data: st.DataObject
    ) -> None:
        """When ring size >= index + 1, general index stays unchanged."""
        ctrl = PanelRingController()

        # Activate general and navigate to a starting index
        ctrl.activate_general(initial_ring_size)
        starting_index = data.draw(
            st.integers(min_value=0, max_value=initial_ring_size - 1),
            label="starting_index",
        )
        # Navigate to the starting index
        for _ in range(starting_index):
            ctrl.next_panel(initial_ring_size)

        assert ctrl.current_index == starting_index

        # Generate a new ring size where M >= I + 1 (index stays valid)
        new_ring_size = data.draw(
            st.integers(min_value=starting_index + 1, max_value=100),
            label="new_ring_size",
        )

        # Re-activate with same or larger ring size
        result = ctrl.activate_general(new_ring_size)

        # Index should stay at the same position (no clamping needed)
        assert result == starting_index
        assert ctrl.current_index == starting_index
