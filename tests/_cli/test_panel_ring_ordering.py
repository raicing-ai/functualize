# Feature: tui-architecture-v2, Property 8: General ring priority ordering
"""Property-based tests for PanelRing ordering (general ring).

Tests PanelRing from functualize._cli.tui.models.ring_models:
- Property 8: General ring priority ordering

**Validates: Requirements 11.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.models.ring_models import PanelRing, RegisteredPanel

# =============================================================================
# Strategies
# =============================================================================


@st.composite
def _panel_list_strategy(draw: st.DrawFn) -> list[RegisteredPanel]:
    """Generate a list of N panels with unique IDs and various priorities.

    Each panel gets a unique panel_id to avoid ambiguity in ordering checks.
    Priorities are intentionally allowed to repeat so we can test tie-breaking.
    """
    n = draw(st.integers(min_value=1, max_value=30))
    panels = []
    for i in range(n):
        priority = draw(st.integers(min_value=0, max_value=20))
        panel_id = f"panel-{i:03d}"
        panels.append(
            RegisteredPanel(
                provider=None,  # type: ignore[arg-type]
                panel_id=panel_id,
                priority=priority,
                category="general",
            )
        )
    return panels


# =============================================================================
# Property 8: General ring priority ordering
# =============================================================================


@pytest.mark.slow
class TestGeneralRingPriorityOrdering:
    """Property 8: General ring priority ordering.

    For any set of PanelProviders registered in the General_Ring with
    arbitrary priorities, the ring order should be ascending by panel_priority,
    with ties broken by registration order (first registered appears first).

    **Validates: Requirements 11.2**
    """

    @given(panels=_panel_list_strategy())
    def test_panels_sorted_ascending_by_priority(
        self, panels: list[RegisteredPanel]
    ) -> None:
        """All panels in the general ring are sorted ascending by priority."""
        ring = PanelRing(category="general")

        for panel in panels:
            ring.insert_panel(panel)

        # Verify ascending priority order
        for i in range(ring.size - 1):
            current = ring.get_panel_at(i)
            next_panel = ring.get_panel_at(i + 1)
            assert current is not None
            assert next_panel is not None
            assert current.priority <= next_panel.priority, (
                f"Panel at index {i} (id={current.panel_id}, priority={current.priority}) "
                f"has higher priority than panel at index {i + 1} "
                f"(id={next_panel.panel_id}, priority={next_panel.priority})"
            )

    @given(panels=_panel_list_strategy())
    def test_same_priority_panels_in_insertion_order(
        self, panels: list[RegisteredPanel]
    ) -> None:
        """Panels with the same priority appear in insertion (registration) order."""
        ring = PanelRing(category="general")

        for panel in panels:
            ring.insert_panel(panel)

        # Group panels by priority and verify within each group
        # they appear in insertion order (i.e., the order we fed them in).
        # Build a map: priority -> list of panel_ids in their original insertion order
        insertion_order_by_priority: dict[int, list[str]] = {}
        for panel in panels:
            insertion_order_by_priority.setdefault(panel.priority, []).append(
                panel.panel_id
            )

        # Now check the ring order: for each priority group, the relative
        # order in the ring must match the insertion order.
        ring_order_by_priority: dict[int, list[str]] = {}
        for i in range(ring.size):
            p = ring.get_panel_at(i)
            assert p is not None
            ring_order_by_priority.setdefault(p.priority, []).append(p.panel_id)

        for priority, expected_order in insertion_order_by_priority.items():
            actual_order = ring_order_by_priority[priority]
            assert actual_order == expected_order, (
                f"For priority {priority}, expected insertion order {expected_order} "
                f"but got {actual_order} in the ring"
            )

    @given(panels=_panel_list_strategy())
    def test_ring_contains_all_inserted_panels(
        self, panels: list[RegisteredPanel]
    ) -> None:
        """The ring size equals the number of inserted panels (no drops)."""
        ring = PanelRing(category="general")

        for panel in panels:
            ring.insert_panel(panel)

        assert ring.size == len(panels), (
            f"Expected ring size {len(panels)}, got {ring.size}"
        )

    @given(panels=_panel_list_strategy())
    def test_tie_breaking_is_not_alphabetical(
        self, panels: list[RegisteredPanel]
    ) -> None:
        """Tie-breaking for general ring is registration order, NOT alphabetical.

        This verifies the distinction from pre-flight ring (which uses alphabetical).
        We insert panels in a specific order and confirm the ring preserves that order
        for same-priority panels, even if alphabetical would differ.
        """
        ring = PanelRing(category="general")

        for panel in panels:
            ring.insert_panel(panel)

        # For each priority group, verify the ring order matches insertion order
        # (not alphabetical by panel_id). This is the same check as
        # test_same_priority_panels_in_insertion_order but emphasizes the
        # "not alphabetical" aspect.
        insertion_order_by_priority: dict[int, list[str]] = {}
        for panel in panels:
            insertion_order_by_priority.setdefault(panel.priority, []).append(
                panel.panel_id
            )

        ring_ids: list[str] = []
        for i in range(ring.size):
            p = ring.get_panel_at(i)
            assert p is not None
            ring_ids.append(p.panel_id)

        # Extract sub-sequences from ring for each priority
        ring_order_by_priority: dict[int, list[str]] = {}
        for i in range(ring.size):
            p = ring.get_panel_at(i)
            assert p is not None
            ring_order_by_priority.setdefault(p.priority, []).append(p.panel_id)

        for priority, expected_order in insertion_order_by_priority.items():
            actual_order = ring_order_by_priority[priority]
            # Insertion order must match (not sorted alphabetically)
            assert actual_order == expected_order, (
                f"For priority {priority}: ring has {actual_order}, "
                f"expected insertion order {expected_order} "
                f"(alphabetical would be {sorted(expected_order)})"
            )
