"""Property-based tests for PanelRing (Property 6).

Property 6: Panel ring navigation wraps correctly
- N consecutive next() calls from any starting position returns to start
- N consecutive prev() calls from any starting position returns to start
- After any single next()/prev() call, index is always in [0, N-1]
- For empty rings, next()/prev() are no-ops (index stays 0)

**Validates: Requirements 8.1, 8.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.panels.ring import PanelRing

# =============================================================================
# Strategies
# =============================================================================


@st.composite
def _panel_ids(draw: st.DrawFn, min_size: int = 1, max_size: int = 50) -> list[str]:
    """Generate a list of unique panel ID strings."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    return [f"panel_{i}" for i in range(size)]


@st.composite
def _ring_with_position(draw: st.DrawFn) -> tuple[PanelRing, int]:
    """Generate a non-empty PanelRing and a valid starting position."""
    panels = draw(_panel_ids(min_size=1, max_size=50))
    start = draw(st.integers(min_value=0, max_value=len(panels) - 1))
    ring = PanelRing(prefix="R", panel_ids=panels)
    # Navigate to starting position
    ring._index = start
    return ring, start


# =============================================================================
# Property 6: Panel ring navigation wraps correctly
# =============================================================================


@pytest.mark.slow
class TestPanelRingNavigationWraps:
    """Property 6: Panel ring navigation wraps correctly."""

    @given(data=st.data())
    def test_next_n_times_returns_to_start(self, data: st.DataObject) -> None:
        """For a ring of size N, calling next() N times returns to start.

        **Validates: Requirements 8.1**
        """
        ring, start = data.draw(_ring_with_position())
        n = len(ring.panel_ids)

        for _ in range(n):
            ring.next()

        assert ring.current_index == start

    @given(data=st.data())
    def test_prev_n_times_returns_to_start(self, data: st.DataObject) -> None:
        """For a ring of size N, calling prev() N times returns to start.

        **Validates: Requirements 8.2**
        """
        ring, start = data.draw(_ring_with_position())
        n = len(ring.panel_ids)

        for _ in range(n):
            ring.prev()

        assert ring.current_index == start

    @given(data=st.data())
    def test_next_index_always_in_bounds(self, data: st.DataObject) -> None:
        """After any single next() call, index is always in [0, N-1].

        **Validates: Requirements 8.1**
        """
        ring, _ = data.draw(_ring_with_position())
        n = len(ring.panel_ids)

        ring.next()

        assert 0 <= ring.current_index < n

    @given(data=st.data())
    def test_prev_index_always_in_bounds(self, data: st.DataObject) -> None:
        """After any single prev() call, index is always in [0, N-1].

        **Validates: Requirements 8.2**
        """
        ring, _ = data.draw(_ring_with_position())
        n = len(ring.panel_ids)

        ring.prev()

        assert 0 <= ring.current_index < n

    @given(prefix=st.sampled_from(["R", "E"]))
    def test_empty_ring_next_is_noop(self, prefix: str) -> None:
        """For empty rings, next() is a no-op (index stays 0).

        **Validates: Requirements 8.1**
        """
        ring = PanelRing(prefix=prefix, panel_ids=[])

        result = ring.next()

        assert ring.current_index == 0
        assert result == 0

    @given(prefix=st.sampled_from(["R", "E"]))
    def test_empty_ring_prev_is_noop(self, prefix: str) -> None:
        """For empty rings, prev() is a no-op (index stays 0).

        **Validates: Requirements 8.2**
        """
        ring = PanelRing(prefix=prefix, panel_ids=[])

        result = ring.prev()

        assert ring.current_index == 0
        assert result == 0
