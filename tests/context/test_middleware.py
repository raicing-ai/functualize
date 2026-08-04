"""Unit tests for the middleware registry and execution engine."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from functualize.job._middleware import (
    MiddlewareEntry,
    MiddlewareRegistry,
    execute_middleware_chain,
)

# --- Test Helpers ---


def make_tracking_middleware(name: str, log: list[str]) -> Any:
    """Create a middleware that logs pre/post phases."""

    def middleware(rc: Any) -> Generator[None]:
        log.append(f"{name}:pre")
        yield
        log.append(f"{name}:post")

    return middleware


def make_error_middleware(name: str, log: list[str], error: Exception) -> Any:
    """Create a middleware that catches job errors in post-yield."""

    def middleware(rc: Any) -> Generator[None]:
        log.append(f"{name}:pre")
        try:
            yield
        except Exception as exc:
            log.append(f"{name}:caught:{exc}")
            raise

    return middleware


# --- MiddlewareEntry Tests ---


class TestMiddlewareEntry:
    """Tests for MiddlewareEntry class."""

    def test_stores_middleware_and_priority(self) -> None:
        def mw(rc: Any) -> Generator[None]:
            yield

        entry = MiddlewareEntry(mw, priority=5)
        assert entry.middleware is mw
        assert entry.priority == 5

    def test_default_priority_is_zero(self) -> None:
        def mw(rc: Any) -> Generator[None]:
            yield

        entry = MiddlewareEntry(mw)
        assert entry.priority == 0

    def test_registration_order_defaults_to_zero(self) -> None:
        def mw(rc: Any) -> Generator[None]:
            yield

        entry = MiddlewareEntry(mw)
        assert entry._registration_order == 0


# --- MiddlewareRegistry Tests ---


class TestMiddlewareRegistry:
    """Tests for MiddlewareRegistry class."""

    def test_has_middleware_false_when_empty(self) -> None:
        registry = MiddlewareRegistry()
        assert registry.has_middleware is False

    def test_has_middleware_true_after_register(self) -> None:
        registry = MiddlewareRegistry()

        def mw(rc: Any) -> Generator[None]:
            yield

        registry.register(mw)
        assert registry.has_middleware is True

    def test_register_assigns_registration_order(self) -> None:
        registry = MiddlewareRegistry()

        def mw1(rc: Any) -> Generator[None]:
            yield

        def mw2(rc: Any) -> Generator[None]:
            yield

        registry.register(mw1)
        registry.register(mw2)
        sorted_entries = registry.get_sorted()
        assert sorted_entries[0]._registration_order == 0
        assert sorted_entries[1]._registration_order == 1

    def test_get_sorted_by_priority(self) -> None:
        registry = MiddlewareRegistry()

        def mw_high(rc: Any) -> Generator[None]:
            yield

        def mw_low(rc: Any) -> Generator[None]:
            yield

        registry.register(mw_high, priority=10)
        registry.register(mw_low, priority=1)
        sorted_entries = registry.get_sorted()
        assert sorted_entries[0].middleware is mw_low
        assert sorted_entries[1].middleware is mw_high

    def test_get_sorted_stable_on_equal_priority(self) -> None:
        registry = MiddlewareRegistry()

        def mw1(rc: Any) -> Generator[None]:
            yield

        def mw2(rc: Any) -> Generator[None]:
            yield

        def mw3(rc: Any) -> Generator[None]:
            yield

        registry.register(mw1, priority=0)
        registry.register(mw2, priority=0)
        registry.register(mw3, priority=0)
        sorted_entries = registry.get_sorted()
        assert sorted_entries[0].middleware is mw1
        assert sorted_entries[1].middleware is mw2
        assert sorted_entries[2].middleware is mw3

    def test_get_sorted_returns_new_list(self) -> None:
        registry = MiddlewareRegistry()

        def mw(rc: Any) -> Generator[None]:
            yield

        registry.register(mw)
        sorted1 = registry.get_sorted()
        sorted2 = registry.get_sorted()
        assert sorted1 is not sorted2


# --- execute_middleware_chain Tests ---


class TestExecuteMiddlewareChainNoMiddleware:
    """Tests for execute_middleware_chain with no middleware."""

    def test_calls_job_directly(self) -> None:
        called_with: list[tuple[Any, ...]] = []

        def job(*args: Any, **kwargs: Any) -> str:
            called_with.append((args, kwargs))
            return "result"

        result = execute_middleware_chain(
            rc=None,
            middleware_entries=[],
            job_fn=job,
            job_args=(1, 2),
            job_kwargs={"key": "val"},
        )
        assert result == "result"
        assert called_with == [((1, 2), {"key": "val"})]

    def test_propagates_job_exception(self) -> None:
        def job(*args: Any, **kwargs: Any) -> None:
            raise ValueError("job failed")

        with pytest.raises(ValueError, match="job failed"):
            execute_middleware_chain(
                rc=None,
                middleware_entries=[],
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )


class TestExecuteMiddlewareChainPreYield:
    """Tests for pre-yield phase of middleware chain."""

    def test_pre_yield_executes_in_order(self) -> None:
        log: list[str] = []

        mw1 = make_tracking_middleware("mw1", log)
        mw2 = make_tracking_middleware("mw2", log)

        entries = [
            MiddlewareEntry(mw1, priority=0),
            MiddlewareEntry(mw2, priority=1),
        ]

        def job() -> str:
            log.append("job")
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )
        assert log == ["mw1:pre", "mw2:pre", "job", "mw2:post", "mw1:post"]

    def test_pre_yield_exception_skips_job(self) -> None:
        log: list[str] = []

        def failing_mw(rc: Any) -> Generator[None]:
            log.append("failing:pre")
            raise RuntimeError("pre-yield fail")
            yield  # noqa: B027 - unreachable but needed for generator type

        def normal_mw(rc: Any) -> Generator[None]:
            log.append("normal:pre")
            yield
            log.append("normal:post")

        entries = [
            MiddlewareEntry(normal_mw, priority=0),
            MiddlewareEntry(failing_mw, priority=1),
        ]

        def job() -> str:
            log.append("job")
            return "ok"

        with pytest.raises(RuntimeError, match="pre-yield fail"):
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        # Job was NOT called
        assert "job" not in log
        # Normal middleware started its pre-yield
        assert "normal:pre" in log


class TestExecuteMiddlewareChainPostYield:
    """Tests for post-yield phase of middleware chain."""

    def test_post_yield_executes_in_reverse_order(self) -> None:
        log: list[str] = []

        mw1 = make_tracking_middleware("mw1", log)
        mw2 = make_tracking_middleware("mw2", log)
        mw3 = make_tracking_middleware("mw3", log)

        entries = [
            MiddlewareEntry(mw1, priority=0),
            MiddlewareEntry(mw2, priority=0),
            MiddlewareEntry(mw3, priority=0),
        ]
        # Set registration orders for proper ordering
        entries[0]._registration_order = 0
        entries[1]._registration_order = 1
        entries[2]._registration_order = 2

        def job() -> str:
            log.append("job")
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )
        assert log == [
            "mw1:pre",
            "mw2:pre",
            "mw3:pre",
            "job",
            "mw3:post",
            "mw2:post",
            "mw1:post",
        ]

    def test_post_yield_receives_exception_via_throw(self) -> None:
        log: list[str] = []

        def catching_mw(rc: Any) -> Generator[None]:
            log.append("catching:pre")
            try:
                yield
            except ValueError as exc:
                log.append(f"catching:got:{exc}")
                raise

        entries = [MiddlewareEntry(catching_mw, priority=0)]

        def job() -> None:
            raise ValueError("job error")

        with pytest.raises(ValueError, match="job error"):
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        assert "catching:got:job error" in log

    def test_middleware_that_does_not_yield_is_skipped(self) -> None:
        log: list[str] = []

        def non_yielding(rc: Any) -> Generator[None]:
            log.append("non-yield")
            return
            yield  # noqa: B027 - unreachable but needed for generator type

        def normal_mw(rc: Any) -> Generator[None]:
            log.append("normal:pre")
            yield
            log.append("normal:post")

        entries = [
            MiddlewareEntry(non_yielding, priority=0),
            MiddlewareEntry(normal_mw, priority=1),
        ]

        def job() -> str:
            log.append("job")
            return "ok"

        execute_middleware_chain(
            rc=None,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )
        # Non-yielding middleware was started but not in post-yield
        assert "non-yield" in log
        assert log == ["non-yield", "normal:pre", "job", "normal:post"]


class TestExecuteMiddlewareChainRunContextMutation:
    """Tests for RC mutability through middleware chain."""

    def test_middleware_can_mutate_rc(self) -> None:
        """Middleware changes to RC are visible to subsequent middleware and job."""
        rc_state: dict[str, Any] = {"value": 0}

        def incrementing_mw(rc: Any) -> Generator[None]:
            rc["value"] += 1
            yield

        def job(rc_ref: Any = None) -> int:
            return rc_state["value"]

        entries = [
            MiddlewareEntry(incrementing_mw, priority=0),
            MiddlewareEntry(incrementing_mw, priority=1),
        ]

        # Pass rc_state as rc to be mutated
        result = execute_middleware_chain(
            rc=rc_state,
            middleware_entries=entries,
            job_fn=lambda: rc_state["value"],
            job_args=(),
            job_kwargs={},
        )
        assert result == 2

    def test_job_return_value_is_preserved(self) -> None:
        def passthrough_mw(rc: Any) -> Generator[None]:
            yield

        entries = [MiddlewareEntry(passthrough_mw, priority=0)]

        def job() -> dict[str, int]:
            return {"answer": 42}

        result = execute_middleware_chain(
            rc=None,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )
        assert result == {"answer": 42}

    def test_post_yield_exception_propagates_when_job_succeeds(self) -> None:
        """If middleware raises in post-yield and job didn't fail, mw error propagates."""
        log: list[str] = []

        def failing_post_mw(rc: Any) -> Generator[None]:
            log.append("pre")
            yield
            log.append("post-before-raise")
            raise RuntimeError("post-yield failure")

        entries = [MiddlewareEntry(failing_post_mw, priority=0)]

        def job() -> str:
            log.append("job")
            return "ok"

        with pytest.raises(RuntimeError, match="post-yield failure"):
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        assert "job" in log

    def test_job_exception_takes_precedence_over_post_yield_exception(self) -> None:
        """If both job and middleware raise, the original job exception propagates."""

        def raising_post_mw(rc: Any) -> Generator[None]:
            yield
            raise RuntimeError("middleware error")

        entries = [MiddlewareEntry(raising_post_mw, priority=0)]

        def job() -> None:
            raise ValueError("job error")

        with pytest.raises(ValueError, match="job error"):
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
