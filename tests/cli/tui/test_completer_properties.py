# Feature: tui-v3-integration, Property 13: SwappableCompleter candidates are always a subset of available choices
"""Property-based tests for SwappableCompleter.

Tests SwappableCompleter from functualize._cli.completions.engine:
- Property 13: SwappableCompleter candidates are always a subset of available choices

**Validates: Requirements 9.2, 9.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.completions.engine import SwappableCompleter

# =============================================================================
# Strategies
# =============================================================================

# Choice strings: mixed-case alphanumeric with underscores, reasonable length
_choice_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=30,
)

# Input text: any string the user might type (including empty)
_input_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "P", "Z"),
        blacklist_characters="\x00\n\r",
    ),
    min_size=0,
    max_size=30,
)

# Choices list: list of choice strings (can be empty)
_choices_list = st.lists(_choice_text, min_size=0, max_size=80)


# =============================================================================
# Property 13: SwappableCompleter candidates are always a subset of available choices
# =============================================================================


@pytest.mark.slow
class TestSwappableCompleterCandidatesSubset:
    """Property 13: SwappableCompleter candidates are always a subset of available choices.

    For any choices list and input text:
    1. Every returned candidate's .main field exists in the original choices list
    2. Every returned candidate matches the input text prefix (case-insensitive)
    3. The result count never exceeds 50
    4. If no choice matches the prefix, the result is empty
    5. When choices is None or empty, result is always empty regardless of input text

    **Validates: Requirements 9.2, 9.5**
    """

    @given(choices=_choices_list, text=_input_text)
    def test_candidates_main_field_in_original_choices(
        self, choices: list[str], text: str
    ) -> None:
        """Every returned candidate's .main exists in the original choices list."""
        completer = SwappableCompleter()
        completer.set_edit_mode("test_field", choices=choices)

        items = completer.get_items(text)

        for item in items:
            assert item.main in choices, (
                f"Candidate '{item.main}' not found in choices: {choices}"
            )

    @given(choices=_choices_list, text=_input_text)
    def test_candidates_match_input_prefix_case_insensitive(
        self, choices: list[str], text: str
    ) -> None:
        """Every returned candidate matches the input text prefix (case-insensitive)."""
        completer = SwappableCompleter()
        completer.set_edit_mode("test_field", choices=choices)

        items = completer.get_items(text)

        prefix_lower = text.lower()
        for item in items:
            if prefix_lower:  # Empty prefix matches everything
                assert item.main.lower().startswith(prefix_lower), (
                    f"Candidate '{item.main}' does not start with prefix '{text}' "
                    f"(case-insensitive)"
                )

    @given(choices=_choices_list, text=_input_text)
    def test_result_count_never_exceeds_50(self, choices: list[str], text: str) -> None:
        """The result count never exceeds 50."""
        completer = SwappableCompleter()
        completer.set_edit_mode("test_field", choices=choices)

        items = completer.get_items(text)

        assert len(items) <= 50, f"Got {len(items)} candidates, expected at most 50"

    @given(choices=_choices_list, text=_input_text)
    def test_no_match_returns_empty(self, choices: list[str], text: str) -> None:
        """If no choice matches the prefix, the result is empty."""
        completer = SwappableCompleter()
        completer.set_edit_mode("test_field", choices=choices)

        items = completer.get_items(text)

        # Compute expected matches manually
        prefix_lower = text.lower()
        expected_matches = (
            [c for c in choices if c.lower().startswith(prefix_lower)]
            if prefix_lower
            else choices
        )

        if not expected_matches:
            assert items == [], (
                f"Expected empty result when no choices match prefix '{text}', "
                f"got {items}"
            )

    @given(text=_input_text)
    def test_none_choices_always_returns_empty(self, text: str) -> None:
        """When choices is None, result is always empty regardless of input text."""
        completer = SwappableCompleter()
        completer.set_edit_mode("test_field", choices=None)

        items = completer.get_items(text)

        assert items == [], (
            f"Expected empty result with choices=None, got {items} for text='{text}'"
        )

    @given(text=_input_text)
    def test_empty_choices_always_returns_empty(self, text: str) -> None:
        """When choices is empty list, result is always empty regardless of input text."""
        completer = SwappableCompleter()
        completer.set_edit_mode("test_field", choices=[])

        items = completer.get_items(text)

        assert items == [], (
            f"Expected empty result with choices=[], got {items} for text='{text}'"
        )
