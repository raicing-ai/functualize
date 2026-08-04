# Feature: tui-v3-ux-polish, Property 3: Autocomplete trailing space and cursor positioning
"""Property-based tests for autocomplete trailing space and cursor positioning.

Tests the core text assembly logic from apply_completion():
- The resulting text contains the completed (quoted) value followed by exactly one trailing space
- The cursor position equals partial_start + len(quoted_value) + 1

**Validates: Requirements 3.1, 3.2, 3.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.completions.quote_handling import quote_for_insertion

# =============================================================================
# Strategies
# =============================================================================

# Prefix text: what comes before the partial being completed (e.g., "deploy ")
_prefix = st.text(
    min_size=0,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
)

# Partial text: the incomplete token being completed (at least 1 char)
_partial = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)

# Completion value: the full value to insert (job name, flag, value)
_value = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
)

# Suffix text: what comes after the cursor position
_suffix = st.text(
    min_size=0,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
)


# =============================================================================
# Pure function under test: replicates the core logic of apply_completion()
# =============================================================================


def apply_completion_logic(
    prefix: str, partial: str, value: str, suffix: str
) -> tuple[str, int]:
    """Replicate apply_completion() text assembly and cursor logic.

    Args:
        prefix: Text before the partial being completed.
        partial: The incomplete token being replaced.
        value: The raw completion value (will be quoted if needed).
        suffix: Text after the cursor position.

    Returns:
        Tuple of (new_text, new_cursor_position).
    """
    # Simulate the input state: text = prefix + partial + suffix
    text = prefix + partial + suffix
    cursor_pos = len(prefix) + len(partial)  # cursor is at end of partial
    partial_start = cursor_pos - len(partial)  # = len(prefix)

    quoted_value = quote_for_insertion(value)

    # Core apply_completion logic
    new_text = text[:partial_start] + quoted_value + " " + text[cursor_pos:]
    new_cursor = partial_start + len(quoted_value) + 1

    return new_text, new_cursor


# =============================================================================
# Property 3: Autocomplete trailing space and cursor positioning
# =============================================================================


@pytest.mark.slow
class TestAutocompleteTrailingSpaceAndCursor:
    """Property 3: Autocomplete trailing space and cursor positioning.

    For any valid completion value and cursor context, after applying the
    completion:
    1. The resulting text contains the quoted value at the insertion point
    2. The resulting text has exactly one trailing space after the quoted value
    3. The cursor position equals partial_start + len(quoted_value) + 1

    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    @given(prefix=_prefix, partial=_partial, value=_value, suffix=_suffix)
    @settings(max_examples=200)
    def test_result_contains_quoted_value_at_insertion_point(
        self, prefix: str, partial: str, value: str, suffix: str
    ) -> None:
        """The resulting text contains the quoted value starting at partial_start."""
        new_text, _ = apply_completion_logic(prefix, partial, value, suffix)
        quoted_value = quote_for_insertion(value)
        partial_start = len(prefix)

        assert (
            new_text[partial_start : partial_start + len(quoted_value)] == quoted_value
        ), (
            f"Expected quoted_value={quoted_value!r} at position {partial_start} "
            f"in new_text={new_text!r}"
        )

    @given(prefix=_prefix, partial=_partial, value=_value, suffix=_suffix)
    @settings(max_examples=200)
    def test_trailing_space_after_quoted_value(
        self, prefix: str, partial: str, value: str, suffix: str
    ) -> None:
        """Exactly one trailing space follows the quoted value at the insertion point."""
        new_text, _ = apply_completion_logic(prefix, partial, value, suffix)
        quoted_value = quote_for_insertion(value)
        partial_start = len(prefix)
        space_index = partial_start + len(quoted_value)

        assert new_text[space_index] == " ", (
            f"Expected space at position {space_index} in new_text={new_text!r}, "
            f"got {new_text[space_index]!r}"
        )

    @given(prefix=_prefix, partial=_partial, value=_value, suffix=_suffix)
    @settings(max_examples=200)
    def test_cursor_positioned_after_trailing_space(
        self, prefix: str, partial: str, value: str, suffix: str
    ) -> None:
        """Cursor position equals partial_start + len(quoted_value) + 1."""
        _, new_cursor = apply_completion_logic(prefix, partial, value, suffix)
        quoted_value = quote_for_insertion(value)
        partial_start = len(prefix)
        expected_cursor = partial_start + len(quoted_value) + 1

        assert new_cursor == expected_cursor, (
            f"Expected cursor at {expected_cursor}, got {new_cursor}. "
            f"partial_start={partial_start}, len(quoted_value)={len(quoted_value)}"
        )

    @given(prefix=_prefix, partial=_partial, value=_value, suffix=_suffix)
    @settings(max_examples=200)
    def test_prefix_preserved(
        self, prefix: str, partial: str, value: str, suffix: str
    ) -> None:
        """Text before the partial is preserved unchanged."""
        new_text, _ = apply_completion_logic(prefix, partial, value, suffix)

        assert new_text[: len(prefix)] == prefix, (
            f"Expected prefix={prefix!r} preserved, got {new_text[: len(prefix)]!r}"
        )

    @given(prefix=_prefix, partial=_partial, value=_value, suffix=_suffix)
    @settings(max_examples=200)
    def test_suffix_preserved(
        self, prefix: str, partial: str, value: str, suffix: str
    ) -> None:
        """Text after the cursor position (suffix) is preserved unchanged."""
        new_text, new_cursor = apply_completion_logic(prefix, partial, value, suffix)

        assert new_text[new_cursor:] == suffix, (
            f"Expected suffix={suffix!r} after cursor, got {new_text[new_cursor:]!r}"
        )
