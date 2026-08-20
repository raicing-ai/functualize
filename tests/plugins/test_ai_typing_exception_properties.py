"""Property-based tests for AI typing and exception wrapping.

Tests Properties 8 and 9 from the Phase 2–5 Domain SDKs design document.

Property 8: AI complete returns correctly typed output — For any valid Pydantic
model T and any provider response that conforms to T's schema, AI.complete(prompt,
response_model=T) SHALL return an instance of type T with field values matching
the provider response. When no response_model is given, AI.complete(prompt) SHALL
return a str.

Property 9: AI wraps provider exceptions — For any exception raised by an
AIProvider during complete() or run(), the AI capability SHALL raise AINotAvailableError
with the original error message preserved in the exception, and SHALL NOT expose
the provider-specific exception type.

**Validates: Requirements 5.2, 5.3, 5.13**
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from functualize_ai import AI, AINotAvailableError, AIResult, TokenUsage, ToolDef
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

if TYPE_CHECKING:
    from functualize_ai._types import AILimits

# ===========================================================================
# Strategies
# ===========================================================================

# Strategy for generating non-empty prompt strings
prompts_st = st.text(min_size=1, max_size=200)

# Strategy for generating string responses (raw text from provider)
raw_text_responses_st = st.text(min_size=0, max_size=500)

# Strategy for valid field values in structured models
field_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)
field_int_st = st.integers(min_value=-10000, max_value=10000)
field_float_st = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)
field_bool_st = st.booleans()

# Strategy for exception messages
error_messages_st = st.text(min_size=1, max_size=200)

# Strategy for exception types (diverse exception classes)
exception_types_st = st.sampled_from(
    [
        RuntimeError,
        IOError,
        OSError,
        ConnectionError,
        TimeoutError,
        PermissionError,
        TypeError,
        KeyError,
        AttributeError,
    ]
)


# ===========================================================================
# Test Pydantic models
# ===========================================================================


class SimpleModel(BaseModel):
    """A simple Pydantic model for testing structured output."""

    name: str
    value: int


class FloatModel(BaseModel):
    """A model with float fields."""

    score: float
    label: str


class BoolModel(BaseModel):
    """A model with a boolean field."""

    flag: bool
    description: str


class NestedModel(BaseModel):
    """A model with a nested structure."""

    title: str
    count: int
    active: bool


# ===========================================================================
# Helpers
# ===========================================================================


class TypedProvider:
    """Provider that returns a pre-configured result for complete()."""

    def __init__(self, complete_result: Any) -> None:
        self._complete_result = complete_result

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        return self._complete_result

    def run(
        self,
        prompt: str,
        *,
        tools: list[ToolDef] | None = None,
        response_model: type | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        return AIResult(
            output="output",
            tool_calls=[],
            usage=TokenUsage(10, 20, 30),
            duration_ms=50.0,
        )

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        return iter(["chunk"])

    def extract(self, text: str, *, model: type) -> Any:
        return self._complete_result


class RaisingProvider:
    """Provider that raises a specified exception type with a given message."""

    def __init__(self, exc_type: type[Exception], message: str) -> None:
        self._exc_type = exc_type
        self._message = message

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        raise self._exc_type(self._message)

    def run(
        self,
        prompt: str,
        *,
        tools: list[ToolDef] | None = None,
        response_model: type | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        raise self._exc_type(self._message)

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raise self._exc_type(self._message)

    def extract(self, text: str, *, model: type) -> Any:
        raise self._exc_type(self._message)


# ===========================================================================
# Property 8: AI complete returns correctly typed output
# ===========================================================================


class TestAICompleteTypedOutputProperty:
    """Property 8: AI complete returns correctly typed output.

    For any valid Pydantic model T and any provider response that conforms to T's
    schema, AI.complete(prompt, response_model=T) SHALL return an instance of type T
    with field values matching the provider response. When no response_model is given,
    AI.complete(prompt) SHALL return a str.

    **Validates: Requirements 5.2, 5.3**
    """

    @given(prompt=prompts_st, response_text=raw_text_responses_st)
    def test_complete_without_response_model_returns_str(
        self, prompt: str, response_text: str
    ) -> None:
        """AI.complete(prompt) without response_model returns a str.

        **Validates: Requirements 5.3**
        """
        provider = TypedProvider(complete_result=response_text)
        ai = AI(_provider=provider)

        result = ai.complete(prompt)

        assert isinstance(result, str)
        assert result == response_text

    @given(prompt=prompts_st, name=field_name_st, value=field_int_st)
    def test_complete_with_simple_model_returns_typed_instance(
        self, prompt: str, name: str, value: int
    ) -> None:
        """AI.complete(prompt, response_model=T) returns instance of T for SimpleModel.

        **Validates: Requirements 5.2**
        """
        model_instance = SimpleModel(name=name, value=value)
        provider = TypedProvider(complete_result=model_instance)
        ai = AI(_provider=provider)

        result = ai.complete(prompt, response_model=SimpleModel)

        assert isinstance(result, SimpleModel)
        assert result.name == name
        assert result.value == value

    @given(prompt=prompts_st, score=field_float_st, label=field_name_st)
    def test_complete_with_float_model_returns_typed_instance(
        self, prompt: str, score: float, label: str
    ) -> None:
        """AI.complete(prompt, response_model=T) returns instance of T for FloatModel.

        **Validates: Requirements 5.2**
        """
        model_instance = FloatModel(score=score, label=label)
        provider = TypedProvider(complete_result=model_instance)
        ai = AI(_provider=provider)

        result = ai.complete(prompt, response_model=FloatModel)

        assert isinstance(result, FloatModel)
        assert result.score == score
        assert result.label == label

    @given(prompt=prompts_st, flag=field_bool_st, description=field_name_st)
    def test_complete_with_bool_model_returns_typed_instance(
        self, prompt: str, flag: bool, description: str
    ) -> None:
        """AI.complete(prompt, response_model=T) returns instance of T for BoolModel.

        **Validates: Requirements 5.2**
        """
        model_instance = BoolModel(flag=flag, description=description)
        provider = TypedProvider(complete_result=model_instance)
        ai = AI(_provider=provider)

        result = ai.complete(prompt, response_model=BoolModel)

        assert isinstance(result, BoolModel)
        assert result.flag == flag
        assert result.description == description

    @given(
        prompt=prompts_st,
        title=field_name_st,
        count=field_int_st,
        active=field_bool_st,
    )
    def test_complete_with_nested_model_returns_typed_instance(
        self, prompt: str, title: str, count: int, active: bool
    ) -> None:
        """AI.complete(prompt, response_model=T) returns instance of T for NestedModel.

        **Validates: Requirements 5.2**
        """
        model_instance = NestedModel(title=title, count=count, active=active)
        provider = TypedProvider(complete_result=model_instance)
        ai = AI(_provider=provider)

        result = ai.complete(prompt, response_model=NestedModel)

        assert isinstance(result, NestedModel)
        assert result.title == title
        assert result.count == count
        assert result.active == active

    @given(prompt=prompts_st, name=field_name_st, value=field_int_st)
    def test_complete_with_dict_response_validates_to_model(
        self, prompt: str, name: str, value: int
    ) -> None:
        """When provider returns a dict conforming to T's schema, AI validates it to T.

        **Validates: Requirements 5.2**
        """
        dict_result = {"name": name, "value": value}
        provider = TypedProvider(complete_result=dict_result)
        ai = AI(_provider=provider)

        result = ai.complete(prompt, response_model=SimpleModel)

        assert isinstance(result, SimpleModel)
        assert result.name == name
        assert result.value == value


# ===========================================================================
# Property 9: AI wraps provider exceptions
# ===========================================================================


class TestAIWrapsProviderExceptionsProperty:
    """Property 9: AI wraps provider exceptions.

    For any exception raised by an AIProvider during complete() or run(), the AI
    capability SHALL raise AINotAvailableError with the original error message preserved
    in the exception, and SHALL NOT expose the provider-specific exception type.

    **Validates: Requirements 5.13**
    """

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    def test_complete_wraps_any_exception_in_ai_not_available(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """AI.complete() wraps any provider exception in AINotAvailableError.

        **Validates: Requirements 5.13**
        """
        provider = RaisingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider)

        # Build the expected message string from the original exception
        original_exc = exc_type(error_msg)
        expected_msg = str(original_exc)

        try:
            ai.complete(prompt)
            raise AssertionError("Expected AINotAvailableError to be raised")
        except AINotAvailableError as exc:
            # Original message preserved (as str(original_exception))
            assert expected_msg in str(exc)
            # Exception type is AINotAvailableError, not the original
            assert type(exc) is AINotAvailableError

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    def test_run_wraps_any_exception_in_ai_not_available(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """AI.run() wraps any provider exception in AINotAvailableError.

        **Validates: Requirements 5.13**
        """
        provider = RaisingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider)

        # Build the expected message string from the original exception
        original_exc = exc_type(error_msg)
        expected_msg = str(original_exc)

        try:
            ai.run(prompt)
            raise AssertionError("Expected AINotAvailableError to be raised")
        except AINotAvailableError as exc:
            # Original message preserved (as str(original_exception))
            assert expected_msg in str(exc)
            # Exception type is AINotAvailableError, not the original
            assert type(exc) is AINotAvailableError

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    def test_original_exception_chained_as_cause(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """The original exception is preserved as __cause__ for debugging.

        **Validates: Requirements 5.13**
        """
        provider = RaisingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider)

        try:
            ai.complete(prompt)
            raise AssertionError("Expected AINotAvailableError to be raised")
        except AINotAvailableError as exc:
            # Original exception should be chained as cause
            assert exc.__cause__ is not None
            assert isinstance(exc.__cause__, exc_type)

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    def test_provider_exception_type_not_exposed(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """Provider-specific exception types are never exposed to the job author.

        **Validates: Requirements 5.13**
        """
        provider = RaisingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider)

        # The only exception a job author should ever see is AINotAvailableError
        # (not RuntimeError, IOError, ConnectionError, etc.)
        without_model_exc = None
        run_exc = None

        try:
            ai.complete(prompt)
        except AINotAvailableError as e:
            without_model_exc = e
        except Exception as exc:
            raise AssertionError(
                f"Expected AINotAvailableError, got {exc_type.__name__}"
            ) from exc

        try:
            ai.complete(prompt, response_model=SimpleModel)
        except AINotAvailableError:
            pass
        except ValueError:
            # ValueError is acceptable for schema validation failures,
            # but only when the provider-specific exception is NOT leaked
            pass
        except Exception as exc:
            raise AssertionError(
                f"Expected AINotAvailableError, got {exc_type.__name__}"
            ) from exc

        try:
            ai.run(prompt)
        except AINotAvailableError as e:
            run_exc = e
        except Exception as exc:
            raise AssertionError(
                f"Expected AINotAvailableError, got {exc_type.__name__}"
            ) from exc

        # At least the basic complete and run should have raised AINotAvailableError
        assert without_model_exc is not None
        assert run_exc is not None

    @given(prompt=prompts_st, error_msg=error_messages_st)
    def test_ai_not_available_from_provider_passes_through(
        self, prompt: str, error_msg: str
    ) -> None:
        """If provider raises AINotAvailableError itself, it passes through without double-wrapping.

        **Validates: Requirements 5.13**
        """
        provider = RaisingProvider(exc_type=AINotAvailableError, message=error_msg)
        ai = AI(_provider=provider)

        try:
            ai.complete(prompt)
            raise AssertionError("Expected AINotAvailableError to be raised")
        except AINotAvailableError as exc:
            # Should pass through directly, not be double-wrapped
            assert error_msg in str(exc)
            # __cause__ should be None since it wasn't wrapped
            assert exc.__cause__ is None
