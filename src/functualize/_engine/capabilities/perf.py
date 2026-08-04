"""Perf capability — performance measurement interface.

Defines the Perf class and its supporting Phase dataclass.
The actual implementation is backed by the observability layer
and wired at runtime. This class raises NotImplementedError until wired.
"""

from __future__ import annotations

from dataclasses import dataclass


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
