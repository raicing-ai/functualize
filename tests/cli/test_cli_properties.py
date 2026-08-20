"""Property-based tests for CLI fallback chain behavior.

# Feature: cli-config-and-discovery-filtering, Property 10: Fallback Chain First-Match-Wins
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.app.adapters.cli import _run_fallback_chain

# =============================================================================
# Helpers: Mock FallbackCommand implementations for testing
# =============================================================================


@dataclass
class MockFallback:
    """A FallbackCommand implementation that records matches() and execute() calls.

    Satisfies the FallbackCommand protocol structurally (duck typing).
    """

    will_match: bool = False
    exit_code: int = 0
    matches_called: bool = field(default=False, init=False)
    execute_called: bool = field(default=False, init=False)
    matches_args: list[str] | None = field(default=None, init=False)
    execute_args: list[str] | None = field(default=None, init=False)

    def matches(self, args: list[str], app: object) -> bool:
        self.matches_called = True
        self.matches_args = args
        return self.will_match

    def execute(self, args: list[str], app: object) -> int:
        self.execute_called = True
        self.execute_args = args
        return self.exit_code


# =============================================================================
# Strategies
# =============================================================================

# Strategy: argument lists (non-empty strings)
_arg_str = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
)
_args_list = st.lists(_arg_str, min_size=1, max_size=10)

# Strategy: exit codes (0-127 range typical for CLI)
_exit_code = st.integers(min_value=0, max_value=127)

# Strategy: boolean match pattern for a fallback (True = will match, False = won't)
_match_pattern = st.booleans()

# Strategy: list of match patterns representing an ordered fallback chain
# At least one element, at most 10
_fallback_patterns = st.lists(
    st.tuples(_match_pattern, _exit_code),
    min_size=1,
    max_size=10,
)


# =============================================================================
# Property 10: Fallback Chain First-Match-Wins
# =============================================================================


@pytest.mark.slow
class TestFallbackChainFirstMatchWins:
    """Property 10: Fallback Chain First-Match-Wins.

    For any ordered list of FallbackCommand instances and any argument list,
    the system SHALL execute the execute() method of the first fallback whose
    matches() returns True, and SHALL not consult subsequent fallbacks.

    **Validates: Requirements 15.2, 15.10**
    """

    @given(
        patterns=_fallback_patterns.filter(lambda ps: any(p[0] for p in ps)),
        args=_args_list,
    )
    def test_first_matching_fallback_execute_is_called(
        self, patterns: list[tuple[bool, int]], args: list[str]
    ):
        """Only the first fallback whose matches() returns True has execute() called.

        **Validates: Requirements 15.2, 15.10**
        """
        fallbacks = [
            MockFallback(will_match=will_match, exit_code=code)
            for will_match, code in patterns
        ]

        _run_fallback_chain(args, app=None, fallbacks=fallbacks)  # type: ignore[arg-type]

        # Find the index of the first matching fallback
        first_match_idx = next(
            i for i, (will_match, _) in enumerate(patterns) if will_match
        )

        # The first matching fallback must have execute() called
        assert fallbacks[first_match_idx].execute_called, (
            f"First matching fallback at index {first_match_idx} "
            f"did not have execute() called"
        )

        # No other fallback should have execute() called
        for i, fb in enumerate(fallbacks):
            if i != first_match_idx:
                assert not fb.execute_called, (
                    f"Fallback at index {i} should not have execute() called, "
                    f"but it was (first match is at index {first_match_idx})"
                )

    @given(
        patterns=_fallback_patterns.filter(lambda ps: any(p[0] for p in ps)),
        args=_args_list,
    )
    def test_fallbacks_after_first_match_not_consulted(
        self, patterns: list[tuple[bool, int]], args: list[str]
    ):
        """Fallbacks after the first match are not consulted (matches() not called).

        **Validates: Requirements 15.2, 15.10**
        """
        fallbacks = [
            MockFallback(will_match=will_match, exit_code=code)
            for will_match, code in patterns
        ]

        _run_fallback_chain(args, app=None, fallbacks=fallbacks)  # type: ignore[arg-type]

        # Find the index of the first matching fallback
        first_match_idx = next(
            i for i, (will_match, _) in enumerate(patterns) if will_match
        )

        # Fallbacks after the first match should NOT have matches() called
        for i in range(first_match_idx + 1, len(fallbacks)):
            assert not fallbacks[i].matches_called, (
                f"Fallback at index {i} had matches() called, "
                f"but it comes after the first match at index {first_match_idx}"
            )

    @given(
        patterns=_fallback_patterns.filter(lambda ps: any(p[0] for p in ps)),
        args=_args_list,
    )
    def test_first_match_exit_code_is_returned(
        self, patterns: list[tuple[bool, int]], args: list[str]
    ):
        """The return value is the exit code from the first matching fallback's execute().

        **Validates: Requirements 15.2, 15.10**
        """
        fallbacks = [
            MockFallback(will_match=will_match, exit_code=code)
            for will_match, code in patterns
        ]

        result = _run_fallback_chain(args, app=None, fallbacks=fallbacks)  # type: ignore[arg-type]

        # Find the expected exit code from the first matching fallback
        first_match_idx = next(
            i for i, (will_match, _) in enumerate(patterns) if will_match
        )
        expected_exit_code = patterns[first_match_idx][1]

        assert result == expected_exit_code, (
            f"Expected exit code {expected_exit_code} from first matching fallback "
            f"at index {first_match_idx}, got {result}"
        )

    @given(
        patterns=_fallback_patterns.filter(lambda ps: not any(p[0] for p in ps)),
        args=_args_list,
    )
    def test_no_match_returns_exit_code_1(
        self, patterns: list[tuple[bool, int]], args: list[str]
    ):
        """When no fallback matches, return exit code 1 (command not found).

        **Validates: Requirements 15.2, 15.10**
        """
        fallbacks = [
            MockFallback(will_match=will_match, exit_code=code)
            for will_match, code in patterns
        ]

        result = _run_fallback_chain(args, app=None, fallbacks=fallbacks)  # type: ignore[arg-type]

        assert result == 1, (
            f"Expected exit code 1 when no fallback matches, got {result}"
        )

        # No fallback should have execute() called
        for i, fb in enumerate(fallbacks):
            assert not fb.execute_called, (
                f"Fallback at index {i} should not have execute() called "
                f"when none match"
            )

    @given(
        patterns=_fallback_patterns.filter(lambda ps: any(p[0] for p in ps)),
        args=_args_list,
    )
    def test_fallbacks_before_first_match_have_matches_called(
        self, patterns: list[tuple[bool, int]], args: list[str]
    ):
        """All fallbacks before the first match have matches() called (consulted).

        **Validates: Requirements 15.2, 15.10**
        """
        fallbacks = [
            MockFallback(will_match=will_match, exit_code=code)
            for will_match, code in patterns
        ]

        _run_fallback_chain(args, app=None, fallbacks=fallbacks)  # type: ignore[arg-type]

        # Find the index of the first matching fallback
        first_match_idx = next(
            i for i, (will_match, _) in enumerate(patterns) if will_match
        )

        # All fallbacks up to and including the first match should have matches() called
        for i in range(first_match_idx + 1):
            assert fallbacks[i].matches_called, (
                f"Fallback at index {i} should have matches() called "
                f"(it precedes or is the first match at index {first_match_idx})"
            )
