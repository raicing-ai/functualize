"""Property-based tests for AI lifecycle event emission.

Tests Property 17 from the Phase 2–5 Domain SDKs design document.

Property 17: AI lifecycle event emission — For any successful AI call,
ai.call.started is emitted first, followed by ai.call.completed. For failed
calls, ai.call.started followed by ai.call.failed. For runs with tool calls,
ai.tool.called events are emitted between started and completed.

**Validates: Requirements 8.1, 8.2, 8.3, 8.5**
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from functualize_ai import AI, AINotAvailableError, AIResult, TokenUsage, ToolDef
from functualize_ai._events import (
    AI_CALL_COMPLETED,
    AI_CALL_FAILED,
    AI_CALL_STARTED,
    AI_TOOL_CALLED,
)
from functualize_ai._types import AILimits, ToolCallRecord
from hypothesis import given, settings
from hypothesis import strategies as st

# ===========================================================================
# Strategies
# ===========================================================================

# Strategy for generating non-empty prompt strings
prompts_st = st.text(min_size=1, max_size=200)

# Strategy for model names
model_names_st = st.text(min_size=1, max_size=50)

# Strategy for tool names (identifiers)
tool_names_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

# Strategy for tool call durations (positive floats)
duration_ms_st = st.floats(
    min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False
)

# Strategy for token counts (positive integers)
token_count_st = st.integers(min_value=0, max_value=100000)

# Strategy for optional cost
cost_st = st.one_of(
    st.none(),
    st.floats(min_value=0.0001, max_value=100.0, allow_nan=False, allow_infinity=False),
)

# Strategy for generating a list of ToolCallRecords
tool_call_records_st = st.lists(
    st.builds(
        ToolCallRecord,
        tool_name=tool_names_st,
        args=st.fixed_dictionaries({}),
        result=st.just("ok"),
        duration_ms=duration_ms_st,
    ),
    min_size=0,
    max_size=5,
)

# Strategy for error messages
error_messages_st = st.text(min_size=1, max_size=200)

# Strategy for exception types the provider might raise
exception_types_st = st.sampled_from(
    [
        RuntimeError,
        IOError,
        OSError,
        ConnectionError,
        TimeoutError,
    ]
)

# Strategy for tool call args dicts
tool_args_st = st.fixed_dictionaries(
    {},
    optional={
        "key": st.text(min_size=1, max_size=20),
        "count": st.integers(min_value=0, max_value=100),
    },
)


# ===========================================================================
# Helpers
# ===========================================================================


class FakeEventBus:
    """Captures all emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_name: str, **payload: Any) -> None:
        self.events.append((event_name, payload))

    @property
    def event_names(self) -> list[str]:
        return [name for name, _ in self.events]

    def get_events(self, name: str) -> list[dict[str, Any]]:
        return [p for n, p in self.events if n == name]


class ConfigurableSuccessProvider:
    """Provider that returns configurable results for each method."""

    def __init__(
        self,
        complete_result: Any = "hello",
        run_result: AIResult | None = None,
        stream_chunks: list[str] | None = None,
    ) -> None:
        self._complete_result = complete_result
        self._run_result = run_result
        self._stream_chunks = stream_chunks or ["chunk"]

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
        if self._run_result is not None:
            return self._run_result
        return AIResult(
            output="output",
            tool_calls=[],
            usage=TokenUsage(10, 20, 30, cost_usd=0.001),
            duration_ms=100.0,
        )

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        return iter(self._stream_chunks)

    def extract(self, text: str, *, model: type) -> Any:
        return self._complete_result


class ConfigurableFailingProvider:
    """Provider that raises a specified exception type."""

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
# Property 17: AI lifecycle event emission — successful calls
# ===========================================================================


class TestAILifecycleSuccessfulCallProperty:
    """Property 17: For any successful AI call, ai.call.started is emitted first,
    followed by ai.call.completed.

    **Validates: Requirements 8.1, 8.2**
    """

    @given(prompt=prompts_st, model_name=model_names_st)
    @settings(max_examples=100)
    def test_complete_emits_started_then_completed(
        self, prompt: str, model_name: str
    ) -> None:
        """For any successful complete() call, started is emitted before completed.

        **Validates: Requirements 8.1, 8.2**
        """
        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(complete_result="response")
        ai = AI(_provider=provider, _event_bus=bus)

        ai.complete(prompt, model=model_name)

        # Exactly two events: started then completed
        assert len(bus.events) == 2
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_COMPLETED]

        # Started payload contains correct prompt_length and model
        started = bus.get_events(AI_CALL_STARTED)[0]
        assert started["prompt_length"] == len(prompt)
        assert started["model"] == model_name
        assert started["tools_count"] == 0

        # Completed payload contains duration_ms >= 0
        completed = bus.get_events(AI_CALL_COMPLETED)[0]
        assert completed["duration_ms"] >= 0
        assert completed["tool_calls_count"] == 0

    @given(
        prompt=prompts_st,
        model_name=model_names_st,
        prompt_tokens=token_count_st,
        completion_tokens=token_count_st,
        cost=cost_st,
    )
    @settings(max_examples=100)
    def test_run_emits_started_then_completed_with_usage(
        self,
        prompt: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float | None,
    ) -> None:
        """For any successful run() call, started is emitted first, then completed with TokenUsage.

        **Validates: Requirements 8.1, 8.2**
        """
        total_tokens = prompt_tokens + completion_tokens
        usage = TokenUsage(
            prompt_tokens, completion_tokens, total_tokens, cost_usd=cost
        )
        run_result = AIResult(
            output="result",
            tool_calls=[],
            usage=usage,
            duration_ms=50.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt, model=model_name)

        # Exactly two events: started then completed
        assert len(bus.events) == 2
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_COMPLETED]

        # Started has correct prompt_length
        started = bus.get_events(AI_CALL_STARTED)[0]
        assert started["prompt_length"] == len(prompt)
        assert started["model"] == model_name

        # Completed has token usage
        completed = bus.get_events(AI_CALL_COMPLETED)[0]
        assert completed["tokens"] == usage
        assert completed["duration_ms"] >= 0
        assert completed["tool_calls_count"] == 0

    @given(prompt=prompts_st)
    @settings(max_examples=100)
    def test_stream_emits_started_then_completed(self, prompt: str) -> None:
        """For any successful stream() call, started is emitted first, then completed.

        **Validates: Requirements 8.1, 8.2**
        """
        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(stream_chunks=["a", "b"])
        ai = AI(_provider=provider, _event_bus=bus)

        ai.stream(prompt)

        assert len(bus.events) == 2
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_COMPLETED]

        started = bus.get_events(AI_CALL_STARTED)[0]
        assert started["prompt_length"] == len(prompt)


# ===========================================================================
# Property 17: AI lifecycle event emission — failed calls
# ===========================================================================


class TestAILifecycleFailedCallProperty:
    """Property 17: For any failed AI call, ai.call.started is emitted first,
    followed by ai.call.failed.

    **Validates: Requirements 8.1, 8.3**
    """

    @given(
        prompt=prompts_st,
        model_name=model_names_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    @settings(max_examples=100)
    def test_complete_failure_emits_started_then_failed(
        self, prompt: str, model_name: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """For any failed complete() call, started is emitted before failed.

        **Validates: Requirements 8.1, 8.3**
        """
        bus = FakeEventBus()
        provider = ConfigurableFailingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider, _event_bus=bus)

        with contextlib.suppress(AINotAvailableError, ValueError):
            ai.complete(prompt, model=model_name)

        # Exactly two events: started then failed
        assert len(bus.events) == 2
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_FAILED]

        # Started has correct prompt_length and model
        started = bus.get_events(AI_CALL_STARTED)[0]
        assert started["prompt_length"] == len(prompt)
        assert started["model"] == model_name

        # Failed has error message and duration
        failed = bus.get_events(AI_CALL_FAILED)[0]
        assert "error" in failed
        assert failed["duration_ms"] >= 0

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    @settings(max_examples=100)
    def test_run_failure_emits_started_then_failed(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """For any failed run() call, started is emitted before failed.

        **Validates: Requirements 8.1, 8.3**
        """
        bus = FakeEventBus()
        provider = ConfigurableFailingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider, _event_bus=bus)

        with contextlib.suppress(AINotAvailableError, ValueError):
            ai.run(prompt)

        # Exactly two events: started then failed
        assert len(bus.events) == 2
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_FAILED]

        # Failed payload contains the error message
        failed = bus.get_events(AI_CALL_FAILED)[0]
        assert failed["duration_ms"] >= 0

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    @settings(max_examples=100)
    def test_stream_failure_emits_started_then_failed(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """For any failed stream() call, started is emitted before failed.

        **Validates: Requirements 8.1, 8.3**
        """
        bus = FakeEventBus()
        provider = ConfigurableFailingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider, _event_bus=bus)

        with contextlib.suppress(AINotAvailableError, ValueError):
            ai.stream(prompt)

        assert len(bus.events) == 2
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_FAILED]


# ===========================================================================
# Property 17: AI lifecycle event emission — tool calls between started/completed
# ===========================================================================


class TestAILifecycleToolCallProperty:
    """Property 17: For runs with tool calls, ai.tool.called events are emitted
    between started and completed.

    **Validates: Requirements 8.1, 8.2, 8.5**
    """

    @given(prompt=prompts_st, tool_calls=tool_call_records_st)
    @settings(max_examples=100)
    def test_run_with_tools_emits_tool_called_between_started_and_completed(
        self, prompt: str, tool_calls: list[ToolCallRecord]
    ) -> None:
        """For any run() with N tool calls, N ai.tool.called events are emitted
        between ai.call.started and ai.call.completed.

        **Validates: Requirements 8.1, 8.2, 8.5**
        """
        usage = TokenUsage(100, 200, 300, cost_usd=0.01)
        run_result = AIResult(
            output="done",
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=150.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt)

        # Expected event sequence: started, [tool_called x N], completed
        n = len(tool_calls)
        expected_total = 2 + n  # started + N tool_called + completed
        assert len(bus.events) == expected_total

        # First event is always started
        assert bus.event_names[0] == AI_CALL_STARTED

        # Last event is always completed
        assert bus.event_names[-1] == AI_CALL_COMPLETED

        # Middle events (if any) are all tool_called
        middle_events = bus.event_names[1:-1]
        assert all(e == AI_TOOL_CALLED for e in middle_events)
        assert len(middle_events) == n

        # Each tool_called event has correct payload
        tool_called_events = bus.get_events(AI_TOOL_CALLED)
        for i, tc_event in enumerate(tool_called_events):
            assert tc_event["tool_name"] == tool_calls[i].tool_name
            assert tc_event["args"] == tool_calls[i].args
            assert tc_event["duration_ms"] == tool_calls[i].duration_ms
            assert tc_event["status"] == "success"

    @given(
        prompt=prompts_st,
        num_tools=st.integers(min_value=1, max_value=5),
        tool_name=tool_names_st,
        tool_duration=duration_ms_st,
    )
    @settings(max_examples=100)
    def test_tool_called_count_matches_tool_calls_in_result(
        self, prompt: str, num_tools: int, tool_name: str, tool_duration: float
    ) -> None:
        """The number of ai.tool.called events equals the number of tool calls in AIResult.

        **Validates: Requirements 8.2, 8.5**
        """
        tool_calls = [
            ToolCallRecord(
                tool_name=f"{tool_name}_{i}",
                args={"idx": i},
                result="ok",
                duration_ms=tool_duration,
            )
            for i in range(num_tools)
        ]
        usage = TokenUsage(50, 100, 150, cost_usd=0.005)
        run_result = AIResult(
            output="result",
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=200.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt)

        tool_called_events = bus.get_events(AI_TOOL_CALLED)
        assert len(tool_called_events) == num_tools

        # Completed event reports correct tool_calls_count
        completed = bus.get_events(AI_CALL_COMPLETED)[0]
        assert completed["tool_calls_count"] == num_tools

    @given(prompt=prompts_st)
    @settings(max_examples=100)
    def test_run_no_tools_emits_zero_tool_called_events(self, prompt: str) -> None:
        """When run() has no tool calls, no ai.tool.called events are emitted.

        **Validates: Requirements 8.5**
        """
        run_result = AIResult(
            output="output",
            tool_calls=[],
            usage=TokenUsage(10, 20, 30, cost_usd=0.001),
            duration_ms=50.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt)

        tool_called_events = bus.get_events(AI_TOOL_CALLED)
        assert len(tool_called_events) == 0

        # Only started + completed
        assert bus.event_names == [AI_CALL_STARTED, AI_CALL_COMPLETED]


# ===========================================================================
# Property 17: ai.call.started payload type invariants
# ===========================================================================


class TestAICallStartedPayloadTypeInvariants:
    """Property 17: ai.call.started payload ALWAYS contains prompt_length (int),
    model (str), and tools_count (int).

    **Validates: Requirements 8.1**
    """

    @given(prompt=prompts_st, model_name=model_names_st)
    @settings(max_examples=100)
    def test_started_payload_prompt_length_is_int(
        self, prompt: str, model_name: str
    ) -> None:
        """For any AI call, ai.call.started.prompt_length is always an int equal to len(prompt).

        **Validates: Requirements 8.1**
        """
        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider()
        ai = AI(_provider=provider, _event_bus=bus)

        ai.complete(prompt, model=model_name)

        started = bus.get_events(AI_CALL_STARTED)[0]
        assert isinstance(started["prompt_length"], int)
        assert started["prompt_length"] == len(prompt)

    @given(prompt=prompts_st, model_name=model_names_st)
    @settings(max_examples=100)
    def test_started_payload_model_is_str(self, prompt: str, model_name: str) -> None:
        """For any AI call, ai.call.started.model is always a str.

        **Validates: Requirements 8.1**
        """
        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider()
        ai = AI(_provider=provider, _event_bus=bus)

        ai.complete(prompt, model=model_name)

        started = bus.get_events(AI_CALL_STARTED)[0]
        assert isinstance(started["model"], str)
        assert started["model"] == model_name

    @given(prompt=prompts_st, model_name=model_names_st)
    @settings(max_examples=100)
    def test_started_payload_tools_count_is_int(
        self, prompt: str, model_name: str
    ) -> None:
        """For any AI call, ai.call.started.tools_count is always a non-negative int.

        **Validates: Requirements 8.1**
        """
        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider()
        ai = AI(_provider=provider, _event_bus=bus)

        ai.complete(prompt, model=model_name)

        started = bus.get_events(AI_CALL_STARTED)[0]
        assert isinstance(started["tools_count"], int)
        assert started["tools_count"] >= 0


# ===========================================================================
# Property 17: ai.call.completed payload type invariants
# ===========================================================================


class TestAICallCompletedPayloadTypeInvariants:
    """Property 17: ai.call.completed payload ALWAYS contains tokens,
    duration_ms (>= 0), and tool_calls_count (>= 0).

    **Validates: Requirements 8.2**
    """

    @given(
        prompt=prompts_st,
        prompt_tokens=token_count_st,
        completion_tokens=token_count_st,
        cost=cost_st,
    )
    @settings(max_examples=100)
    def test_completed_payload_tokens_present(
        self,
        prompt: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float | None,
    ) -> None:
        """For any successful AI.run() call, ai.call.completed.tokens contains the TokenUsage.

        **Validates: Requirements 8.2**
        """
        total_tokens = prompt_tokens + completion_tokens
        usage = TokenUsage(
            prompt_tokens, completion_tokens, total_tokens, cost_usd=cost
        )
        run_result = AIResult(
            output="result",
            tool_calls=[],
            usage=usage,
            duration_ms=50.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt)

        completed = bus.get_events(AI_CALL_COMPLETED)[0]
        assert "tokens" in completed
        assert completed["tokens"] == usage

    @given(prompt=prompts_st)
    @settings(max_examples=100)
    def test_completed_payload_duration_ms_non_negative(self, prompt: str) -> None:
        """For any successful AI call, ai.call.completed.duration_ms is always >= 0.

        **Validates: Requirements 8.2**
        """
        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider()
        ai = AI(_provider=provider, _event_bus=bus)

        ai.complete(prompt)

        completed = bus.get_events(AI_CALL_COMPLETED)[0]
        assert "duration_ms" in completed
        assert isinstance(completed["duration_ms"], int | float)
        assert completed["duration_ms"] >= 0

    @given(prompt=prompts_st, tool_calls=tool_call_records_st)
    @settings(max_examples=100)
    def test_completed_payload_tool_calls_count_non_negative(
        self, prompt: str, tool_calls: list[ToolCallRecord]
    ) -> None:
        """For any successful AI.run() call, ai.call.completed.tool_calls_count >= 0.

        **Validates: Requirements 8.2**
        """
        usage = TokenUsage(10, 20, 30, cost_usd=0.001)
        run_result = AIResult(
            output="done",
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=100.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt)

        completed = bus.get_events(AI_CALL_COMPLETED)[0]
        assert "tool_calls_count" in completed
        assert isinstance(completed["tool_calls_count"], int)
        assert completed["tool_calls_count"] >= 0
        assert completed["tool_calls_count"] == len(tool_calls)


# ===========================================================================
# Property 17: ai.call.failed payload type invariants
# ===========================================================================


class TestAICallFailedPayloadTypeInvariants:
    """Property 17: ai.call.failed payload ALWAYS contains error (str)
    and duration_ms (>= 0).

    **Validates: Requirements 8.3**
    """

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    @settings(max_examples=100)
    def test_failed_payload_error_is_str(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """For any failed AI call, ai.call.failed.error is always a str.

        **Validates: Requirements 8.3**
        """
        bus = FakeEventBus()
        provider = ConfigurableFailingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider, _event_bus=bus)

        with contextlib.suppress(AINotAvailableError, ValueError):
            ai.complete(prompt)

        failed = bus.get_events(AI_CALL_FAILED)[0]
        assert "error" in failed
        assert isinstance(failed["error"], str)
        assert len(failed["error"]) > 0

    @given(
        prompt=prompts_st,
        exc_type=exception_types_st,
        error_msg=error_messages_st,
    )
    @settings(max_examples=100)
    def test_failed_payload_duration_ms_non_negative(
        self, prompt: str, exc_type: type[Exception], error_msg: str
    ) -> None:
        """For any failed AI call, ai.call.failed.duration_ms is always >= 0.

        **Validates: Requirements 8.3**
        """
        bus = FakeEventBus()
        provider = ConfigurableFailingProvider(exc_type=exc_type, message=error_msg)
        ai = AI(_provider=provider, _event_bus=bus)

        with contextlib.suppress(AINotAvailableError, ValueError):
            ai.run(prompt)

        failed = bus.get_events(AI_CALL_FAILED)[0]
        assert "duration_ms" in failed
        assert isinstance(failed["duration_ms"], int | float)
        assert failed["duration_ms"] >= 0


# ===========================================================================
# Property 17: ai.tool.called payload invariants
# ===========================================================================


class TestAIToolCalledPayloadInvariants:
    """Property 17: For each tool call in AIResult.tool_calls, ai.tool.called
    is emitted with tool_name, args, duration_ms, and status.

    **Validates: Requirements 8.5**
    """

    @given(
        prompt=prompts_st,
        tool_calls=st.lists(
            st.builds(
                ToolCallRecord,
                tool_name=tool_names_st,
                args=tool_args_st,
                result=st.just("ok"),
                duration_ms=duration_ms_st,
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    def test_tool_called_payload_contains_required_fields(
        self, prompt: str, tool_calls: list[ToolCallRecord]
    ) -> None:
        """For each tool call, the emitted event has tool_name (str), args (dict),
        duration_ms (float >= 0), and status (str).

        **Validates: Requirements 8.5**
        """
        usage = TokenUsage(50, 100, 150, cost_usd=0.005)
        run_result = AIResult(
            output="done",
            tool_calls=tool_calls,
            usage=usage,
            duration_ms=200.0,
        )

        bus = FakeEventBus()
        provider = ConfigurableSuccessProvider(run_result=run_result)
        ai = AI(_provider=provider, _event_bus=bus)

        ai.run(prompt)

        tool_called_events = bus.get_events(AI_TOOL_CALLED)
        assert len(tool_called_events) == len(tool_calls)

        for i, event in enumerate(tool_called_events):
            # tool_name is a str matching the ToolCallRecord
            assert "tool_name" in event
            assert isinstance(event["tool_name"], str)
            assert event["tool_name"] == tool_calls[i].tool_name

            # args is a dict matching the ToolCallRecord
            assert "args" in event
            assert isinstance(event["args"], dict)
            assert event["args"] == tool_calls[i].args

            # duration_ms is a numeric value >= 0
            assert "duration_ms" in event
            assert isinstance(event["duration_ms"], int | float)
            assert event["duration_ms"] >= 0

            # status is a str
            assert "status" in event
            assert isinstance(event["status"], str)
