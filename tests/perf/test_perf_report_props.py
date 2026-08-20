# Feature: perf-timeline-mark, Property 6: JSON projection
"""Property-based tests for the PerfReport JSON projection.

**Validates: Requirements 7.5**

Property 6: JSON projection
`to_json()` is a *rounded view* of a report, not a serialization format —
there is no `from_json`, durations are emitted as `duration_ms` rounded to two
decimals, and phases come out ordered by duration descending. So the property
is projection fidelity, not round-trip equality: every phase appears exactly
once, under its own name, with its duration rounded the documented way, and the
ordering the caller is promised.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._events.perf import PerfReport, Phase

# --- Strategies ---

# Phase name segment: 1-8 lowercase alpha chars
_segment = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    min_size=1,
    max_size=8,
)

# Phase name: 1-4 dot-delimited segments (e.g., "boot.plugins.load")
_phase_name = st.lists(_segment, min_size=1, max_size=4).map(".".join)

# Mark name: reuse phase name strategy
_mark_name = _phase_name

# Timestamps in nanoseconds (realistic range)
_timestamp_ns = st.integers(min_value=0, max_value=10**15)


@st.composite
def _phase_strategy(draw: st.DrawFn) -> Phase:
    """Generate a random Phase with valid start_ns <= end_ns."""
    name = draw(_phase_name)
    start_ns = draw(_timestamp_ns)
    # end_ns must be >= start_ns
    duration = draw(st.integers(min_value=0, max_value=10**9))
    end_ns = start_ns + duration
    return Phase(name=name, start_ns=start_ns, end_ns=end_ns)


# List of phases (0-10)
_phases = st.lists(_phase_strategy(), min_size=0, max_size=10)

# List of marks as (name, timestamp_ns) tuples (0-15)
_marks = st.lists(
    st.tuples(_mark_name, _timestamp_ns),
    min_size=0,
    max_size=15,
)


@st.composite
def _perf_report_strategy(draw: st.DrawFn) -> PerfReport:
    """Generate a random PerfReport with consistent total_ms."""
    phases = draw(_phases)
    marks = draw(_marks)

    # Compute total_ms from phases if non-empty, otherwise from marks
    if phases:
        all_times = [p.start_ns for p in phases] + [p.end_ns for p in phases]
        total_ms = (max(all_times) - min(all_times)) / 1_000_000
    elif marks:
        timestamps = [ts for _, ts in marks]
        total_ms = (max(timestamps) - min(timestamps)) / 1_000_000
    else:
        total_ms = 0.0

    return PerfReport(phases=phases, total_ms=total_ms, marks=marks)


class TestJSONProjectionProperty:
    """Property 6: JSON projection fidelity."""

    @given(report=_perf_report_strategy())
    def test_json_phases_are_projected_once_each(self, report: PerfReport) -> None:
        """Every phase appears exactly once, with its rounded duration."""
        data = json.loads(report.to_json())
        json_phases = data["phases"]

        assert len(json_phases) == len(report.phases)
        assert [p["name"] for p in json_phases] == [
            p.name
            for p in sorted(report.phases, key=lambda p: p.duration_ns, reverse=True)
        ]
        for entry in json_phases:
            assert set(entry) == {"name", "duration_ms"}

    @given(report=_perf_report_strategy())
    def test_json_phases_are_ordered_by_duration_descending(
        self, report: PerfReport
    ) -> None:
        """Phases are emitted slowest-first, which is what the report is read for."""
        data = json.loads(report.to_json())
        durations = [p["duration_ms"] for p in data["phases"]]

        assert durations == sorted(durations, reverse=True)

    @given(report=_perf_report_strategy())
    def test_json_total_ms_is_rounded_not_exact(self, report: PerfReport) -> None:
        """total_ms is rounded to 2dp — a sub-microsecond total lands on 0.0."""
        data = json.loads(report.to_json())

        assert data["total_ms"] == round(report.total_ms, 2)

    @given(report=_perf_report_strategy())
    def test_json_marks_are_preserved_exactly(self, report: PerfReport) -> None:
        """Marks carry raw nanosecond timestamps and are not rounded."""
        data = json.loads(report.to_json())

        assert [(m["name"], m["timestamp_ns"]) for m in data["marks"]] == list(
            report.marks
        )


# Feature: perf-timeline-mark, Property 4: PerfReport is immutable
# **Validates: Requirements 5.1**
#
# `PerfReport.filter(include, exclude)` no longer exists; narrowing is done by
# the read-only selectors (`phases_matching`, `phases_above`) and by
# `to_json(include=)` / `summary(include=)`, which build a view without
# touching the report. The invariant the old filter tests guarded — that
# narrowing cannot mutate the original — is now carried by the type itself,
# so that is what gets asserted.


class TestPerfReportImmutabilityProperty:
    """Property 4: a report cannot be mutated, and narrowing it does not try."""

    @given(report=_perf_report_strategy(), prefix=_segment)
    def test_report_fields_are_frozen(self, report: PerfReport, prefix: str) -> None:
        """Assigning to any field raises — PerfReport is a frozen dataclass."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.total_ms = 1.0  # type: ignore[misc]

    @given(report=_perf_report_strategy(), prefix=_segment)
    def test_narrowing_does_not_mutate_the_report(
        self, report: PerfReport, prefix: str
    ) -> None:
        """The selectors and views leave the original phase list untouched."""
        original_phases = list(report.phases)

        report.phases_matching(prefix)
        report.phases_above(0.0)
        report.to_json(include=prefix)
        report.summary(include=prefix)

        assert report.phases == original_phases

    @given(report=_perf_report_strategy(), prefix=_segment)
    def test_narrowing_returns_a_subset_of_the_phases(
        self, report: PerfReport, prefix: str
    ) -> None:
        """A narrowed view only ever contains phases the report already had."""
        matched = report.phases_matching(prefix)

        assert all(p in report.phases for p in matched)
        assert all(p.name.startswith(prefix) for p in matched)
