"""Workflow graph types and decorator — the public facade.

The vocabulary itself lives in ``functualize._types.workflow`` so that boot and
discovery can read declarations without an internal layer importing the public
surface; this module is the user-facing re-export, mirroring how
``functualize.job`` fronts ``_types.job_declaration``.

Public API:
    - workflow: Decorator for declaring multi-step workflows.
    - Step: A node that runs a registered job.
    - Gate: A node that pauses for input.
    - AgentStep: A node performed by an agent, via a registered executor.
    - Tool: A job a gate offers, with gate-fixed arguments narrowed away.
    - Edge: Directed connection between two workflow nodes.
    - ConditionalEdge: Branching connection based on runtime condition.
    - END: Sentinel marking workflow termination.
    - FromStep: A read of this walk's recorded result for one step, used to
      bind a gate tool's argument (``Tool(read_file, allowed=FromStep(...))``).
    - ChoiceDecision: A gate's declared decision (``Gate(decide=...)``) — which
      field a decision provider fills, from which step's result, and the
      thresholds a proposal must clear. Provisional: outside the names 1.0
      promises to keep.
"""

from functualize._types.decision import ChoiceDecision
from functualize._types.from_job import FromStep
from functualize._types.workflow import (
    END,
    AgentStep,
    ConditionalEdge,
    Edge,
    Gate,
    Loop,
    Notification,
    Notify,
    OnFailure,
    Step,
    Tool,
    _EndSentinel,
)
from functualize.workflow._decorator import workflow

__all__ = [
    "workflow",
    "AgentStep",
    # Provisional: outside the names 1.0 promises to keep, and this comment is
    # the marker until the mechanism that marks provisional names exists.
    "ChoiceDecision",
    "ConditionalEdge",
    "Edge",
    "END",
    "FromStep",
    "Gate",
    "Loop",
    "Notification",
    "Notify",
    "OnFailure",
    "Step",
    "Tool",
    "_EndSentinel",
]
