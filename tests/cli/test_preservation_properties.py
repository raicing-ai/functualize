"""Preservation property tests for TUI CLI audit cleanup.

# Feature: tui-cli-audit-cleanup, Property 2: Preservation
# Data Model and State Machine Behavior Unchanged

These tests observe and assert baseline behavior of data models and state machines
on UNFIXED code (importing from archive locations). They are expected to PASS,
confirming the behaviors that must be preserved during the refactoring.

After the fix, imports will be updated to canonical locations and these tests
must continue to PASS (confirming no regressions).

**Validates: Requirements 3.1, 3.5, 3.6, 3.7, 3.8**
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, note, settings
from hypothesis import strategies as st

from functualize._cli.data.config_target import ConfigTarget
from functualize._cli.tui.models.focus_state import (
    KEYMAPS,
    FocusMode,
    FocusState,
    FocusZone,
)
from functualize._cli.tui.models.panel_ring_controller import (
    Category,
    PanelRingController,
)

# Import from CANONICAL locations (fixed code)
from functualize._cli.tui.models.ring_models import BreadcrumbState

# =============================================================================
# Strategies
# =============================================================================

# BreadcrumbState strategy
_type_prefixes = st.sampled_from(["D", "R", "E"])
_positions = st.integers(min_value=1, max_value=99)
_totals = st.integers(min_value=1, max_value=99)
_titles = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"), whitelist_characters=" _-"
    ),
    min_size=1,
    max_size=30,
).filter(lambda t: t.strip() != "")
_sub_level_items = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"), whitelist_characters=" _-:"
    ),
    min_size=1,
    max_size=20,
).filter(lambda t: t.strip() != "")
_sub_levels = (
    st.tuples()
    | st.tuples(_sub_level_items)
    | st.tuples(_sub_level_items, _sub_level_items)
)

_breadcrumb_states = st.builds(
    BreadcrumbState,
    type_prefix=_type_prefixes,
    position=_positions,
    total=_totals,
    title=_titles,
    sub_levels=_sub_levels,
)

# PanelRingController strategies
_ring_sizes = st.integers(min_value=1, max_value=20)
_nav_actions = st.sampled_from(["next", "prev", "first", "last"])
_nav_sequences = st.lists(_nav_actions, min_size=1, max_size=20)
_categories = st.sampled_from([Category.PRE_FLIGHT, Category.GENERAL])

# FocusState strategies
_focus_modes = st.sampled_from(list(FocusMode))
_focus_zones = st.sampled_from(list(FocusZone))

# ConfigTarget strategies. Two non-overlapping vocabularies share this field
# under the SmartBar-as-CLI model: job-config persistence targets ("file"|"env")
# and the settings-panel-only "unsaved" marker (see config_target.py).
_config_types = st.sampled_from(["file", "env", "unsaved"])
_labels = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" _-"),
    min_size=1,
    max_size=20,
).filter(lambda t: t.strip() != "")
_details = st.none() | st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"), whitelist_characters=" _-/"
    ),
    min_size=1,
    max_size=30,
).filter(lambda t: t.strip() != "")


# Valid transitions as defined in the source
_VALID_TRANSITIONS: set[tuple[FocusMode, FocusMode]] = {
    (FocusMode.COMMAND, FocusMode.NORMAL),
    (FocusMode.NORMAL, FocusMode.COMMAND),
    (FocusMode.NORMAL, FocusMode.INSERT),
    (FocusMode.NORMAL, FocusMode.FILTER),
    (FocusMode.INSERT, FocusMode.NORMAL),
    (FocusMode.FILTER, FocusMode.NORMAL),
    (FocusMode.COMMAND, FocusMode.COMMAND),
}

# =============================================================================
# Property 2: Preservation — BreadcrumbState.render()
# =============================================================================


@pytest.mark.slow
class TestBreadcrumbStateRenderPreservation:
    """BreadcrumbState.render() produces format [TYPE:N/M] Title [> Sub1 [> Sub2]].

    **Validates: Requirements 3.5**
    """

    @given(state=_breadcrumb_states)
    @settings(max_examples=200)
    def test_render_format_matches_spec(self, state: BreadcrumbState) -> None:
        """For all valid BreadcrumbState inputs, render() produces the documented format.

        Format: [TYPE:N/M] Title [> SubLevel1 [> SubLevel2]]

        **Validates: Requirements 3.5**
        """
        result = state.render()
        note(
            f"BreadcrumbState: prefix={state.type_prefix}, pos={state.position}, "
            f"total={state.total}, title={state.title!r}, subs={state.sub_levels}"
        )
        note(f"render() = {result!r}")

        # Must start with [TYPE:N/M]
        prefix_pattern = f"[{state.type_prefix}:{state.position}/{state.total}]"
        assert result.startswith(prefix_pattern), (
            f"Expected render to start with {prefix_pattern!r}, got {result!r}"
        )

        # After the prefix, must have a space then the title
        after_prefix = result[len(prefix_pattern) :]
        assert after_prefix.startswith(f" {state.title}"), (
            f"Expected title '{state.title}' after prefix, got {after_prefix!r}"
        )

        # If sub_levels present, must have ' > ' separators
        if state.sub_levels:
            for sub in state.sub_levels:
                assert f"> {sub}" in result, (
                    f"Expected sub-level '{sub}' in render output: {result!r}"
                )

        # If no sub_levels, no ' > ' separator
        if not state.sub_levels:
            assert " > " not in result, (
                f"Expected no ' > ' separator when sub_levels is empty, got {result!r}"
            )

    @given(state=_breadcrumb_states)
    @settings(max_examples=100)
    def test_render_is_deterministic(self, state: BreadcrumbState) -> None:
        """Calling render() twice on the same state produces identical output.

        **Validates: Requirements 3.5**
        """
        assert state.render() == state.render()


# =============================================================================
# Property 2: Preservation — PanelRingController Navigation
# =============================================================================


@pytest.mark.slow
class TestPanelRingControllerPreservation:
    """PanelRingController wrapping, clamping, and breadcrumb operations behave identically.

    **Validates: Requirements 3.6**
    """

    @given(ring_size=_ring_sizes, nav_seq=_nav_sequences, category=_categories)
    @settings(max_examples=200)
    def test_wrapping_and_clamping_produce_valid_indices(
        self, ring_size: int, nav_seq: list[str], category: Category
    ) -> None:
        """For all valid ring sizes and navigation sequences, indices stay in [0, ring_size-1].

        **Validates: Requirements 3.6**
        """
        ctrl = PanelRingController()

        # Activate the category
        if category == Category.PRE_FLIGHT:
            ctrl.activate_pre_flight(ring_size)
        else:
            ctrl.activate_general(ring_size)

        note(f"ring_size={ring_size}, category={category.value}, nav_seq={nav_seq}")

        for action in nav_seq:
            if action == "next":
                idx = ctrl.next_panel(ring_size)
            elif action == "prev":
                idx = ctrl.prev_panel(ring_size)
            elif action == "first":
                idx = ctrl.first_panel()
            else:  # "last"
                idx = ctrl.last_panel(ring_size)

            assert 0 <= idx < ring_size, (
                f"Index {idx} out of range [0, {ring_size - 1}] after action '{action}'"
            )
            assert idx == ctrl.current_index, (
                f"Returned index {idx} != controller's current_index {ctrl.current_index}"
            )

    @given(ring_size=_ring_sizes)
    @settings(max_examples=100)
    def test_next_wraps_at_boundary(self, ring_size: int) -> None:
        """Calling next_panel ring_size times returns to index 0 (modular wrapping).

        **Validates: Requirements 3.6**
        """
        ctrl = PanelRingController()
        ctrl.activate_general(ring_size)

        # Start at 0, go around the full ring
        for _ in range(ring_size):
            ctrl.next_panel(ring_size)

        assert ctrl.current_index == 0, (
            f"After {ring_size} next_panel calls on ring of size {ring_size}, "
            f"expected index 0, got {ctrl.current_index}"
        )

    @given(ring_size=_ring_sizes)
    @settings(max_examples=100)
    def test_prev_wraps_at_boundary(self, ring_size: int) -> None:
        """Calling prev_panel from index 0 wraps to ring_size - 1.

        **Validates: Requirements 3.6**
        """
        ctrl = PanelRingController()
        ctrl.activate_general(ring_size)
        # Start at 0
        ctrl.first_panel()

        idx = ctrl.prev_panel(ring_size)
        expected = ring_size - 1
        assert idx == expected, (
            f"prev_panel from 0 should wrap to {expected}, got {idx}"
        )

    @given(
        ring_size=st.integers(min_value=1, max_value=10),
        labels=st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=3),
    )
    @settings(max_examples=100)
    def test_breadcrumb_stack_push_pop_consistency(
        self, ring_size: int, labels: list[str]
    ) -> None:
        """Push/pop breadcrumbs maintain stack semantics with max depth 3.

        **Validates: Requirements 3.6**
        """
        ctrl = PanelRingController()
        ctrl.activate_general(ring_size)

        pushed: list[str] = []
        for label in labels:
            success = ctrl.push_breadcrumb(label)
            if success:
                pushed.append(label)
            # Max depth is 3
            assert ctrl.breadcrumb_depth <= 3

        # Pop in reverse order (LIFO)
        while pushed:
            popped = ctrl.pop_breadcrumb()
            expected = pushed.pop()
            assert popped == expected, f"Expected to pop {expected!r}, got {popped!r}"

        # After all pops, stack should be empty
        assert ctrl.pop_breadcrumb() is None
        assert ctrl.breadcrumb_depth == 0

    @given(
        start_size=st.integers(min_value=1, max_value=10),
        index=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=100)
    def test_clamping_on_activation(self, start_size: int, index: int) -> None:
        """activate_general/activate_pre_flight clamps index to valid range.

        **Validates: Requirements 3.6**
        """
        ctrl = PanelRingController()
        # Manually set an out-of-range index to test clamping
        ctrl._general_index = index
        result = ctrl.activate_general(start_size)

        assert result is not None
        assert 0 <= result < start_size, (
            f"Clamped index {result} out of range [0, {start_size - 1}] "
            f"for original index {index}"
        )


# =============================================================================
# Property 2: Preservation — FocusState Transitions
# =============================================================================


@pytest.mark.slow
class TestFocusStateTransitionPreservation:
    """FocusState mode transitions accept valid transitions and reject invalid ones.

    **Validates: Requirements 3.6**
    """

    @given(from_mode=_focus_modes, to_mode=_focus_modes)
    @settings(max_examples=100)
    def test_valid_transitions_accepted_invalid_rejected(
        self, from_mode: FocusMode, to_mode: FocusMode
    ) -> None:
        """For all FocusMode pairs, transition() succeeds iff (from, to) is valid.

        **Validates: Requirements 3.6**
        """
        fs = FocusState()
        # Force to the starting mode
        fs.force(from_mode, FocusZone.PANEL)

        result = fs.transition(to_mode)
        is_valid = (from_mode, to_mode) in _VALID_TRANSITIONS

        note(
            f"from={from_mode.value} -> to={to_mode.value}, valid={is_valid}, result={result}"
        )

        assert result == is_valid, (
            f"Transition ({from_mode.value} -> {to_mode.value}): "
            f"expected {'accepted' if is_valid else 'rejected'}, "
            f"got {'accepted' if result else 'rejected'}"
        )

    @given(from_mode=_focus_modes, to_mode=_focus_modes, zone=_focus_zones)
    @settings(max_examples=100)
    def test_successful_transition_updates_mode(
        self, from_mode: FocusMode, to_mode: FocusMode, zone: FocusZone
    ) -> None:
        """When a valid transition succeeds, mode is updated to the target mode.

        **Validates: Requirements 3.6**
        """
        assume((from_mode, to_mode) in _VALID_TRANSITIONS)

        fs = FocusState()
        fs.force(from_mode, FocusZone.PANEL)
        fs.transition(to_mode, zone)

        assert fs.mode == to_mode, (
            f"After valid transition to {to_mode.value}, mode should be {to_mode.value}, "
            f"got {fs.mode.value}"
        )

    @given(from_mode=_focus_modes, to_mode=_focus_modes)
    @settings(max_examples=100)
    def test_failed_transition_preserves_state(
        self, from_mode: FocusMode, to_mode: FocusMode
    ) -> None:
        """When a transition is rejected, mode and zone remain unchanged.

        **Validates: Requirements 3.6**
        """
        assume((from_mode, to_mode) not in _VALID_TRANSITIONS)

        fs = FocusState()
        fs.force(from_mode, FocusZone.PANEL)

        original_mode = fs.mode
        original_zone = fs.zone

        result = fs.transition(to_mode)

        assert result is False
        assert fs.mode == original_mode, (
            f"Mode changed from {original_mode.value} to {fs.mode.value} on rejected transition"
        )
        assert fs.zone == original_zone, (
            f"Zone changed from {original_zone.value} to {fs.zone.value} on rejected transition"
        )

    def test_keymaps_define_actions_for_all_modes(self) -> None:
        """KEYMAPS has entries for all four FocusMode values.

        **Validates: Requirements 3.6**
        """
        for mode in FocusMode:
            assert mode in KEYMAPS, f"KEYMAPS missing entry for {mode.value}"
            assert len(KEYMAPS[mode]) > 0, f"KEYMAPS[{mode.value}] has no key bindings"

    def test_command_to_normal_sets_zone_to_smartbar_on_return(self) -> None:
        """Transitioning to COMMAND mode auto-sets zone to SMARTBAR.

        **Validates: Requirements 3.6**
        """
        fs = FocusState()
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        fs.transition(FocusMode.COMMAND)
        assert fs.zone == FocusZone.SMARTBAR


# =============================================================================
# Property 2: Preservation — ConfigTarget.display_label()
# =============================================================================


@pytest.mark.slow
class TestConfigTargetDisplayLabelPreservation:
    """ConfigTarget.display_label() formatting unchanged.

    **Validates: Requirements 3.5**
    """

    @given(type_=_config_types, label=_labels, detail=_details)
    @settings(max_examples=100)
    def test_display_label_format(
        self, type_: str, label: str, detail: str | None
    ) -> None:
        """display_label() returns 'label (detail)' when detail present, else just 'label'.

        **Validates: Requirements 3.5**
        """
        target = ConfigTarget(type=type_, label=label, detail=detail)
        result = target.display_label()

        note(f"ConfigTarget(type={type_!r}, label={label!r}, detail={detail!r})")
        note(f"display_label() = {result!r}")

        if detail:
            expected = f"{label} ({detail})"
            assert result == expected, f"Expected {expected!r}, got {result!r}"
        else:
            assert result == label, f"Expected {label!r} (no detail), got {result!r}"
