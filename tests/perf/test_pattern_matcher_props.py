# Feature: perf-timeline-mark, Property 3: Phase filter semantics
"""Property-based tests for pattern matcher filter semantics.

**Validates: Requirements 3.3, 3.4, 3.5, 3.6, 5.2, 5.3, 5.4, 5.5**

Property 3: Phase filter semantics — include then exclude
For any list of phase names and any combination of include/exclude patterns,
filter_phases(names, include, exclude) returns exactly the set of names that
match at least one include pattern AND do not match any exclude pattern,
preserving original order.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._events._pattern_matcher import (
    filter_phases,
    matches_any,
    parse_patterns,
)

# --- Strategies ---

# Phase name segment: 1-8 lowercase alpha chars
_segment = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=1,
    max_size=8,
)

# Phase name: 1-4 dot-delimited segments (e.g., "boot.plugins.load")
_phase_name = st.lists(_segment, min_size=1, max_size=4).map(".".join)

# List of phase names (1-20 names)
_phase_names = st.lists(_phase_name, min_size=1, max_size=20)

# Pattern: either a prefix (no wildcard) or a glob with * or **
_prefix_pattern = _segment  # simple prefix match
_glob_pattern = st.one_of(
    # Single wildcard: "segment.*"
    st.tuples(_segment, st.just(".*")).map("".join),
    # Double wildcard: "segment.**"
    st.tuples(_segment, st.just(".**")).map("".join),
    # Wildcard in middle: "seg*.seg"
    st.tuples(_segment, st.just("*."), _segment).map("".join),
    # Just a wildcard
    st.just("**"),
)

_single_pattern = st.one_of(_prefix_pattern, _glob_pattern)

# Comma-separated pattern string (1-3 patterns)
_pattern_string = st.lists(_single_pattern, min_size=1, max_size=3).map(", ".join)

# Optional pattern (None or a pattern string)
_optional_pattern = st.one_of(st.none(), _pattern_string)


class TestFilterSemanticsProperty:
    """Property 3: Phase filter semantics — include then exclude."""

    @given(names=_phase_names, include=_pattern_string, exclude=_pattern_string)
    def test_filter_equals_include_and_not_exclude(
        self,
        names: list[str],
        include: str,
        exclude: str,
    ) -> None:
        """filter_phases with both include and exclude returns exactly names
        matching at least one include pattern AND not matching any exclude pattern.
        """
        result = filter_phases(names, include=include, exclude=exclude)

        include_patterns = parse_patterns(include)
        exclude_patterns = parse_patterns(exclude)

        expected = [
            n
            for n in names
            if matches_any(n, include_patterns) and not matches_any(n, exclude_patterns)
        ]

        assert result == expected

    @given(names=_phase_names, include=_pattern_string)
    def test_include_only_matches_at_least_one_pattern(
        self,
        names: list[str],
        include: str,
    ) -> None:
        """filter_phases with only include returns names matching at least one
        include pattern, preserving order.
        """
        result = filter_phases(names, include=include, exclude=None)

        include_patterns = parse_patterns(include)
        expected = [n for n in names if matches_any(n, include_patterns)]

        assert result == expected

    @given(names=_phase_names, exclude=_pattern_string)
    def test_exclude_only_removes_matching(
        self,
        names: list[str],
        exclude: str,
    ) -> None:
        """filter_phases with only exclude returns names NOT matching any
        exclude pattern, preserving order.
        """
        result = filter_phases(names, include=None, exclude=exclude)

        exclude_patterns = parse_patterns(exclude)
        expected = [n for n in names if not matches_any(n, exclude_patterns)]

        assert result == expected

    @given(names=_phase_names, include=_optional_pattern, exclude=_optional_pattern)
    def test_order_preservation(
        self,
        names: list[str],
        include: str | None,
        exclude: str | None,
    ) -> None:
        """filter_phases preserves the relative order of names from the input."""
        result = filter_phases(names, include=include, exclude=exclude)

        # Every element in result must appear in names in the same relative order
        result_indices = []
        for r in result:
            # Find the index of r in names starting after the last found index
            start = result_indices[-1] + 1 if result_indices else 0
            for i in range(start, len(names)):
                if names[i] == r:
                    result_indices.append(i)
                    break

        # Indices must be strictly increasing (order preserved)
        assert result_indices == sorted(result_indices)
        assert len(result_indices) == len(result)

    @given(names=_phase_names)
    def test_no_filters_returns_all(
        self,
        names: list[str],
    ) -> None:
        """filter_phases with no include/exclude returns all names unchanged."""
        result = filter_phases(names, include=None, exclude=None)
        assert result == names
