# Feature: tui-v3-ux-polish, Property 5: CSS class exclusivity for readiness states
"""Property-based tests for CSS class exclusivity of readiness states.

Tests SmartBar._set_readiness() from functualize._cli.tui.bar:
- Property 5: For any BarReadiness enum value, after _set_readiness(value),
  exactly one class from {"grey", "pending", "ready", "editing", "invalid"}
  is applied and no others are present.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.bar import BarReadiness, SmartBar

# =============================================================================
# Constants
# =============================================================================

_READINESS_CLASSES = frozenset({"grey", "pending", "ready", "editing", "invalid"})


# =============================================================================
# Strategies
# =============================================================================

_readiness_strategy = st.sampled_from(list(BarReadiness))

_transition_sequence = st.lists(
    st.sampled_from(list(BarReadiness)),
    min_size=1,
    max_size=10,
)


# =============================================================================
# Property 5: CSS class exclusivity for readiness states
# =============================================================================


@pytest.mark.slow
class TestCSSClassExclusivity:
    """Property 5: CSS class exclusivity for readiness states.

    For any BarReadiness enum value, after _set_readiness(value) completes,
    the SmartBar widget has exactly one CSS class from the set
    {"grey", "pending", "ready", "editing", "invalid"} applied — specifically
    the one matching value.value — and none of the other readiness classes
    are present.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
    """

    @given(readiness=_readiness_strategy)
    def test_single_transition_has_exactly_one_readiness_class(
        self,
        readiness: BarReadiness,
    ) -> None:
        """After _set_readiness(value), exactly one readiness class is applied."""
        bar = SmartBar(id="test")

        # Force transition by setting a different initial state first
        # (SmartBar starts at GREY, _set_readiness is a no-op if same)
        if readiness == BarReadiness.GREY:
            # Move away from GREY first so transition actually fires
            bar._set_readiness(BarReadiness.READY)
        bar._set_readiness(readiness)

        # Check which readiness classes are present
        present_classes = _READINESS_CLASSES & bar.classes

        assert present_classes == {readiness.value}, (
            f"After _set_readiness({readiness}),\n"
            f"  Expected exactly: {{'{readiness.value}'}}\n"
            f"  Found: {present_classes}\n"
            f"  All classes on widget: {bar.classes}"
        )

    @given(transitions=_transition_sequence)
    def test_sequence_of_transitions_ends_with_exactly_one_class(
        self,
        transitions: list[BarReadiness],
    ) -> None:
        """After a sequence of readiness transitions, exactly one class remains."""
        bar = SmartBar(id="test")

        # Ensure the first transition is always effective by moving away from
        # the initial GREY state (which has no CSS class applied in __init__).
        # We force a real transition first so the class management logic fires.
        bar._set_readiness(BarReadiness.READY)

        # Apply all transitions in sequence
        for readiness in transitions:
            bar._set_readiness(readiness)

        final = transitions[-1]
        present_classes = _READINESS_CLASSES & bar.classes

        assert present_classes == {final.value}, (
            f"After transitions {[t.value for t in transitions]},\n"
            f"  Expected exactly: {{'{final.value}'}}\n"
            f"  Found: {present_classes}\n"
            f"  All classes on widget: {bar.classes}"
        )

    @given(readiness=_readiness_strategy)
    def test_no_stale_readiness_classes_after_transition(
        self,
        readiness: BarReadiness,
    ) -> None:
        """After _set_readiness(value), no other readiness classes remain."""
        bar = SmartBar(id="test")

        # Start from a different state to ensure removal logic fires
        other_states = [r for r in BarReadiness if r != readiness]
        if other_states:
            bar._set_readiness(other_states[0])

        bar._set_readiness(readiness)

        # The "other" readiness classes must NOT be present
        other_classes = (_READINESS_CLASSES - {readiness.value}) & bar.classes

        assert not other_classes, (
            f"After _set_readiness({readiness}),\n"
            f"  Stale classes still present: {other_classes}\n"
            f"  Expected only: '{readiness.value}'"
        )

    @given(
        first=_readiness_strategy,
        second=_readiness_strategy,
    )
    def test_transition_between_any_two_states_is_exclusive(
        self,
        first: BarReadiness,
        second: BarReadiness,
    ) -> None:
        """Transitioning from any state to any other state yields exclusivity."""
        bar = SmartBar(id="test")

        # Bootstrap: move to a state different from `first` so the first
        # _set_readiness call is guaranteed to fire (not a no-op).
        bootstrap = (
            BarReadiness.READY if first != BarReadiness.READY else BarReadiness.PENDING
        )
        bar._set_readiness(bootstrap)

        # Now perform the actual pair of transitions
        bar._set_readiness(first)
        bar._set_readiness(second)

        present_classes = _READINESS_CLASSES & bar.classes

        assert present_classes == {second.value}, (
            f"Transition {first.value} -> {second.value}:\n"
            f"  Expected exactly: {{'{second.value}'}}\n"
            f"  Found: {present_classes}"
        )
