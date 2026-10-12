"""Keep one claimed workflow scope live while its walk executes."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
from types import TracebackType

from functualize._engine.frontier import RenewalOutcome

HEARTBEAT_INTERVAL_SECONDS = 60.0


class LeaseHeartbeat:
    """Renew at most once per interval, and join before the claim is released.

    A transient storage failure leaves the worker running so the next interval
    can retry. A stale generation is definitive: the old walk no longer owns
    the scope, and its caller must suppress a normal end report.
    """

    def __init__(
        self,
        renew: Callable[[], RenewalOutcome],
        scope_id: str,
        *,
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._renew = renew
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._superseded = Event()
        self._thread = Thread(
            target=self._run, name=f"lease-heartbeat:{scope_id}", daemon=False
        )

    @property
    def superseded(self) -> bool:
        """Whether renewal learned that another runner owns this scope."""
        return self._superseded.is_set()

    def __enter__(self) -> LeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            if self._renew() is RenewalOutcome.SUPERSEDED:
                self._superseded.set()
                return
