"""Property-based tests for instrumentation point fault tolerance (Property 20).

Tests that the underlying operation executes and returns/raises correctly
even if event emission or middleware raises during instrumentation.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._events.bus import EventBus
from functualize._events.instrumentation import instrument_point
from functualize._events.middleware_stack import MiddlewareStack

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for operation return values
return_values_st = st.one_of(
    st.integers(),
    st.text(min_size=0, max_size=50),
    st.lists(st.integers(), max_size=5),
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False),
)

# Strategy for error messages used by failing instrumentation
error_messages_st = st.text(min_size=1, max_size=50)

# Strategy for operation point names (valid event name format: at least 3 dot-separated segments)
operation_point_st = st.sampled_from(
    [
        "job.execute.run",
        "config.file.parse",
        "plugin.load.init",
        "cli.parse.args",
        "tui.session.start",
    ]
)


class TestProperty20InstrumentationPointFaultTolerance:
    """Property 20: Instrumentation point fault tolerance.

    *For any* operation wrapped by `instrument_point`, the operation's return
    value SHALL be preserved even if a subscriber raises during event emission,
    the operation's exception SHALL be re-raised even if a subscriber raises
    during the error event emission, and the operation's result SHALL be
    returned even if middleware raises during post-yield processing.

    **Validates: Requirements 6.5**
    """

    @given(
        return_value=return_values_st,
        operation_point=operation_point_st,
        subscriber_error_msg=error_messages_st,
    )
    def test_operation_result_preserved_when_subscriber_raises(
        self,
        return_value: Any,
        operation_point: str,
        subscriber_error_msg: str,
    ) -> None:
        """Operation succeeds, subscriber raises → instrument_point still returns result."""
        event_bus = EventBus()
        middleware_stack = MiddlewareStack()

        # Subscribe a callback that always raises
        def failing_subscriber(event: Any) -> None:
            raise RuntimeError(subscriber_error_msg)

        event_bus.subscribe("*", failing_subscriber)

        # Operation that returns a known value
        def operation() -> Any:
            return return_value

        # instrument_point should still return the operation's result
        result = instrument_point(
            event_bus,
            middleware_stack,
            operation_point,
            operation,
            resource="test-resource",
        )

        assert result == return_value

    @given(
        operation_point=operation_point_st,
        operation_error_msg=error_messages_st,
        subscriber_error_msg=error_messages_st,
    )
    def test_operation_exception_preserved_when_subscriber_raises(
        self,
        operation_point: str,
        operation_error_msg: str,
        subscriber_error_msg: str,
    ) -> None:
        """Operation raises, subscriber raises during error event → original exception propagated."""
        event_bus = EventBus()
        middleware_stack = MiddlewareStack()

        # Subscribe a callback that always raises
        def failing_subscriber(event: Any) -> None:
            raise RuntimeError(subscriber_error_msg)

        event_bus.subscribe("*", failing_subscriber)

        class OperationError(Exception):
            pass

        # Operation that raises
        def failing_operation() -> Any:
            raise OperationError(operation_error_msg)

        # instrument_point should re-raise the operation's original exception
        raised = False
        try:
            instrument_point(
                event_bus,
                middleware_stack,
                operation_point,
                failing_operation,
                resource="test-resource",
            )
        except OperationError as exc:
            raised = True
            assert str(exc) == operation_error_msg

        assert raised, "Expected OperationError to be re-raised"

    @given(
        return_value=return_values_st,
        operation_point=operation_point_st,
        middleware_error_msg=error_messages_st,
    )
    def test_operation_result_preserved_when_middleware_raises_post_yield(
        self,
        return_value: Any,
        operation_point: str,
        middleware_error_msg: str,
    ) -> None:
        """Operation succeeds, middleware raises during post-yield → result still returned."""
        event_bus = EventBus()
        middleware_stack = MiddlewareStack()

        # Middleware that raises after the yield (post-yield phase)
        def failing_post_yield_middleware(
            ctx: dict[str, Any],
        ) -> Generator[Any, Any]:
            yield
            raise RuntimeError(middleware_error_msg)

        middleware_stack.register(operation_point, failing_post_yield_middleware)

        # Operation that returns a known value
        def operation() -> Any:
            return return_value

        # instrument_point should still return the operation's result
        result = instrument_point(
            event_bus,
            middleware_stack,
            operation_point,
            operation,
            resource="test-resource",
        )

        assert result == return_value
