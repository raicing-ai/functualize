"""Everything a job can observe about its own run — `rc.events`.

Extracted from :class:`~functualize._engine.capabilities.runcontext.RunContext`
(engine-sealed-construction/T8). One subject with four faces, which is why they
are one facade rather than four:

* **events** — `emit`, `on_event`, `off_event`: the bus, for a job that wants to
  say something a plugin can subscribe to.
* **phases** — `track_phase`, `get_phase`, `phases`, `current_phase`: named
  spans inside one run.
* **run status** — `track_run_status`, `set_run_status`, `run_status`,
  `run_duration`: what this run is currently claiming about itself.
* **perf** — `perf_mark*`, `get_perf_phases`: the timeline those spans feed.

They share state (`_perf_timeline`, the callback lists) and they answer the same
question at different resolutions: *what is happening in this run, and what
happened*. Splitting them into four accessors would have made a job reach three
of them to instrument one step.

`rc.log` deliberately **did not** move. It is the one line every job writes, and
a diet that makes the most-used call longer has optimised the wrong number.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from functualize._engine.capabilities.runcontext import (
    _TERMINAL_STATES,
    InvalidStateTransitionError,
    _dispatch_to_surfaces,
)
from functualize._types.enums import RunStatus

# Imported from `runcontext`, not moved out of it: `_TERMINAL_STATES` and
# `InvalidStateTransitionError` are re-exported publicly through
# `functualize.job.context`, so moving them would change a published import path
# to no purpose. A module-level import back is safe — `runcontext` imports this
# facade lazily, inside the `events` property, so nothing is circular at load.

if TYPE_CHECKING:
    from collections.abc import Callable

    from functualize._engine.capabilities.runcontext import JobPhase, RunContext
    from functualize._events.perf import PerfTimeline, Phase

__all__ = ["ObservabilityFacade"]


class ObservabilityFacade:
    """`rc.events` — events, phases, run status and the perf timeline."""

    __slots__ = ("_rc",)

    def __init__(self, rc: RunContext) -> None:
        self._rc = rc

    def on_status_change(self, callback: Any) -> None:
        """Register a callback invoked on status transitions."""
        self._rc._status_callbacks.append(callback)

    def on_phase_change(self, callback: Any) -> None:
        """Register a callback invoked on phase changes."""
        self._rc._phase_callbacks.append(callback)

    def _resolve_timeline(self) -> Any:
        if self._rc._perf_timeline is not None:
            return self._rc._perf_timeline
        from functualize._events.perf import perf_timeline

        return perf_timeline

    @property
    def phases(self) -> list[JobPhase]:
        return self._rc._get_tracker().steps

    @property
    def current_phase(self) -> JobPhase | None:
        return self._rc._get_tracker().current_step

    def track_phase(
        self,
        phase_name: str,
        phase_message: str,
        phase_status: RunStatus = RunStatus.RUNNING,
    ) -> None:
        """Track a job phase. Delegates to WorkflowTracker.track_step()."""
        # Determine if this is a new phase or an update
        existing = self._rc._get_tracker().get_step(phase_name)
        action = "updated" if existing is not None else "created"

        self._rc._get_tracker().track_step(phase_name, phase_message, phase_status)

        # Build phase dict for callbacks (backward compat)
        phase_dict: JobPhase = {
            "name": phase_name,
            "message": phase_message,
            "status": phase_status,
            "start_time": None,
            "end_time": None,
            "duration": None,
        }

        # Invoke phase callbacks with (phase_dict, action)
        for cb in self._rc._phase_callbacks:
            try:
                cb(phase_dict, action)
            except Exception:
                self._rc._logger.warning(
                    "Phase callback %r raised an exception", cb, exc_info=True
                )

    def get_phase(self, phase_name: str) -> JobPhase | None:
        return self._rc._get_tracker().get_step(phase_name)

    def _resolve_event_bus(self) -> Any | None:
        """Resolve the EventBus from the host the engine was built for."""
        if self._rc._execution_engine is None:
            return None
        host = self._rc._execution_engine.host
        if host is None:
            return None
        return host.event_bus

    def emit(self, event_name: str, resource: str = "", **payload: Any) -> None:
        """Emit a structured event. Delegates to EventBus.emit()."""
        return self._emit_event(event_name, resource, payload)

    def on_event(self, pattern: str, callback: Callable[[Any], None]) -> Any | None:
        """Subscribe to structured events for the life of this execution.

        The inbound counterpart to :meth:`emit` — lets code holding a
        RunContext (notably a job-owned UI, which receives the context via
        its ``TTY`` handle) observe events as they happen, including those
        emitted by children started with :meth:`invoke`.

        Args:
            pattern: Exact event name, prefix wildcard (``"job.*"``), or
                the global wildcard (``"*"``).
            callback: Receives a StructuredEvent. Called synchronously on the
                emitting thread — which is a worker thread for most job
                events, so a UI callback must marshal onto its own loop.

        Returns:
            A SubscriptionHandle for :meth:`off_event`, or None when no
            EventBus is reachable (e.g. a RunContext built outside the
            engine), so callers can subscribe unconditionally.
        """
        event_bus = self._resolve_event_bus()
        if event_bus is None:
            return None
        return event_bus.subscribe(pattern, callback)

    def off_event(self, handle: Any) -> None:
        """Remove a subscription created by :meth:`on_event`.

        Accepts None (what ``on_event`` returns when no bus was reachable)
        so teardown paths need no guard of their own.
        """
        if handle is None:
            return
        event_bus = self._resolve_event_bus()
        if event_bus is not None:
            event_bus.unsubscribe(handle)

    def _emit_event(
        self, event_name: str, resource: str, payload: dict[str, Any]
    ) -> None:
        """Internal emit implementation — resolves EventBus and dispatches."""
        event_bus = self._resolve_event_bus()
        if event_bus is not None:
            event_bus.emit(event_name, resource=resource, **payload)
        host = self._rc._execution_engine.host if self._rc._execution_engine else None
        if host is not None and not any(
            event_name.startswith(p) for p in self._rc._FRAMEWORK_EVENT_PREFIXES
        ):
            _dispatch_to_surfaces(host, event_name, resource, payload)

    def track_run_status(
        self,
        run_status: RunStatus = RunStatus.RUNNING,
        failure_message: str = "",
    ) -> None:
        current_status = self._rc._metadata["run_status"]
        if current_status in _TERMINAL_STATES:
            raise InvalidStateTransitionError(
                f"Cannot transition from terminal state {current_status.value} "
                f"to {run_status.value}"
            )
        self._rc._metadata["run_status"] = run_status
        if run_status in _TERMINAL_STATES:
            self._rc._metadata["end_time"] = datetime.now(UTC)
            start_time = self._rc._metadata["start_time"]
            if start_time is not None:
                self._rc._metadata["duration"] = (
                    self._rc._metadata["end_time"] - start_time
                ).total_seconds()
        if failure_message:
            self._rc._logger.error(
                f"Run status: {run_status.value} - {failure_message}"
            )

    def set_run_status(self, status: RunStatus, message: str = "") -> None:
        old_status = self._rc._metadata["run_status"]
        self.track_run_status(run_status=status, failure_message=message)
        # Invoke status callbacks
        for cb in self._rc._status_callbacks:
            try:
                cb(old_status, status, message)
            except Exception:
                self._rc._logger.warning(
                    "Status change callback %r raised an exception", cb, exc_info=True
                )

    @property
    def run_status(self) -> RunStatus:
        return cast("RunStatus", self._rc._metadata["run_status"])

    @property
    def run_duration(self) -> float:
        duration = self._rc._metadata.get("duration")
        if duration is not None:
            return float(duration)
        start = self._rc._metadata.get("start_time")
        if start is None:
            return 0.0
        return float((datetime.now(UTC) - start).total_seconds())

    @property
    def _timeline(self) -> PerfTimeline:
        if self._rc._perf_timeline is not None:
            return self._rc._perf_timeline
        from functualize._events.perf import perf_timeline

        return perf_timeline

    def _validate_mark_name(self, name: str) -> None:
        if not name or len(name) > 256:
            raise ValueError(
                "Mark name must be a non-empty string of at most 256 characters."
            )

    def perf_mark(self, name: str) -> None:
        self._validate_mark_name(name)
        tl = self._timeline
        if tl.enabled:
            tl.mark(f"{self._rc._name}.{name}")

    def perf_mark_start(self, name: str) -> None:
        self._validate_mark_name(name)
        tl = self._timeline
        if tl.enabled:
            tl.mark(f"{self._rc._name}.{name}.start")

    def perf_mark_end(self, name: str) -> None:
        self._validate_mark_name(name)
        tl = self._timeline
        if tl.enabled:
            tl.mark(f"{self._rc._name}.{name}.end")

    def get_perf_phases(
        self,
        include: str | None = None,
        exclude: str | None = None,
    ) -> list[Phase]:
        from functualize._events._pattern_matcher import filter_phases

        report = self._timeline.report()
        prefix = f"{self._rc._name}."
        job_phases = [p for p in report.phases if p.name.startswith(prefix)]
        unprefixed = [p.name[len(prefix) :] for p in job_phases]
        matching = set(filter_phases(unprefixed, include, exclude))
        return [p for p, u in zip(job_phases, unprefixed, strict=True) if u in matching]
