"""MockAI — pattern-matching AI testing double.

Provides a deterministic mock for the AI capability class that matches
prompts against glob patterns and returns pre-configured responses. Useful
for testing AI-powered jobs without network calls or API keys.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, TypeVar

from functualize_ai._ai import AI
from functualize_ai._types import AILimits, AIResult, TokenUsage

T = TypeVar("T")


@dataclass
class MockAICall:
    """A record of a single MockAI call."""

    prompt: str
    response_model: type | None
    response: Any


class MockAI(AI):
    """Pattern-matching AI mock for deterministic testing.

    Matches prompts against glob patterns in the ``responses`` dict and returns
    the associated value. When the value is an instance of a type (i.e. an
    object), it is returned as structured output. When the value is a string,
    it is returned as raw text.

    Args:
        responses: A dict mapping glob patterns to response values.
            Patterns are matched using ``fnmatch`` (Unix shell-style wildcards).

    Examples:
        >>> mock = MockAI(responses={"*summarize*": "A brief summary."})
        >>> mock.complete("Please summarize this text")
        'A brief summary.'

        >>> from pydantic import BaseModel
        >>> class Sentiment(BaseModel):
        ...     score: float
        ...     label: str
        >>> mock = MockAI(responses={"*sentiment*": Sentiment(score=0.9, label="positive")})
        >>> result = mock.complete("Analyze sentiment of this", response_model=Sentiment)
        >>> result.label
        'positive'

    Raises:
        ValueError: When a prompt does not match any pattern in the responses dict.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        # Initialize parent with no provider (we override all methods)
        super().__init__(_provider=None, _event_bus=None, _state_ns=None)
        self._responses = responses
        self._calls: list[MockAICall] = []

    @property
    def call_count(self) -> int:
        """Return the total number of calls made."""
        return len(self._calls)

    @property
    def calls(self) -> list[MockAICall]:
        """Return the list of all call records."""
        return self._calls

    @property
    def last_prompt(self) -> str:
        """Return the prompt string of the most recent call.

        Raises:
            IndexError: If no calls have been made.
        """
        if not self._calls:
            raise IndexError("No calls have been made to MockAI")
        return self._calls[-1].prompt

    def _match_prompt(self, prompt: str) -> Any:
        """Find the first matching pattern for a prompt.

        Iterates through the responses dict and returns the value for
        the first pattern that matches the prompt (using fnmatch glob matching).

        Args:
            prompt: The prompt string to match against patterns.

        Returns:
            The response value associated with the first matching pattern.

        Raises:
            ValueError: If no pattern matches the prompt.
        """
        for pattern, response in self._responses.items():
            if fnmatch(prompt, pattern):
                return response
        raise ValueError(
            f"No matching response configured for prompt: {prompt!r}. "
            f"Configured patterns: {list(self._responses.keys())}"
        )

    def _record_call(
        self, prompt: str, response_model: type | None, response: Any
    ) -> None:
        """Record a call in the calls list."""
        self._calls.append(
            MockAICall(prompt=prompt, response_model=response_model, response=response)
        )

    def complete(
        self, prompt: str, *, response_model: type[T] | None = None, **kwargs: Any
    ) -> Any:
        """Complete a prompt using pattern matching.

        Returns the value associated with the first matching glob pattern.
        When the value is a type instance, returns as structured output.
        When the value is a string, returns as raw text.

        Args:
            prompt: The prompt text to match against patterns.
            response_model: Optional type for structured output (used for recording).
            **kwargs: Ignored (accepted for API compatibility).

        Returns:
            The matched response value.

        Raises:
            ValueError: If no pattern matches the prompt.
        """
        response = self._match_prompt(prompt)
        self._record_call(prompt, response_model, response)
        return response

    def run(
        self,
        prompt: str,
        *,
        tools: Any | None = None,
        response_model: type[T] | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        """Run a prompt using pattern matching, returning an AIResult.

        Returns an AIResult wrapping the matched response value with
        empty tool calls and zero usage.

        Args:
            prompt: The prompt text to match against patterns.
            tools: Ignored (accepted for API compatibility).
            response_model: Optional type for structured output (used for recording).
            limits: Ignored (accepted for API compatibility).
            **kwargs: Ignored (accepted for API compatibility).

        Returns:
            An AIResult containing the matched response.

        Raises:
            ValueError: If no pattern matches the prompt.
        """
        response = self._match_prompt(prompt)
        self._record_call(prompt, response_model, response)
        return AIResult(
            output=response,
            tool_calls=[],
            usage=TokenUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=None,
            ),
            duration_ms=0.0,
        )

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Stream a response using pattern matching.

        Returns an iterator that yields the matched string response
        as a single chunk.

        Args:
            prompt: The prompt text to match against patterns.
            **kwargs: Ignored (accepted for API compatibility).

        Returns:
            An iterator yielding the matched response string.

        Raises:
            ValueError: If no pattern matches the prompt.
        """
        response = self._match_prompt(prompt)
        self._record_call(prompt, None, response)
        if isinstance(response, str):
            yield response
        else:
            yield str(response)

    def extract(self, text: str, *, model: type[T]) -> Any:
        """Extract structured data using pattern matching.

        Uses the text as the prompt for pattern matching.

        Args:
            text: The text to match against patterns.
            model: The expected output type (used for recording).

        Returns:
            The matched response value.

        Raises:
            ValueError: If no pattern matches the text.
        """
        response = self._match_prompt(text)
        self._record_call(text, model, response)
        return response
