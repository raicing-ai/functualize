"""Property-based tests for MockAI pattern matching and call recording.

Tests Property 18 from the Phase 2–5 Domain SDKs design document.

Property 18: MockAI pattern matching and call recording — For any responses dict
mapping glob patterns to values, and any prompt string, MockAI SHALL return the
value of the first matching pattern. If no pattern matches, it SHALL raise
ValueError. After N calls, call_count SHALL equal N, calls SHALL be a list of
length N, and last_prompt SHALL equal the prompt of the Nth call.

**Validates: Requirements 9.1, 9.4, 9.5, 9.6, 9.7**
"""

from __future__ import annotations

from fnmatch import fnmatch

import pytest
from functualize_ai.testing import MockAI
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ===========================================================================
# Strategies
# ===========================================================================

# Simple glob patterns that can match various prompts
# Use patterns with wildcards that are useful for matching
simple_patterns = st.sampled_from(
    [
        "*",
        "*hello*",
        "*world*",
        "*test*",
        "*foo*",
        "*bar*",
        "hello*",
        "*goodbye",
        "?test*",
        "*ask*question*",
    ]
)

# Prompt strings that may or may not match patterns
prompt_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"), whitelist_characters=" "
    ),
    min_size=1,
    max_size=100,
)

# Response values — either strings or simple objects
response_values_st = st.one_of(
    st.text(min_size=1, max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000, max_value=1000),
    st.booleans(),
)


@st.composite
def pattern_response_dicts(draw: st.DrawFn) -> dict[str, object]:
    """Generate a non-empty responses dict with glob patterns mapped to values."""
    num_patterns = draw(st.integers(min_value=1, max_value=5))
    patterns = draw(
        st.lists(
            simple_patterns, min_size=num_patterns, max_size=num_patterns, unique=True
        )
    )
    responses: dict[str, object] = {}
    for pattern in patterns:
        value = draw(response_values_st)
        responses[pattern] = value
    return responses


@st.composite
def matching_prompt_and_responses(
    draw: st.DrawFn,
) -> tuple[dict[str, object], str, object]:
    """Generate a responses dict and a prompt that is guaranteed to match at least one pattern.

    Returns (responses_dict, prompt, expected_response) where expected_response
    is the value of the FIRST matching pattern.
    """
    responses = draw(pattern_response_dicts())

    # Pick one pattern to guarantee a match against
    target_pattern = draw(st.sampled_from(list(responses.keys())))

    # Generate a prompt that matches the target pattern
    if target_pattern == "*":
        prompt = draw(prompt_st)
    elif target_pattern.startswith("*") and target_pattern.endswith("*"):
        # Pattern like *hello* — embed the middle part in a prompt
        middle = target_pattern.strip("*")
        prefix = draw(st.text(alphabet="abcdef ", min_size=0, max_size=10))
        suffix = draw(st.text(alphabet="abcdef ", min_size=0, max_size=10))
        prompt = prefix + middle + suffix
    elif target_pattern.startswith("*"):
        # Pattern like *goodbye — end with the suffix
        suffix = target_pattern.lstrip("*")
        prefix = draw(st.text(alphabet="abcdef ", min_size=0, max_size=10))
        prompt = prefix + suffix
    elif target_pattern.endswith("*"):
        # Pattern like hello* — start with the prefix
        prefix = target_pattern.rstrip("*")
        suffix = draw(st.text(alphabet="abcdef ", min_size=0, max_size=10))
        prompt = prefix + suffix
    elif "?" in target_pattern:
        # Pattern like ?test* — replace ? with a single char
        parts = target_pattern.split("?")
        prompt = "x".join(parts)
        # Handle trailing wildcards
        if prompt.endswith("*"):
            prompt = prompt.rstrip("*") + draw(
                st.text(alphabet="abc", min_size=0, max_size=5)
            )
    else:
        # Exact match
        prompt = target_pattern

    # Determine the actual expected response (first matching pattern wins)
    expected = None
    for pattern, value in responses.items():
        if fnmatch(prompt, pattern):
            expected = value
            break

    assume(expected is not None)
    return responses, prompt, expected


@st.composite
def non_matching_prompt_and_responses(
    draw: st.DrawFn,
) -> tuple[dict[str, object], str]:
    """Generate a responses dict and a prompt that does NOT match any pattern.

    We achieve this by using patterns that require specific substrings
    and generating prompts that don't contain those substrings.
    """
    # Use very specific patterns that are unlikely to match random text
    specific_patterns = [
        "*xyzzy*",
        "*plugh*",
        "*qwerty12345*",
        "*zxcvbnm*",
    ]
    num_patterns = draw(st.integers(min_value=1, max_value=3))
    patterns = draw(
        st.lists(
            st.sampled_from(specific_patterns),
            min_size=num_patterns,
            max_size=num_patterns,
            unique=True,
        )
    )

    responses: dict[str, object] = {}
    for pattern in patterns:
        value = draw(response_values_st)
        responses[pattern] = value

    # Generate a prompt that avoids all the specific substrings
    prompt = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L",), whitelist_characters=" "
            ),
            min_size=1,
            max_size=30,
        )
    )

    # Ensure it doesn't accidentally match any pattern
    assume(not any(fnmatch(prompt, p) for p in responses))

    return responses, prompt


# ===========================================================================
# Property 18: MockAI pattern matching and call recording
# ===========================================================================


class TestMockAIPatternMatchingProperty:
    """Property 18: MockAI pattern matching and call recording.

    For any responses dict mapping glob patterns to values, and any prompt string,
    MockAI SHALL return the value of the first matching pattern. If no pattern matches,
    it SHALL raise ValueError. After N calls, call_count SHALL equal N, calls SHALL be
    a list of length N, and last_prompt SHALL equal the prompt of the Nth call.

    **Validates: Requirements 9.1, 9.4, 9.5, 9.6, 9.7**
    """

    @given(data=matching_prompt_and_responses())
    @settings(max_examples=100)
    def test_matching_prompt_returns_first_match(
        self, data: tuple[dict[str, object], str, object]
    ) -> None:
        """MockAI.complete(prompt) returns the value of the first matching pattern.

        **Validates: Requirements 9.1**
        """
        responses, prompt, expected = data
        mock = MockAI(responses=responses)
        result = mock.complete(prompt)
        assert result == expected

    @given(data=non_matching_prompt_and_responses())
    @settings(max_examples=100)
    def test_non_matching_prompt_raises_value_error(
        self, data: tuple[dict[str, object], str]
    ) -> None:
        """MockAI raises ValueError when no pattern matches the prompt.

        **Validates: Requirements 9.4**
        """
        responses, prompt = data
        mock = MockAI(responses=responses)
        with pytest.raises(ValueError):
            mock.complete(prompt)

    @given(
        num_calls=st.integers(min_value=1, max_value=20),
        prompts=st.lists(prompt_st, min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_call_count_increments_by_one_per_call(
        self, num_calls: int, prompts: list[str]
    ) -> None:
        """call_count increments by 1 per call, equaling total calls made.

        **Validates: Requirements 9.5**
        """
        # Use a catch-all pattern so all prompts match
        mock = MockAI(responses={"*": "ok"})
        actual_calls = min(num_calls, len(prompts))

        for i in range(actual_calls):
            assert mock.call_count == i
            mock.complete(prompts[i])

        assert mock.call_count == actual_calls

    @given(prompts=st.lists(prompt_st, min_size=1, max_size=20))
    @settings(max_examples=100)
    def test_calls_list_grows_by_one_per_call(self, prompts: list[str]) -> None:
        """calls list grows by 1 per call with correct prompt/response_model/response.

        **Validates: Requirements 9.6**
        """
        mock = MockAI(responses={"*": "response_value"})

        for i, prompt in enumerate(prompts):
            mock.complete(prompt)
            assert len(mock.calls) == i + 1
            assert mock.calls[i].prompt == prompt
            assert mock.calls[i].response_model is None
            assert mock.calls[i].response == "response_value"

    @given(prompts=st.lists(prompt_st, min_size=1, max_size=20))
    @settings(max_examples=100)
    def test_last_prompt_is_most_recent(self, prompts: list[str]) -> None:
        """last_prompt is always the most recent prompt.

        **Validates: Requirements 9.7**
        """
        mock = MockAI(responses={"*": "ok"})

        for prompt in prompts:
            mock.complete(prompt)
            assert mock.last_prompt == prompt

    @given(data=matching_prompt_and_responses())
    @settings(max_examples=100)
    def test_calls_record_contains_correct_response(
        self, data: tuple[dict[str, object], str, object]
    ) -> None:
        """Each call record contains the correct prompt, response_model, and response.

        **Validates: Requirements 9.6**
        """
        responses, prompt, expected = data
        mock = MockAI(responses=responses)
        result = mock.complete(prompt)

        assert len(mock.calls) == 1
        assert mock.calls[0].prompt == prompt
        assert mock.calls[0].response == result
        assert mock.calls[0].response == expected

    @given(
        prompts=st.lists(prompt_st, min_size=2, max_size=10),
    )
    @settings(max_examples=100)
    def test_multiple_calls_all_recorded_in_order(self, prompts: list[str]) -> None:
        """After N calls, calls list has exactly N entries in call order.

        **Validates: Requirements 9.5, 9.6**
        """
        mock = MockAI(responses={"*": "value"})

        for prompt in prompts:
            mock.complete(prompt)

        # call_count == N
        assert mock.call_count == len(prompts)
        # calls list has exactly N items
        assert len(mock.calls) == len(prompts)
        # Each entry matches the call order
        for i, prompt in enumerate(prompts):
            assert mock.calls[i].prompt == prompt

    @given(data=matching_prompt_and_responses())
    @settings(max_examples=100)
    def test_first_pattern_wins_on_multiple_matches(
        self, data: tuple[dict[str, object], str, object]
    ) -> None:
        """When multiple patterns match, the first one in dict order wins.

        **Validates: Requirements 9.1**
        """
        responses, prompt, expected = data
        mock = MockAI(responses=responses)
        result = mock.complete(prompt)

        # Verify the result matches what fnmatch would give for the first pattern
        for pattern, value in responses.items():
            if fnmatch(prompt, pattern):
                assert result == value
                break
