"""Property-based tests for AFTER_SUCCESS result passing.

Tests Properties 1, 2, 3 from the design document using Hypothesis:
- Property 1: AFTER_SUCCESS hooks receive the job's return value
- Property 2: Hook exception isolation preserves remaining dispatch
- Property 3: Hook invocation order (global-first, then job-scoped, registration order)

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for generating arbitrary return values (including None, dicts, lists)
return_values = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(min_size=0, max_size=50),
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.integers(),
        min_size=0,
        max_size=5,
    ),
    st.lists(st.integers(), min_size=0, max_size=10),
)

# Strategy for job names
job_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)

# Strategy for number of hooks
hook_counts = st.integers(min_value=1, max_value=8)


class TestProperty1AfterSuccessReceivesResult:
    """Property 1: AFTER_SUCCESS hooks receive the job's return value.

    For any job that completes successfully and returns any value (including None),
    all registered AFTER_SUCCESS hooks whose signature includes a `result` parameter
    SHALL receive that exact value as the `result` keyword argument.

    **Validates: Requirements 1.1, 1.2, 1.3**
    """

    @settings(max_examples=100)
    @given(
        result_value=return_values,
        num_hooks=hook_counts,
        job_name=job_names,
    )
    def test_all_hooks_with_result_param_receive_exact_value(
        self,
        result_value: Any,
        num_hooks: int,
        job_name: str,
    ) -> None:
        """All hooks accepting `result` receive the exact return value."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        received_values: list[Any] = []

        # Register multiple hooks that accept result
        for _ in range(num_hooks):

            def hook(rc, result=None, _received=received_values):
                _received.append(result)

            registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        # All hooks must have received the exact same value
        assert len(received_values) == num_hooks
        for received in received_values:
            assert received is result_value or received == result_value

    @settings(max_examples=100)
    @given(
        result_value=return_values,
        job_name=job_names,
    )
    def test_hooks_without_result_param_still_invoked(
        self,
        result_value: Any,
        job_name: str,
    ) -> None:
        """Hooks that don't accept `result` are invoked without it (no TypeError).

        **Validates: Requirement 1.3**
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        legacy_called: list[bool] = []
        new_received: list[Any] = []

        def legacy_hook(rc):
            legacy_called.append(True)

        def new_hook(rc, result=None):
            new_received.append(result)

        registry.register_global(HookEvent.AFTER_SUCCESS, legacy_hook)
        registry.register_global(HookEvent.AFTER_SUCCESS, new_hook)

        # Should not raise TypeError
        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        assert legacy_called == [True]
        assert len(new_received) == 1
        assert new_received[0] is result_value or new_received[0] == result_value

    @settings(max_examples=100)
    @given(
        result_value=return_values,
        job_name=job_names,
    )
    def test_kwargs_catch_all_receives_result(
        self,
        result_value: Any,
        job_name: str,
    ) -> None:
        """Hooks with **kwargs also receive the result value."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        received: list[Any] = []

        def hook_with_kwargs(rc, **kwargs):
            received.append(kwargs.get("result"))

        registry.register_global(HookEvent.AFTER_SUCCESS, hook_with_kwargs)
        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        assert len(received) == 1
        assert received[0] is result_value or received[0] == result_value


class TestProperty2ExceptionIsolation:
    """Property 2: Hook exception isolation preserves remaining dispatch.

    For any sequence of registered AFTER_SUCCESS hooks where one or more hooks raise
    exceptions, all remaining non-raising hooks in the sequence SHALL still be invoked,
    and the job's completion status SHALL remain SUCCESS.

    **Validates: Requirements 1.4**
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        result_value=return_values,
        job_name=job_names,
        num_hooks=st.integers(min_value=2, max_value=8),
        failing_indices=st.frozensets(
            st.integers(min_value=0, max_value=7), min_size=1, max_size=4
        ),
    )
    def test_non_raising_hooks_still_invoked_after_exceptions(
        self,
        result_value: Any,
        job_name: str,
        num_hooks: int,
        failing_indices: frozenset[int],
    ) -> None:
        """Non-raising hooks still execute even when others raise exceptions."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invoked: list[int] = []

        # Suppress log noise during test
        hook_logger = logging.getLogger("functualize._events.hooks")
        original_level = hook_logger.level
        hook_logger.setLevel(logging.CRITICAL)

        try:
            for i in range(num_hooks):
                if i in failing_indices:

                    def make_failing(idx):
                        def hook(rc, result=None):
                            raise RuntimeError(f"hook_{idx}_exploded")

                        hook.__name__ = f"failing_hook_{idx}"
                        return hook

                    registry.register_global(HookEvent.AFTER_SUCCESS, make_failing(i))
                else:

                    def make_good(idx):
                        def hook(rc, result=None):
                            invoked.append(idx)

                        return hook

                    registry.register_global(HookEvent.AFTER_SUCCESS, make_good(i))

            # Invoke should not raise
            registry.invoke(
                HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value
            )

            # All non-failing hooks should have been invoked
            expected_invoked = sorted(
                i for i in range(num_hooks) if i not in failing_indices
            )
            assert sorted(invoked) == expected_invoked
        finally:
            hook_logger.setLevel(original_level)

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        result_value=return_values,
        job_name=job_names,
        num_hooks=st.integers(min_value=2, max_value=8),
        failing_indices=st.frozensets(
            st.integers(min_value=0, max_value=7), min_size=1, max_size=4
        ),
    )
    def test_exceptions_are_logged_at_error_level(
        self,
        result_value: Any,
        job_name: str,
        num_hooks: int,
        failing_indices: frozenset[int],
    ) -> None:
        """All hook exceptions are logged at ERROR level."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        log_records: list[logging.LogRecord] = []

        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)  # type: ignore[assignment]
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            for i in range(num_hooks):
                if i in failing_indices:

                    def make_failing(idx):
                        def hook(rc, result=None):
                            raise RuntimeError(f"hook_{idx}_error")

                        hook.__name__ = f"hook_{idx}"
                        return hook

                    registry.register_global(HookEvent.AFTER_SUCCESS, make_failing(i))
                else:
                    registry.register_global(
                        HookEvent.AFTER_SUCCESS, lambda rc, result=None: None
                    )

            registry.invoke(
                HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value
            )

            # Each failing hook should produce an ERROR log
            actual_failing = [i for i in range(num_hooks) if i in failing_indices]
            log_text = " ".join(r.getMessage() for r in log_records)
            for idx in actual_failing:
                assert f"hook_{idx}_error" in log_text

            # All log records should be at ERROR level
            for record in log_records:
                assert record.levelno == logging.ERROR
        finally:
            hook_logger.removeHandler(handler)

    @settings(max_examples=50)
    @given(
        result_value=return_values,
        job_name=job_names,
        num_hooks=st.integers(min_value=1, max_value=6),
    )
    def test_invoke_does_not_raise_when_hooks_fail(
        self,
        result_value: Any,
        job_name: str,
        num_hooks: int,
    ) -> None:
        """The invoke() call itself never raises even if all hooks fail."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        # Suppress log noise
        hook_logger = logging.getLogger("functualize._events.hooks")
        original_level = hook_logger.level
        hook_logger.setLevel(logging.CRITICAL)

        try:
            # Register ALL failing hooks
            for i in range(num_hooks):

                def make_failing(idx):
                    def hook(rc, result=None):
                        raise RuntimeError(f"all_fail_{idx}")

                    hook.__name__ = f"all_fail_{idx}"
                    return hook

                registry.register_global(HookEvent.AFTER_SUCCESS, make_failing(i))

            # Should not raise — job status remains SUCCESS
            registry.invoke(
                HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value
            )
        finally:
            hook_logger.setLevel(original_level)


class TestProperty3InvocationOrder:
    """Property 3: Hook invocation order (global-first, then job-scoped, registration order).

    For any combination of N global hooks and M job-scoped hooks registered for
    AFTER_SUCCESS, the engine SHALL invoke all global hooks in registration order first,
    then all job-scoped hooks in registration order, with each hook receiving the same
    result value.

    **Validates: Requirements 1.5**
    """

    @settings(max_examples=100)
    @given(
        result_value=return_values,
        job_name=job_names,
        num_global=st.integers(min_value=0, max_value=8),
        num_job_scoped=st.integers(min_value=0, max_value=8),
    )
    def test_global_hooks_invoked_before_job_scoped_in_registration_order(
        self,
        result_value: Any,
        job_name: str,
        num_global: int,
        num_job_scoped: int,
    ) -> None:
        """Global hooks run first in registration order, then job-scoped."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invocation_order: list[str] = []

        # Register global hooks
        for i in range(num_global):

            def make_global_hook(idx):
                def hook(rc, result=None):
                    invocation_order.append(f"global_{idx}")

                return hook

            registry.register_global(HookEvent.AFTER_SUCCESS, make_global_hook(i))

        # Register job-scoped hooks
        for i in range(num_job_scoped):

            def make_job_hook(idx):
                def hook(rc, result=None):
                    invocation_order.append(f"job_{idx}")

                return hook

            registry.register_for_job(
                job_name, HookEvent.AFTER_SUCCESS, make_job_hook(i)
            )

        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        # Build expected order
        expected = [f"global_{i}" for i in range(num_global)] + [
            f"job_{i}" for i in range(num_job_scoped)
        ]
        assert invocation_order == expected

    @settings(max_examples=100)
    @given(
        result_value=return_values,
        job_name=job_names,
        num_global=st.integers(min_value=1, max_value=6),
        num_job_scoped=st.integers(min_value=1, max_value=6),
    )
    def test_all_hooks_receive_same_result_value(
        self,
        result_value: Any,
        job_name: str,
        num_global: int,
        num_job_scoped: int,
    ) -> None:
        """Every hook (global and job-scoped) receives the same result value."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        received_results: list[Any] = []

        # Register global hooks
        for _ in range(num_global):

            def make_hook(_received=received_results):
                def hook(rc, result=None):
                    _received.append(result)

                return hook

            registry.register_global(HookEvent.AFTER_SUCCESS, make_hook())

        # Register job-scoped hooks
        for _ in range(num_job_scoped):

            def make_hook(_received=received_results):
                def hook(rc, result=None):
                    _received.append(result)

                return hook

            registry.register_for_job(job_name, HookEvent.AFTER_SUCCESS, make_hook())

        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        # All hooks should have received the value
        total_hooks = num_global + num_job_scoped
        assert len(received_results) == total_hooks
        for received in received_results:
            assert received is result_value or received == result_value

    @settings(max_examples=100)
    @given(
        result_value=return_values,
        job_name=job_names,
        num_global=st.integers(min_value=1, max_value=5),
        num_job_scoped=st.integers(min_value=1, max_value=5),
    )
    def test_job_scoped_hooks_not_invoked_for_different_job(
        self,
        result_value: Any,
        job_name: str,
        num_global: int,
        num_job_scoped: int,
    ) -> None:
        """Job-scoped hooks registered for one job don't fire for another."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invocation_order: list[str] = []

        # Register global hooks
        for i in range(num_global):

            def make_hook(idx):
                def hook(rc, result=None):
                    invocation_order.append(f"global_{idx}")

                return hook

            registry.register_global(HookEvent.AFTER_SUCCESS, make_hook(i))

        # Register job-scoped hooks for a DIFFERENT job
        other_job = job_name + "_other"
        for _i in range(num_job_scoped):
            registry.register_for_job(
                other_job,
                HookEvent.AFTER_SUCCESS,
                lambda rc, result=None: invocation_order.append("wrong_job"),
            )

        # Invoke for the original job
        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        # Only global hooks should have been invoked
        expected = [f"global_{i}" for i in range(num_global)]
        assert invocation_order == expected
