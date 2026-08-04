# Feature: perf-timeline-mark, Property 1: Mark prefixing correctness
"""Property-based tests for RunContext mark prefixing correctness.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5

Property 1: For any valid job name and valid mark name, calling perf_mark(name) on a
RunContext SHALL record a mark whose name equals "{job_name}.{name}", calling
perf_mark_start(name) SHALL record "{job_name}.{name}.start", and calling
perf_mark_end(name) SHALL record "{job_name}.{name}.end".
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._events.perf import PerfTimeline
from functualize.job.context import RunContext

# --- Strategies ---

# Job names: alphanumeric + hyphens, 1-20 chars
job_name_strategy = st.from_regex(r"[a-zA-Z0-9\-]{1,20}", fullmatch=True)

# Mark names: alphanumeric + dots + hyphens, 1-50 chars
mark_name_strategy = st.from_regex(r"[a-zA-Z0-9.\-]{1,50}", fullmatch=True)


def _make_run_context(job_name: str, timeline: PerfTimeline) -> RunContext:
    """Create a RunContext with injected PerfTimeline and the given job name."""
    mock_config = MagicMock()
    mock_logger = MagicMock()
    return RunContext(
        name=job_name,
        config=mock_config,
        logger=mock_logger,
        perf_timeline=timeline,
    )


class TestMarkPrefixingCorrectness:
    """Property 1: Mark prefixing correctness.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    """

    @given(job_name=job_name_strategy, mark_name=mark_name_strategy)
    @settings(max_examples=100)
    def test_perf_mark_prefixes_with_job_name(
        self, job_name: str, mark_name: str
    ) -> None:
        """perf_mark(name) records a mark named '{job_name}.{name}'.

        **Validates: Requirements 2.1**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        rc.perf_mark(mark_name)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected = f"{job_name}.{mark_name}"
        assert expected in recorded_names, (
            f"Expected mark '{expected}' not found in {recorded_names}"
        )

    @given(job_name=job_name_strategy, mark_name=mark_name_strategy)
    @settings(max_examples=100)
    def test_perf_mark_start_prefixes_with_job_name_and_start_suffix(
        self, job_name: str, mark_name: str
    ) -> None:
        """perf_mark_start(name) records a mark named '{job_name}.{name}.start'.

        **Validates: Requirements 2.2, 2.4**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        rc.perf_mark_start(mark_name)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected = f"{job_name}.{mark_name}.start"
        assert expected in recorded_names, (
            f"Expected mark '{expected}' not found in {recorded_names}"
        )

    @given(job_name=job_name_strategy, mark_name=mark_name_strategy)
    @settings(max_examples=100)
    def test_perf_mark_end_prefixes_with_job_name_and_end_suffix(
        self, job_name: str, mark_name: str
    ) -> None:
        """perf_mark_end(name) records a mark named '{job_name}.{name}.end'.

        **Validates: Requirements 2.3, 2.5**
        """
        timeline = PerfTimeline(enabled=True)
        rc = _make_run_context(job_name, timeline)

        rc.perf_mark_end(mark_name)

        report = timeline.report()
        recorded_names = [name for name, _ in report.marks]
        expected = f"{job_name}.{mark_name}.end"
        assert expected in recorded_names, (
            f"Expected mark '{expected}' not found in {recorded_names}"
        )
