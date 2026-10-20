"""Keep one claimed workflow scope live while its walk executes."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
from types import TracebackType

from functualize._engine.frontier import RenewalOutcome

HEARTBEAT_INTERVAL_SECONDS = 60.0


class LeaseHeartbeat:
    """Renew once on entry, then at most once per interval, and join on exit.

    The entry renewal runs on the walking thread, before any step. A claim's
    expiry is computed before its durable write, and the claim path does more
    work after that write, so by the time the walk starts some of the lease is
    already spent. Renewing here anchors the lease to the start of the work,
    and the renewal cannot queue for the lock behind the walk's own writes.

    A transient storage failure leaves the worker running so the next interval
    can retry. A stale generation is definitive: the old walk no longer owns
    the scope, and its caller must suppress a normal end report. If the entry
    renewal finds that, no worker starts and the caller must run nothing.
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
        if self._renew() is RenewalOutcome.SUPERSEDED:
            self._superseded.set()
            return self
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            if self._renew() is RenewalOutcome.SUPERSEDED:
                self._superseded.set()
                return
