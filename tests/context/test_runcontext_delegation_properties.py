"""Property-based tests for RunContext delegation (Property 2).

# Feature: codebase-restructure, Property 2: RunContext delegation preserves behavior

**Validates: Requirements 7.1, 7.2, 7.4, 7.6**

For any valid job name, kwargs, StructuredEvent, or workflow step name, calling
the corresponding RunContext facade method (invoke, invoke_parallel, emit,
track_phase) SHALL produce identical observable effects (return values,
emitted events, state changes) as directly calling the underlying capability
class (Invoke, EventBus.emit, WorkflowTracker.track_step) with the same arguments.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize._engine.capabilities.workflow import WorkflowTracker
from functualize._types.enums import RunStatus
from functualize.job.context import RunContext

# =============================================================================
# Strategies
# =============================================================================

# Strategy: valid job names (alphanumeric + hyphens/underscores)
_job_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

# Strategy: kwargs dictionaries with simple values
_kwargs_values = st.one_of(
    st.integers(min_value=-10000, max_value=10000),
    st.text(min_size=0, max_size=30),
    st.booleans(),
    st.none(),
)

_kwargs_strategy = st.dictionaries(
    keys=st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True),
    values=_kwargs_values,
    min_size=0,
    max_size=5,
)

# Strategy: valid event names ({domain}.{resource}.{action}, at least 3 segments)
_segment = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_event_name_strategy = st.tuples(_segment, _segment, _segment).map(
    lambda parts: f"{parts[0]}.{parts[1]}.{parts[2]}"
)

# Strategy: resource strings
_resource_strategy = st.text(
    min_size=0, max_size=50, alphabet=st.characters(categories=("L", "N", "P"))
)

# Strategy: event payload
_payload_keys = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_payload_values = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(min_size=0, max_size=20),
    st.booleans(),
)
_payload_strategy = st.dictionaries(
    keys=_payload_keys, values=_payload_values, min_size=0, max_size=4
)

# Strategy: workflow step names
_step_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=50,
)

# Strategy: step messages (including overflow past 1000 chars)
_step_message_strategy = st.text(min_size=0, max_size=1200)

# Strategy: step statuses
_step_status_strategy = st.sampled_from(list(RunStatus))

# Strategy: list of jobs for invoke_parallel (1-5 items)
_parallel_jobs_strategy = st.lists(
    st.tuples(_job_name_strategy, _kwargs_strategy),
    min_size=1,
    max_size=5,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_runcontext_with_engine(
    name: str = "test-job",
    event_bus: Any = None,
) -> RunContext:
    """Create a RunContext with a mocked execution engine for delegation testing."""
    config = MagicMock(spec=JobConfigView)
    config.set_prefix = MagicMock()
    logger = MagicMock(spec=logging.Logger)

    app = MagicMock()
    app._surfaces = []
    if event_bus is not None:
        app._event_bus = event_bus
        app.event_bus = event_bus
    else:
        app._event_bus = None
        app.event_bus = MagicMock()

    engine = MagicMock()
    engine._app = app

    rc = RunContext(
        name=name,
        config=config,
        logger=logger,
        _execution_engine=engine,
        _max_invoke_depth=10,
    )
    return rc


def _make_standalone_tracker(
    job_name: str = "test-job",
) -> WorkflowTracker:
    """Create a standalone WorkflowTracker for direct comparison."""
    return WorkflowTracker(
        job_name=job_name,
        run_context=None,
        perf_timeline=None,
        execution_engine=None,
        step_logger=MagicMock(spec=logging.Logger),
    )


# =============================================================================
# Property 2: RunContext delegation preserves behavior
# =============================================================================


class TestRunContextInvokeDelegation:
    """Property 2 (invoke): RunContext.invoke() delegates to Invoke capability.

    For any valid job name and kwargs, calling rc.invoke(job_name, **kwargs)
    produces identical observable effects as calling Invoke.invoke(job_name, **kwargs)
    directly — the same arguments are forwarded to the Invoke capability.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(job_name=_job_name_strategy, kwargs=_kwargs_strategy)
    def test_invoke_delegates_to_invoke_capability(
        self, job_name: str, kwargs: dict[str, Any]
    ) -> None:
        """rc.invoke(job_name, **kwargs) delegates to Invoke.invoke() with same args.

        **Validates: Requirements 7.1, 7.2**
        """
        rc = _make_runcontext_with_engine(name="delegation-test")

        # Mock the Invoke capability that gets lazily created
        mock_invoke = MagicMock()
        expected_result = MagicMock()
        mock_invoke.return_value = expected_result
        rc._invoke_capability = mock_invoke

        # Call through the facade
        result = rc.invoke(job_name, **kwargs)

        # Verify delegation: same job_name and kwargs forwarded
        mock_invoke.assert_called_once_with(job_name, timeout=None, **kwargs)
        # Return value is identical
        assert result is expected_result

    @given(
        job_name=_job_name_strategy,
        kwargs=_kwargs_strategy,
        propagate_scope=st.booleans(),
        timeout=st.one_of(st.none(), st.floats(min_value=0.1, max_value=60.0)),
    )
    def test_invoke_forwards_all_optional_params(
        self,
        job_name: str,
        kwargs: dict[str, Any],
        propagate_scope: bool,
        timeout: float | None,
    ) -> None:
        """rc.invoke() forwards _propagate_scope and timeout to Invoke.invoke().

        **Validates: Requirements 7.1, 7.2**
        """
        rc = _make_runcontext_with_engine(name="delegation-test")

        mock_invoke = MagicMock()
        expected_result = MagicMock()
        mock_invoke.return_value = expected_result
        rc._invoke_capability = mock_invoke

        result = rc.invoke(
            job_name, _propagate_scope=propagate_scope, timeout=timeout, **kwargs
        )

        mock_invoke.assert_called_once_with(job_name, timeout=timeout, **kwargs)
        assert result is expected_result


class TestRunContextInvokeParallelDelegation:
    """Property 2 (invoke_parallel): RunContext.invoke_parallel() delegates to Invoke.parallel().

    For any list of (job_name, kwargs) tuples, calling rc.invoke_parallel(jobs)
    produces identical observable effects as calling Invoke.parallel(jobs) directly.

    **Validates: Requirements 7.1, 7.6**
    """

    @given(jobs=_parallel_jobs_strategy)
    def test_invoke_parallel_delegates_to_invoke_parallel_capability(
        self, jobs: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """rc.invoke_parallel(jobs) delegates to Invoke.parallel(jobs) with same args.

        **Validates: Requirements 7.1, 7.6**
        """
        rc = _make_runcontext_with_engine(name="parallel-test")

        mock_invoke = MagicMock()
        expected_results = [MagicMock() for _ in jobs]
        mock_invoke.parallel.return_value = expected_results
        rc._invoke_capability = mock_invoke

        result = rc.invoke_parallel(jobs)

        # Verify delegation: same jobs list forwarded
        mock_invoke.parallel.assert_called_once_with(jobs)
        # Return value is identical
        assert result is expected_results

    @given(jobs=_parallel_jobs_strategy)
    def test_invoke_parallel_return_value_identity(
        self, jobs: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """The return value from Invoke.parallel() is returned unchanged by the facade.

        **Validates: Requirements 7.1, 7.6**
        """
        rc = _make_runcontext_with_engine(name="parallel-test")

        mock_invoke = MagicMock()
        # Generate a unique list of mock results
        expected_results = [MagicMock(name=f"result-{i}") for i in range(len(jobs))]
        mock_invoke.parallel.return_value = expected_results
        rc._invoke_capability = mock_invoke

        result = rc.invoke_parallel(jobs)

        assert len(result) == len(jobs)
        for actual, expected in zip(result, expected_results, strict=False):
            assert actual is expected


class TestRunContextEmitDelegation:
    """Property 2 (emit): RunContext.emit() delegates to EventBus.emit().

    For any valid event_name, resource, and payload kwargs, calling rc.emit()
    produces identical observable effects as calling EventBus.emit() directly
    with the same arguments.

    **Validates: Requirements 7.4**
    """

    @given(
        event_name=_event_name_strategy,
        resource=_resource_strategy,
        payload=_payload_strategy,
    )
    def test_emit_delegates_to_event_bus(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """rc.emit(event_name, resource, **payload) delegates to EventBus.emit() with same args.

        **Validates: Requirements 7.4**
        """
        event_bus = MagicMock()
        rc = _make_runcontext_with_engine(name="emit-test", event_bus=event_bus)

        rc.emit(event_name, resource=resource, **payload)

        # EventBus.emit called with same arguments
        event_bus.emit.assert_called_once_with(event_name, resource=resource, **payload)

    @given(
        event_name=_event_name_strategy,
        resource=_resource_strategy,
    )
    def test_emit_with_no_payload_delegates_correctly(
        self, event_name: str, resource: str
    ) -> None:
        """rc.emit(event_name, resource) delegates with no extra payload kwargs.

        **Validates: Requirements 7.4**
        """
        event_bus = MagicMock()
        rc = _make_runcontext_with_engine(name="emit-test", event_bus=event_bus)

        rc.emit(event_name, resource=resource)

        event_bus.emit.assert_called_once_with(event_name, resource=resource)

    @given(
        event_name=_event_name_strategy,
        payload=_payload_strategy,
    )
    def test_emit_with_default_resource_delegates_correctly(
        self, event_name: str, payload: dict[str, Any]
    ) -> None:
        """rc.emit(event_name, **payload) uses default empty resource.

        **Validates: Requirements 7.4**
        """
        event_bus = MagicMock()
        rc = _make_runcontext_with_engine(name="emit-test", event_bus=event_bus)

        rc.emit(event_name, **payload)

        event_bus.emit.assert_called_once_with(event_name, resource="", **payload)


class TestRunContextTrackPhaseDelegation:
    """Property 2 (track_phase): RunContext.track_phase() delegates to WorkflowTracker.

    For any valid step name, message, and status, calling rc.track_phase()
    produces identical observable effects (step state changes) as calling
    WorkflowTracker.track_step() directly with the same arguments.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(
        step_name=_step_name_strategy,
        step_message=_step_message_strategy,
        step_status=_step_status_strategy,
    )
    def test_track_phase_delegates_to_tracker(
        self, step_name: str, step_message: str, step_status: RunStatus
    ) -> None:
        """rc.track_phase() delegates to WorkflowTracker.track_step() with same args.

        **Validates: Requirements 7.1, 7.2**
        """
        rc = _make_runcontext_with_engine(name="workflow-test")

        # Mock the WorkflowTracker
        mock_tracker = MagicMock(spec=WorkflowTracker)
        rc._workflow_tracker = mock_tracker

        rc.track_phase(step_name, step_message, step_status)

        mock_tracker.track_step.assert_called_once_with(
            step_name, step_message, step_status
        )

    @given(
        step_name=_step_name_strategy,
        step_message=_step_message_strategy,
        step_status=_step_status_strategy,
    )
    def test_track_phase_state_matches_direct_tracker_call(
        self, step_name: str, step_message: str, step_status: RunStatus
    ) -> None:
        """Calling rc.track_phase() produces identical step state as calling
        WorkflowTracker.track_step() directly.

        **Validates: Requirements 7.1, 7.2**
        """
        # Create RunContext and track step via facade
        rc = _make_runcontext_with_engine(name="workflow-test")
        # Create a real tracker for the RunContext
        real_tracker_for_rc = WorkflowTracker(
            job_name="workflow-test",
            run_context=rc,
            perf_timeline=None,
            execution_engine=None,
            step_logger=MagicMock(spec=logging.Logger),
        )
        rc._workflow_tracker = real_tracker_for_rc

        # Create a standalone tracker and call directly
        standalone_tracker = _make_standalone_tracker(job_name="workflow-test")

        # Call through facade
        rc.track_phase(step_name, step_message, step_status)

        # Call directly on standalone tracker
        standalone_tracker.track_step(step_name, step_message, step_status)

        # Compare observable state
        facade_steps = real_tracker_for_rc.steps
        direct_steps = standalone_tracker.steps

        assert len(facade_steps) == len(direct_steps)
        assert len(facade_steps) == 1

        facade_step = facade_steps[0]
        direct_step = direct_steps[0]

        # Same name, status, message
        assert facade_step["name"] == direct_step["name"]
        assert facade_step["status"] == direct_step["status"]
        assert facade_step["message"] == direct_step["message"]
        # Both have start_time set (not None)
        assert facade_step["start_time"] is not None
        assert direct_step["start_time"] is not None

    @given(
        steps=st.lists(
            st.tuples(
                _step_name_strategy, _step_message_strategy, _step_status_strategy
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0],
        ),
    )
    def test_multiple_steps_produce_identical_state_via_facade_and_direct(
        self, steps: list[tuple[str, str, RunStatus]]
    ) -> None:
        """For any sequence of distinct workflow steps, the facade and direct calls
        produce identical step lists (same names, statuses, messages in same order).

        **Validates: Requirements 7.1, 7.2**
        """
        # Create RunContext path
        rc = _make_runcontext_with_engine(name="multi-step-test")
        facade_tracker = WorkflowTracker(
            job_name="multi-step-test",
            run_context=rc,
            perf_timeline=None,
            execution_engine=None,
            step_logger=MagicMock(spec=logging.Logger),
        )
        rc._workflow_tracker = facade_tracker

        # Create direct path
        direct_tracker = _make_standalone_tracker(job_name="multi-step-test")

        # Execute same operations through both paths
        for step_name, step_message, step_status in steps:
            rc.track_phase(step_name, step_message, step_status)
            direct_tracker.track_step(step_name, step_message, step_status)

        # Compare: same number of steps in same order
        facade_steps = facade_tracker.steps
        direct_steps = direct_tracker.steps

        assert len(facade_steps) == len(direct_steps)

        for facade_step, direct_step in zip(facade_steps, direct_steps, strict=False):
            assert facade_step["name"] == direct_step["name"]
            assert facade_step["status"] == direct_step["status"]
            assert facade_step["message"] == direct_step["message"]
            # Timing fields are populated for both
            assert facade_step["start_time"] is not None
            assert direct_step["start_time"] is not None
            # Terminal states have end_time set in both
            if facade_step["status"] in (
                RunStatus.SUCCESS,
                RunStatus.FAILURE,
                RunStatus.CANCELLED,
                RunStatus.TIMEOUT,
            ):
                assert facade_step["end_time"] is not None
                assert direct_step["end_time"] is not None
