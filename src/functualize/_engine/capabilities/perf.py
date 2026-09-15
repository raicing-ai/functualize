"""Perf capability — performance measurement interface.

Defines the Perf class and its supporting Phase dataclass.
The actual implementation is backed by the observability layer
and wired at runtime. This class raises NotImplementedError until wired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from functualize._engine.capabilities.spec import CapabilitySpec


@dataclass(frozen=True)
class Phase:
    """A recorded performance phase with timing information.

    Attributes:
        name: The phase identifier.
        start_ms: Start time in milliseconds (relative to invocation start).
        end_ms: End time in milliseconds (relative to invocation start), or None if still running.
        duration_ms: Duration in milliseconds, or None if not yet ended.
    """

    name: str
    start_ms: float
    end_ms: float | None = None
    duration_ms: float | None = None


class Perf:
    """Performance measurement capability.

    Provides methods for marking instants and measuring durations
    during job execution. The actual implementation is backed by the
    observability layer and wired at runtime.

    This class raises NotImplementedError until wired.
    """

    def mark(self, name: str) -> None:
        """Record an instant performance mark.

        Args:
            name: The mark name (non-empty, max 256 characters).

        Raises:
            NotImplementedError: Until wired by the observability layer.
        """
        raise NotImplementedError(
            "Perf.mark is not wired. "
            "This instance must be replaced by the observability layer at runtime."
        )

    def mark_start(self, name: str) -> None:
        """Start a named timing phase.

        Args:
            name: The phase name (non-empty, max 256 characters).

        Raises:
            NotImplementedError: Until wired by the observability layer.
        """
        raise NotImplementedError(
            "Perf.mark_start is not wired. "
            "This instance must be replaced by the observability layer at runtime."
        )

    def mark_end(self, name: str) -> None:
        """End a named timing phase.

        Args:
            name: The phase name (must match a previous mark_start call).

        Raises:
            NotImplementedError: Until wired by the observability layer.
        """
        raise NotImplementedError(
            "Perf.mark_end is not wired. "
            "This instance must be replaced by the observability layer at runtime."
        )

    def phases(
        self, include: str | None = None, exclude: str | None = None
    ) -> list[Phase]:
        """Retrieve recorded phases with optional filtering.

        Args:
            include: Optional regex pattern — only return phases whose names match.
            exclude: Optional regex pattern — exclude phases whose names match.

        Returns:
            List of Phase objects matching the filters.

        Raises:
            NotImplementedError: Until wired by the observability layer.
        """
        raise NotImplementedError(
            "Perf.phases is not wired. "
            "This instance must be replaced by the observability layer at runtime."
        )


class WiredPerf(Perf):
    """The engine-connected Perf — one timeline, shared with ``rc.events``.

    Every method delegates to the same ``ObservabilityFacade`` that backs
    ``rc.events.perf_mark*``, so a mark made through a ``perf: Perf``
    parameter and one made through the RunContext land in one timeline under
    one job prefix. Delegating rather than reimplementing is the point: a
    second copy of the prefixing and `enabled` rules is how the two paths
    drift.

    The RunContext is resolved from the live capability map at **call** time,
    not construction time, because this factory runs during parameter
    resolution — a job written ``def j(perf: Perf, rc: RunContext)`` resolves
    ``perf`` first. ``TTY.ctx`` and ``WiredInvoke._rc`` resolve the same fact
    the same way.

    Before this existed the registry's factory returned the bare ``Perf``
    stub, so **every** method of an injected ``perf`` raised
    ``NotImplementedError``: the capability was declarable, type-checked,
    stripped from the CLI surface, and unusable. No test caught it because
    every test that calls ``perf.mark`` uses ``NoopPerf``, the double that
    accepts everything silently.
    """

    def __init__(self, caps: dict[type, Any]) -> None:
        self._caps = caps

    def _events(self) -> Any:
        from functualize._engine.capabilities.runcontext import RunContext

        rc = self._caps.get(RunContext)
        if rc is None:
            raise RuntimeError(
                "Perf has no RunContext to record against. The engine puts one "
                "in the capability map for every invocation, so this means the "
                "capability was built outside a run."
            )
        return rc.events

    def mark(self, name: str) -> None:
        """Record an instant mark, prefixed with the job name."""
        self._events().perf_mark(name)

    def mark_start(self, name: str) -> None:
        """Open a named timing phase."""
        self._events().perf_mark_start(name)

    def mark_end(self, name: str) -> None:
        """Close a named timing phase."""
        self._events().perf_mark_end(name)

    def phases(
        self, include: str | None = None, exclude: str | None = None
    ) -> list[Phase]:
        """The phases recorded for this job, filtered."""
        return cast(
            "list[Phase]",
            self._events().get_perf_phases(include=include, exclude=exclude),
        )


# ── Registry entry (ADR-014) ───────────────────────────────────────────────

CAPABILITY = CapabilitySpec(
    name="Perf",
    type=Perf,
    factory=lambda ctx: WiredPerf(ctx.caps),
)
