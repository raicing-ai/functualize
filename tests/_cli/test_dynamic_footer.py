"""Property-based tests for DynamicFooter rendering.

# Feature: tui-architecture-v2, Property 5: Dynamic footer renders action tuples faithfully

Tests render_footer() from functualize._cli.tui.dynamic_footer:
- Property 5: Dynamic footer renders action tuples faithfully

**Validates: Requirements 3.1, 3.8**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.dynamic_footer import render_footer

# =============================================================================
# Strategies
# =============================================================================

# Non-empty strings without double-spaces (to avoid ambiguity in splitting)
_action_text_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\n\r\t",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: "  " not in s and s.strip() == s)

# A single (key, label) tuple
_action_tuple_strategy = st.tuples(_action_text_strategy, _action_text_strategy)

# A list of action tuples (0 to 10 items)
_action_list_strategy = st.lists(_action_tuple_strategy, min_size=0, max_size=10)


# =============================================================================
# Property 5: Dynamic footer renders action tuples faithfully
# =============================================================================


@pytest.mark.slow
class TestDynamicFooterRendering:
    """Property 5: Dynamic footer renders action tuples faithfully.

    For any list of (key, label) tuples returned by get_available_actions(focused),
    the rendered footer string should contain each key-label pair formatted as
    "key label" with pairs separated by double spaces, and an empty list should
    produce an empty string.

    **Validates: Requirements 3.1, 3.8**
    """

    @given(actions=_action_list_strategy)
    @settings(max_examples=100)
    def test_empty_list_produces_empty_string(
        self, actions: list[tuple[str, str]]
    ) -> None:
        """Empty action list produces empty string (Req 3.8)."""
        if len(actions) == 0:
            result = render_footer(actions)
            assert result == ""

    @given(actions=st.lists(_action_tuple_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_all_keys_and_labels_appear_in_output(
        self, actions: list[tuple[str, str]]
    ) -> None:
        """All keys and labels appear in the rendered output (Req 3.1)."""
        result = render_footer(actions)
        for key, label in actions:
            assert key in result, (
                f"Key {key!r} not found in rendered output: {result!r}"
            )
            assert label in result, (
                f"Label {label!r} not found in rendered output: {result!r}"
            )

    @given(actions=st.lists(_action_tuple_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_pairs_formatted_as_key_space_label(
        self, actions: list[tuple[str, str]]
    ) -> None:
        """Each pair is formatted as 'key label' (Req 3.1)."""
        result = render_footer(actions)
        for key, label in actions:
            expected_pair = f"{key} {label}"
            assert expected_pair in result, (
                f"Expected pair {expected_pair!r} not found in: {result!r}"
            )

    @given(actions=st.lists(_action_tuple_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_splitting_on_double_space_gives_n_pairs(
        self, actions: list[tuple[str, str]]
    ) -> None:
        """Output splits on '  ' (double space) to give exactly N pairs (Req 3.1)."""
        result = render_footer(actions)
        parts = result.split("  ")
        assert len(parts) == len(actions), (
            f"Expected {len(actions)} pairs but got {len(parts)} when splitting: {result!r}"
        )

    @given(actions=st.lists(_action_tuple_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_split_parts_match_key_label_pairs_in_order(
        self, actions: list[tuple[str, str]]
    ) -> None:
        """Split parts match key-label pairs in the original order (Req 3.1)."""
        result = render_footer(actions)
        parts = result.split("  ")
        for i, (key, label) in enumerate(actions):
            expected_pair = f"{key} {label}"
            assert parts[i] == expected_pair, (
                f"Part {i}: expected {expected_pair!r} but got {parts[i]!r}"
            )
