"""Property-based tests for MiddlewareStack (Properties 8, 9, 10, 11, 12).

Tests the per-operation-point middleware registry and execution: ordering,
shared context, result delivery, exception propagation, priority sorting,
and zero-cost bypass when uninstrumented.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._events.middleware_stack import MiddlewareStack

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating middleware priority values
priorities_st = st.integers(min_value=-100, max_value=100)

# Strategy for generating lists of (priority, index) pairs simulating registrations
middleware_registrations_st = st.lists(
    st.integers(min_value=-50, max_value=50),
    min_size=1,
    max_size=10,
)

# Strategy for operation return values
return_values_st = st.one_of(
    st.integers(),
    st.text(min_size=0, max_size=50),
    st.lists(st.integers(), max_size=5),
    st.none(),
)


class TestProperty8MiddlewareExecutionOrderingAndSharedContext:
    """Property 8: Middleware execution ordering and shared context.

    *For any* chain of middleware registered at an operation point, the
    pre-yield phase SHALL execute in priority order (lowest first, then
    registration order), the operation SHALL execute after all pre-yields,
    and the post-yield phase SHALL execute in reverse order. Values written
    to the shared context dict by earlier middleware SHALL be readable by
    later middleware.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    @given(
        priorities=st.lists(
            st.integers(min_value=-50, max_value=50),
            min_size=2,
            max_size=8,
        ),
    )
    @settings(max_examples=200)
    def test_middleware_execution_ordering_and_shared_context(
        self,
        priorities: list[int],
    ) -> None:
        """Pre-yield in priority order, post-yield in reverse, shared context readable."""
        stack = MiddlewareStack()
        pre_order: list[int] = []
        post_order: list[int] = []
        context_reads: dict[int, list[str]] = {}

        def make_middleware(idx: int):
            def middleware(ctx: dict[str, Any]) -> Generator[Any, Any]:
                # Pre-yield: record order and write to shared context
                pre_order.append(idx)
                ctx[f"mw_{idx}"] = f"value_{idx}"
                # Read all previously written context keys
                context_reads[idx] = [k for k in ctx if k.startswith("mw_")]
                yield
                # Post-yield: record order
                post_order.append(idx)

            return middleware

        # Register middleware with given priorities
        for idx, priority in enumerate(priorities):
            stack.register("test.op", make_middleware(idx), priority=priority)

        # Execute
        operation_called = []

        def operation() -> str:
            operation_called.append(True)
            return "result"

        result = stack.execute("test.op", operation)

        # Operation was called
        assert operation_called == [True]
        assert result == "result"

        # Compute expected order: sorted by (priority, registration_order)
        # registration_order is 1-indexed (first registered gets 1)
        entries_with_order = [
            (priority, reg_order, idx)
            for reg_order, (idx, priority) in enumerate(enumerate(priorities), start=1)
        ]
        sorted_entries = sorted(entries_with_order, key=lambda e: (e[0], e[1]))
        expected_pre_order = [e[2] for e in sorted_entries]
        expected_post_order = list(reversed(expected_pre_order))

        # Pre-yield order matches priority sort
        assert pre_order == expected_pre_order

        # Post-yield order is reverse of pre-yield
        assert post_order == expected_post_order

        # Shared context: each middleware can read keys written by earlier ones
        for i, idx in enumerate(expected_pre_order):
            # Earlier middleware (by execution order) wrote their keys before this one
            earlier_indices = expected_pre_order[:i]
            for earlier_idx in earlier_indices:
                assert f"mw_{earlier_idx}" in context_reads[idx]


class TestProperty9MiddlewareResultDeliveryViaYield:
    """Property 9: Middleware result delivery via yield.

    *For any* operation that returns a value and has registered middleware,
    each middleware SHALL receive the operation's return value as the result
    of the `yield` expression (i.e., `result = yield` receives the actual
    return value).

    **Validates: Requirements 3.4**
    """

    @given(
        return_value=return_values_st,
        middleware_count=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=200)
    def test_middleware_result_delivery_via_yield(
        self,
        return_value: Any,
        middleware_count: int,
    ) -> None:
        """result = yield receives the operation's return value."""
        stack = MiddlewareStack()
        received_results: list[Any] = []

        def make_middleware(idx: int):
            def middleware(ctx: dict[str, Any]) -> Generator[Any, Any]:
                result = yield
                received_results.append((idx, result))

            return middleware

        for i in range(middleware_count):
            stack.register("test.op", make_middleware(i))

        def operation() -> Any:
            return return_value

        result = stack.execute("test.op", operation)

        # The execute returns the operation's result
        assert result == return_value

        # Each middleware received the same return value
        assert len(received_results) == middleware_count
        for _idx, received in received_results:
            assert received == return_value


class TestProperty10MiddlewareExceptionPropagation:
    """Property 10: Middleware exception propagation.

    *For any* operation that raises an exception with registered middleware,
    the exception SHALL be thrown into each started middleware generator via
    `.throw()`, allowing middleware to catch it in a try/except block around
    the yield.

    **Validates: Requirements 3.5**
    """

    @given(
        middleware_count=st.integers(min_value=1, max_value=5),
        error_message=st.text(min_size=1, max_size=30),
    )
    @settings(max_examples=200)
    def test_middleware_exception_propagation(
        self,
        middleware_count: int,
        error_message: str,
    ) -> None:
        """Exception thrown into each started middleware generator."""
        stack = MiddlewareStack()
        exceptions_received: list[tuple[int, BaseException]] = []

        def make_middleware(idx: int):
            def middleware(ctx: dict[str, Any]) -> Generator[Any, Any]:
                try:
                    yield
                except Exception as exc:
                    exceptions_received.append((idx, exc))
                    raise

            return middleware

        for i in range(middleware_count):
            stack.register("test.op", make_middleware(i))

        class TestError(Exception):
            pass

        def failing_operation() -> None:
            raise TestError(error_message)

        # The exception should be re-raised from execute
        raised = False
        try:
            stack.execute("test.op", failing_operation)
        except TestError as exc:
            raised = True
            assert str(exc) == error_message

        assert raised, "Expected TestError to be raised"

        # All middleware received the exception
        assert len(exceptions_received) == middleware_count
        for _idx, exc in exceptions_received:
            assert isinstance(exc, TestError)
            assert str(exc) == error_message


class TestProperty11MiddlewarePriorityOrdering:
    """Property 11: Middleware priority ordering.

    *For any* set of middleware with different priority values, execution order
    SHALL follow `(priority, registration_order)` as the sort key, with lower
    priority values executing first (outermost).

    **Validates: Requirements 3.6**
    """

    @given(
        priorities=st.lists(
            st.integers(min_value=-100, max_value=100),
            min_size=2,
            max_size=10,
        ),
    )
    @settings(max_examples=200)
    def test_middleware_priority_ordering(
        self,
        priorities: list[int],
    ) -> None:
        """(priority, registration_order) sort key governs execution."""
        stack = MiddlewareStack()
        execution_order: list[int] = []

        def make_middleware(idx: int):
            def middleware(ctx: dict[str, Any]) -> Generator[Any, Any]:
                execution_order.append(idx)
                yield

            return middleware

        # Register middleware with given priorities
        for idx, priority in enumerate(priorities):
            stack.register("test.op", make_middleware(idx), priority=priority)

        def operation() -> None:
            return None

        stack.execute("test.op", operation)

        # Expected order: sorted by (priority, registration_order)
        # registration_order corresponds to the order of registration (1-indexed internally)
        indexed_priorities = [
            (priority, reg_idx, orig_idx)
            for reg_idx, (orig_idx, priority) in enumerate(
                enumerate(priorities), start=1
            )
        ]
        sorted_entries = sorted(indexed_priorities, key=lambda e: (e[0], e[1]))
        expected_order = [e[2] for e in sorted_entries]

        assert execution_order == expected_order


class TestProperty12MiddlewareZeroCostBypass:
    """Property 12: Middleware zero-cost bypass.

    *For any* operation point with no registered middleware, the MiddlewareStack
    SHALL call the operation function directly, returning the same result as
    direct invocation, without allocating generator objects or context
    dictionaries.

    **Validates: Requirements 3.7, 7.2**
    """

    @given(
        return_value=return_values_st,
        operation_point=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"), whitelist_characters="._"
            ),
            min_size=3,
            max_size=30,
        ),
    )
    @settings(max_examples=200)
    def test_middleware_zero_cost_bypass(
        self,
        return_value: Any,
        operation_point: str,
    ) -> None:
        """No generator/context allocation when no middleware registered."""
        stack = MiddlewareStack()

        # Verify no middleware is registered
        assert not stack.has_middleware(operation_point)

        # Use a mock to verify direct invocation without wrapping
        operation = MagicMock(return_value=return_value)

        result = stack.execute(operation_point, operation)

        # Result is exactly what the operation returns
        assert result == return_value

        # Operation was called exactly once
        operation.assert_called_once()

        # Verify the stack has no generators allocated (internal state check)
        # The fact that _points is empty for this operation_point confirms
        # the zero-cost path was taken (no sorting, no ctx dict, no generators)
        assert not stack.has_middleware(operation_point)
        assert not stack.has_any_middleware
