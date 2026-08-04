"""RunContext implementation — re-exports from canonical internal location.

The implementation lives in _engine/capabilities/runcontext.py. This module
provides backward-compatible imports for the public API surface.
"""

from functualize._engine.capabilities.runcontext import (
    _TERMINAL_STATES,
    InvalidStateTransitionError,
    JobPhase,
    RunContext,
    inject_resource,
)
from functualize._types.enums import RunStatus, RunType

__all__ = [
    "RunContext",
    "InvalidStateTransitionError",
    "RunStatus",
    "RunType",
    "JobPhase",
    "_TERMINAL_STATES",
    "inject_resource",
]
