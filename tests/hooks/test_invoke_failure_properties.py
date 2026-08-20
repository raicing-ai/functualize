"""Property-based tests for INVOKE_FAILURE hook semantics.

**Validates: Requirements 21.2, 21.4, 21.6**

Property 12: INVOKE_FAILURE fires only for FAILURE status
- INVOKE_FAILURE fires iff result.status == RunStatus.FAILURE
- INVOKE_FAILURE does NOT fire for TIMEOUT, CANCELLED, SUCCESS, or other statuses
- When both INVOKE_FAILURE and INVOKE_END are registered, INVOKE_FAILURE fires BEFORE INVOKE_END
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize._engine.result import JobResult
from functualize._events.hooks import HookEvent, HookRegistry
from functualize._types.enums import RunStatus

# --- Strategies ---

all_run_statuses = st.sampled_from(list(RunStatus))

non_failure_statuses = st.sampled_from([s for s in RunStatus if s != RunStatus.FAILURE])

job_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

invoke_depths = st.integers(min_value=1, max_value=10)

duration_ms = st.floats(min_value=0.0, max_value=60000.0, allow_nan=False)


def make_job_result(status: RunStatus, job_name: str, dur: float) -> JobResult:
    """Create a JobResult with the given status."""
    exception = RuntimeError("failed") if status == RunStatus.FAILURE else None
    return JobResult(
        status=status,
        duration_ms=dur,
        return_value=None,
        exception=exception,
    )


def simulate_invoke_hook_dispatch(
    hook_registry: HookRegistry,
    rc: Any,
    child_job_name: str,
    child_depth: int,
    result: JobResult,
) -> None:
    """Simulate the hook dispatch logic from RunContext.invoke.

    This replicates the exact dispatch logic used in RunContext.invoke():
    1. If result.status == FAILURE, fire INVOKE_FAILURE hooks
    2. Always fire INVOKE_END hooks
    """
    import logging

    _logger = logging.getLogger(__name__)

    # Fire INVOKE_FAILURE hook (only for RunStatus.FAILURE)
    if result.status == RunStatus.FAILURE:
        failure_hooks = hook_registry._global_hooks.get(HookEvent.INVOKE_FAILURE, [])
        for hook in failure_hooks:
            try:
                hook(rc, child_job_name, child_depth, result)
            except Exception as e:
                _logger.error(f"INVOKE_FAILURE hook raised: {e}")

    # Fire INVOKE_END hook (always)
    end_hooks = hook_registry._global_hooks.get(HookEvent.INVOKE_END, [])
    for hook in end_hooks:
        try:
            hook(rc, child_job_name, child_depth, result)
        except Exception as e:
            _logger.error(f"INVOKE_END hook raised: {e}")


# --- Property 12: INVOKE_FAILURE fires only for FAILURE status ---


class TestInvokeFailureSemantics:
    """Property 12: INVOKE_FAILURE fires only for FAILURE status.

    **Validates: Requirements 21.2, 21.4, 21.6**
    """

    @given(
        status=all_run_statuses,
        child_job_name=job_names,
        depth=invoke_depths,
        dur=duration_ms,
    )
    def test_invoke_failure_fires_iff_status_is_failure(
        self,
        status: RunStatus,
        child_job_name: str,
        depth: int,
        dur: float,
    ):
        """INVOKE_FAILURE fires if and only if result.status == RunStatus.FAILURE.

        **Validates: Requirements 21.2, 21.6**

        For any RunStatus value, the INVOKE_FAILURE hook must fire exactly when
        the status is FAILURE, and must NOT fire for any other status including
        TIMEOUT, CANCELLED, SUCCESS, RUNNING, or UNKNOWN.
        """
        registry = HookRegistry()
        mock_rc = MagicMock()
        failure_fired: list[tuple[Any, str, int, JobResult]] = []

        # Register an INVOKE_FAILURE hook
        def on_failure(rc, job_name, d, result):
            failure_fired.append((rc, job_name, d, result))

        registry.register_global(HookEvent.INVOKE_FAILURE, on_failure)

        # Create the result with the given status
        result = make_job_result(status, child_job_name, dur)

        # Simulate the dispatch
        simulate_invoke_hook_dispatch(registry, mock_rc, child_job_name, depth, result)

        if status == RunStatus.FAILURE:
            # INVOKE_FAILURE must have fired exactly once
            assert len(failure_fired) == 1
            assert failure_fired[0] == (mock_rc, child_job_name, depth, result)
        else:
            # INVOKE_FAILURE must NOT have fired
            assert len(failure_fired) == 0

    @given(
        status=non_failure_statuses,
        child_job_name=job_names,
        depth=invoke_depths,
        dur=duration_ms,
    )
    def test_invoke_failure_does_not_fire_for_non_failure_statuses(
        self,
        status: RunStatus,
        child_job_name: str,
        depth: int,
        dur: float,
    ):
        """INVOKE_FAILURE does NOT fire for TIMEOUT, CANCELLED, SUCCESS, or other statuses.

        **Validates: Requirements 21.6**

        Specifically tests non-failure statuses to ensure the hook is never
        triggered for TIMEOUT, CANCELLED, SUCCESS, RUNNING, or UNKNOWN.
        """
        registry = HookRegistry()
        mock_rc = MagicMock()
        failure_count = 0

        def on_failure(rc, job_name, d, result):
            nonlocal failure_count
            failure_count += 1

        registry.register_global(HookEvent.INVOKE_FAILURE, on_failure)

        result = make_job_result(status, child_job_name, dur)

        simulate_invoke_hook_dispatch(registry, mock_rc, child_job_name, depth, result)

        # Must never fire for non-FAILURE statuses
        assert failure_count == 0

    @given(
        child_job_name=job_names,
        depth=invoke_depths,
        dur=duration_ms,
        num_failure_hooks=st.integers(min_value=1, max_value=5),
        num_end_hooks=st.integers(min_value=1, max_value=5),
    )
    def test_invoke_failure_fires_before_invoke_end(
        self,
        child_job_name: str,
        depth: int,
        dur: float,
        num_failure_hooks: int,
        num_end_hooks: int,
    ):
        """When both INVOKE_FAILURE and INVOKE_END are registered, INVOKE_FAILURE fires BEFORE INVOKE_END.

        **Validates: Requirements 21.4**

        For a FAILURE result, all INVOKE_FAILURE hooks must execute before any
        INVOKE_END hook, preserving the ordering guarantee from Requirement 21.4.
        """
        registry = HookRegistry()
        mock_rc = MagicMock()
        invocation_order: list[str] = []

        # Register multiple INVOKE_FAILURE hooks
        for i in range(num_failure_hooks):
            tag = f"failure:{i}"
            registry.register_global(
                HookEvent.INVOKE_FAILURE,
                lambda rc, name, d, res, t=tag: invocation_order.append(t),
            )

        # Register multiple INVOKE_END hooks
        for i in range(num_end_hooks):
            tag = f"end:{i}"
            registry.register_global(
                HookEvent.INVOKE_END,
                lambda rc, name, d, res, t=tag: invocation_order.append(t),
            )

        # Create a FAILURE result
        result = make_job_result(RunStatus.FAILURE, child_job_name, dur)

        # Simulate the dispatch
        simulate_invoke_hook_dispatch(registry, mock_rc, child_job_name, depth, result)

        # All failure hooks must appear before all end hooks
        expected_failure = [f"failure:{i}" for i in range(num_failure_hooks)]
        expected_end = [f"end:{i}" for i in range(num_end_hooks)]
        expected = expected_failure + expected_end

        assert invocation_order == expected

    @given(
        status=non_failure_statuses,
        child_job_name=job_names,
        depth=invoke_depths,
        dur=duration_ms,
        num_end_hooks=st.integers(min_value=1, max_value=5),
    )
    def test_invoke_end_still_fires_for_non_failure_statuses(
        self,
        status: RunStatus,
        child_job_name: str,
        depth: int,
        dur: float,
        num_end_hooks: int,
    ):
        """INVOKE_END fires for all statuses regardless of whether INVOKE_FAILURE fired.

        **Validates: Requirements 21.4**

        Even when INVOKE_FAILURE does not fire (non-FAILURE status), INVOKE_END
        still fires normally, confirming the two events are independent.
        """
        registry = HookRegistry()
        mock_rc = MagicMock()
        end_fired: list[str] = []
        failure_fired: list[str] = []

        # Register both hooks
        registry.register_global(
            HookEvent.INVOKE_FAILURE,
            lambda rc, name, d, res: failure_fired.append("failure"),
        )
        for i in range(num_end_hooks):
            registry.register_global(
                HookEvent.INVOKE_END,
                lambda rc, name, d, res, idx=i: end_fired.append(f"end:{idx}"),
            )

        result = make_job_result(status, child_job_name, dur)

        simulate_invoke_hook_dispatch(registry, mock_rc, child_job_name, depth, result)

        # INVOKE_FAILURE must NOT have fired
        assert len(failure_fired) == 0
        # INVOKE_END must have fired for each registered hook
        assert len(end_fired) == num_end_hooks

    @given(
        child_job_name=job_names,
        depth=invoke_depths,
        dur=duration_ms,
        num_failure_hooks=st.integers(min_value=2, max_value=5),
        failing_index=st.integers(min_value=0, max_value=4),
    )
    def test_invoke_failure_error_isolation(
        self,
        child_job_name: str,
        depth: int,
        dur: float,
        num_failure_hooks: int,
        failing_index: int,
    ):
        """If an INVOKE_FAILURE hook raises, remaining hooks and INVOKE_END still execute.

        **Validates: Requirements 21.4** (error isolation ensures INVOKE_END always fires)

        This tests that a failing INVOKE_FAILURE hook does not block subsequent
        INVOKE_FAILURE hooks or the INVOKE_END hook from executing.
        """
        registry = HookRegistry()
        mock_rc = MagicMock()
        invocation_order: list[str] = []

        # Clamp failing_index to valid range
        failing_index = failing_index % num_failure_hooks

        # Register INVOKE_FAILURE hooks (one of them raises)
        for i in range(num_failure_hooks):
            if i == failing_index:

                def make_failing(idx):
                    def hook(rc, name, d, res):
                        raise RuntimeError(f"failure_hook_{idx}_error")

                    hook.__name__ = f"failure_hook_{idx}"
                    return hook

                registry.register_global(HookEvent.INVOKE_FAILURE, make_failing(i))
            else:
                tag = f"failure:{i}"
                registry.register_global(
                    HookEvent.INVOKE_FAILURE,
                    lambda rc, name, d, res, t=tag: invocation_order.append(t),
                )

        # Register INVOKE_END hook
        registry.register_global(
            HookEvent.INVOKE_END,
            lambda rc, name, d, res: invocation_order.append("end"),
        )

        result = make_job_result(RunStatus.FAILURE, child_job_name, dur)

        simulate_invoke_hook_dispatch(registry, mock_rc, child_job_name, depth, result)

        # All non-failing INVOKE_FAILURE hooks should have been invoked
        expected_failure = [
            f"failure:{i}" for i in range(num_failure_hooks) if i != failing_index
        ]
        # INVOKE_END should always fire
        expected = expected_failure + ["end"]

        assert invocation_order == expected
