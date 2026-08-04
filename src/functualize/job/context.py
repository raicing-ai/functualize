"""Public RunContext facade for job authors.

Re-exports from the private implementation module so that users can do:

    from functualize.job import RunContext
    from functualize.job.context import RunContext, inject_resource

Delegates to capability classes:
- invoke() / invoke_parallel() → _engine.capabilities.invoke.Invoke
- track_phase() → _engine.capabilities.workflow.WorkflowTracker
- emit() → EventBus.emit() (direct delegation)
"""

from functualize.job._runcontext import (
    _TERMINAL_STATES,
    InvalidStateTransitionError,
    JobPhase,
    RunContext,
    RunStatus,
    RunType,
    inject_resource,
)

__all__ = [
    "RunContext",
    "InvalidStateTransitionError",
    "RunStatus",
    "RunType",
    "JobPhase",
    "_TERMINAL_STATES",
    "inject_resource",
]
