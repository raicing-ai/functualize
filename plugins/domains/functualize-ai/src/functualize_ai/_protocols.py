"""AIProvider protocol for the AI Domain SDK."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize_ai._types import AILimits, AIResult, ToolDef


@runtime_checkable
class AIProvider(Protocol):
    """Protocol that AI implementation plugins must satisfy.

    Defines the interface for LLM interaction backends. Implementations
    provide the actual API calls to language models while the AI capability
    class handles orchestration, validation retries, budget enforcement,
    and event emission.
    """

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        """Complete a prompt, optionally returning structured output.

        Args:
            prompt: The prompt text to send to the LLM.
            response_model: Optional Pydantic model type for structured output.
            **kwargs: Additional provider-specific parameters.

        Returns:
            If response_model is provided, an instance of that type.
            Otherwise, the raw text response as a string.
        """
        ...

    def run(
        self,
        prompt: str,
        *,
        tools: list[ToolDef] | None = None,
        response_model: type | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        """Run a prompt with optional tool calling and limits.

        Args:
            prompt: The prompt text to send to the LLM.
            tools: Optional list of tool definitions available for the call.
            response_model: Optional Pydantic model type for structured output.
            limits: Optional budget and constraint caps.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An AIResult containing output, tool call records, usage, and duration.
        """
        ...

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Stream a response as incremental text chunks.

        Args:
            prompt: The prompt text to send to the LLM.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An iterator yielding string chunks of the response.
        """
        ...

    def extract(self, text: str, *, model: type) -> Any:
        """Extract structured data from text.

        Args:
            text: The text to extract data from.
            model: The Pydantic model type to extract into.

        Returns:
            An instance of the model type populated from the text.
        """
        ...
