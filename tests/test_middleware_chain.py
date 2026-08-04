"""Unit tests for MiddlewareChain[TContext, TResult].

Tests the core middleware executor from functualize.primitives.middleware:
- Priority sorting (lower = first, default 100, range 0–999)
- Pre/post semantics via yield
- gen.send(result) pattern for result-aware middleware
- Exception propagation in reverse order via generator.throw()

# Feature: unified-architecture-redesign, Task 1.3
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from functualize._primitives.middleware import MiddlewareChain

# =============================================================================
# Priority Sorting Tests
# =============================================================================


class TestPrioritySorting:
    """Middleware executes in ascending priority order (lower = first)."""

    def test_default_priority_is_100(self):
        """Middleware added without explicit priority gets priority 100."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        order: list[str] = []

        def mw(ctx: dict) -> Generator[None, str | None, None]:
            order.append("default")
            yield

        chain.add(mw)
        chain.execute({}, lambda: "ok")
        assert order == ["default"]

    def test_lower_priority_runs_first(self):
        """Middleware with lower priority value runs before higher."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        order: list[int] = []

        def make_mw(pri: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                order.append(pri)
                yield

            return mw

        chain.add(make_mw(200), priority=200)
        chain.add(make_mw(50), priority=50)
        chain.add(make_mw(100), priority=100)

        chain.execute({}, lambda: "result")
        assert order == [50, 100, 200]

    def test_same_priority_uses_registration_order(self):
        """Middleware with equal priority runs in registration order."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        order: list[str] = []

        def make_mw(name: str):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                order.append(name)
                yield

            return mw

        chain.add(make_mw("first"), priority=100)
        chain.add(make_mw("second"), priority=100)
        chain.add(make_mw("third"), priority=100)

        chain.execute({}, lambda: "result")
        assert order == ["first", "second", "third"]

    def test_priority_range_validation(self):
        """Priority must be in range [0, 999]."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()

        def mw(ctx: dict) -> Generator[None, str | None, None]:
            yield

        with pytest.raises(ValueError, match="0 and 999"):
            chain.add(mw, priority=-1)

        with pytest.raises(ValueError, match="0 and 999"):
            chain.add(mw, priority=1000)

    def test_priority_boundary_values(self):
        """Priority 0 and 999 are valid."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        order: list[int] = []

        def make_mw(pri: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                order.append(pri)
                yield

            return mw

        chain.add(make_mw(999), priority=999)
        chain.add(make_mw(0), priority=0)

        chain.execute({}, lambda: "result")
        assert order == [0, 999]


# =============================================================================
# Pre/Post Semantics Tests
# =============================================================================


class TestPrePostSemantics:
    """Code before yield = pre-phase, after yield = post-phase."""

    def test_pre_phase_before_operation(self):
        """Code before yield runs before the operation."""
        events: list[str] = []
        chain: MiddlewareChain[dict, str] = MiddlewareChain()

        def mw(ctx: dict) -> Generator[None, str | None, None]:
            events.append("pre")
            yield
            events.append("post")

        chain.add(mw)

        def operation() -> str:
            events.append("operation")
            return "result"

        chain.execute({}, operation)
        assert events == ["pre", "operation", "post"]

    def test_post_phase_in_reverse_order(self):
        """Post-phase runs in reverse priority order."""
        events: list[str] = []
        chain: MiddlewareChain[dict, str] = MiddlewareChain()

        def make_mw(name: str):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                events.append(f"{name}-pre")
                yield
                events.append(f"{name}-post")

            return mw

        chain.add(make_mw("A"), priority=10)
        chain.add(make_mw("B"), priority=20)
        chain.add(make_mw("C"), priority=30)

        chain.execute({}, lambda: "result")
        assert events == ["A-pre", "B-pre", "C-pre", "C-post", "B-post", "A-post"]

    def test_no_middleware_calls_operation_directly(self):
        """With no middleware, the operation runs directly."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        result = chain.execute({}, lambda: "direct")
        assert result == "direct"

    def test_context_passed_to_middleware(self):
        """Each middleware receives the context object."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        received_ctx: list[dict] = []

        def mw(ctx: dict) -> Generator[None, str | None, None]:
            received_ctx.append(ctx)
            yield

        chain.add(mw)
        ctx = {"key": "value"}
        chain.execute(ctx, lambda: "result")
        assert received_ctx == [ctx]

    def test_middleware_that_doesnt_yield_is_skipped(self):
        """Middleware that returns without yielding is silently skipped."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        events: list[str] = []

        def no_yield_mw(ctx: dict) -> Generator[None, str | None, None]:
            events.append("no-yield")
            return  # type: ignore[return-value]
            yield  # make it a generator  # noqa: RET503

        def normal_mw(ctx: dict) -> Generator[None, str | None, None]:
            events.append("normal-pre")
            yield
            events.append("normal-post")

        chain.add(no_yield_mw, priority=50)
        chain.add(normal_mw, priority=100)

        result = chain.execute({}, lambda: "ok")
        assert result == "ok"
        assert events == ["no-yield", "normal-pre", "normal-post"]


# =============================================================================
# gen.send(result) Pattern Tests
# =============================================================================


class TestGenSendResult:
    """Middleware receives operation result via gen.send(result)."""

    def test_middleware_receives_result_from_yield(self):
        """The yield expression evaluates to the operation result."""
        chain: MiddlewareChain[dict, int] = MiddlewareChain()
        received_results: list[int | None] = []

        def mw(ctx: dict) -> Generator[None, int | None, None]:
            result = yield
            received_results.append(result)

        chain.add(mw)
        chain.execute({}, lambda: 42)
        assert received_results == [42]

    def test_multiple_middleware_all_receive_result(self):
        """All middleware receive the same operation result."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        received: list[str | None] = []

        def make_mw():
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                result = yield
                received.append(result)

            return mw

        chain.add(make_mw(), priority=10)
        chain.add(make_mw(), priority=20)
        chain.add(make_mw(), priority=30)

        chain.execute({}, lambda: "hello")
        assert received == ["hello", "hello", "hello"]

    def test_middleware_not_using_send_receives_none_on_exception(self):
        """When operation raises, middleware receives exception via throw."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        received_exc: list[BaseException] = []

        def mw(ctx: dict) -> Generator[None, str | None, None]:
            try:
                yield
            except ValueError as e:
                received_exc.append(e)

        chain.add(mw)

        with pytest.raises(ValueError, match="boom"):
            chain.execute({}, lambda: (_ for _ in ()).throw(ValueError("boom")))

        assert len(received_exc) == 1
        assert str(received_exc[0]) == "boom"


# =============================================================================
# Exception Propagation Tests
# =============================================================================


class TestExceptionPropagation:
    """Exceptions propagate through generators in reverse order."""

    def test_operation_exception_propagated_to_middleware(self):
        """When operation raises, middleware receives exception via throw."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        caught: list[str] = []

        def mw(ctx: dict) -> Generator[None, str | None, None]:
            try:
                yield
            except RuntimeError as e:
                caught.append(str(e))
                raise

        chain.add(mw)

        def bad_op() -> str:
            raise RuntimeError("operation failed")

        with pytest.raises(RuntimeError, match="operation failed"):
            chain.execute({}, bad_op)

        assert caught == ["operation failed"]

    def test_exception_propagates_in_reverse_order(self):
        """Exception flows through middleware in reverse priority order."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        order: list[str] = []

        def make_mw(name: str):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                try:
                    yield
                except RuntimeError:
                    order.append(f"{name}-caught")
                    raise

            return mw

        chain.add(make_mw("A"), priority=10)
        chain.add(make_mw("B"), priority=20)
        chain.add(make_mw("C"), priority=30)

        with pytest.raises(RuntimeError):
            chain.execute({}, lambda: (_ for _ in ()).throw(RuntimeError("fail")))

        # Reverse order: C (highest priority value, last in pre-phase) catches first
        assert order == ["C-caught", "B-caught", "A-caught"]

    def test_pre_yield_exception_propagates_to_started_middleware(self):
        """If middleware raises in pre-yield, already-started middleware get throw."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        events: list[str] = []

        def mw_a(ctx: dict) -> Generator[None, str | None, None]:
            events.append("A-pre")
            try:
                yield
            except ValueError:
                events.append("A-received-exc")
                raise

        def mw_b(ctx: dict) -> Generator[None, str | None, None]:
            events.append("B-pre")
            raise ValueError("B failed in pre")
            yield  # noqa: RET503

        chain.add(mw_a, priority=10)
        chain.add(mw_b, priority=20)

        with pytest.raises(ValueError, match="B failed in pre"):
            chain.execute({}, lambda: "should not run")

        assert "A-pre" in events
        assert "B-pre" in events
        assert "A-received-exc" in events

    def test_middleware_can_suppress_exception_without_affecting_propagation(self):
        """Middleware can catch without re-raising but the original still propagates."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        events: list[str] = []

        def suppressing_mw(ctx: dict) -> Generator[None, str | None, None]:
            try:
                yield
            except RuntimeError:
                events.append("suppressed")
                # Don't re-raise — absorb

        def observing_mw(ctx: dict) -> Generator[None, str | None, None]:
            try:
                yield
            except RuntimeError:
                events.append("observed")
                raise

        chain.add(observing_mw, priority=10)
        chain.add(suppressing_mw, priority=20)

        with pytest.raises(RuntimeError):
            chain.execute({}, lambda: (_ for _ in ()).throw(RuntimeError("err")))

        # suppressing_mw (higher priority value) is reversed first
        assert "suppressed" in events

    def test_middleware_exception_in_post_phase_propagates(self):
        """If middleware raises in post-phase, that exception propagates."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()

        def bad_post_mw(ctx: dict) -> Generator[None, str | None, None]:
            yield
            raise ValueError("post-phase failure")

        chain.add(bad_post_mw)

        with pytest.raises(ValueError, match="post-phase failure"):
            chain.execute({}, lambda: "ok")


# =============================================================================
# Generic Type / Integration Tests
# =============================================================================


class TestMiddlewareChainIntegration:
    """Integration behavior of the full chain."""

    def test_return_value_flows_through(self):
        """Operation return value is returned from execute."""
        chain: MiddlewareChain[str, int] = MiddlewareChain()

        def mw(ctx: str) -> Generator[None, int | None, None]:
            yield

        chain.add(mw)
        result = chain.execute("ctx", lambda: 42)
        assert result == 42

    def test_middleware_can_modify_context_before_operation(self):
        """Middleware can mutate the shared context dict in pre-phase."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()

        def enriching_mw(ctx: dict) -> Generator[None, str | None, None]:
            ctx["enriched"] = True
            yield

        chain.add(enriching_mw)
        ctx: dict[str, Any] = {}

        def op() -> str:
            return f"enriched={ctx.get('enriched')}"

        result = chain.execute(ctx, op)
        assert result == "enriched=True"

    def test_many_middleware_execution(self):
        """Chain handles many middleware correctly."""
        chain: MiddlewareChain[dict, int] = MiddlewareChain()
        pre_order: list[int] = []
        post_order: list[int] = []

        def make_mw(idx: int):
            def mw(ctx: dict) -> Generator[None, int | None, None]:
                pre_order.append(idx)
                yield
                post_order.append(idx)

            return mw

        for i in range(10):
            chain.add(make_mw(i), priority=i * 10)

        result = chain.execute({}, lambda: 99)
        assert result == 99
        assert pre_order == list(range(10))
        assert post_order == list(reversed(range(10)))

    def test_sorted_cache_invalidated_on_add(self):
        """Adding new middleware invalidates the internal sort cache."""
        chain: MiddlewareChain[dict, str] = MiddlewareChain()
        order: list[int] = []

        def make_mw(pri: int):
            def mw(ctx: dict) -> Generator[None, str | None, None]:
                order.append(pri)
                yield

            return mw

        chain.add(make_mw(200), priority=200)
        chain.execute({}, lambda: "a")
        assert order == [200]

        # Add higher-priority middleware and verify it runs first
        order.clear()
        chain.add(make_mw(50), priority=50)
        chain.execute({}, lambda: "b")
        assert order == [50, 200]
