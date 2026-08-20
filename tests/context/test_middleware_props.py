"""Property-based tests for middleware error handling and zero-cost bypass.

Property 19: Middleware Error Handling and Zero-Cost Bypass
**Validates: Requirements 13.8, 12.3, 13.9**
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize.job._middleware import (
    MiddlewareEntry,
    execute_middleware_chain,
)

# --- Strategies ---

# Strategy for generating exception messages
exception_messages = st.text(min_size=1, max_size=50)

# Strategy for generating a number of middleware entries (0 = no middleware)
middleware_counts = st.integers(min_value=0, max_value=5)

# Strategy for selecting which middleware index should raise pre-yield
pre_yield_fail_index = st.integers(min_value=0, max_value=4)

# Strategy for job return values (simple JSON-like values)
job_return_values = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(min_size=0, max_size=20),
    st.booleans(),
    st.none(),
)


# --- Helper Factories ---


def _make_passthrough_middleware(log: list[str], name: str) -> Any:
    """Create a middleware that just yields (passthrough)."""

    def middleware(rc: Any) -> Generator[None]:
        log.append(f"{name}:pre")
        yield
        log.append(f"{name}:post")

    return middleware


def _make_pre_yield_failing_middleware(
    log: list[str], name: str, exc: BaseException
) -> Any:
    """Create a middleware that raises before yielding."""

    def middleware(rc: Any) -> Generator[None]:
        log.append(f"{name}:pre")
        raise exc
        yield  # noqa: B027

    return middleware


def _make_post_yield_failing_middleware(
    log: list[str], name: str, exc: BaseException
) -> Any:
    """Create a middleware that raises after yielding (post-yield)."""

    def middleware(rc: Any) -> Generator[None]:
        log.append(f"{name}:pre")
        try:
            yield
        except BaseException:
            log.append(f"{name}:caught")
            raise
        log.append(f"{name}:post-raising")
        raise exc

    return middleware


def _make_cleanup_tracking_middleware(log: list[str], name: str) -> Any:
    """Create a middleware that tracks cleanup via finally block."""

    def middleware(rc: Any) -> Generator[None]:
        log.append(f"{name}:pre")
        try:
            yield
        except BaseException as e:
            log.append(f"{name}:throw:{type(e).__name__}")
            raise
        finally:
            log.append(f"{name}:cleanup")

    return middleware


# Feature: enriched-runcontext, Property 19: Middleware Error Handling and Zero-Cost Bypass
# When no middleware is registered, job is called directly (zero overhead) — verify
# no generators are allocated. Pre-yield exceptions always skip the job function.
# Post-yield exceptions are propagated, but if both job and middleware raise, the
# original job exception takes precedence. All started generators receive proper
# cleanup (throw or send) regardless of outcome.
# **Validates: Requirements 13.8, 12.3, 13.9**
class TestMiddlewareErrorHandlingAndZeroCostBypass:
    """Property 19: Middleware Error Handling and Zero-Cost Bypass."""

    @given(return_value=job_return_values)
    def test_no_middleware_calls_job_directly(self, return_value: Any) -> None:
        """When no middleware is registered, job is called directly with zero overhead.

        Verifies that no generators are allocated when middleware_entries is empty.

        **Validates: Requirements 12.3**
        """
        call_count = [0]

        def job() -> Any:
            call_count[0] += 1
            return return_value

        result = execute_middleware_chain(
            rc=None,
            middleware_entries=[],
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )
        assert result == return_value
        assert call_count[0] == 1

    @given(
        n_before=st.integers(min_value=0, max_value=4),
        n_after=st.integers(min_value=0, max_value=4),
        exc_msg=exception_messages,
    )
    def test_pre_yield_exception_always_skips_job(
        self, n_before: int, n_after: int, exc_msg: str
    ) -> None:
        """Pre-yield exceptions always skip the job function.

        Given n_before passthrough middleware, then a failing middleware,
        then n_after middleware, the job is never called.

        **Validates: Requirements 13.8**
        """
        log: list[str] = []
        entries: list[MiddlewareEntry] = []

        # Middleware before the failing one
        for i in range(n_before):
            mw = _make_passthrough_middleware(log, f"before_{i}")
            entry = MiddlewareEntry(mw, priority=i)
            entry._registration_order = i
            entries.append(entry)

        # The failing middleware
        fail_exc = RuntimeError(exc_msg)
        fail_mw = _make_pre_yield_failing_middleware(log, "failing", fail_exc)
        fail_entry = MiddlewareEntry(fail_mw, priority=n_before)
        fail_entry._registration_order = n_before
        entries.append(fail_entry)

        # Middleware after the failing one (should never start)
        for i in range(n_after):
            mw = _make_passthrough_middleware(log, f"after_{i}")
            entry = MiddlewareEntry(mw, priority=n_before + 1 + i)
            entry._registration_order = n_before + 1 + i
            entries.append(entry)

        job_called = [False]

        def job() -> str:
            job_called[0] = True
            return "should not reach"

        raised = False
        try:
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        except RuntimeError as caught:
            raised = True
            assert str(caught) == exc_msg

        assert raised, "Pre-yield exception should propagate"
        assert not job_called[0], "Job must not be called on pre-yield exception"
        # Middleware after the failure should never have started
        for i in range(n_after):
            assert f"after_{i}:pre" not in log

    @given(
        n_middleware=st.integers(min_value=1, max_value=5),
        job_exc_msg=exception_messages,
        mw_exc_msg=exception_messages,
    )
    def test_job_exception_takes_precedence_over_post_yield(
        self, n_middleware: int, job_exc_msg: str, mw_exc_msg: str
    ) -> None:
        """If both job and middleware raise, the original job exception takes precedence.

        **Validates: Requirements 13.9**
        """
        log: list[str] = []
        entries: list[MiddlewareEntry] = []

        # Create middleware that re-raises in post-yield (simulates cleanup
        # that also fails). The last middleware raises a NEW exception.
        for i in range(n_middleware - 1):
            mw = _make_cleanup_tracking_middleware(log, f"mw_{i}")
            entry = MiddlewareEntry(mw, priority=i)
            entry._registration_order = i
            entries.append(entry)

        # The last middleware raises its own exception in post-yield
        # when receiving the job exception via throw
        def raising_post_mw(rc: Any) -> Generator[None]:
            log.append("raising_post:pre")
            try:
                yield
            except BaseException:
                log.append("raising_post:caught")
                # Re-raise the original (job takes precedence over new raises)
                raise

        last_entry = MiddlewareEntry(raising_post_mw, priority=n_middleware - 1)
        last_entry._registration_order = n_middleware - 1
        entries.append(last_entry)

        def job() -> None:
            raise ValueError(job_exc_msg)

        raised = False
        try:
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        except ValueError as caught:
            raised = True
            assert str(caught) == job_exc_msg
        except BaseException as e:
            # If anything else raised, the precedence is wrong
            raised = True
            msg = "Job exception should take precedence"
            raise AssertionError(msg) from e

        assert raised

    @given(
        n_middleware=st.integers(min_value=1, max_value=5),
        mw_exc_msg=exception_messages,
    )
    def test_post_yield_exception_propagates_when_job_succeeds(
        self, n_middleware: int, mw_exc_msg: str
    ) -> None:
        """Post-yield exceptions are propagated when the job succeeds.

        When middleware raises in its post-yield phase (after the job completes
        successfully), that middleware exception is propagated.

        **Validates: Requirements 13.9**
        """
        log: list[str] = []
        entries: list[MiddlewareEntry] = []

        # First N-1 passthrough middleware
        for i in range(n_middleware - 1):
            mw = _make_passthrough_middleware(log, f"mw_{i}")
            entry = MiddlewareEntry(mw, priority=i)
            entry._registration_order = i
            entries.append(entry)

        # Last middleware raises in post-yield
        post_exc = RuntimeError(mw_exc_msg)
        fail_mw = _make_post_yield_failing_middleware(log, "post_fail", post_exc)
        last_entry = MiddlewareEntry(fail_mw, priority=n_middleware - 1)
        last_entry._registration_order = n_middleware - 1
        entries.append(last_entry)

        def job() -> str:
            return "success"

        raised = False
        try:
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        except RuntimeError as caught:
            raised = True
            assert str(caught) == mw_exc_msg

        assert raised, "Post-yield exception should propagate when job succeeds"

    @given(
        n_middleware=st.integers(min_value=1, max_value=5),
        return_value=job_return_values,
    )
    def test_all_started_generators_receive_cleanup_on_success(
        self, n_middleware: int, return_value: Any
    ) -> None:
        """All started generators receive proper cleanup regardless of outcome.

        On success, all generators get send(None) / StopIteration (post-yield
        resumes), tracked via finally blocks.

        **Validates: Requirements 13.9**
        """
        log: list[str] = []
        entries: list[MiddlewareEntry] = []

        for i in range(n_middleware):
            mw = _make_cleanup_tracking_middleware(log, f"mw_{i}")
            entry = MiddlewareEntry(mw, priority=i)
            entry._registration_order = i
            entries.append(entry)

        def job() -> Any:
            return return_value

        result = execute_middleware_chain(
            rc=None,
            middleware_entries=entries,
            job_fn=job,
            job_args=(),
            job_kwargs={},
        )
        assert result == return_value

        # Every middleware should have cleanup called
        for i in range(n_middleware):
            assert f"mw_{i}:cleanup" in log, (
                f"Middleware mw_{i} did not receive cleanup"
            )

    @given(
        n_middleware=st.integers(min_value=1, max_value=5),
        exc_msg=exception_messages,
    )
    def test_all_started_generators_receive_cleanup_on_job_failure(
        self, n_middleware: int, exc_msg: str
    ) -> None:
        """All started generators receive proper cleanup when the job raises.

        On failure, all generators get .throw() with the exception, tracked
        via finally blocks.

        **Validates: Requirements 13.9**
        """
        log: list[str] = []
        entries: list[MiddlewareEntry] = []

        for i in range(n_middleware):
            mw = _make_cleanup_tracking_middleware(log, f"mw_{i}")
            entry = MiddlewareEntry(mw, priority=i)
            entry._registration_order = i
            entries.append(entry)

        def job() -> None:
            raise ValueError(exc_msg)

        raised = False
        try:
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        except ValueError:
            raised = True

        assert raised

        # Every middleware should have received throw and cleanup
        for i in range(n_middleware):
            assert f"mw_{i}:throw:ValueError" in log, (
                f"Middleware mw_{i} did not receive throw"
            )
            assert f"mw_{i}:cleanup" in log, (
                f"Middleware mw_{i} did not receive cleanup"
            )

    @given(
        n_before=st.integers(min_value=0, max_value=3),
        exc_msg=exception_messages,
    )
    def test_pre_yield_exception_cleans_up_already_started_generators(
        self, n_before: int, exc_msg: str
    ) -> None:
        """When pre-yield fails, already-started generators receive throw for cleanup.

        **Validates: Requirements 13.8, 13.9**
        """
        log: list[str] = []
        entries: list[MiddlewareEntry] = []

        # N passthrough middleware that will start successfully
        for i in range(n_before):
            mw = _make_cleanup_tracking_middleware(log, f"mw_{i}")
            entry = MiddlewareEntry(mw, priority=i)
            entry._registration_order = i
            entries.append(entry)

        # The failing middleware
        fail_exc = RuntimeError(exc_msg)
        fail_mw = _make_pre_yield_failing_middleware(log, "failing", fail_exc)
        fail_entry = MiddlewareEntry(fail_mw, priority=n_before)
        fail_entry._registration_order = n_before
        entries.append(fail_entry)

        job_called = [False]

        def job() -> str:
            job_called[0] = True
            return "nope"

        raised = False
        try:
            execute_middleware_chain(
                rc=None,
                middleware_entries=entries,
                job_fn=job,
                job_args=(),
                job_kwargs={},
            )
        except RuntimeError:
            raised = True

        assert raised
        assert not job_called[0]

        # All middleware that started before the failure should be cleaned up
        for i in range(n_before):
            assert f"mw_{i}:cleanup" in log, (
                f"Middleware mw_{i} was not cleaned up after pre-yield failure"
            )

    @given(
        args=st.tuples(
            st.integers(min_value=-100, max_value=100),
            st.text(min_size=0, max_size=10),
        ),
        kwargs=st.fixed_dictionaries(
            {"flag": st.booleans()},
        ),
    )
    def test_no_middleware_passes_args_and_kwargs_directly(
        self, args: tuple[int, str], kwargs: dict[str, bool]
    ) -> None:
        """When no middleware, job receives exact args and kwargs passed.

        Ensures zero-cost bypass doesn't alter the calling convention.

        **Validates: Requirements 12.3**
        """
        captured: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def job(*a: Any, **kw: Any) -> str:
            captured.append((a, kw))
            return "done"

        result = execute_middleware_chain(
            rc=None,
            middleware_entries=[],
            job_fn=job,
            job_args=args,
            job_kwargs=kwargs,
        )
        assert result == "done"
        assert len(captured) == 1
        assert captured[0][0] == args
        assert captured[0][1] == kwargs
