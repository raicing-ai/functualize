"""WorkflowTracker capability — manages job phase lifecycle.

Encapsulates job phase state machine transitions, phase list management,
perf marking, and hook firing. Extracted from RunContext to keep the
facade thin (~500 LOC) while preserving full phase tracking behavior.

Only imports from `_types/`, `_primitives/`, `_events/`, and stdlib.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

from functualize._types.enums import RunStatus

logger = logging.getLogger(__name__)

# Terminal states that cannot be transitioned from
_TERMINAL_STATES = frozenset(
    {RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED, RunStatus.TIMEOUT}
)


class TrackedStep(TypedDict):
    """A single tracked job phase."""

    name: str
    status: RunStatus
    message: str
    start_time: datetime | None
    end_time: datetime | None
    duration: float | None


class WorkflowTracker:
    """Manages job phase lifecycle within a job execution.

    Tracks named phases with status transitions, message updates, timing,
    and perf marks. Fires phase lifecycle hooks via the hook registry.

    Args:
        job_name: Name of the job this tracker belongs to.
        run_context: The RunContext instance (passed to hooks as first arg).
        perf_timeline: PerfTimeline for recording phase timing marks (optional).
        execution_engine: Engine reference for hook registry access (optional).
        step_logger: Logger instance for phase status messages.
    """

    def __init__(
        self,
        job_name: str,
        run_context: Any = None,
        perf_timeline: Any | None = None,
        execution_engine: Any | None = None,
        step_logger: logging.Logger | None = None,
    ) -> None:
        self._job_name = job_name
        self._rc = run_context
        self._perf_timeline = perf_timeline
        self._execution_engine = execution_engine
        self._logger = step_logger or logging.getLogger(job_name)
        self._steps: list[TrackedStep] = []

    @property
    def steps(self) -> list[TrackedStep]:
        """Get the ordered list of tracked job phases."""
        return self._steps

    @property
    def current_step(self) -> TrackedStep | None:
        """Most recently updated job phase, or None if no phases tracked."""
        if not self._steps:
            return None
        return self._steps[-1]

    def get_step(self, step_name: str) -> TrackedStep | None:
        """Retrieve a job phase by name.

        Args:
            step_name: The identifier of the job phase.

        Returns:
            The TrackedStep dict if found, None otherwise.
        """
        for step in self._steps:
            if step["name"] == step_name:
                return step
        return None

    def track_step(
        self,
        step_name: str,
        step_message: str,
        step_status: RunStatus = RunStatus.RUNNING,
    ) -> None:
        """Track a job phase with state machine enforcement.

        Records named phases with status, message (truncated to 1000 chars),
        and timing information. Phases are stored in order of first appearance.
        Fires phase lifecycle hooks after tracking.

        Args:
            step_name: Identifier for the job phase.
            step_message: Description message (truncated to 1000 characters).
            step_status: Current status of the phase.
        """
        truncated_message = step_message[:1000]

        # Check if phase already exists
        existing_step: TrackedStep | None = None
        for step in self._steps:
            if step["name"] == step_name:
                existing_step = step
                break

        if existing_step is None:
            # Create a new job phase
            new_step: TrackedStep = {
                "name": step_name,
                "status": step_status,
                "message": truncated_message,
                "start_time": datetime.now(UTC),
                "end_time": None,
                "duration": None,
            }

            # If the phase is already terminal on creation, set end time
            if step_status in _TERMINAL_STATES:
                new_step["end_time"] = new_step["start_time"]
                new_step["duration"] = 0.0

            self._steps.append(new_step)

            # Perf marking for new phase
            self._mark_step_start(step_name)
            if step_status in _TERMINAL_STATES:
                self._mark_step_end(step_name)

            self._logger.info(
                f"Job phase '{step_name}' status: {step_status.value} - {truncated_message}"
            )

            # Fire phase lifecycle hooks
            self._fire_step_hook(
                "on_phase_start", step_name, step_status, truncated_message
            )

            if step_status == RunStatus.FAILURE:
                self._fire_step_hook(
                    "on_phase_failure", step_name, step_status, truncated_message
                )
            elif step_status == RunStatus.SUCCESS:
                self._fire_step_hook(
                    "on_phase_complete", step_name, step_status, truncated_message
                )
        else:
            # Update existing phase
            existing_step["status"] = step_status
            existing_step["message"] = truncated_message

            # Set end_time and duration when transitioning to terminal
            if step_status in _TERMINAL_STATES:
                end_time = datetime.now(UTC)
                existing_step["end_time"] = end_time
                start_time = existing_step["start_time"]
                if start_time is not None:
                    existing_step["duration"] = (end_time - start_time).total_seconds()

                # Perf marking for phase end
                self._mark_step_end(step_name)

            self._logger.info(
                f"Job phase '{step_name}' status: {step_status.value} - {truncated_message}"
            )

            # Fire status change events
            if step_status == RunStatus.FAILURE:
                self._fire_step_hook(
                    "on_phase_failure", step_name, step_status, truncated_message
                )
            elif step_status == RunStatus.SUCCESS:
                self._fire_step_hook(
                    "on_phase_complete", step_name, step_status, truncated_message
                )

    def _fire_step_hook(
        self,
        event: str,
        step_name: str,
        step_status: RunStatus,
        step_message: str,
    ) -> None:
        """Fire a phase lifecycle hook with error isolation.

        Looks up hooks from the HookRegistry (both global and job-scoped)
        and invokes them with (rc, phase_name, phase_status, phase_message).
        Any exception raised by a hook is logged and execution continues
        to remaining hooks.

        Args:
            event: The hook event name (e.g. "on_phase_start").
            step_name: The job phase name.
            step_status: The phase's RunStatus.
            step_message: The phase's message (already truncated).
        """
        if self._execution_engine is None:
            return

        hook_registry = getattr(self._execution_engine, "_hook_registry", None)
        if hook_registry is None:
            return

        # Collect global hooks then job-scoped hooks
        hooks: list[Callable[..., Any]] = []
        hooks.extend(hook_registry._global_hooks.get(event, []))

        job_hooks = hook_registry._job_hooks.get(self._job_name, {})
        hooks.extend(job_hooks.get(event, []))

        for hook in hooks:
            try:
                hook(self._rc, step_name, step_status, step_message)
            except Exception as e:
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.error(
                    f"Phase hook {hook_name!r} raised an error during "
                    f"'{event}' for phase '{step_name}': {e}"
                )

    def _mark_step_start(self, step_name: str) -> None:
        """Record a perf start mark for a phase."""
        if self._perf_timeline is not None and self._perf_timeline.enabled:
            self._perf_timeline.mark(f"{self._job_name}.phase.{step_name}.start")

    def _mark_step_end(self, step_name: str) -> None:
        """Record a perf end mark for a phase."""
        if self._perf_timeline is not None and self._perf_timeline.enabled:
            self._perf_timeline.mark(f"{self._job_name}.phase.{step_name}.end")
