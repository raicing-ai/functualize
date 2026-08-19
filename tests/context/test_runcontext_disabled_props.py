# Feature: perf-timeline-mark, Property 2: Disabled timeline no-op
"""Property-based tests for disabled timeline no-op behavior.

Property 2: For any sequence of mark operations (perf_mark, perf_mark_start,
perf_mark_end) performed while the PerfTimeline is disabled, the timeline's
mark list SHALL remain unchanged (no marks added).

**Validates: Requirements 2.6, 4.5**
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from functualize._events.perf import PerfTimeline
from functualize.job.context import RunContext

# --- Strategies ---

# Valid mark names: non-empty strings up to 256 characters using
# letters, numbers, hyphens, dots, and underscores.
valid_mark_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd"), include_characters="._"),
    min_size=1,
    max_size=256,
)

# Valid job names
valid_job_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

# Mark operation types
mark_operations = st.sampled_from(["perf_mark", "perf_mark_start", "perf_mark_end"])

# A single mark operation: (operation_name, mark_name)
mark_op_with_name = st.tuples(mark_operations, valid_mark_names)

# A sequence of mark operations
mark_op_sequences = st.lists(mark_op_with_name, min_size=1, max_size=20)


# --- Helpers ---


def make_disabled_run_context(name: str) -> tuple[RunContext, PerfTimeline]:
    """Create a RunContext with a DISABLED PerfTimeline."""
    disabled_timeline = PerfTimeline(enabled=False)
    mock_config = MagicMock()
    mock_logger = MagicMock()
    rc = RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        perf_timeline=disabled_timeline,
    )
    return rc, disabled_timeline


def execute_mark_operation(rc: RunContext, op: str, name: str) -> None:
    """Execute a mark operation on the RunContext."""
    if op == "perf_mark":
        rc.perf_mark(name)
    elif op == "perf_mark_start":
        rc.perf_mark_start(name)
    elif op == "perf_mark_end":
        rc.perf_mark_end(name)


# --- Property Tests ---


class TestDisabledTimelineNoOp:
    """Property 2: Disabled timeline no-op.

    For any sequence of mark operations with disabled timeline,
    verify no marks are added.
    """

    @given(job_name=valid_job_names, operations=mark_op_sequences)
    def test_no_marks_added_with_disabled_timeline(
        self,
        job_name: str,
        operations: list[tuple[str, str]],
    ) -> None:
        """For any sequence of mark operations with disabled timeline, no marks are recorded.

        **Validates: Requirements 2.6, 4.5**
        """
        rc, disabled_timeline = make_disabled_run_context(job_name)

        # Execute all mark operations
        for op, name in operations:
            execute_mark_operation(rc, op, name)

        # Verify: timeline has zero marks after all operations
        report = disabled_timeline.report()
        assert report.marks == [], (
            f"Expected no marks with disabled timeline, "
            f"but found {len(report.marks)} marks: {report.marks}"
        )

    @given(job_name=valid_job_names, mark_name=valid_mark_names)
    def test_perf_mark_noop_when_disabled(
        self,
        job_name: str,
        mark_name: str,
    ) -> None:
        """perf_mark is a no-op when timeline is disabled.

        **Validates: Requirements 2.6, 4.5**
        """
        rc, disabled_timeline = make_disabled_run_context(job_name)

        rc.perf_mark(mark_name)

        report = disabled_timeline.report()
        assert report.marks == []

    @given(job_name=valid_job_names, mark_name=valid_mark_names)
    def test_perf_mark_start_noop_when_disabled(
        self,
        job_name: str,
        mark_name: str,
    ) -> None:
        """perf_mark_start is a no-op when timeline is disabled.

        **Validates: Requirements 2.6, 4.5**
        """
        rc, disabled_timeline = make_disabled_run_context(job_name)

        rc.perf_mark_start(mark_name)

        report = disabled_timeline.report()
        assert report.marks == []

    @given(job_name=valid_job_names, mark_name=valid_mark_names)
    def test_perf_mark_end_noop_when_disabled(
        self,
        job_name: str,
        mark_name: str,
    ) -> None:
        """perf_mark_end is a no-op when timeline is disabled.

        **Validates: Requirements 2.6, 4.5**
        """
        rc, disabled_timeline = make_disabled_run_context(job_name)

        rc.perf_mark_end(mark_name)

        report = disabled_timeline.report()
        assert report.marks == []

    @given(job_name=valid_job_names, operations=mark_op_sequences)
    def test_no_phases_with_disabled_timeline(
        self,
        job_name: str,
        operations: list[tuple[str, str]],
    ) -> None:
        """No phases are derived when timeline is disabled, regardless of operations.

        **Validates: Requirements 2.6, 4.5**
        """
        rc, disabled_timeline = make_disabled_run_context(job_name)

        # Execute all mark operations
        for op, name in operations:
            execute_mark_operation(rc, op, name)

        # Verify: no phases exist either
        report = disabled_timeline.report()
        assert report.phases == []
        assert report.total_ms == 0.0
