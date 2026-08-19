"""Property-based tests for HookRegistry lifecycle hooks.

Tests Property 25 (Hook Invocation Order) and Property 26 (Hook Resilience
and Teardown Guarantee) using Hypothesis.
"""

import logging
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job.context import RunContext

# --- Strategies ---

hook_events = st.sampled_from(
    [
        HookEvent.BEFORE_JOB,
        HookEvent.AFTER_SUCCESS,
        HookEvent.AFTER_FAILURE,
        HookEvent.ON_TEARDOWN,
    ]
)

job_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

# Strategy for generating a list of hook labels (used to track invocation order)
hook_labels = st.lists(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"), whitelist_characters="_"
        ),
        min_size=1,
        max_size=10,
    ),
    min_size=0,
    max_size=10,
)


# --- Property 25: Hook Invocation Order ---
# Feature: functualize, Property 25: Hook Invocation Order


class TestHookInvocationOrder:
    """Property 25: For any set of registered lifecycle hooks (global and job-scoped)
    for the same event, the framework SHALL invoke global hooks first (in registration
    order), then job-scoped hooks (in registration order).

    Validates: Requirements 9.2, 9.8
    """

    @given(
        event=hook_events,
        job_name=job_names,
        global_labels=hook_labels,
        job_labels=hook_labels,
    )
    def test_global_hooks_invoked_before_job_hooks_in_registration_order(
        self, event: str, job_name: str, global_labels: list[str], job_labels: list[str]
    ):
        # Feature: functualize, Property 25: Hook Invocation Order
        """Global hooks are invoked first in registration order, then job-scoped hooks
        in registration order, for any event and any combination of hooks."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invocation_order: list[str] = []

        # Register global hooks
        for label in global_labels:
            tag = f"global:{label}"
            if event == HookEvent.AFTER_FAILURE:
                registry.register_global(
                    event, lambda rc, exc, t=tag: invocation_order.append(t)
                )
            else:
                registry.register_global(
                    event, lambda rc, t=tag: invocation_order.append(t)
                )

        # Register job-scoped hooks
        for label in job_labels:
            tag = f"job:{label}"
            if event == HookEvent.AFTER_FAILURE:
                registry.register_for_job(
                    job_name, event, lambda rc, exc, t=tag: invocation_order.append(t)
                )
            else:
                registry.register_for_job(
                    job_name, event, lambda rc, t=tag: invocation_order.append(t)
                )

        # Invoke
        exception = ValueError("test") if event == HookEvent.AFTER_FAILURE else None
        registry.invoke(event, job_name, mock_rc, exception=exception)

        # Build expected order: global hooks first, then job hooks
        expected = [f"global:{label}" for label in global_labels] + [
            f"job:{label}" for label in job_labels
        ]

        assert invocation_order == expected

    @given(
        event=hook_events,
        job_name=job_names,
        global_labels=hook_labels,
    )
    def test_job_scoped_hooks_not_invoked_for_other_jobs(
        self, event: str, job_name: str, global_labels: list[str]
    ):
        # Feature: functualize, Property 25: Hook Invocation Order
        """Job-scoped hooks registered for one job are not invoked when a different
        job triggers the same event."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invocation_order: list[str] = []

        # Register global hooks
        for label in global_labels:
            tag = f"global:{label}"
            if event == HookEvent.AFTER_FAILURE:
                registry.register_global(
                    event, lambda rc, exc, t=tag: invocation_order.append(t)
                )
            else:
                registry.register_global(
                    event, lambda rc, t=tag: invocation_order.append(t)
                )

        # Register job-scoped hooks for a DIFFERENT job
        other_job = job_name + "_other"
        if event == HookEvent.AFTER_FAILURE:
            registry.register_for_job(
                other_job,
                event,
                lambda rc, exc: invocation_order.append("should_not_appear"),
            )
        else:
            registry.register_for_job(
                other_job,
                event,
                lambda rc: invocation_order.append("should_not_appear"),
            )

        # Invoke for the original job
        exception = ValueError("test") if event == HookEvent.AFTER_FAILURE else None
        registry.invoke(event, job_name, mock_rc, exception=exception)

        # Only global hooks should have been invoked
        expected = [f"global:{label}" for label in global_labels]
        assert invocation_order == expected


# --- Property 26: Hook Resilience and Teardown Guarantee ---
# Feature: functualize, Property 26: Hook Resilience and Teardown Guarantee


class TestHookResilienceAndTeardownGuarantee:
    """Property 26: For any lifecycle hook that raises an exception, the framework
    SHALL log the error and continue executing remaining hooks. The on_teardown hooks
    SHALL always be invoked regardless of whether the job succeeded or failed.

    Validates: Requirements 9.5, 9.7
    """

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        event=hook_events,
        job_name=job_names,
        num_hooks=st.integers(min_value=1, max_value=8),
        failing_indices=st.frozensets(
            st.integers(min_value=0, max_value=7), max_size=5
        ),
    )
    def test_failing_hooks_do_not_prevent_remaining_hooks(
        self,
        event: str,
        job_name: str,
        num_hooks: int,
        failing_indices: frozenset[int],
    ):
        # Feature: functualize, Property 26: Hook Resilience and Teardown Guarantee
        """When some hooks raise exceptions, remaining hooks still execute."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invoked: list[int] = []

        # Set up a log handler to capture error messages
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            for i in range(num_hooks):
                if i in failing_indices:
                    if event == HookEvent.AFTER_FAILURE:

                        def make_failing(idx):
                            def hook(rc, exc):
                                raise RuntimeError(f"hook_{idx}_failed")

                            hook.__name__ = f"hook_{idx}"
                            return hook
                    else:

                        def make_failing(idx):
                            def hook(rc):
                                raise RuntimeError(f"hook_{idx}_failed")

                            hook.__name__ = f"hook_{idx}"
                            return hook

                    registry.register_global(event, make_failing(i))
                else:
                    if event == HookEvent.AFTER_FAILURE:
                        registry.register_global(
                            event, lambda rc, exc, idx=i: invoked.append(idx)
                        )
                    else:
                        registry.register_global(
                            event, lambda rc, idx=i: invoked.append(idx)
                        )

            # Invoke
            exception = (
                ValueError("job error") if event == HookEvent.AFTER_FAILURE else None
            )
            registry.invoke(event, job_name, mock_rc, exception=exception)

            # All non-failing hooks should have been invoked
            expected_invoked = sorted(
                i for i in range(num_hooks) if i not in failing_indices
            )
            assert sorted(invoked) == expected_invoked

            # All failing hooks should have been logged
            log_text = " ".join(r.getMessage() for r in log_records)
            actual_failing = [i for i in range(num_hooks) if i in failing_indices]
            for idx in actual_failing:
                assert f"hook_{idx}_failed" in log_text
        finally:
            hook_logger.removeHandler(handler)

    @given(
        job_name=job_names,
        job_succeeded=st.booleans(),
        num_teardown_hooks=st.integers(min_value=1, max_value=6),
    )
    def test_teardown_hooks_always_invoked_regardless_of_job_outcome(
        self,
        job_name: str,
        job_succeeded: bool,
        num_teardown_hooks: int,
    ):
        # Feature: functualize, Property 26: Hook Resilience and Teardown Guarantee
        """on_teardown hooks are always invoked whether the job succeeded or failed."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        teardown_invoked: list[int] = []

        # Register teardown hooks (both global and job-scoped)
        global_count = num_teardown_hooks // 2
        job_count = num_teardown_hooks - global_count

        for i in range(global_count):
            registry.register_global(
                HookEvent.ON_TEARDOWN,
                lambda rc, idx=i: teardown_invoked.append(idx),
            )

        for i in range(job_count):
            registry.register_for_job(
                job_name,
                HookEvent.ON_TEARDOWN,
                lambda rc, idx=global_count + i: teardown_invoked.append(idx),
            )

        # Simulate job outcome: invoke after_success or after_failure first
        if job_succeeded:
            registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc)
        else:
            exc = RuntimeError("job failed")
            registry.invoke(HookEvent.AFTER_FAILURE, job_name, mock_rc, exception=exc)

        # Then invoke teardown (as the framework always does)
        registry.invoke(HookEvent.ON_TEARDOWN, job_name, mock_rc)

        # All teardown hooks must have been invoked
        expected = list(range(num_teardown_hooks))
        assert sorted(teardown_invoked) == expected

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        job_name=job_names,
        job_succeeded=st.booleans(),
        num_teardown_hooks=st.integers(min_value=2, max_value=6),
        failing_index=st.integers(min_value=0, max_value=5),
    )
    def test_teardown_hooks_continue_even_when_some_fail(
        self,
        job_name: str,
        job_succeeded: bool,
        num_teardown_hooks: int,
        failing_index: int,
    ):
        # Feature: functualize, Property 26: Hook Resilience and Teardown Guarantee
        """Even if a teardown hook raises, remaining teardown hooks still execute."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        teardown_invoked: list[int] = []

        # Clamp failing_index to valid range
        failing_index = failing_index % num_teardown_hooks

        # Set up a log handler to capture error messages
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            for i in range(num_teardown_hooks):
                if i == failing_index:

                    def make_failing(idx):
                        def hook(rc):
                            raise RuntimeError(f"teardown_{idx}_failed")

                        hook.__name__ = f"teardown_hook_{idx}"
                        return hook

                    registry.register_global(HookEvent.ON_TEARDOWN, make_failing(i))
                else:
                    registry.register_global(
                        HookEvent.ON_TEARDOWN,
                        lambda rc, idx=i: teardown_invoked.append(idx),
                    )

            # Simulate job outcome
            if job_succeeded:
                registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc)
            else:
                exc = RuntimeError("job failed")
                registry.invoke(
                    HookEvent.AFTER_FAILURE, job_name, mock_rc, exception=exc
                )

            # Invoke teardown
            registry.invoke(HookEvent.ON_TEARDOWN, job_name, mock_rc)

            # All non-failing teardown hooks should have been invoked
            expected = [i for i in range(num_teardown_hooks) if i != failing_index]
            assert sorted(teardown_invoked) == expected

            # The failing hook error should be logged
            log_text = " ".join(r.getMessage() for r in log_records)
            assert f"teardown_{failing_index}_failed" in log_text
        finally:
            hook_logger.removeHandler(handler)
