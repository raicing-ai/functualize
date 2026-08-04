"""PydanticAI subclass — Extended AI capability with PydanticAI-specific extras.

Provides run_agent_loop for multi-turn agent execution and run_with_history
for continuing conversations from message history. Bridges PydanticAI's async
agent API to functualize's synchronous execution model.
"""

from __future__ import annotations

import time
from typing import Any

from functualize_ai import (
    AI,
    AIResult,
    TokenUsage,
    ToolCallRecord,
    ToolDef,
    ToolScope,
)

from functualize_ai_pydantic._async_bridge import run_sync
from functualize_ai_pydantic._tool_translator import ToolScopeTranslator

__all__ = ["PydanticAI"]


class PydanticAI(AI):
    """Extended AI capability with PydanticAI-specific methods.

    Subclass of AI that exposes additional methods for multi-turn
    agent execution and conversation continuation from message history.
    Uses PydanticAI's Agent under the hood for agentic loop behavior.

    Args:
        _provider: The AIProvider implementation to delegate to, or None.
        _event_bus: An optional event bus (duck-typed with ``emit()``).
        _state_ns: An optional StateNamespace (duck-typed with ``get``/``set``).
        _model: The model name string for PydanticAI agent (e.g. "claude-sonnet-4-20250514").
        _job_registry: Optional job registry for resolving ToolScope to tool defs.
    """

    def __init__(
        self,
        *,
        _provider: Any | None = None,
        _event_bus: Any | None = None,
        _state_ns: Any | None = None,
        _model: str = "claude-sonnet-4-20250514",
        _job_registry: Any | None = None,
    ) -> None:
        super().__init__(
            _provider=_provider,
            _event_bus=_event_bus,
            _state_ns=_state_ns,
        )
        self._model = _model
        self._job_registry = _job_registry
        self._translator = ToolScopeTranslator()

    def run_agent_loop(
        self,
        prompt: str,
        *,
        tools: ToolScope | None = None,
        max_iterations: int = 10,
    ) -> AIResult:
        """Run a multi-turn agent loop with tool calling.

        Executes the agent loop for up to max_iterations turns,
        allowing the LLM to call tools and respond iteratively.
        Each iteration may involve the LLM selecting and calling a tool,
        then receiving the result before deciding the next action.

        This uses PydanticAI's Agent.run() under the hood, bridging
        async to sync execution.

        Args:
            prompt: The initial prompt to start the agent loop.
            tools: A ToolScope defining which tools are available.
            max_iterations: Maximum number of agent loop iterations.

        Returns:
            AIResult containing output, tool calls, usage, and duration.

        Raises:
            AINotAvailableError: If no provider is configured.
        """
        from functualize_ai._errors import AINotAvailableError

        self._ensure_provider()

        start_time = time.time()

        # Resolve tools from the ToolScope
        tool_defs = self._resolve_tool_defs(tools)

        # Translate tool defs into PydanticAI-native Tool objects
        pydantic_tools = self._translator.translate(tool_defs)

        # Build and run the PydanticAI agent
        try:
            result = run_sync(
                self._run_agent_loop_async(
                    prompt=prompt,
                    tools=pydantic_tools,
                    max_iterations=max_iterations,
                )
            )
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            if isinstance(exc, AINotAvailableError):
                raise
            raise AINotAvailableError(str(exc)) from exc

        duration_ms = (time.time() - start_time) * 1000

        # Emit tool.called events
        if self._event_bus is not None:
            from functualize_ai._events import AI_TOOL_CALLED

            for tc in result.tool_calls:
                self._event_bus.emit(
                    AI_TOOL_CALLED,
                    tool_name=tc.tool_name,
                    args=tc.args,
                    duration_ms=tc.duration_ms,
                    status="success",
                )

        return AIResult(
            output=result.output,
            tool_calls=result.tool_calls,
            usage=result.usage,
            duration_ms=duration_ms,
        )

    def run_with_history(
        self,
        messages: list[Any],
        *,
        tools: ToolScope | None = None,
    ) -> AIResult:
        """Continue a conversation from message history.

        Resumes an AI conversation using the provided message history,
        optionally with a specific set of tools available. The last message
        in the history is used as the current prompt, with preceding messages
        providing context.

        Args:
            messages: Previous conversation messages to continue from.
                Each message should be a dict with 'role' and 'content' keys,
                or a PydanticAI ModelMessage object.
            tools: A ToolScope defining which tools are available.

        Returns:
            AIResult containing output, tool calls, usage, and duration.

        Raises:
            AINotAvailableError: If no provider is configured.
            ValueError: If messages list is empty.
        """
        from functualize_ai._errors import AINotAvailableError

        self._ensure_provider()

        if not messages:
            raise ValueError("messages list must not be empty")

        start_time = time.time()

        # Resolve tools from the ToolScope
        tool_defs = self._resolve_tool_defs(tools)

        # Translate tool defs into PydanticAI-native Tool objects
        pydantic_tools = self._translator.translate(tool_defs)

        try:
            result = run_sync(
                self._run_with_history_async(
                    messages=messages,
                    tools=pydantic_tools,
                )
            )
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            if isinstance(exc, AINotAvailableError):
                raise
            raise AINotAvailableError(str(exc)) from exc

        duration_ms = (time.time() - start_time) * 1000

        # Emit tool.called events
        if self._event_bus is not None:
            from functualize_ai._events import AI_TOOL_CALLED

            for tc in result.tool_calls:
                self._event_bus.emit(
                    AI_TOOL_CALLED,
                    tool_name=tc.tool_name,
                    args=tc.args,
                    duration_ms=tc.duration_ms,
                    status="success",
                )

        return AIResult(
            output=result.output,
            tool_calls=result.tool_calls,
            usage=result.usage,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_tool_defs(self, tools: ToolScope | None) -> list[ToolDef]:
        """Resolve a ToolScope into a list of ToolDef instances."""
        if tools is None:
            return []
        registry = self._job_registry if self._job_registry is not None else []
        return tools.to_tool_defs(registry)

    async def _run_agent_loop_async(
        self,
        *,
        prompt: str,
        tools: list[Any],
        max_iterations: int,
    ) -> AIResult:
        """Async implementation of the agent loop using PydanticAI Agent.

        Creates a PydanticAI Agent with the configured model and tools,
        runs it with the given prompt, and collects results including
        tool call records and token usage.
        """
        try:
            from pydantic_ai import Agent
            from pydantic_ai.usage import UsageLimits
        except ImportError as exc:
            from functualize_ai._errors import AINotAvailableError

            raise AINotAvailableError(
                "pydantic-ai is required for run_agent_loop. "
                "Install it: pip install pydantic-ai"
            ) from exc

        # Create agent with the configured model and tools
        agent = Agent(
            self._model,
            tools=tools,
        )

        # Run the agent with request limit controlling max iterations
        usage_limits = UsageLimits(request_limit=max_iterations)

        result = await agent.run(
            prompt,
            usage_limits=usage_limits,
        )

        # Extract tool call records from messages
        tool_calls = _extract_tool_calls(result)

        # Extract token usage
        usage = _extract_usage(result)

        return AIResult(
            output=result.data,
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=0.0,  # Duration tracked by caller
        )

    async def _run_with_history_async(
        self,
        *,
        messages: list[Any],
        tools: list[Any],
    ) -> AIResult:
        """Async implementation of conversation continuation.

        Creates a PydanticAI Agent and runs it with message history
        to continue an existing conversation.
        """
        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            from functualize_ai._errors import AINotAvailableError

            raise AINotAvailableError(
                "pydantic-ai is required for run_with_history. "
                "Install it: pip install pydantic-ai"
            ) from exc

        # Create agent with the configured model and tools
        agent = Agent(
            self._model,
            tools=tools,
        )

        # Convert messages to the format PydanticAI expects
        # Extract the last user message as the prompt, rest as history
        prompt = ""
        message_history: list[Any] = []

        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                message_history.append({"role": role, "content": content})
            else:
                # Assume it's a PydanticAI ModelMessage object, pass through
                message_history.append(msg)

        # The last message becomes the active prompt
        if message_history:
            last_msg = message_history.pop()
            if isinstance(last_msg, dict):
                prompt = last_msg.get("content", "")
            else:
                prompt = getattr(last_msg, "content", str(last_msg))

        # Run with message history
        # PydanticAI's message_history accepts ModelMessage objects or None
        # For dict-based messages, we pass them as message_history if they're
        # PydanticAI ModelMessage objects, otherwise use prompt only
        run_kwargs: dict[str, Any] = {}
        if message_history and not isinstance(message_history[0], dict):
            run_kwargs["message_history"] = message_history

        result = await agent.run(prompt, **run_kwargs)

        # Extract tool call records from messages
        tool_calls = _extract_tool_calls(result)

        # Extract token usage
        usage = _extract_usage(result)

        return AIResult(
            output=result.data,
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=0.0,  # Duration tracked by caller
        )


# ===========================================================================
# Internal helpers for result extraction
# ===========================================================================


def _extract_tool_calls(result: Any) -> list[ToolCallRecord]:
    """Extract tool call records from a PydanticAI RunResult.

    PydanticAI stores tool calls in the message history. We scan
    for ToolCallPart and ToolReturnPart messages to reconstruct records.
    """
    tool_calls: list[ToolCallRecord] = []

    # PydanticAI stores messages in result.all_messages() or result.new_messages()
    all_messages: list[Any] = []
    if hasattr(result, "all_messages"):
        try:
            all_messages = result.all_messages()
        except TypeError:
            all_messages = result.all_messages
    elif hasattr(result, "new_messages"):
        try:
            all_messages = result.new_messages()
        except TypeError:
            all_messages = result.new_messages

    # Track tool calls and their results
    pending_calls: dict[str, dict[str, Any]] = {}

    for msg in all_messages:
        # PydanticAI messages have 'parts' attribute
        parts = getattr(msg, "parts", None)
        if parts is None:
            continue

        for part in parts:
            part_kind = getattr(part, "part_kind", "")

            if part_kind == "tool-call":
                tool_call_id = getattr(part, "tool_call_id", "")
                tool_name = getattr(part, "tool_name", "")
                args = getattr(part, "args", None)
                if isinstance(args, str):
                    import json

                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {"raw": args}
                elif not isinstance(args, dict):
                    args = {}
                pending_calls[tool_call_id] = {
                    "tool_name": tool_name,
                    "args": args,
                }

            elif part_kind == "tool-return":
                tool_call_id = getattr(part, "tool_call_id", "")
                content = getattr(part, "content", None)
                call_info = pending_calls.pop(tool_call_id, None)
                if call_info:
                    tool_calls.append(
                        ToolCallRecord(
                            tool_name=call_info["tool_name"],
                            args=call_info["args"],
                            result=content,
                            duration_ms=0.0,
                        )
                    )

    # Any pending calls without results (shouldn't happen normally)
    for _call_id, call_info in pending_calls.items():
        tool_calls.append(
            ToolCallRecord(
                tool_name=call_info["tool_name"],
                args=call_info["args"],
                result=None,
                duration_ms=0.0,
            )
        )

    return tool_calls


def _extract_usage(result: Any) -> TokenUsage:
    """Extract token usage from a PydanticAI RunResult.

    PydanticAI exposes usage via result.usage() which returns a Usage object
    with request_tokens, response_tokens, total_tokens fields.
    """
    usage_obj = None
    if hasattr(result, "usage"):
        usage_fn = result.usage
        usage_obj = usage_fn() if callable(usage_fn) else usage_fn

    if usage_obj is not None:
        prompt_tokens = getattr(usage_obj, "request_tokens", 0) or 0
        completion_tokens = getattr(usage_obj, "response_tokens", 0) or 0
        total_tokens = getattr(usage_obj, "total_tokens", None)
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=None,
        )

    return TokenUsage(
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost_usd=None,
    )
