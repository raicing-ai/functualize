"""Unit tests for the PerfTimeline module."""

from __future__ import annotations

import time

from functualize._events.perf import PerfTimeline


class TestPerfTimeline:
    """Tests for PerfTimeline mark recording and report generation."""

    def test_empty_report(self) -> None:
        """Empty timeline produces empty report."""
        tl = PerfTimeline()
        report = tl.report()
        assert report.phases == []
        assert report.total_ms == 0.0
        assert report.marks == []

    def test_single_phase(self) -> None:
        """Paired start/end marks produce a phase."""
        tl = PerfTimeline()
        tl.mark("test_phase.start")
        time.sleep(0.001)  # 1ms
        tl.mark("test_phase.end")

        report = tl.report()
        assert len(report.phases) == 1
        phase = report.phases[0]
        assert phase.name == "test_phase"
        assert phase.duration_ms >= 0.5  # At least ~0.5ms (sleep imprecision)
        assert phase.duration_ns > 0

    def test_nested_phases(self) -> None:
        """Nested phases are correctly paired."""
        tl = PerfTimeline()
        tl.mark("outer.start")
        tl.mark("inner.start")
        time.sleep(0.001)
        tl.mark("inner.end")
        tl.mark("outer.end")

        report = tl.report()
        assert len(report.phases) == 2

        inner = report.phase("inner")
        outer = report.phase("outer")
        assert inner is not None
        assert outer is not None
        assert outer.duration_ns >= inner.duration_ns

    def test_convenience_mark_start_end(self) -> None:
        """mark_start/mark_end convenience methods work."""
        tl = PerfTimeline()
        tl.mark_start("my_phase")
        time.sleep(0.001)
        tl.mark_end("my_phase")

        report = tl.report()
        phase = report.phase("my_phase")
        assert phase is not None
        assert phase.duration_ms >= 0.5

    def test_disabled_timeline(self) -> None:
        """Disabled timeline records nothing."""
        tl = PerfTimeline(enabled=False)
        tl.mark("something.start")
        tl.mark("something.end")

        report = tl.report()
        assert report.marks == []
        assert report.phases == []

    def test_phases_above_threshold(self) -> None:
        """phases_above filters correctly."""
        tl = PerfTimeline()
        tl.mark("fast.start")
        tl.mark("fast.end")
        tl.mark("slow.start")
        time.sleep(0.005)  # ~5ms
        tl.mark("slow.end")

        report = tl.report()
        slow_phases = report.phases_above(2.0)  # > 2ms
        assert len(slow_phases) >= 1
        assert any(p.name == "slow" for p in slow_phases)

    def test_unpaired_marks_ignored_in_phases(self) -> None:
        """Unpaired marks appear in raw marks but not phases."""
        tl = PerfTimeline()
        tl.mark("orphan.start")
        tl.mark("complete.start")
        tl.mark("complete.end")

        report = tl.report()
        assert len(report.marks) == 3
        assert len(report.phases) == 1
        assert report.phases[0].name == "complete"

    def test_reset_clears_marks(self) -> None:
        """reset() clears all recorded marks."""
        tl = PerfTimeline()
        tl.mark("a.start")
        tl.mark("a.end")
        tl.reset()

        report = tl.report()
        assert report.marks == []

    def test_summary_output(self) -> None:
        """summary() returns a human-readable string."""
        tl = PerfTimeline()
        tl.mark("boot.start")
        time.sleep(0.001)
        tl.mark("boot.end")

        report = tl.report()
        summary = report.summary()
        assert "Total:" in summary
        assert "boot:" in summary

    def test_total_ms_spans_all_marks(self) -> None:
        """total_ms covers first to last mark."""
        tl = PerfTimeline()
        tl.mark("first")
        time.sleep(0.002)
        tl.mark("last")

        report = tl.report()
        assert report.total_ms >= 1.0  # At least ~1ms
