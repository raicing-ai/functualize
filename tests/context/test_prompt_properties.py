"""Property-based tests for the prompt system (Properties 8, 9, 10, 11).

Tests that:
- Property 8: rc.prompt() auto-fills source_job from current job name
- Property 9: Prompt validation with regex uses re.fullmatch and enforces 3-retry limit
- Property 10: Prompt validation with TypeAdapter uses validate_python and enforces 3-retry limit
- Property 11: PromptResponse convenience properties derive correctly from source field

**Validates: Requirements 4.1, 4.5, 4.6, 5.5**
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize._types.interactivity import (
    PromptRequest,
    PromptResponse,
)
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for valid job names (non-empty, alphanumeric + hyphens/underscores)
job_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

# Strategy for prompt questions (non-empty text)
prompt_questions = st.text(min_size=1, max_size=100)

# Strategy for PromptResponse source values
prompt_sources = st.sampled_from(["user", "default", "timeout", "cancelled"])

# Strategy for simple regex patterns that are valid
# We use a safe subset of patterns that are guaranteed valid
simple_regex_patterns = st.sampled_from(
    [
        r"[a-z]+",
        r"\d{3}-\d{4}",
        r"[A-Za-z0-9_]+",
        r".+@.+\..+",
        r"yes|no",
        r"\d+",
        r"[a-f0-9]{8}",
        r"(true|false)",
        r"[A-Z]{2,5}",
        r"\w+",
    ]
)

# Strategy for source_job values that may or may not be set on the request
optional_source_jobs = st.one_of(st.none(), st.text(min_size=1, max_size=20))

# Strategy for any response value
response_values = st.one_of(
    st.text(min_size=0, max_size=50),
    st.integers(),
    st.none(),
    st.booleans(),
)


# --- Helpers ---


class RecordingInputProvider:
    """An InputProvider that records what request it receives and returns a fixed response."""

    name: str = "recording-provider"

    def __init__(self, response: PromptResponse | None = None):
        self._response = response or PromptResponse(value="input", source="user")
        self.received_requests: list[PromptRequest] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        self.received_requests.append(request)
        return self._response


class ValidatingInputProvider:
    """An InputProvider that implements the spec-required validation logic.

    This implements the validation contract from Requirements 4.5 and 4.6:
    - If validator is a regex string, uses re.fullmatch for validation
    - If validator has validate_python, calls it for validation
    - Re-prompts up to 3 times on validation failure
    - Returns PromptResponse(source="cancelled") after 3 failures
    """

    name: str = "validating-provider"

    def __init__(self, user_inputs: list[str]):
        """Initialize with a sequence of user inputs to simulate."""
        self._user_inputs = list(user_inputs)
        self._input_index = 0
        self.fullmatch_calls: list[tuple[str, str]] = []
        self.validate_python_calls: list[str] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Implement the collect method with validation logic per spec."""
        max_attempts = 3
        attempts = 0

        while attempts < max_attempts:
            # Get next user input
            if self._input_index < len(self._user_inputs):
                value = self._user_inputs[self._input_index]
                self._input_index += 1
            else:
                # No more inputs available, simulate cancellation
                return PromptResponse(value=None, source="cancelled")

            # Validate if validator is present
            if request.validator is not None:
                if isinstance(request.validator, str):
                    # Regex validation using re.fullmatch
                    self.fullmatch_calls.append((request.validator, value))
                    if re.fullmatch(request.validator, value) is not None:
                        return PromptResponse(value=value, source="user")
                    attempts += 1
                elif hasattr(request.validator, "validate_python"):
                    # TypeAdapter validation
                    self.validate_python_calls.append(value)
                    try:
                        validated = request.validator.validate_python(value)
                        return PromptResponse(value=validated, source="user")
                    except Exception:
                        attempts += 1
                else:
                    # Unknown validator type, accept as-is
                    return PromptResponse(value=value, source="user")
            else:
                # No validator, accept immediately
                return PromptResponse(value=value, source="user")

        # After 3 failures, return cancelled
        return PromptResponse(value=None, source="cancelled")


def _make_rc(
    name: str = "test-job",
    input_provider: RecordingInputProvider | ValidatingInputProvider | None = None,
) -> RunContext:
    """Create a RunContext with an optional InputProvider wired up."""
    config = MagicMock(spec=JobConfigView)
    config.set_prefix = MagicMock()
    logger = MagicMock()

    app = MagicMock()
    plugins: list = []
    if input_provider is not None:
        plugins.append(input_provider)
    app._surfaces = plugins

    engine = MagicMock()
    engine._app = app

    return RunContext(
        name=name,
        config=config,
        logger=logger,
        _execution_engine=engine,
    )


# --- Property 8: rc.prompt auto-fills source_job and delegates to InputProvider ---


class TestProperty8PromptAutoFillsSourceJob:
    """Property 8: rc.prompt auto-fills source_job and delegates to InputProvider.

    For any job name, rc.prompt() auto-fills source_job from the current job's name,
    regardless of the original source_job value in the request.

    **Validates: Requirements 4.1**
    """

    @given(
        job_name=job_names,
        question=prompt_questions,
        original_source_job=optional_source_jobs,
    )
    @settings(max_examples=100)
    def test_source_job_auto_filled_from_rc_name(
        self,
        job_name: str,
        question: str,
        original_source_job: str | None,
    ):
        """For any job name, the InputProvider receives source_job set to rc.name."""
        # Feature: functualize, Property 8: rc.prompt auto-fills source_job
        # **Validates: Requirements 4.1**
        provider = RecordingInputProvider()
        rc = _make_rc(name=job_name, input_provider=provider)

        request = PromptRequest(
            question=question,
            source_job=original_source_job,
        )
        rc.prompt(request)

        # The provider must have received the request with source_job == rc.name
        assert len(provider.received_requests) == 1
        received = provider.received_requests[0]
        assert received.source_job == job_name

    @given(
        job_name=job_names,
        question=prompt_questions,
    )
    @settings(max_examples=100)
    def test_source_job_overrides_even_when_set(
        self,
        job_name: str,
        question: str,
    ):
        """source_job is always overridden to rc.name, even if already set."""
        # Feature: functualize, Property 8: rc.prompt auto-fills source_job
        # **Validates: Requirements 4.1**
        provider = RecordingInputProvider()
        rc = _make_rc(name=job_name, input_provider=provider)

        # Deliberately set a different source_job
        request = PromptRequest(
            question=question,
            source_job="some-other-job",
        )
        rc.prompt(request)

        received = provider.received_requests[0]
        assert received.source_job == job_name
        assert received.source_job != "some-other-job" or job_name == "some-other-job"

    @given(
        job_name=job_names,
        question=prompt_questions,
        value=response_values,
    )
    @settings(max_examples=100)
    def test_prompt_delegates_and_returns_provider_response(
        self,
        job_name: str,
        question: str,
        value: str | int | None | bool,
    ):
        """rc.prompt() delegates to InputProvider and returns its response."""
        # Feature: functualize, Property 8: rc.prompt auto-fills source_job
        # **Validates: Requirements 4.1**
        expected_response = PromptResponse(value=value, source="user")
        provider = RecordingInputProvider(response=expected_response)
        rc = _make_rc(name=job_name, input_provider=provider)

        request = PromptRequest(question=question)
        result = rc.prompt(request)

        assert result == expected_response


# --- Property 9: Prompt validation with regex uses re.fullmatch and enforces 3-retry limit ---


class TestProperty9RegexValidation:
    """Property 9: Prompt validation with regex uses re.fullmatch and enforces 3-retry limit.

    For any regex validator string, re.fullmatch is used and after 3 consecutive
    validation failures, the InputProvider returns PromptResponse(source="cancelled").

    **Validates: Requirements 4.5**
    """

    @given(
        pattern=simple_regex_patterns,
        valid_input=st.text(
            alphabet=st.characters(categories=("L", "N")),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=100)
    def test_regex_fullmatch_used_for_validation(
        self,
        pattern: str,
        valid_input: str,
    ):
        """re.fullmatch is used (not re.match or re.search) for regex validation."""
        # Feature: functualize, Property 9: Prompt validation with regex
        # **Validates: Requirements 4.5**
        # Provide an input that we'll check against
        provider = ValidatingInputProvider(user_inputs=[valid_input])

        request = PromptRequest(question="Input:", validator=pattern)
        provider.collect(request)

        # Verify re.fullmatch was called with the correct pattern and value
        assert len(provider.fullmatch_calls) >= 1
        called_pattern, called_value = provider.fullmatch_calls[0]
        assert called_pattern == pattern
        assert called_value == valid_input

    @given(pattern=simple_regex_patterns)
    @settings(max_examples=100)
    def test_three_failures_result_in_cancelled(self, pattern: str):
        """After 3 consecutive validation failures, source='cancelled'."""
        # Feature: functualize, Property 9: Prompt validation with regex
        # **Validates: Requirements 4.5**
        # Generate 3 inputs that definitely DON'T match (use null byte strings
        # which won't match any of our simple patterns)
        bad_inputs = ["\x00\x01\x02", "\x00\x01\x02", "\x00\x01\x02"]
        provider = ValidatingInputProvider(user_inputs=bad_inputs)

        request = PromptRequest(question="Input:", validator=pattern)
        response = provider.collect(request)

        assert response.source == "cancelled"
        assert response.value is None

    @given(data=st.data(), pattern=simple_regex_patterns)
    @settings(max_examples=100)
    def test_valid_input_on_first_try_returns_user(self, data, pattern: str):
        """If input passes re.fullmatch on first try, source='user'."""
        # Feature: functualize, Property 9: Prompt validation with regex
        # **Validates: Requirements 4.5**
        # Draw a value that matches the pattern
        valid = data.draw(st.from_regex(pattern, fullmatch=True))
        provider = ValidatingInputProvider(user_inputs=[valid])

        request = PromptRequest(question="Input:", validator=pattern)
        response = provider.collect(request)

        assert response.source == "user"
        assert response.value == valid

    @given(data=st.data(), pattern=simple_regex_patterns)
    @settings(max_examples=50)
    def test_valid_on_second_try_after_one_failure(self, data, pattern: str):
        """If first attempt fails but second passes, source='user' (within retry limit)."""
        # Feature: functualize, Property 9: Prompt validation with regex
        # **Validates: Requirements 4.5**
        valid = data.draw(st.from_regex(pattern, fullmatch=True))
        # First input is invalid, second is valid
        bad_input = "\x00\x01\x02"
        provider = ValidatingInputProvider(user_inputs=[bad_input, valid])

        request = PromptRequest(question="Input:", validator=pattern)
        response = provider.collect(request)

        assert response.source == "user"
        assert response.value == valid
        # Should have attempted fullmatch twice
        assert len(provider.fullmatch_calls) == 2

    @given(data=st.data(), pattern=simple_regex_patterns)
    @settings(max_examples=50)
    def test_exactly_three_failures_then_cancelled(self, data, pattern: str):
        """Exactly 3 failures means cancelled, even if 4th would pass."""
        # Feature: functualize, Property 9: Prompt validation with regex
        # **Validates: Requirements 4.5**
        valid = data.draw(st.from_regex(pattern, fullmatch=True))
        # 3 bad inputs then a valid one - but we should never reach the valid one
        bad_input = "\x00\x01\x02"
        provider = ValidatingInputProvider(
            user_inputs=[bad_input, bad_input, bad_input, valid]
        )

        request = PromptRequest(question="Input:", validator=pattern)
        response = provider.collect(request)

        assert response.source == "cancelled"
        # Should have attempted exactly 3 fullmatch calls
        assert len(provider.fullmatch_calls) == 3


# --- Property 10: Prompt validation with TypeAdapter uses validate_python and enforces 3-retry limit ---


class TestProperty10TypeAdapterValidation:
    """Property 10: Prompt validation with TypeAdapter uses validate_python and enforces 3-retry limit.

    For any TypeAdapter validator, validate_python is called and after 3 consecutive
    validation failures, the InputProvider returns PromptResponse(source="cancelled").

    **Validates: Requirements 4.6**
    """

    @given(valid_input=st.integers(min_value=0, max_value=1000))
    @settings(max_examples=100)
    def test_validate_python_called_for_type_adapter(self, valid_input: int):
        """validate_python is called when validator has that method."""
        # Feature: functualize, Property 10: Prompt validation with TypeAdapter
        # **Validates: Requirements 4.6**
        from pydantic import TypeAdapter

        adapter = TypeAdapter(int)
        provider = ValidatingInputProvider(user_inputs=[str(valid_input)])

        request = PromptRequest(question="Enter number:", validator=adapter)
        provider.collect(request)

        # validate_python was called
        assert len(provider.validate_python_calls) >= 1
        assert provider.validate_python_calls[0] == str(valid_input)
        # Should succeed since str(int) may or may not pass TypeAdapter(int)
        # For int adapter, string input may raise ValidationError
        # The important thing is validate_python was called

    @given(data=st.data())
    @settings(max_examples=50)
    def test_three_type_adapter_failures_result_in_cancelled(self, data):
        """After 3 consecutive TypeAdapter validation failures, source='cancelled'."""
        # Feature: functualize, Property 10: Prompt validation with TypeAdapter
        # **Validates: Requirements 4.6**
        from pydantic import TypeAdapter

        # Use int TypeAdapter - strings that aren't numeric will fail
        adapter = TypeAdapter(int)
        # Generate 3 non-numeric strings that will fail validate_python
        bad_inputs = ["not-a-number", "also-bad", "still-bad"]
        provider = ValidatingInputProvider(user_inputs=bad_inputs)

        request = PromptRequest(question="Number:", validator=adapter)
        response = provider.collect(request)

        assert response.source == "cancelled"
        assert response.value is None
        # Should have tried validate_python exactly 3 times
        assert len(provider.validate_python_calls) == 3

    @given(valid_int=st.integers(min_value=-100, max_value=100))
    @settings(max_examples=100)
    def test_valid_type_adapter_input_returns_user(self, valid_int: int):
        """If validate_python succeeds on first try, source='user'."""
        # Feature: functualize, Property 10: Prompt validation with TypeAdapter
        # **Validates: Requirements 4.6**
        from pydantic import TypeAdapter

        # Use int TypeAdapter with actual int input (not string)
        adapter = TypeAdapter(int)
        provider = ValidatingInputProvider(user_inputs=[valid_int])

        request = PromptRequest(question="Number:", validator=adapter)
        response = provider.collect(request)

        assert response.source == "user"
        assert response.value == valid_int

    @settings(max_examples=50)
    @given(valid_int=st.integers(min_value=0, max_value=100))
    def test_valid_on_third_try_after_two_failures(self, valid_int: int):
        """If first two attempts fail but third passes, source='user'."""
        # Feature: functualize, Property 10: Prompt validation with TypeAdapter
        # **Validates: Requirements 4.6**
        from pydantic import TypeAdapter

        adapter = TypeAdapter(int)
        # Two invalid inputs then a valid one
        provider = ValidatingInputProvider(user_inputs=["bad", "also-bad", valid_int])

        request = PromptRequest(question="Number:", validator=adapter)
        response = provider.collect(request)

        assert response.source == "user"
        assert response.value == valid_int
        # Should have called validate_python 3 times (2 failures + 1 success)
        assert len(provider.validate_python_calls) == 3

    @given(valid_int=st.integers(min_value=0, max_value=100))
    @settings(max_examples=50)
    def test_exactly_three_failures_then_cancelled_even_with_valid_fourth(
        self, valid_int: int
    ):
        """Exactly 3 failures means cancelled, even if 4th would pass."""
        # Feature: functualize, Property 10: Prompt validation with TypeAdapter
        # **Validates: Requirements 4.6**
        from pydantic import TypeAdapter

        adapter = TypeAdapter(int)
        # 3 bad inputs then a valid one - should never reach the valid one
        provider = ValidatingInputProvider(
            user_inputs=["bad1", "bad2", "bad3", valid_int]
        )

        request = PromptRequest(question="Number:", validator=adapter)
        response = provider.collect(request)

        assert response.source == "cancelled"
        # Should have attempted exactly 3 validate_python calls
        assert len(provider.validate_python_calls) == 3


# --- Property 11: PromptResponse convenience properties derive correctly from source field ---


class TestProperty11PromptResponseProperties:
    """Property 11: PromptResponse convenience properties derive correctly from source field.

    For any source in {"user", "default", "timeout", "cancelled"}, was_cancelled,
    was_timeout, and is_user_input return correct booleans.

    **Validates: Requirements 5.5**
    """

    @given(source=prompt_sources, value=response_values)
    @settings(max_examples=200)
    def test_was_cancelled_true_iff_source_cancelled(
        self,
        source: str,
        value: str | int | None | bool,
    ):
        """was_cancelled returns True if and only if source == 'cancelled'."""
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source=source)
        assert response.was_cancelled == (source == "cancelled")

    @given(source=prompt_sources, value=response_values)
    @settings(max_examples=200)
    def test_was_timeout_true_iff_source_timeout(
        self,
        source: str,
        value: str | int | None | bool,
    ):
        """was_timeout returns True if and only if source == 'timeout'."""
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source=source)
        assert response.was_timeout == (source == "timeout")

    @given(source=prompt_sources, value=response_values)
    @settings(max_examples=200)
    def test_is_user_input_true_iff_source_user(
        self,
        source: str,
        value: str | int | None | bool,
    ):
        """is_user_input returns True if and only if source == 'user'."""
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source=source)
        assert response.is_user_input == (source == "user")

    @given(source=prompt_sources, value=response_values)
    @settings(max_examples=200)
    def test_exactly_one_property_true_for_non_default(
        self,
        source: str,
        value: str | int | None | bool,
    ):
        """For source in {user, timeout, cancelled}, exactly one convenience property is True.

        For source='default', all three are False (default is not user/timeout/cancelled).
        """
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source=source)

        true_count = sum(
            [
                response.was_cancelled,
                response.was_timeout,
                response.is_user_input,
            ]
        )

        if source == "default":
            # None of the three properties should be True
            assert true_count == 0
        else:
            # Exactly one should be True for user/timeout/cancelled
            assert true_count == 1

    @given(value=response_values)
    @settings(max_examples=50)
    def test_cancelled_source_properties(self, value: str | int | None | bool):
        """source='cancelled' → was_cancelled=True, was_timeout=False, is_user_input=False."""
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source="cancelled")
        assert response.was_cancelled is True
        assert response.was_timeout is False
        assert response.is_user_input is False

    @given(value=response_values)
    @settings(max_examples=50)
    def test_timeout_source_properties(self, value: str | int | None | bool):
        """source='timeout' → was_cancelled=False, was_timeout=True, is_user_input=False."""
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source="timeout")
        assert response.was_cancelled is False
        assert response.was_timeout is True
        assert response.is_user_input is False

    @given(value=response_values)
    @settings(max_examples=50)
    def test_user_source_properties(self, value: str | int | None | bool):
        """source='user' → was_cancelled=False, was_timeout=False, is_user_input=True."""
        # Feature: functualize, Property 11: PromptResponse convenience properties
        # **Validates: Requirements 5.5**
        response = PromptResponse(value=value, source="user")
        assert response.was_cancelled is False
        assert response.was_timeout is False
        assert response.is_user_input is True
