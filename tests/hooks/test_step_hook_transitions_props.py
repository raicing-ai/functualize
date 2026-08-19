"""Property-based tests for step hook transitions (Property 11).

Property 11: Step hooks fire on correct transitions
- ON_PHASE_START fires only on NEW step creation (first call with step_name), not updates
- ON_PHASE_FAILURE fires for each call with RunStatus.FAILURE status
- ON_PHASE_COMPLETE fires for each call with RunStatus.SUCCESS status
- These are independent: a step created with FAILURE should fire both START and FAILURE

**Validates: Requirements 19.2, 20.2, 32.1, 32.2, 32.3**
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize._events.hooks import HookRegistry
from functualize.job.context import RunContext, RunStatus

# --- Strategies ---

# Strategy for valid step names (non-empty alphanumeric + dashes/underscores)
step_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

# Strategy for step messages
step_messages = st.text(min_size=0, max_size=200)

# Strategy for step statuses (all valid RunStatus values)
step_statuses = st.sampled_from(list(RunStatus))

# Strategy for generating a list of (step_name, status) tuples
step_sequences = st.lists(
    st.tuples(step_names, step_statuses, step_messages),
    min_size=1,
    max_size=20,
)


# --- Helpers ---


def make_run_context_with_hooks(
    name: str = "test-job",
) -> tuple[RunContext, HookRegistry]:
    """Create a RunContext wired to a HookRegistry via a fake execution engine."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()

    hook_registry = HookRegistry()

    # Create a fake execution engine that exposes _hook_registry
    fake_engine = MagicMock()
    fake_engine._hook_registry = hook_registry

    rc = RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        _execution_engine=fake_engine,
    )
    return rc, hook_registry


# Feature: functualize, Property 11: Step hooks fire on correct transitions
# **Validates: Requirements 19.2, 20.2, 32.1, 32.2, 32.3**
class TestStepHookTransitions:
    """Property 11: Step hooks fire on correct transitions.

    Verifies that ON_PHASE_START, ON_PHASE_FAILURE, and ON_PHASE_COMPLETE
    fire at the correct times based on step creation vs update and status.
    """

    @given(steps=step_sequences)
    def test_on_phase_start_fires_only_on_new_step_creation(
        self, steps: list[tuple[str, RunStatus, str]]
    ) -> None:
        """ON_PHASE_START fires exactly once per unique step name (first call only).

        **Validates: Requirements 32.1, 32.2, 32.3**
        """
        rc, registry = make_run_context_with_hooks()
        start_fired: list[str] = []

        # Register a global ON_PHASE_START hook
        def on_start(rc_arg, step_name, step_status, step_message):
            start_fired.append(step_name)

        registry.register_global("on_phase_start", on_start)

        # Track steps in sequence
        for step_name, status, message in steps:
            rc.track_phase(step_name, message, status)

        # ON_PHASE_START should fire exactly once per unique step name
        unique_names_in_order: list[str] = []
        seen: set[str] = set()
        for step_name, _, _ in steps:
            if step_name not in seen:
                unique_names_in_order.append(step_name)
                seen.add(step_name)

        assert start_fired == unique_names_in_order

    @given(steps=step_sequences)
    def test_on_phase_failure_fires_for_each_failure_status(
        self, steps: list[tuple[str, RunStatus, str]]
    ) -> None:
        """ON_PHASE_FAILURE fires for each call with RunStatus.FAILURE status,
        regardless of whether step is new or updated.

        **Validates: Requirements 19.2**
        """
        rc, registry = make_run_context_with_hooks()
        failure_fired: list[tuple[str, RunStatus]] = []

        # Register a global ON_PHASE_FAILURE hook
        def on_failure(rc_arg, step_name, step_status, step_message):
            failure_fired.append((step_name, step_status))

        registry.register_global("on_phase_failure", on_failure)

        # Track steps in sequence
        for step_name, status, message in steps:
            rc.track_phase(step_name, message, status)

        # ON_PHASE_FAILURE should fire for every call where status is FAILURE
        expected_failures = [
            (step_name, RunStatus.FAILURE)
            for step_name, status, _ in steps
            if status == RunStatus.FAILURE
        ]

        assert failure_fired == expected_failures

    @given(steps=step_sequences)
    def test_on_phase_complete_fires_for_each_success_status(
        self, steps: list[tuple[str, RunStatus, str]]
    ) -> None:
        """ON_PHASE_COMPLETE fires for each call with RunStatus.SUCCESS status.

        **Validates: Requirements 20.2**
        """
        rc, registry = make_run_context_with_hooks()
        complete_fired: list[tuple[str, RunStatus]] = []

        # Register a global ON_PHASE_COMPLETE hook
        def on_complete(rc_arg, step_name, step_status, step_message):
            complete_fired.append((step_name, step_status))

        registry.register_global("on_phase_complete", on_complete)

        # Track steps in sequence
        for step_name, status, message in steps:
            rc.track_phase(step_name, message, status)

        # ON_PHASE_COMPLETE should fire for every call where status is SUCCESS
        expected_completions = [
            (step_name, RunStatus.SUCCESS)
            for step_name, status, _ in steps
            if status == RunStatus.SUCCESS
        ]

        assert complete_fired == expected_completions

    @given(
        step_name=step_names,
        message=step_messages,
    )
    def test_step_created_with_failure_fires_both_start_and_failure(
        self, step_name: str, message: str
    ) -> None:
        """A step created with FAILURE status fires both ON_PHASE_START and
        ON_PHASE_FAILURE (they are independent events).

        **Validates: Requirements 19.2, 32.2**
        """
        rc, registry = make_run_context_with_hooks()
        events_fired: list[str] = []

        def on_start(rc_arg, sn, ss, sm):
            events_fired.append("start")

        def on_failure(rc_arg, sn, ss, sm):
            events_fired.append("failure")

        def on_complete(rc_arg, sn, ss, sm):
            events_fired.append("complete")

        registry.register_global("on_phase_start", on_start)
        registry.register_global("on_phase_failure", on_failure)
        registry.register_global("on_phase_complete", on_complete)

        # Create a step with FAILURE status
        rc.track_phase(step_name, message, RunStatus.FAILURE)

        # Both START and FAILURE should fire, but not COMPLETE
        assert "start" in events_fired
        assert "failure" in events_fired
        assert "complete" not in events_fired

    @given(
        step_name=step_names,
        message=step_messages,
    )
    def test_step_created_with_success_fires_both_start_and_complete(
        self, step_name: str, message: str
    ) -> None:
        """A step created with SUCCESS status fires both ON_PHASE_START and
        ON_PHASE_COMPLETE (they are independent events).

        **Validates: Requirements 20.2, 32.2**
        """
        rc, registry = make_run_context_with_hooks()
        events_fired: list[str] = []

        def on_start(rc_arg, sn, ss, sm):
            events_fired.append("start")

        def on_failure(rc_arg, sn, ss, sm):
            events_fired.append("failure")

        def on_complete(rc_arg, sn, ss, sm):
            events_fired.append("complete")

        registry.register_global("on_phase_start", on_start)
        registry.register_global("on_phase_failure", on_failure)
        registry.register_global("on_phase_complete", on_complete)

        # Create a step with SUCCESS status
        rc.track_phase(step_name, message, RunStatus.SUCCESS)

        # Both START and COMPLETE should fire, but not FAILURE
        assert "start" in events_fired
        assert "complete" in events_fired
        assert "failure" not in events_fired

    @given(
        step_name=step_names,
        msg1=step_messages,
        msg2=step_messages,
    )
    def test_update_does_not_fire_start_but_fires_status_hooks(
        self, step_name: str, msg1: str, msg2: str
    ) -> None:
        """Updating an existing step does NOT fire ON_PHASE_START again,
        but DOES fire status-specific hooks if applicable.

        **Validates: Requirements 32.3**
        """
        rc, registry = make_run_context_with_hooks()
        start_count = [0]
        failure_count = [0]

        def on_start(rc_arg, sn, ss, sm):
            start_count[0] += 1

        def on_failure(rc_arg, sn, ss, sm):
            failure_count[0] += 1

        registry.register_global("on_phase_start", on_start)
        registry.register_global("on_phase_failure", on_failure)

        # First call: creates step (RUNNING status, no failure/complete hook)
        rc.track_phase(step_name, msg1, RunStatus.RUNNING)
        assert start_count[0] == 1

        # Second call: updates step (FAILURE status)
        rc.track_phase(step_name, msg2, RunStatus.FAILURE)
        # START should NOT fire again
        assert start_count[0] == 1
        # FAILURE should fire on update
        assert failure_count[0] == 1

    @given(
        steps=st.lists(
            st.tuples(step_names, step_statuses, step_messages),
            min_size=1,
            max_size=15,
        )
    )
    def test_hook_counts_match_expected_totals(
        self, steps: list[tuple[str, RunStatus, str]]
    ) -> None:
        """Total hook fire counts match the expected totals across all calls.

        - start_count == number of unique step names
        - failure_count == number of calls with FAILURE status
        - complete_count == number of calls with SUCCESS status

        **Validates: Requirements 19.2, 20.2, 32.1, 32.2, 32.3**
        """
        rc, registry = make_run_context_with_hooks()
        start_count = [0]
        failure_count = [0]
        complete_count = [0]

        registry.register_global(
            "on_phase_start",
            lambda rc, sn, ss, sm: start_count.__setitem__(0, start_count[0] + 1),
        )
        registry.register_global(
            "on_phase_failure",
            lambda rc, sn, ss, sm: failure_count.__setitem__(0, failure_count[0] + 1),
        )
        registry.register_global(
            "on_phase_complete",
            lambda rc, sn, ss, sm: complete_count.__setitem__(0, complete_count[0] + 1),
        )

        # Track all steps
        for step_name, status, message in steps:
            rc.track_phase(step_name, message, status)

        # Compute expected counts
        unique_step_names = set()
        expected_start = 0
        expected_failure = 0
        expected_complete = 0

        for step_name, status, _ in steps:
            if step_name not in unique_step_names:
                expected_start += 1
                unique_step_names.add(step_name)
            if status == RunStatus.FAILURE:
                expected_failure += 1
            if status == RunStatus.SUCCESS:
                expected_complete += 1

        assert start_count[0] == expected_start
        assert failure_count[0] == expected_failure
        assert complete_count[0] == expected_complete
