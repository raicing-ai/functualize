"""Unit tests for the AI capability class."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from functualize_ai import AI, AINotAvailableError, AIResult, TokenUsage, ToolDef
from functualize_ai._tool_scope import ToolScope

if TYPE_CHECKING:
    from functualize_ai._types import AILimits

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class SampleModel:
    """A simple model for structured output testing."""

    name: str
    value: int = 0


class FakeProvider:
    """A minimal AIProvider for happy-path testing."""

    def __init__(
        self,
        complete_result: Any = "raw text",
        run_result: AIResult | None = None,
        stream_chunks: list[str] | None = None,
        extract_result: Any = None,
    ) -> None:
        self._complete_result = complete_result
        self._run_result = run_result or AIResult(
            output="output",
            tool_calls=[],
            usage=TokenUsage(10, 20, 30),
            duration_ms=50.0,
        )
        self._stream_chunks = stream_chunks or ["hello", " world"]
        self._extract_result = extract_result

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
        return self._run_result

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        return iter(self._stream_chunks)

    def extract(self, text: str, *, model: type) -> Any:
        return self._extract_result or model(name="extracted")


class FailingValidationProvider:
    """Provider that always raises ValueError on complete/extract."""

    def __init__(self) -> None:
        self.complete_count = 0
        self.extract_count = 0

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        self.complete_count += 1
        raise ValueError("field 'name' invalid")

    def run(self, prompt: str, **kwargs: Any) -> AIResult:
        raise ValueError("not expected")

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        return iter([])

    def extract(self, text: str, *, model: type) -> Any:
        self.extract_count += 1
        raise ValueError("extraction failed for 'value'")


class ExplodingProvider:
    """Provider that raises unexpected exceptions (non-ValueError)."""

    def __init__(self, error_msg: str = "connection refused") -> None:
        self._error_msg = error_msg

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        raise RuntimeError(self._error_msg)

    def run(self, prompt: str, **kwargs: Any) -> AIResult:
        raise RuntimeError(self._error_msg)

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raise RuntimeError(self._error_msg)

    def extract(self, text: str, *, model: type) -> Any:
        raise RuntimeError(self._error_msg)


# ---------------------------------------------------------------------------
# Tests: No provider configured
# ---------------------------------------------------------------------------


class TestAINotAvailableError:
    """When no provider is configured, all methods raise AINotAvailableError."""

    def test_complete_raises(self) -> None:
        ai = AI()
        with pytest.raises(
            AINotAvailableError, match="pip install functualize-ai-pydantic"
        ):
            ai.complete("hello")

    def test_run_raises(self) -> None:
        ai = AI()
        with pytest.raises(
            AINotAvailableError, match="pip install functualize-ai-pydantic"
        ):
            ai.run("hello")

    def test_stream_raises(self) -> None:
        ai = AI()
        with pytest.raises(
            AINotAvailableError, match="pip install functualize-ai-pydantic"
        ):
            ai.stream("hello")

    def test_extract_raises(self) -> None:
        ai = AI()
        with pytest.raises(
            AINotAvailableError, match="pip install functualize-ai-pydantic"
        ):
            ai.extract("text", model=SampleModel)

    def test_error_message_includes_install_instructions(self) -> None:
        ai = AI()
        with pytest.raises(AINotAvailableError) as exc_info:
            ai.complete("hello")
        assert "No AI provider configured" in str(exc_info.value)
        assert "pip install functualize-ai-pydantic" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests: complete()
# ---------------------------------------------------------------------------


class TestAIComplete:
    """Tests for AI.complete() method."""

    def test_without_response_model_returns_string(self) -> None:
        ai = AI(_provider=FakeProvider(complete_result="hello world"))
        result = ai.complete("prompt")
        assert result == "hello world"

    def test_with_response_model_returns_validated_instance(self) -> None:
        model = SampleModel(name="test", value=42)
        ai = AI(_provider=FakeProvider(complete_result=model))
        result = ai.complete("prompt", response_model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_with_response_model_retries_on_validation_failure(self) -> None:
        provider = FailingValidationProvider()
        ai = AI(_provider=provider)
        with pytest.raises(
            ValueError, match="Schema validation failed after 3 retries"
        ):
            ai.complete("prompt", response_model=SampleModel)
        assert provider.complete_count == 3

    def test_wraps_provider_exception_in_ai_not_available(self) -> None:
        ai = AI(_provider=ExplodingProvider("timeout error"))
        with pytest.raises(AINotAvailableError, match="timeout error"):
            ai.complete("prompt")

    def test_wraps_exception_with_response_model(self) -> None:
        ai = AI(_provider=ExplodingProvider("api key invalid"))
        with pytest.raises(AINotAvailableError, match="api key invalid"):
            ai.complete("prompt", response_model=SampleModel)


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------


class TestAIRun:
    """Tests for AI.run() method."""

    def test_returns_ai_result(self) -> None:
        ai = AI(_provider=FakeProvider())
        result = ai.run("prompt")
        assert isinstance(result, AIResult)
        assert result.output == "output"
        assert result.duration_ms == 50.0

    def test_with_tool_scope(self) -> None:
        ai = AI(_provider=FakeProvider())
        scope = ToolScope.only(["job_a", "job_b"])
        result = ai.run("prompt", tools=scope)
        assert isinstance(result, AIResult)

    def test_wraps_provider_exception(self) -> None:
        ai = AI(_provider=ExplodingProvider("network error"))
        with pytest.raises(AINotAvailableError, match="network error"):
            ai.run("prompt")


# ---------------------------------------------------------------------------
# Tests: stream()
# ---------------------------------------------------------------------------


class TestAIStream:
    """Tests for AI.stream() method."""

    def test_returns_iterator_of_strings(self) -> None:
        ai = AI(_provider=FakeProvider(stream_chunks=["a", "b", "c"]))
        chunks = list(ai.stream("prompt"))
        assert chunks == ["a", "b", "c"]

    def test_wraps_provider_exception(self) -> None:
        ai = AI(_provider=ExplodingProvider("stream connection lost"))
        with pytest.raises(AINotAvailableError, match="stream connection lost"):
            ai.stream("prompt")


# ---------------------------------------------------------------------------
# Tests: extract()
# ---------------------------------------------------------------------------


class TestAIExtract:
    """Tests for AI.extract() method."""

    def test_returns_validated_instance(self) -> None:
        model = SampleModel(name="extracted", value=99)
        ai = AI(_provider=FakeProvider(extract_result=model))
        result = ai.extract("some text", model=SampleModel)
        assert isinstance(result, SampleModel)
        assert result.name == "extracted"

    def test_retries_on_validation_failure(self) -> None:
        provider = FailingValidationProvider()
        ai = AI(_provider=provider)
        with pytest.raises(
            ValueError, match="Schema validation failed after 3 retries"
        ):
            ai.extract("text", model=SampleModel)
        assert provider.extract_count == 3

    def test_wraps_provider_exception(self) -> None:
        ai = AI(_provider=ExplodingProvider("API error"))
        with pytest.raises(AINotAvailableError, match="API error"):
            ai.extract("text", model=SampleModel)


# ---------------------------------------------------------------------------
# Tests: Exception wrapping behavior
# ---------------------------------------------------------------------------


class TestExceptionWrapping:
    """Verify provider exceptions are wrapped preserving original message."""

    def test_original_message_preserved_in_complete(self) -> None:
        ai = AI(_provider=ExplodingProvider("specific provider error 12345"))
        with pytest.raises(AINotAvailableError) as exc_info:
            ai.complete("hello")
        assert "specific provider error 12345" in str(exc_info.value)

    def test_original_exception_is_cause(self) -> None:
        ai = AI(_provider=ExplodingProvider("original"))
        with pytest.raises(AINotAvailableError) as exc_info:
            ai.complete("hello")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_does_not_expose_provider_specific_types(self) -> None:
        """Job authors only see AINotAvailableError, never the provider's error type."""
        ai = AI(_provider=ExplodingProvider("something broke"))
        with pytest.raises(AINotAvailableError):
            ai.complete("hello")
        # The exception raised is AINotAvailableError, not RuntimeError

    def test_ai_not_available_from_provider_not_double_wrapped(self) -> None:
        """If provider itself raises AINotAvailableError, it passes through."""

        class PassthroughProvider:
            def complete(self, prompt, *, response_model=None, **kwargs):
                raise AINotAvailableError("already an AINotAvailableError")

            def run(self, prompt, **kwargs):
                pass

            def stream(self, prompt, **kwargs):
                return iter([])

            def extract(self, text, *, model):
                pass

        ai = AI(_provider=PassthroughProvider())
        with pytest.raises(AINotAvailableError, match="already an AINotAvailableError"):
            ai.complete("hello")
