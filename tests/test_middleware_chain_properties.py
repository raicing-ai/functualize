"""Property-based tests for MiddlewareChain (Property 1).

Tests the core middleware executor from functualize.primitives.middleware:
- Property 1: Middleware priority ordering and exception propagation

For any set of middleware functions with distinct integer priorities registered
on a MiddlewareChain, when execute() is called, the pre-phase of each middleware
SHALL execute in ascending priority order (lower value first), and exceptions
SHALL propagate through generators in reverse registration order via
generator.throw().

# Feature: unified-architecture-redesign, Property 1
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._primitives.middleware import MiddlewareChain

# =============================================================================
# Strategies
# =============================================================================


@st.composite
def _distinct_priorities(draw: st.DrawFn) -> list[int]:
    """Generate a list of distinct integer priorities in range [0, 999]."""
    count = draw(st.integers(min_value=1, max_value=15))
    priorities = draw(
        st.lists(
            st.integers(min_value=0, max_value=999),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    return priorities


# =============================================================================
# Property 1: Middleware priority ordering and exception propagation
# =============================================================================


class TestMiddlewarePriorityOrderingAndExceptionPropagation:
    """Property 1: Middleware priority ordering and exception propagation.

    For any set of middleware functions with distinct integer priorities
    registered on a MiddlewareChain, when execute() is called, the pre-phase
    of each middleware SHALL execute in ascending priority order (lower value
    first), and exceptions SHALL propagate through generators in reverse
    registration order via generator.throw().

    **Validates: Requirements 1.2, 1.3**
    """

    @given(priorities=_distinct_priorities())
    @settings(max_examples=200)
    def test_pre_phase_executes_in_ascending_priority_order(
        self, priorities: list[int]
    ):
        """Pre-phase of middleware executes in ascending priority order.

        For any set of distinct priorities, after execute(), the recorded
        pre-phase order must equal the sorted priorities (ascending).

        **Validates: Requirements 1.2, 1.3**
        """
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        pre_order: list[int] = []

        def make_mw(priority: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                pre_order.append(priority)
                yield

            return mw

        # Register in arbitrary order (the order priorities are generated)
        for p in priorities:
            chain.add(make_mw(p), priority=p)

        chain.execute({}, lambda: "result")

        # Pre-phase must be in ascending priority order
        assert pre_order == sorted(priorities)

    @given(priorities=_distinct_priorities())
    @settings(max_examples=200)
    def test_post_phase_executes_in_reverse_priority_order(self, priorities: list[int]):
        """Post-phase of middleware executes in reverse priority order.

        Since generators are resumed in reverse order, middleware with
        the highest priority value (last in pre-phase) gets resumed first
        in the post-phase.

        **Validates: Requirements 1.2, 1.3**
        """
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        post_order: list[int] = []

        def make_mw(priority: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                yield
                post_order.append(priority)

            return mw

        for p in priorities:
            chain.add(make_mw(p), priority=p)

        chain.execute({}, lambda: "result")

        # Post-phase is reverse of sorted ascending
        assert post_order == sorted(priorities, reverse=True)

    @given(priorities=_distinct_priorities())
    @settings(max_examples=200)
    def test_exception_propagates_through_generators_in_reverse_order(
        self, priorities: list[int]
    ):
        """Exceptions propagate via generator.throw() in reverse registration order.

        When the operation raises, each started generator receives the exception
        via throw() in reverse order (highest priority value first, since
        post-phase/throw order is reversed).

        **Validates: Requirements 1.2, 1.3**
        """
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        throw_order: list[int] = []

        def make_mw(priority: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                try:
                    yield
                except RuntimeError:
                    throw_order.append(priority)
                    raise

            return mw

        for p in priorities:
            chain.add(make_mw(p), priority=p)

        with contextlib.suppress(RuntimeError):
            chain.execute({}, _raise_runtime_error)

        # Exception propagation is in reverse sorted priority order
        # (highest priority value = last in pre-phase = first to receive throw)
        assert throw_order == sorted(priorities, reverse=True)

    @given(priorities=_distinct_priorities())
    @settings(max_examples=200)
    def test_all_middleware_receive_operation_result_via_send(
        self, priorities: list[int]
    ):
        """All middleware receive the operation result via gen.send(result).

        Each middleware's yield expression evaluates to the operation result,
        regardless of priority.

        **Validates: Requirements 1.2, 1.3**
        """
        chain: MiddlewareChain[dict, int] = MiddlewareChain()
        received_results: list[tuple[int, int | None]] = []

        def make_mw(priority: int):
            def mw(ctx: dict) -> Generator[None, int | None, None]:
                result = yield
                received_results.append((priority, result))

            return mw

        for p in priorities:
            chain.add(make_mw(p), priority=p)

        expected_result = 42
        chain.execute({}, lambda: expected_result)

        # All middleware should have received the same result
        assert len(received_results) == len(priorities)
        for _priority, result in received_results:
            assert result == expected_result

    @given(
        priorities=_distinct_priorities(),
        fail_index=st.data(),
    )
    @settings(max_examples=200)
    def test_pre_phase_exception_propagates_to_already_started_generators(
        self, priorities: list[int], fail_index: st.DataObject
    ):
        """Pre-phase exceptions propagate to generators that already started.

        If a middleware raises during pre-phase, all generators that have
        already been advanced past their yield point receive throw() in
        reverse order.

        **Validates: Requirements 1.2, 1.3**
        """
        sorted_priorities = sorted(priorities)
        # Pick an index (not the first one) where failure occurs
        if len(sorted_priorities) < 2:
            return  # Need at least 2 middleware to test this

        # Choose a failure index from 1..len-1 (so at least one middleware
        # has already started before the failing one)
        idx = fail_index.draw(
            st.integers(min_value=1, max_value=len(sorted_priorities) - 1)
        )
        failing_priority = sorted_priorities[idx]

        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        pre_order: list[int] = []
        throw_received: list[int] = []

        def make_mw(priority: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                pre_order.append(priority)
                if priority == failing_priority:
                    raise ValueError(f"fail at {priority}")
                try:
                    yield
                except ValueError:
                    throw_received.append(priority)
                    raise

            return mw

        for p in priorities:
            chain.add(make_mw(p), priority=p)

        with contextlib.suppress(ValueError):
            chain.execute({}, lambda: "should not run")

        # Middleware with lower priority (earlier in pre-phase) that successfully
        # started should receive the exception via throw
        started_before_failure = sorted_priorities[:idx]
        assert throw_received == list(reversed(started_before_failure))

    @given(
        priorities=st.lists(
            st.integers(min_value=0, max_value=999),
            min_size=2,
            max_size=10,
            unique=True,
        )
    )
    @settings(max_examples=200)
    def test_ordering_independent_of_registration_order(self, priorities: list[int]):
        """Priority ordering holds regardless of the registration order.

        Two chains with the same set of priorities but different registration
        orders should produce the same pre-phase execution order.

        **Validates: Requirements 1.2, 1.3**
        """
        # Chain 1: register in given order
        chain1: MiddlewareChain[dict, str] = MiddlewareChain()
        order1: list[int] = []

        # Chain 2: register in reversed order
        chain2: MiddlewareChain[dict, str] = MiddlewareChain()
        order2: list[int] = []

        def make_mw(target: list[int], priority: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                target.append(priority)
                yield

            return mw

        for p in priorities:
            chain1.add(make_mw(order1, p), priority=p)

        for p in reversed(priorities):
            chain2.add(make_mw(order2, p), priority=p)

        chain1.execute({}, lambda: "a")
        chain2.execute({}, lambda: "b")

        # Both must produce the same ascending order
        assert order1 == order2 == sorted(priorities)


# =============================================================================
# Helper
# =============================================================================


def _raise_runtime_error() -> str:
    raise RuntimeError("test exception")
