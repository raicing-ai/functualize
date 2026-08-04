"""Property-based tests for quote handling round-trip.

# Feature: tui-architecture-v2, Property 13: Quote handling round-trip

Tests quote_for_insertion and tokenize_smart_bar from functualize._cli.quote_handling:
- Property 13: Quote handling round-trip

**Validates: Requirements 21.1, 21.3, 21.4**
"""

from __future__ import annotations

import shlex

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.completions.quote_handling import (
    quote_for_insertion,
    tokenize_smart_bar,
)

# =============================================================================
# Strategies
# =============================================================================

# Non-space, non-quote, non-backslash printable characters
_word_char = st.characters(
    whitelist_categories=("L", "N", "P"),
    blacklist_characters="\"' \t\x00\n\r\\",
)

# Word segments (non-empty, no spaces/quotes)
_word_segment = st.text(alphabet=_word_char, min_size=1, max_size=15)


@st.composite
def _value_with_spaces_no_quotes(draw: st.DrawFn) -> str:
    """Generate strings with at least one space but no quote characters.

    Builds by joining 2+ word segments with spaces.
    """
    segments = draw(st.lists(_word_segment, min_size=2, max_size=5))
    return " ".join(segments)


# Strings with no spaces (should be returned as-is)
_value_no_spaces = st.text(
    alphabet=_word_char,
    min_size=1,
    max_size=50,
)

# Non-space, non-single-quote, non-backslash printable characters (allows double quotes)
_word_or_dquote_char = st.characters(
    whitelist_categories=("L", "N", "P"),
    blacklist_characters="' \t\x00\n\r\\",
)

_word_or_dquote_segment = st.text(
    alphabet=_word_or_dquote_char, min_size=1, max_size=15
)


@st.composite
def _value_with_spaces_and_double_quotes(draw: st.DrawFn) -> str:
    """Generate strings that contain at least one space AND at least one double quote.

    No single quotes (to allow single-quoting round-trip).
    Builds by joining segments with spaces and ensuring at least one has a double quote.
    """
    # Generate 2+ segments (some may contain double quotes)
    segments = draw(st.lists(_word_or_dquote_segment, min_size=2, max_size=5))
    # Ensure at least one segment contains a double quote
    insert_idx = draw(st.integers(min_value=0, max_value=len(segments) - 1))
    if '"' not in segments[insert_idx]:
        # Insert a double quote into one segment
        pos = draw(st.integers(min_value=0, max_value=len(segments[insert_idx])))
        seg = segments[insert_idx]
        segments[insert_idx] = seg[:pos] + '"' + seg[pos:]
    return " ".join(segments)


# Strings for testing tokenize_smart_bar with unclosed quotes (doesn't crash)
_arbitrary_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00\n\r",
    ),
    min_size=0,
    max_size=100,
)


# =============================================================================
# Property 13: Quote handling round-trip
# =============================================================================


@pytest.mark.slow
class TestQuoteHandlingRoundTrip:
    """Property 13: Quote handling round-trip.

    For any string value containing spaces (but no unbalanced quotes),
    wrapping it in double quotes and then tokenizing with shlex.split
    should recover the original string as a single token. For values
    containing both spaces and double quotes, single-quoting should
    produce a valid single token.

    **Validates: Requirements 21.1, 21.3, 21.4**
    """

    @given(value=_value_no_spaces)
    @settings(max_examples=100)
    def test_no_spaces_returned_as_is(self, value: str) -> None:
        """Values without spaces are returned unchanged (Req 21.3 precondition).

        When value has no spaces, quote_for_insertion returns it as-is,
        and tokenizing should recover the original.
        """
        quoted = quote_for_insertion(value)
        assert quoted == value, f"Expected as-is but got {quoted!r} for {value!r}"
        # Tokenizing should also recover it as a single token
        tokens = shlex.split(quoted)
        assert tokens == [value]

    @given(value=_value_with_spaces_no_quotes())
    @settings(max_examples=100)
    def test_spaces_no_quotes_double_quoted_round_trip(self, value: str) -> None:
        """Values with spaces but no double quotes are double-quoted and round-trip (Req 21.3).

        quote_for_insertion wraps in double quotes, shlex.split recovers original.
        """
        quoted = quote_for_insertion(value)
        # Should be wrapped in double quotes
        assert quoted.startswith('"'), f"Expected double-quote start: {quoted!r}"
        assert quoted.endswith('"'), f"Expected double-quote end: {quoted!r}"
        # Round-trip: tokenize should recover original value
        tokens = shlex.split(quoted)
        assert len(tokens) == 1, f"Expected 1 token, got {len(tokens)}: {tokens!r}"
        assert tokens[0] == value

    @given(value=_value_with_spaces_and_double_quotes())
    @settings(max_examples=100)
    def test_spaces_and_double_quotes_single_quoted_round_trip(
        self, value: str
    ) -> None:
        """Values with spaces and double quotes are single-quoted and round-trip (Req 21.4).

        quote_for_insertion wraps in single quotes, shlex.split recovers original.
        """
        quoted = quote_for_insertion(value)
        # Should be wrapped in single quotes
        assert quoted.startswith("'"), f"Expected single-quote start: {quoted!r}"
        assert quoted.endswith("'"), f"Expected single-quote end: {quoted!r}"
        # Round-trip: tokenize should recover original value
        tokens = shlex.split(quoted)
        assert len(tokens) == 1, f"Expected 1 token, got {len(tokens)}: {tokens!r}"
        assert tokens[0] == value

    @given(text=_arbitrary_text)
    @settings(max_examples=100)
    def test_tokenize_smart_bar_never_crashes(self, text: str) -> None:
        """tokenize_smart_bar handles any input gracefully (Req 21.2).

        For any string (including unclosed quotes), tokenize_smart_bar
        returns a list without raising an exception.
        """
        result = tokenize_smart_bar(text)
        assert isinstance(result, list)
        # All elements should be strings
        for token in result:
            assert isinstance(token, str)
