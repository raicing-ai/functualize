"""PydanticAI Provider — AIProvider protocol implementation.

Implements the AIProvider protocol using PydanticAI and LiteLLM as the
backing engine. Translates ToolScope output into PydanticAI native toolsets
and bridges async PydanticAI calls to functualize's sync engine.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from functualize_ai._types import (
    AILimits,
    AIResult,
    TokenUsage,
    ToolCallRecord,
    ToolDef,
)
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from functualize_ai_pydantic._async_bridge import run_sync
from functualize_ai_pydantic._tool_translator import ToolScopeTranslator

if TYPE_CHECKING:
    from functualize_ai._config import AIConfig

__all__ = ["PydanticAIProvider"]


class PydanticAIProvider:
    """AIProvider implementation backed by PydanticAI and LiteLLM.

    Translates functualize ToolDef instances into PydanticAI's native
    Tool format, reads configuration from AIConfig, and bridges async
    PydanticAI operations to functualize's sync engine.

    Args:
        config: The AIConfig instance providing model, max_tokens, and other settings.
    """

    def __init__(self, config: AIConfig) -> None:
        self._config = config
        self._translator = ToolScopeTranslator()

    def complete(
        self, prompt: str, *, response_model: type | None = None, **kwargs: Any
    ) -> Any:
        """Complete a prompt, optionally returning a structured response.

        Creates a PydanticAI Agent configured with the model from AIConfig,
        runs it synchronously, and returns either structured output or raw text.

        Args:
            prompt: The prompt text to send to the LLM.
            response_model: Optional Pydantic model type for structured output.
            **kwargs: Additional provider-specific parameters (e.g., model override).

        Returns:
            If response_model is provided, an instance of that type.
            Otherwise, the raw text response as a string.
        """
        model = kwargs.pop("model", None) or self._config.model
        model_settings = self._build_model_settings(**kwargs)

        agent: Agent[None, Any]
        if response_model is not None:
            agent = Agent(
                model,
                output_type=response_model,
                model_settings=model_settings,
            )
        else:
            agent = Agent(
                model,
                model_settings=model_settings,
            )

        result = agent.run_sync(prompt)
        return result.output

    def run(
        self,
        prompt: str,
        *,
        tools: list[ToolDef] | None = None,
        response_model: type | None = None,
        limits: AILimits | None = None,
        **kwargs: Any,
    ) -> AIResult:
        """Run a prompt with tool calling support, returning AIResult.

        Creates a PydanticAI Agent with translated tools, optional structured
        output, and usage limits. Bridges the async operation to sync and
        converts PydanticAI's result format into functualize's AIResult.

        Args:
            prompt: The prompt text to send to the LLM.
            tools: Optional list of ToolDef instances for tool calling.
            response_model: Optional Pydantic model type for structured output.
            limits: Optional AILimits for budget/constraint caps.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An AIResult containing output, tool call records, usage, and duration.
        """
        model = kwargs.pop("model", None) or self._config.model
        model_settings = self._build_model_settings(**kwargs)

        # Translate ToolDef list into PydanticAI native tools
        pydantic_tools = []
        if tools:
            pydantic_tools = self._translator.translate(tools)

        # Build usage limits from AILimits
        usage_limits = self._build_usage_limits(limits)

        # Create agent
        agent_kwargs: dict[str, Any] = {
            "model_settings": model_settings,
        }
        if pydantic_tools:
            agent_kwargs["tools"] = pydantic_tools
        if response_model is not None:
            agent_kwargs["output_type"] = response_model

        agent: Agent[None, Any] = Agent(model, **agent_kwargs)

        # Run and measure
        start_time = time.time()
        result = agent.run_sync(prompt, usage_limits=usage_limits)
        duration_ms = (time.time() - start_time) * 1000

        # Extract tool call records from messages
        tool_calls = self._extract_tool_calls(result)

        # Convert usage
        usage = self._convert_usage(result.usage)

        return AIResult(
            output=result.output,
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=duration_ms,
        )

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Stream response tokens as an iterator of string chunks.

        Uses PydanticAI's run_stream to get incremental text responses,
        bridging the async stream to a sync iterator.

        Args:
            prompt: The prompt text to send to the LLM.
            **kwargs: Additional provider-specific parameters.

        Returns:
            An iterator yielding string chunks of the response.
        """
        model = kwargs.pop("model", None) or self._config.model
        model_settings = self._build_model_settings(**kwargs)

        agent: Agent[None, str] = Agent(model, model_settings=model_settings)

        # Use the async bridge to collect streamed chunks
        async def _stream_chunks() -> list[str]:
            chunks: list[str] = []
            async with agent.run_stream(prompt) as stream:
                async for text in stream.stream_text():
                    chunks.append(text)
            return chunks

        chunks = run_sync(_stream_chunks())
        return iter(chunks)

    def extract(self, text: str, *, model: type) -> Any:
        """Extract structured data from text using the given model.

        Creates a PydanticAI Agent configured with the output type and
        sends an extraction prompt to the LLM.

        Args:
            text: The text to extract data from.
            model: The Pydantic model type to extract into.

        Returns:
            An instance of the model type populated from the text.
        """
        llm_model = self._config.model
        model_settings = self._build_model_settings()

        agent: Agent[None, Any] = Agent(
            llm_model,
            output_type=model,
            model_settings=model_settings,
        )

        extraction_prompt = (
            f"Extract the following structured data from this text:\n\n{text}"
        )
        result = agent.run_sync(extraction_prompt)
        return result.output

    def _build_model_settings(self, **kwargs: Any) -> dict[str, Any]:
        """Build model settings dict from AIConfig and overrides.

        Combines the base configuration from AIConfig with any additional
        keyword argument overrides.

        Returns:
            A dict of model settings for the PydanticAI Agent.
        """
        settings: dict[str, Any] = {}

        if self._config.max_tokens:
            settings["max_tokens"] = self._config.max_tokens

        if self._config.timeout_seconds:
            settings["timeout"] = self._config.timeout_seconds

        # Merge any additional kwargs into settings
        settings.update(kwargs)

        return settings

    def _build_usage_limits(self, limits: AILimits | None) -> UsageLimits | None:
        """Convert functualize AILimits into PydanticAI UsageLimits.

        Args:
            limits: Optional functualize AILimits to convert.

        Returns:
            PydanticAI UsageLimits if limits are specified, otherwise None.
        """
        if limits is None:
            return None

        kwargs: dict[str, Any] = {}

        if limits.max_tool_calls is not None:
            kwargs["tool_calls_limit"] = limits.max_tool_calls

        if limits.max_tokens is not None:
            kwargs["output_tokens_limit"] = limits.max_tokens

        if not kwargs:
            return None

        return UsageLimits(**kwargs)

    def _extract_tool_calls(self, result: Any) -> list[ToolCallRecord]:
        """Extract tool call records from PydanticAI result messages.

        Inspects the message history in the result to find tool call/return
        pairs and converts them into functualize ToolCallRecord instances.

        Args:
            result: The PydanticAI AgentRunResult.

        Returns:
            A list of ToolCallRecord instances.
        """
        from pydantic_ai.messages import (
            ModelResponse,
            ToolCallPart,
            ToolReturnPart,
        )

        tool_calls: list[ToolCallRecord] = []

        # Collect all tool returns indexed by tool_call_id for matching
        tool_returns: dict[str, Any] = {}
        for message in result.all_messages():
            if hasattr(message, "parts"):
                for part in message.parts:
                    if isinstance(part, ToolReturnPart):
                        tool_returns[part.tool_call_id] = part.content

        # Now extract tool calls
        for message in result.all_messages():
            if isinstance(message, ModelResponse):
                for part in message.parts:
                    if isinstance(part, ToolCallPart):
                        args = part.args if isinstance(part.args, dict) else {}
                        return_content = tool_returns.get(part.tool_call_id)
                        tool_calls.append(
                            ToolCallRecord(
                                tool_name=part.tool_name,
                                args=args,
                                result=return_content,
                                duration_ms=0.0,  # PydanticAI doesn't track per-tool duration
                            )
                        )

        return tool_calls

    def _convert_usage(self, usage: Any) -> TokenUsage:
        """Convert PydanticAI RunUsage into functualize TokenUsage.

        Args:
            usage: The PydanticAI RunUsage instance.

        Returns:
            A functualize TokenUsage dataclass.
        """
        prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=None,  # Cost calculation delegated to budget layer
        )
