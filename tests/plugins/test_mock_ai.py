"""Unit tests for the MockAI testing double."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from functualize_ai._types import AIResult
from functualize_ai.testing import MockAI

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class SentimentResult:
    """A simple structured output model for testing."""

    score: float
    label: str


@dataclass
class Summary:
    """Another structured output model."""

    text: str
    word_count: int


# ---------------------------------------------------------------------------
# Tests: Pattern matching
# ---------------------------------------------------------------------------


class TestMockAIPatternMatching:
    """Tests for glob pattern matching behavior."""

    def test_exact_match(self) -> None:
        mock = MockAI(responses={"hello": "world"})
        assert mock.complete("hello") == "world"

    def test_glob_wildcard_match(self) -> None:
        mock = MockAI(responses={"*summarize*": "A brief summary."})
        assert mock.complete("Please summarize this text") == "A brief summary."

    def test_glob_question_mark(self) -> None:
        mock = MockAI(responses={"test?": "matched"})
        assert mock.complete("testX") == "matched"

    def test_first_matching_pattern_wins(self) -> None:
        mock = MockAI(
            responses={
                "*foo*": "first",
                "*bar*": "second",
                "*foo*bar*": "third",
            }
        )
        # "foobar" matches both *foo* and *foo*bar*, but first wins
        assert mock.complete("foobar") == "first"

    def test_no_match_raises_value_error(self) -> None:
        mock = MockAI(responses={"*summarize*": "summary"})
        with pytest.raises(ValueError, match="No matching response configured"):
            mock.complete("something completely different")

    def test_no_match_error_includes_prompt(self) -> None:
        mock = MockAI(responses={"*hello*": "hi"})
        with pytest.raises(ValueError, match="unrelated prompt"):
            mock.complete("unrelated prompt")

    def test_no_match_error_includes_patterns(self) -> None:
        mock = MockAI(responses={"*hello*": "hi", "*world*": "earth"})
        with pytest.raises(ValueError, match="hello"):
            mock.complete("unmatched")


# ---------------------------------------------------------------------------
# Tests: Structured vs string responses
# ---------------------------------------------------------------------------


class TestMockAIResponseTypes:
    """Tests for type-based response behavior."""

    def test_string_value_returned_as_text(self) -> None:
        mock = MockAI(responses={"*": "raw text response"})
        result = mock.complete("anything")
        assert result == "raw text response"
        assert isinstance(result, str)

    def test_type_instance_returned_as_structured_output(self) -> None:
        sentiment = SentimentResult(score=0.9, label="positive")
        mock = MockAI(responses={"*sentiment*": sentiment})
        result = mock.complete("analyze sentiment", response_model=SentimentResult)
        assert isinstance(result, SentimentResult)
        assert result.score == 0.9
        assert result.label == "positive"

    def test_different_patterns_different_types(self) -> None:
        mock = MockAI(
            responses={
                "*sentiment*": SentimentResult(score=0.5, label="neutral"),
                "*summary*": Summary(text="Short.", word_count=1),
            }
        )
        r1 = mock.complete("sentiment check")
        assert isinstance(r1, SentimentResult)

        r2 = mock.complete("generate summary")
        assert isinstance(r2, Summary)
        assert r2.word_count == 1


# ---------------------------------------------------------------------------
# Tests: Call tracking properties
# ---------------------------------------------------------------------------


class TestMockAICallTracking:
    """Tests for call_count, calls, and last_prompt properties."""

    def test_call_count_starts_at_zero(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        assert mock.call_count == 0

    def test_call_count_increments(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        mock.complete("a")
        assert mock.call_count == 1
        mock.complete("b")
        assert mock.call_count == 2
        mock.complete("c")
        assert mock.call_count == 3

    def test_calls_list_records_each_call(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        mock.complete("first")
        mock.complete("second", response_model=SentimentResult)

        assert len(mock.calls) == 2
        assert mock.calls[0].prompt == "first"
        assert mock.calls[0].response_model is None
        assert mock.calls[0].response == "ok"

        assert mock.calls[1].prompt == "second"
        assert mock.calls[1].response_model is SentimentResult
        assert mock.calls[1].response == "ok"

    def test_last_prompt_returns_most_recent(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        mock.complete("alpha")
        mock.complete("beta")
        mock.complete("gamma")
        assert mock.last_prompt == "gamma"

    def test_last_prompt_raises_when_no_calls(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        with pytest.raises(IndexError, match="No calls have been made"):
            _ = mock.last_prompt


# ---------------------------------------------------------------------------
# Tests: run() method
# ---------------------------------------------------------------------------


class TestMockAIRun:
    """Tests for MockAI.run() behavior."""

    def test_run_returns_ai_result(self) -> None:
        mock = MockAI(responses={"*": "result output"})
        result = mock.run("do something")
        assert isinstance(result, AIResult)
        assert result.output == "result output"
        assert result.tool_calls == []
        assert result.usage.total_tokens == 0
        assert result.duration_ms == 0.0

    def test_run_increments_call_count(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        mock.run("prompt")
        assert mock.call_count == 1

    def test_run_records_in_calls(self) -> None:
        mock = MockAI(responses={"*": "output"})
        mock.run("my prompt", response_model=Summary)
        assert mock.calls[0].prompt == "my prompt"
        assert mock.calls[0].response_model is Summary
        assert mock.calls[0].response == "output"

    def test_run_raises_on_no_match(self) -> None:
        mock = MockAI(responses={"*specific*": "found"})
        with pytest.raises(ValueError, match="No matching response"):
            mock.run("no match here")


# ---------------------------------------------------------------------------
# Tests: stream() method
# ---------------------------------------------------------------------------


class TestMockAIStream:
    """Tests for MockAI.stream() behavior."""

    def test_stream_yields_string_response(self) -> None:
        mock = MockAI(responses={"*": "streamed text"})
        chunks = list(mock.stream("prompt"))
        assert chunks == ["streamed text"]

    def test_stream_records_call(self) -> None:
        mock = MockAI(responses={"*": "chunk"})
        list(mock.stream("streaming prompt"))
        assert mock.call_count == 1
        assert mock.last_prompt == "streaming prompt"

    def test_stream_raises_on_no_match(self) -> None:
        mock = MockAI(responses={"*specific*": "found"})
        with pytest.raises(ValueError, match="No matching response"):
            list(mock.stream("no match"))


# ---------------------------------------------------------------------------
# Tests: extract() method
# ---------------------------------------------------------------------------


class TestMockAIExtract:
    """Tests for MockAI.extract() behavior."""

    def test_extract_returns_matched_response(self) -> None:
        sentiment = SentimentResult(score=0.8, label="positive")
        mock = MockAI(responses={"*": sentiment})
        result = mock.extract("some text", model=SentimentResult)
        assert result is sentiment

    def test_extract_records_call(self) -> None:
        mock = MockAI(responses={"*": SentimentResult(score=0.5, label="neutral")})
        mock.extract("text data", model=SentimentResult)
        assert mock.call_count == 1
        assert mock.calls[0].prompt == "text data"
        assert mock.calls[0].response_model is SentimentResult

    def test_extract_raises_on_no_match(self) -> None:
        mock = MockAI(responses={"*specific*": SentimentResult(score=0.0, label="n/a")})
        with pytest.raises(ValueError, match="No matching response"):
            mock.extract("no match text", model=SentimentResult)


# ---------------------------------------------------------------------------
# Tests: Mixed methods share call state
# ---------------------------------------------------------------------------


class TestMockAIMixedMethods:
    """Verify that all methods share the same call tracking state."""

    def test_mixed_calls_all_tracked(self) -> None:
        mock = MockAI(responses={"*": "ok"})
        mock.complete("one")
        mock.run("two")
        list(mock.stream("three"))
        mock.extract("four", model=SentimentResult)

        assert mock.call_count == 4
        assert mock.calls[0].prompt == "one"
        assert mock.calls[1].prompt == "two"
        assert mock.calls[2].prompt == "three"
        assert mock.calls[3].prompt == "four"
        assert mock.last_prompt == "four"
