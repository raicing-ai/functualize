"""Lightweight performance timeline for startup and runtime profiling.

Records named marks with nanosecond precision. Derives phases from
paired start/end marks. Designed for zero overhead when not queried:
- mark() is a single append to a list + perf_counter_ns() call
- No string formatting, no allocation beyond the tuple

Thread-safe via a simple lock for concurrent mark recording.

Only imports from _types/, _primitives/, and stdlib.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Phase:
    """A computed phase derived from paired start/end marks.

    Attributes:
        name: Phase name (derived from mark name by stripping .start/.end suffix).
        start_ns: Start time in nanoseconds (from perf_counter_ns).
        end_ns: End time in nanoseconds (from perf_counter_ns).
    """

    name: str
    start_ns: int
    end_ns: int

    @property
    def duration_ns(self) -> int:
        """Duration in nanoseconds."""
        return self.end_ns - self.start_ns

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        return (self.end_ns - self.start_ns) / 1_000_000

    @property
    def duration_us(self) -> float:
        """Duration in microseconds."""
        return (self.end_ns - self.start_ns) / 1_000


@dataclass(frozen=True, slots=True)
class PerfReport:
    """Computed performance report from timeline marks.

    Attributes:
        phases: Ordered list of computed phases.
        total_ms: Total time from first to last mark in milliseconds.
        marks: Raw mark data as list of (name, timestamp_ns) tuples.
    """

    phases: list[Phase]
    total_ms: float
    marks: list[tuple[str, int]]

    def phase(self, name: str) -> Phase | None:
        """Look up a phase by name.

        Args:
            name: The phase name (without .start/.end suffix).

        Returns:
            The Phase if found, None otherwise.
        """
        for p in self.phases:
            if p.name == name:
                return p
        return None

    def phases_above(self, threshold_ms: float) -> list[Phase]:
        """Return phases exceeding the given duration threshold.

        Args:
            threshold_ms: Minimum duration in milliseconds.

        Returns:
            List of phases whose duration_ms exceeds threshold_ms.
        """
        return [p for p in self.phases if p.duration_ms > threshold_ms]

    def phases_matching(self, prefix: str) -> list[Phase]:
        """Return phases whose name starts with the given prefix.

        Args:
            prefix: Phase name prefix to match.

        Returns:
            List of matching phases sorted by duration (descending).
        """
        matching = [p for p in self.phases if p.name.startswith(prefix)]
        return sorted(matching, key=lambda p: p.duration_ns, reverse=True)

    def summary(self, include: str | None = None) -> str:
        """Return a human-readable summary of the performance report.

        Includes total time and per-phase durations sorted by duration descending.

        Args:
            include: Optional filter prefix — only show phases matching this prefix.

        Returns:
            Formatted multi-line string with performance data.
        """
        if not self.phases and self.total_ms == 0.0:
            return "No performance data available."

        lines: list[str] = []
        lines.append(f"Total: {self.total_ms:.2f} ms")

        sorted_phases = sorted(self.phases, key=lambda p: p.duration_ns, reverse=True)
        for phase in sorted_phases:
            if include and not phase.name.startswith(include):
                continue
            lines.append(f"  {phase.name}: {phase.duration_ms:.2f} ms")

        if include and len(lines) == 1:
            return "No performance data available."

        return "\n".join(lines)

    def to_json(self, include: str | None = None) -> str:
        """Return a JSON representation of the performance report.

        Args:
            include: Optional filter prefix — only show phases matching this prefix.

        Returns:
            JSON string with performance data.
        """
        import json

        phases = self.phases
        if include:
            phases = [p for p in phases if p.name.startswith(include)]

        data = {
            "total_ms": round(self.total_ms, 2),
            "phases": [
                {"name": p.name, "duration_ms": round(p.duration_ms, 2)}
                for p in sorted(phases, key=lambda p: p.duration_ns, reverse=True)
            ],
            "marks": [{"name": name, "timestamp_ns": ts} for name, ts in self.marks],
        }
        return json.dumps(data)


class PerfTimeline:
    """Lightweight timeline recorder for performance profiling.

    Records named marks with nanosecond precision using time.perf_counter_ns().
    Phases are computed lazily from paired marks (name.start / name.end).

    Thread-safe: marks can be recorded from any thread.

    Usage:
        timeline = PerfTimeline()
        timeline.mark("phase_a.start")
        # ... work ...
        timeline.mark("phase_a.end")

        report = timeline.report()
        print(report.summary())
    """

    __slots__ = ("_marks", "_lock", "_enabled")

    def __init__(self, *, enabled: bool = True) -> None:
        self._marks: list[tuple[str, int]] = []
        self._lock = threading.Lock()
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        """Whether mark recording is active."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable mark recording."""
        self._enabled = value

    def mark(self, name: str) -> None:
        """Record a named mark at the current time.

        Zero-cost when disabled: single boolean check + return.

        Args:
            name: Mark name. Convention: use "phase.start" and "phase.end"
                suffixes for automatic phase derivation. Nested phases
                are supported (e.g., "boot.plugins.start", "boot.plugins.end").
        """
        if not self._enabled:
            return
        ts = time.perf_counter_ns()
        with self._lock:
            self._marks.append((name, ts))

    def mark_start(self, name: str) -> None:
        """Convenience: record a start mark for the given phase name.

        Equivalent to: mark(f"{name}.start")
        """
        self.mark(f"{name}.start")

    def mark_end(self, name: str) -> None:
        """Convenience: record an end mark for the given phase name.

        Equivalent to: mark(f"{name}.end")
        """
        self.mark(f"{name}.end")

    def report(self) -> PerfReport:
        """Compute a performance report from recorded marks.

        Derives phases from paired start/end marks. Unpaired marks are
        ignored in phase computation but included in raw marks.

        Returns:
            A PerfReport with computed phases and total duration.
        """
        with self._lock:
            marks = list(self._marks)

        if not marks:
            return PerfReport(phases=[], total_ms=0.0, marks=[])

        # Compute total span
        first_ts = marks[0][1]
        last_ts = marks[-1][1]
        total_ms = (last_ts - first_ts) / 1_000_000

        # Derive phases from paired marks
        starts: dict[str, int] = {}
        phases: list[Phase] = []

        for name, ts in marks:
            if name.endswith(".start"):
                phase_name = name[: -len(".start")]
                starts[phase_name] = ts
            elif name.endswith(".end"):
                phase_name = name[: -len(".end")]
                if phase_name in starts:
                    phases.append(
                        Phase(
                            name=phase_name,
                            start_ns=starts[phase_name],
                            end_ns=ts,
                        )
                    )
                    del starts[phase_name]

        return PerfReport(phases=phases, total_ms=total_ms, marks=marks)

    def reset(self) -> None:
        """Clear all recorded marks. Useful for testing."""
        with self._lock:
            self._marks.clear()


# Global singleton timeline — records framework-level startup phases
perf_timeline = PerfTimeline()
