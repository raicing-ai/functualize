"""Unit tests for AI event emission.

Validates Requirements 8.1, 8.2, 8.3, 8.4, 8.5 — structured event emission
for ai.call.started, ai.call.completed, ai.call.failed, ai.budget.exceeded,
and ai.tool.called.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from functualize_ai import (
    AI,
    AINotAvailableError,
    AIResult,
    BudgetExceededError,
    TokenUsage,
    ToolDef,
)
from functualize_ai._budget import BUDGET_SPENT_KEY
from functualize_ai._events import (
    AI_BUDGET_EXCEEDED,
    AI_CALL_COMPLETED,
    AI_CALL_FAILED,
    AI_CALL_STARTED,
    AI_TOOL_CALLED,
)
from functualize_ai._tool_scope import ToolScope
from functualize_ai._types import AILimits, ToolCallRecord

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeEventBus:
    """Captures all emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_name: str, **payload: Any) -> None:
        self.events.append((event_name, payload))

    def get_events(self, name: str) -> list[dict[str, Any]]:
        """Return payloads for events matching the given name."""
        return [p for n, p in self.events if n == name]


class FakeStateNamespace:
    """Minimal state namespace for testing budget persistence."""

    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._data[key] = value


class SuccessProvider:
    """Provider that returns canned successes."""

    def __init__(
        self,
        complete_result: Any = "hello",
        run_result: AIResult | None = None,
        stream_chunks: list[str] | None = None,
        extract_result: Any = None,
    ) -> None:
        self._complete_result = complete_result
        self._run_result = run_result or AIResult(
            output="output",
            tool_calls=[],
            usage=TokenUsage(10, 20, 30, cost_usd=0.001),
            duration_ms=100.0,
        )
        self._stream_chunks = stream_chunks or ["chunk1", "chunk2"]
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


class FailingProvider:
    """Provider that always raises a RuntimeError."""

    def __init__(self, error_msg: str = "provider error") -> None:
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


@dataclass
class SampleModel:
    """Simple model for structured output testing."""

    name: str
    value: int = 0


# ---------------------------------------------------------------------------
# Tests: ai.call.started event (Requirement 8.1)
# ---------------------------------------------------------------------------


class TestAICallStartedEvent:
    """Requirement 8.1: ai.call.started emitted with prompt_length, model, tools_count."""

    def test_complete_emits_started_event(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.complete("hello world")

        started = bus.get_events(AI_CALL_STARTED)
        assert len(started) == 1
        assert started[0]["prompt_length"] == len("hello world")
        assert started[0]["model"] == "unknown"
        assert started[0]["tools_count"] == 0

    def test_complete_emits_started_with_model_from_kwargs(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.complete("hello", model="gpt-4o")

        started = bus.get_events(AI_CALL_STARTED)
        assert started[0]["model"] == "gpt-4o"

    def test_run_emits_started_with_tools_count(self) -> None:
        """tools_count reflects the number of resolved ToolDefs from the scope."""

        # Create a fake registry that returns 3 matching descriptors
        class FakeDescriptor:
            def __init__(self, name: str):
                self.name = name
                self.docstring = f"desc for {name}"
                self.group = ""
                self.metadata = {}
                self.config_fields = []

        class FakeRegistry:
            def get_descriptors(self):
                return [
                    FakeDescriptor("job_a"),
                    FakeDescriptor("job_b"),
                    FakeDescriptor("job_c"),
                ]

        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        scope = ToolScope.only(["job_a", "job_b", "job_c"])
        ai.run("do something", tools=scope, job_registry=FakeRegistry())

        started = bus.get_events(AI_CALL_STARTED)
        assert len(started) == 1
        assert started[0]["prompt_length"] == len("do something")
        assert started[0]["tools_count"] == 3

    def test_stream_emits_started_event(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.stream("prompt text")

        started = bus.get_events(AI_CALL_STARTED)
        assert len(started) == 1
        assert started[0]["prompt_length"] == len("prompt text")
        assert started[0]["tools_count"] == 0

    def test_extract_emits_started_event(self) -> None:
        bus = FakeEventBus()
        ai = AI(
            _provider=SuccessProvider(extract_result=SampleModel(name="x")),
            _event_bus=bus,
        )
        ai.extract("some long text to extract from", model=SampleModel)

        started = bus.get_events(AI_CALL_STARTED)
        assert len(started) == 1
        assert started[0]["prompt_length"] == len("some long text to extract from")


# ---------------------------------------------------------------------------
# Tests: ai.call.completed event (Requirement 8.2)
# ---------------------------------------------------------------------------


class TestAICallCompletedEvent:
    """Requirement 8.2: ai.call.completed with tokens, duration_ms, tool_calls_count."""

    def test_complete_emits_completed_event(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.complete("hello")

        completed = bus.get_events(AI_CALL_COMPLETED)
        assert len(completed) == 1
        assert "duration_ms" in completed[0]
        assert completed[0]["duration_ms"] >= 0
        assert completed[0]["tool_calls_count"] == 0

    def test_run_emits_completed_with_token_usage(self) -> None:
        usage = TokenUsage(100, 200, 300, cost_usd=0.05)
        result = AIResult(
            output="result",
            tool_calls=[
                ToolCallRecord(tool_name="t1", args={}, result="ok", duration_ms=10),
                ToolCallRecord(
                    tool_name="t2", args={"x": 1}, result="ok", duration_ms=20
                ),
            ],
            usage=usage,
            duration_ms=150.0,
        )
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(run_result=result), _event_bus=bus)
        ai.run("prompt")

        completed = bus.get_events(AI_CALL_COMPLETED)
        assert len(completed) == 1
        assert completed[0]["tokens"] == usage
        assert completed[0]["tool_calls_count"] == 2
        assert completed[0]["duration_ms"] >= 0

    def test_stream_emits_completed_event(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.stream("prompt")

        completed = bus.get_events(AI_CALL_COMPLETED)
        assert len(completed) == 1
        assert completed[0]["tool_calls_count"] == 0

    def test_extract_emits_completed_event(self) -> None:
        bus = FakeEventBus()
        ai = AI(
            _provider=SuccessProvider(extract_result=SampleModel(name="x")),
            _event_bus=bus,
        )
        ai.extract("text", model=SampleModel)

        completed = bus.get_events(AI_CALL_COMPLETED)
        assert len(completed) == 1
        assert completed[0]["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Tests: ai.call.failed event (Requirement 8.3)
# ---------------------------------------------------------------------------


class TestAICallFailedEvent:
    """Requirement 8.3: ai.call.failed with error, duration_ms."""

    def test_complete_emits_failed_on_provider_error(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=FailingProvider("connection reset"), _event_bus=bus)

        with pytest.raises(AINotAvailableError):
            ai.complete("hello")

        failed = bus.get_events(AI_CALL_FAILED)
        assert len(failed) == 1
        assert "connection reset" in failed[0]["error"]
        assert failed[0]["duration_ms"] >= 0

    def test_run_emits_failed_on_provider_error(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=FailingProvider("timeout"), _event_bus=bus)

        with pytest.raises(AINotAvailableError):
            ai.run("hello")

        failed = bus.get_events(AI_CALL_FAILED)
        assert len(failed) == 1
        assert "timeout" in failed[0]["error"]
        assert failed[0]["duration_ms"] >= 0

    def test_stream_emits_failed_on_provider_error(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=FailingProvider("stream error"), _event_bus=bus)

        with pytest.raises(AINotAvailableError):
            ai.stream("hello")

        failed = bus.get_events(AI_CALL_FAILED)
        assert len(failed) == 1
        assert "stream error" in failed[0]["error"]

    def test_extract_emits_failed_on_provider_error(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=FailingProvider("API error"), _event_bus=bus)

        with pytest.raises(AINotAvailableError):
            ai.extract("text", model=SampleModel)

        failed = bus.get_events(AI_CALL_FAILED)
        assert len(failed) == 1
        assert "API error" in failed[0]["error"]

    def test_complete_emits_failed_after_validation_exhaustion(self) -> None:
        """When all retries are exhausted, ai.call.failed is emitted."""

        class AlwaysInvalidProvider:
            def complete(self, prompt, *, response_model=None, **kwargs):
                raise ValueError("validation failed")

            def run(self, prompt, **kwargs):
                pass

            def stream(self, prompt, **kwargs):
                return iter([])

            def extract(self, text, *, model):
                pass

        bus = FakeEventBus()
        ai = AI(_provider=AlwaysInvalidProvider(), _event_bus=bus)

        with pytest.raises(ValueError, match="Schema validation failed"):
            ai.complete("hello", response_model=SampleModel)

        failed = bus.get_events(AI_CALL_FAILED)
        assert len(failed) == 1
        assert "validation failed" in failed[0]["error"]


# ---------------------------------------------------------------------------
# Tests: ai.budget.exceeded event (Requirement 8.4)
# ---------------------------------------------------------------------------


class TestAIBudgetExceededEvent:
    """Requirement 8.4: ai.budget.exceeded with limit, actual, job_name."""

    def test_run_emits_budget_exceeded_event(self) -> None:
        bus = FakeEventBus()
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 10.0)

        ai = AI(_provider=SuccessProvider(), _event_bus=bus, _state_ns=state)
        limits = AILimits(budget_usd=5.0)

        with pytest.raises(BudgetExceededError):
            ai.run("prompt", limits=limits, job_name="my_job")

        exceeded = bus.get_events(AI_BUDGET_EXCEEDED)
        assert len(exceeded) == 1
        assert exceeded[0]["limit"] == 5.0
        assert exceeded[0]["actual"] == 10.0
        assert exceeded[0]["job_name"] == "my_job"

    def test_run_no_budget_exceeded_when_under_limit(self) -> None:
        bus = FakeEventBus()
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 1.0)

        ai = AI(_provider=SuccessProvider(), _event_bus=bus, _state_ns=state)
        limits = AILimits(budget_usd=10.0)

        ai.run("prompt", limits=limits)

        exceeded = bus.get_events(AI_BUDGET_EXCEEDED)
        assert len(exceeded) == 0

    def test_budget_exceeded_defaults_empty_job_name(self) -> None:
        bus = FakeEventBus()
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 5.0)

        ai = AI(_provider=SuccessProvider(), _event_bus=bus, _state_ns=state)
        limits = AILimits(budget_usd=3.0)

        with pytest.raises(BudgetExceededError):
            ai.run("prompt", limits=limits)

        exceeded = bus.get_events(AI_BUDGET_EXCEEDED)
        assert exceeded[0]["job_name"] == ""


# ---------------------------------------------------------------------------
# Tests: ai.tool.called event (Requirement 8.5)
# ---------------------------------------------------------------------------


class TestAIToolCalledEvent:
    """Requirement 8.5: ai.tool.called with tool_name, args, duration_ms, status."""

    def test_run_emits_tool_called_for_each_tool_call(self) -> None:
        tool_calls = [
            ToolCallRecord(
                tool_name="search",
                args={"query": "test"},
                result="found",
                duration_ms=50.0,
            ),
            ToolCallRecord(
                tool_name="fetch",
                args={"url": "http://x"},
                result="data",
                duration_ms=75.0,
            ),
        ]
        result = AIResult(
            output="done",
            tool_calls=tool_calls,
            usage=TokenUsage(100, 200, 300, cost_usd=0.01),
            duration_ms=200.0,
        )
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(run_result=result), _event_bus=bus)
        ai.run("use tools")

        called = bus.get_events(AI_TOOL_CALLED)
        assert len(called) == 2

        assert called[0]["tool_name"] == "search"
        assert called[0]["args"] == {"query": "test"}
        assert called[0]["duration_ms"] == 50.0
        assert called[0]["status"] == "success"

        assert called[1]["tool_name"] == "fetch"
        assert called[1]["args"] == {"url": "http://x"}
        assert called[1]["duration_ms"] == 75.0
        assert called[1]["status"] == "success"

    def test_run_no_tool_called_events_when_no_tools_used(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.run("simple prompt")

        called = bus.get_events(AI_TOOL_CALLED)
        assert len(called) == 0


# ---------------------------------------------------------------------------
# Tests: No event bus configured (silent discard)
# ---------------------------------------------------------------------------


class TestNoEventBus:
    """When no event bus is configured, methods work without error."""

    def test_complete_works_without_event_bus(self) -> None:
        ai = AI(_provider=SuccessProvider())
        result = ai.complete("hello")
        assert result == "hello"

    def test_run_works_without_event_bus(self) -> None:
        ai = AI(_provider=SuccessProvider())
        result = ai.run("hello")
        assert result.output == "output"

    def test_stream_works_without_event_bus(self) -> None:
        ai = AI(_provider=SuccessProvider())
        chunks = list(ai.stream("hello"))
        assert chunks == ["chunk1", "chunk2"]

    def test_extract_works_without_event_bus(self) -> None:
        ai = AI(_provider=SuccessProvider(extract_result=SampleModel(name="x")))
        result = ai.extract("text", model=SampleModel)
        assert result.name == "x"


# ---------------------------------------------------------------------------
# Tests: Event ordering
# ---------------------------------------------------------------------------


class TestEventOrdering:
    """Events are emitted in correct order: started → completed/failed."""

    def test_complete_success_order(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(), _event_bus=bus)
        ai.complete("hello")

        event_names = [name for name, _ in bus.events]
        assert event_names == [AI_CALL_STARTED, AI_CALL_COMPLETED]

    def test_complete_failure_order(self) -> None:
        bus = FakeEventBus()
        ai = AI(_provider=FailingProvider(), _event_bus=bus)

        with pytest.raises(AINotAvailableError):
            ai.complete("hello")

        event_names = [name for name, _ in bus.events]
        assert event_names == [AI_CALL_STARTED, AI_CALL_FAILED]

    def test_run_with_tools_order(self) -> None:
        tool_calls = [
            ToolCallRecord(tool_name="t1", args={}, result="r", duration_ms=10),
        ]
        result = AIResult(
            output="done",
            tool_calls=tool_calls,
            usage=TokenUsage(10, 20, 30, cost_usd=0.001),
            duration_ms=50.0,
        )
        bus = FakeEventBus()
        ai = AI(_provider=SuccessProvider(run_result=result), _event_bus=bus)
        ai.run("prompt")

        event_names = [name for name, _ in bus.events]
        assert event_names == [AI_CALL_STARTED, AI_TOOL_CALLED, AI_CALL_COMPLETED]

    def test_budget_exceeded_does_not_emit_started(self) -> None:
        """Budget check happens BEFORE the call, so started is not emitted."""
        bus = FakeEventBus()
        state = FakeStateNamespace()
        state.set(BUDGET_SPENT_KEY, 10.0)

        ai = AI(_provider=SuccessProvider(), _event_bus=bus, _state_ns=state)
        limits = AILimits(budget_usd=5.0)

        with pytest.raises(BudgetExceededError):
            ai.run("prompt", limits=limits)

        event_names = [name for name, _ in bus.events]
        # Budget exceeded is emitted, but NOT ai.call.started
        assert AI_BUDGET_EXCEEDED in event_names
        assert AI_CALL_STARTED not in event_names
