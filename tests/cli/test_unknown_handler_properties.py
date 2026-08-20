"""Property-based tests for the unknown command handler.

# Feature: eliminate-fallback-group
# Property 6: Unknown Command Error Output
# Property 7: Suggestion Boundedness
# Property 8: Fuzzy Match Completeness
"""

from __future__ import annotations

import sys
from io import StringIO

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.main import _fuzzy_suggest, _handle_unknown, _levenshtein

# =============================================================================
# Strategies
# =============================================================================

# Characters valid for command names (lowercase alphanumeric + underscore/dash)
_cmd_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-")

# A command name: non-empty string of valid characters
_cmd_name = st.text(_cmd_chars, min_size=1, max_size=20)

# A set of job names (possibly empty)
_job_names_set = st.frozensets(_cmd_name, min_size=0, max_size=50).map(set)

# A non-empty set of job names (for suggestion tests)
_nonempty_job_names_set = st.frozensets(_cmd_name, min_size=1, max_size=50).map(set)


# =============================================================================
# Property 6: Unknown Command Error Output
# =============================================================================


@pytest.mark.slow
class TestUnknownCommandErrorOutput:
    """Property 6: Unknown Command Error Output.

    For any unrecognized command string, _handle_unknown SHALL produce output
    to stderr that contains both the unrecognized command name and guidance
    directing the user to run `func` for the full command list.

    **Validates: Requirements 5.1, 5.4, 5.6**
    """

    @given(cmd=_cmd_name, job_names=_job_names_set)
    def test_output_contains_unrecognized_command(
        self, cmd: str, job_names: set[str]
    ) -> None:
        """stderr output always contains the unrecognized command name.

        **Validates: Requirements 5.1, 5.4, 5.6**
        """
        # Remove cmd from job_names so it's genuinely unknown
        clean_job_names = job_names - {cmd}

        captured = StringIO()
        old_stderr = sys.stderr
        try:
            sys.stderr = captured
            _handle_unknown([cmd], clean_job_names)
        finally:
            sys.stderr = old_stderr

        output = captured.getvalue()

        assert cmd in output, (
            f"Expected unrecognized command '{cmd}' to appear in stderr output, "
            f"but got: {output!r}"
        )

    @given(cmd=_cmd_name, job_names=_job_names_set)
    def test_output_contains_func_guidance(self, cmd: str, job_names: set[str]) -> None:
        """stderr output always contains 'func' guidance for full command list.

        **Validates: Requirements 5.1, 5.4, 5.6**
        """
        # Remove cmd from job_names so it's genuinely unknown
        clean_job_names = job_names - {cmd}

        captured = StringIO()
        old_stderr = sys.stderr
        try:
            sys.stderr = captured
            _handle_unknown([cmd], clean_job_names)
        finally:
            sys.stderr = old_stderr

        output = captured.getvalue()

        assert "func" in output, (
            f"Expected 'func' guidance in stderr output, but got: {output!r}"
        )

    @given(cmd=_cmd_name, job_names=_job_names_set)
    def test_output_contains_both_command_and_guidance(
        self, cmd: str, job_names: set[str]
    ) -> None:
        """stderr output contains BOTH the command name AND func guidance.

        **Validates: Requirements 5.1, 5.4, 5.6**
        """
        clean_job_names = job_names - {cmd}

        captured = StringIO()
        old_stderr = sys.stderr
        try:
            sys.stderr = captured
            _handle_unknown([cmd], clean_job_names)
        finally:
            sys.stderr = old_stderr

        output = captured.getvalue()

        assert cmd in output and "func" in output, (
            f"Expected both '{cmd}' and 'func' in output, got: {output!r}"
        )


# =============================================================================
# Property 7: Suggestion Boundedness
# =============================================================================


@pytest.mark.slow
class TestSuggestionBoundedness:
    """Property 7: Suggestion Boundedness.

    For any unknown command and any job_names set (regardless of size), the
    fuzzy suggestion algorithm SHALL return at most 5 suggestions, and every
    suggestion SHALL be a member of the job_names set.

    **Validates: Requirement 5.2**
    """

    @given(cmd=_cmd_name, job_names=_nonempty_job_names_set)
    def test_suggestions_at_most_five(self, cmd: str, job_names: set[str]) -> None:
        """_fuzzy_suggest returns at most 5 suggestions.

        **Validates: Requirement 5.2**
        """
        suggestions = _fuzzy_suggest(cmd, job_names)

        assert len(suggestions) <= 5, (
            f"Expected at most 5 suggestions for cmd='{cmd}', "
            f"got {len(suggestions)}: {suggestions}"
        )

    @given(cmd=_cmd_name, job_names=_nonempty_job_names_set)
    def test_all_suggestions_are_members_of_job_names(
        self, cmd: str, job_names: set[str]
    ) -> None:
        """Every suggestion returned is a member of the job_names set.

        **Validates: Requirement 5.2**
        """
        suggestions = _fuzzy_suggest(cmd, job_names)

        for suggestion in suggestions:
            assert suggestion in job_names, (
                f"Suggestion '{suggestion}' is not in job_names {job_names}"
            )

    @given(cmd=_cmd_name, job_names=_nonempty_job_names_set)
    def test_suggestions_bounded_with_large_job_set(
        self, cmd: str, job_names: set[str]
    ) -> None:
        """Even with many job names, suggestions stay bounded at max_results.

        **Validates: Requirement 5.2**
        """
        # Use a custom max_results to test the bound is respected
        max_results = 3
        suggestions = _fuzzy_suggest(cmd, job_names, max_results=max_results)

        assert len(suggestions) <= max_results, (
            f"Expected at most {max_results} suggestions, got {len(suggestions)}"
        )
        for suggestion in suggestions:
            assert suggestion in job_names

    @given(cmd=_cmd_name)
    def test_empty_job_names_returns_empty_suggestions(self, cmd: str) -> None:
        """With empty job_names set, suggestions are always empty.

        **Validates: Requirement 5.2**
        """
        suggestions = _fuzzy_suggest(cmd, set())

        assert suggestions == [], (
            f"Expected empty suggestions for empty job_names, got {suggestions}"
        )


# =============================================================================
# Property 8: Fuzzy Match Completeness
# =============================================================================


@pytest.mark.slow
class TestFuzzyMatchCompleteness:
    """Property 8: Fuzzy Match Completeness.

    For any job name in job_names that has Levenshtein distance ≤ 2 from
    the unknown command, the fuzzy suggestion algorithm SHALL include that
    job name in its candidate set (before the top-5 cutoff).

    **Validates: Requirement 5.3**
    """

    @given(job_name=_cmd_name, job_names=_nonempty_job_names_set)
    def test_levenshtein_within_2_appears_in_candidates(
        self, job_name: str, job_names: set[str]
    ) -> None:
        """Any job within Levenshtein ≤ 2 of cmd appears in candidates (before top-5 cut).

        **Validates: Requirement 5.3**
        """
        # Ensure job_name is in job_names
        augmented_job_names = job_names | {job_name}

        # Generate a command that is within Levenshtein distance 2 of job_name
        # by making a single-character substitution (distance = 1)
        if len(job_name) >= 2:
            # Swap a character to create a typo (distance 1)
            cmd_chars = list(job_name)
            # Change first character to something different
            original_char = cmd_chars[0]
            for c in "zyxwvutsrqponmlkjihgfedcba":
                if c != original_char:
                    cmd_chars[0] = c
                    break
            cmd = "".join(cmd_chars)
        else:
            # Single char: add a char (distance 1)
            cmd = job_name + "x"

        # Verify our generated cmd is within distance 2
        dist = _levenshtein(cmd, job_name)
        if dist > 2:
            # Skip if our mutation exceeded distance 2 (shouldn't happen with single sub)
            return

        # Use a large max_results to avoid the top-5 cutoff masking the result
        suggestions = _fuzzy_suggest(cmd, augmented_job_names, max_results=100)

        assert job_name in suggestions, (
            f"Job '{job_name}' has Levenshtein distance {dist} from cmd '{cmd}' "
            f"but was not in suggestions: {suggestions}"
        )

    @given(
        base=st.text(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz"), min_size=3, max_size=10
        ),
        job_names=_nonempty_job_names_set,
    )
    def test_single_deletion_within_distance_2(
        self, base: str, job_names: set[str]
    ) -> None:
        """A job name formed by deleting 1 char from cmd (distance 1) is in candidates.

        **Validates: Requirement 5.3**
        """
        # cmd is the base, job_name is base with one character deleted (distance 1)
        job_name = base[1:]  # Delete first character

        dist = _levenshtein(base, job_name)
        if dist > 2:
            return

        augmented = job_names | {job_name}
        suggestions = _fuzzy_suggest(base, augmented, max_results=100)

        assert job_name in suggestions, (
            f"Job '{job_name}' has Levenshtein distance {dist} from '{base}' "
            f"but was not in suggestions: {suggestions}"
        )

    @given(
        base=st.text(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz"), min_size=3, max_size=10
        ),
        insert_char=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        job_names=_nonempty_job_names_set,
    )
    def test_single_insertion_within_distance_2(
        self, base: str, insert_char: str, job_names: set[str]
    ) -> None:
        """A job name formed by inserting 1 char into cmd (distance 1) is in candidates.

        **Validates: Requirement 5.3**
        """
        # job_name is base with one character inserted at position 1 (distance 1)
        job_name = base[0] + insert_char + base[1:]

        dist = _levenshtein(base, job_name)
        if dist > 2:
            return

        augmented = job_names | {job_name}
        suggestions = _fuzzy_suggest(base, augmented, max_results=100)

        assert job_name in suggestions, (
            f"Job '{job_name}' has Levenshtein distance {dist} from '{base}' "
            f"but was not in suggestions: {suggestions}"
        )

    @given(
        base=st.text(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz"), min_size=4, max_size=10
        ),
        job_names=_nonempty_job_names_set,
    )
    def test_two_substitutions_within_distance_2(
        self, base: str, job_names: set[str]
    ) -> None:
        """A job name with 2 substitutions from cmd (distance 2) is in candidates.

        **Validates: Requirement 5.3**
        """
        # Create a job_name by substituting 2 characters
        chars = list(base)
        for c in "zyxw":
            if c != chars[0]:
                chars[0] = c
                break
        for c in "zyxw":
            if c != chars[-1]:
                chars[-1] = c
                break
        job_name = "".join(chars)

        dist = _levenshtein(base, job_name)
        if dist > 2:
            return

        augmented = job_names | {job_name}
        suggestions = _fuzzy_suggest(base, augmented, max_results=100)

        assert job_name in suggestions, (
            f"Job '{job_name}' has Levenshtein distance {dist} from '{base}' "
            f"but was not in suggestions: {suggestions}"
        )
