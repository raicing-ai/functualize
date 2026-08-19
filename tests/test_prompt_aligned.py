"""Property-based tests for Prompt alignment (Properties 12–15).

Tests that:
- Property 12: Prompt.choice returns string for any valid choices (via InputProvider)
- Property 13: Prompt.choice raises InputNotAvailable when no provider registered
- Property 14: Prompt.text raises InputNotAvailable when no provider registered
- Property 15: Prompt.confirm raises InputNotAvailable when no provider registered

**Validates: Requirements 5.1, 5.2, 5.4, 5.6, 6.7, 6.8**

Note: the Prompt capability delegates to a PromptCollector and raises
InputNotAvailable when none is available.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._engine.capabilities.prompt import Prompt
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptChoice,
    PromptRequest,
    PromptResponse,
)

# --- Strategies ---

# Strategy for generating valid PromptChoice objects
prompt_choice_objects = st.builds(
    PromptChoice,
    value=st.text(min_size=1, max_size=30),
    label=st.text(min_size=1, max_size=50),
    description=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
)

# Strategy for plain string choices
plain_string_choices = st.text(min_size=1, max_size=50)

# Strategy for mixed choice items (str or PromptChoice)
mixed_choice_item = st.one_of(plain_string_choices, prompt_choice_objects)

# Strategy for valid choice lists (1–50 items)
valid_choice_lists = st.lists(mixed_choice_item, min_size=1, max_size=50)

# Strategy for questions
questions = st.text(min_size=1, max_size=100)


# --- Helper: FakeInputProvider ---


class FakeInputProvider:
    """A fake InputProvider that returns a fixed response."""

    def __init__(self, value: str = "selected") -> None:
        self._value = value

    def collect(self, request: PromptRequest) -> PromptResponse:
        return PromptResponse(value=self._value, source="user")


# --- Property 12: Prompt.choice returns string for any valid choices ---


class TestProperty12PromptChoiceReturnsString:
    """Property 12: Prompt.choice returns string for any valid choices.

    For any list of PromptChoice items, Prompt.choice() SHALL return a
    plain str value when an InputProvider is registered.

    **Validates: Requirements 5.1, 5.2, 5.4**
    """

    @given(
        question=questions,
        choices=st.lists(prompt_choice_objects, min_size=1, max_size=50),
    )
    def test_choice_return_type_is_str(
        self, question: str, choices: list[PromptChoice]
    ):
        """Prompt.choice always returns a str for any valid choices list.

        **Validates: Requirements 5.1, 5.2, 5.4**
        """
        prompt = Prompt(_provider=FakeInputProvider())
        result = prompt.choice(question, choices)
        assert isinstance(result, str)

    @given(
        question=questions,
        choices=st.lists(prompt_choice_objects, min_size=1, max_size=50),
    )
    def test_choice_accepts_prompt_choice_objects(
        self, question: str, choices: list[PromptChoice]
    ):
        """Prompt.choice accepts a list of PromptChoice objects without raising.

        **Validates: Requirements 5.1**
        """
        prompt = Prompt(_provider=FakeInputProvider())
        result = prompt.choice(question, choices)
        assert isinstance(result, str)


# --- Property 13: Prompt.choice raises InputNotAvailable when no provider ---


class TestProperty13PromptChoiceNoProvider:
    """Property 13: Prompt.choice raises InputNotAvailable when no provider.

    When no InputProvider is registered, Prompt.choice() SHALL raise
    InputNotAvailable.

    **Validates: Requirements 5.6**
    """

    @given(
        question=questions,
        choices=st.lists(prompt_choice_objects, min_size=1, max_size=50),
    )
    def test_no_provider_raises_input_not_available(
        self, question: str, choices: list[PromptChoice]
    ):
        """No provider raises InputNotAvailable for any choices.

        **Validates: Requirements 5.6**
        """
        prompt = Prompt()
        with pytest.raises(InputNotAvailable):
            prompt.choice(question, choices)

    @given(question=questions)
    def test_empty_choices_no_provider_raises_input_not_available(self, question: str):
        """No provider raises InputNotAvailable even with empty choices.

        **Validates: Requirements 5.6**
        """
        prompt = Prompt()
        with pytest.raises(InputNotAvailable):
            prompt.choice(question, [])


# --- Property 14: Prompt.text raises InputNotAvailable when no provider ---


class TestProperty14PromptTextNoProvider:
    """Property 14: Prompt.text raises InputNotAvailable when no provider.

    When no InputProvider is registered, Prompt.text() SHALL raise
    InputNotAvailable.

    **Validates: Requirements 6.7**
    """

    @given(question=questions, default=st.text(min_size=0, max_size=50))
    def test_no_provider_raises_input_not_available(self, question: str, default: str):
        """No provider raises InputNotAvailable regardless of default type.

        **Validates: Requirements 6.7**
        """
        prompt = Prompt()
        with pytest.raises(InputNotAvailable):
            prompt.text(question, default=default)

    @given(question=questions)
    def test_with_provider_returns_string(self, question: str):
        """With a provider, text() returns a string.

        **Validates: Requirements 6.7**
        """
        prompt = Prompt(_provider=FakeInputProvider(value="hello"))
        result = prompt.text(question)
        assert isinstance(result, str)


# --- Property 15: Prompt.confirm raises InputNotAvailable when no provider ---


class TestProperty15PromptConfirmNoProvider:
    """Property 15: Prompt.confirm raises InputNotAvailable when no provider.

    When no InputProvider is registered, Prompt.confirm() SHALL raise
    InputNotAvailable.

    **Validates: Requirements 6.8**
    """

    @given(question=questions, default=st.booleans())
    def test_no_provider_raises_input_not_available(self, question: str, default: bool):
        """No provider raises InputNotAvailable regardless of default.

        **Validates: Requirements 6.8**
        """
        prompt = Prompt()
        with pytest.raises(InputNotAvailable):
            prompt.confirm(question, default=default)

    @given(question=questions)
    def test_with_provider_returns_bool(self, question: str):
        """With a provider, confirm() returns a bool.

        **Validates: Requirements 6.8**
        """
        prompt = Prompt(_provider=FakeInputProvider(value="true"))
        result = prompt.confirm(question)
        assert isinstance(result, bool)
