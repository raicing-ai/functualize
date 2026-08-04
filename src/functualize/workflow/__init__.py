"""Workflow graph types and decorator — the public facade.

The vocabulary itself lives in ``functualize._types.workflow`` so that boot and
discovery can read declarations without an internal layer importing the public
surface; this module is the user-facing re-export, mirroring how
``functualize.job`` fronts ``_types.job_declaration``.

Public API:
    - workflow: Decorator for declaring multi-step workflows.
    - Step: A node that runs a registered job.
    - Gate: A node that pauses for input.
    - Tool: A job a gate offers, with gate-fixed arguments narrowed away.
    - Edge: Directed connection between two workflow nodes.
    - ConditionalEdge: Branching connection based on runtime condition.
    - END: Sentinel marking workflow termination.
    - FromStep: A read of this walk's recorded result for one step, used to
      bind a gate tool's argument (``Tool(read_file, allowed=FromStep(...))``).
"""

from functualize._types.from_job import FromStep
from functualize._types.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    Tool,
    _EndSentinel,
)
from functualize.workflow._decorator import workflow

__all__ = [
    "workflow",
    "ConditionalEdge",
    "Edge",
    "END",
    "FromStep",
    "Gate",
    "Step",
    "Tool",
    "_EndSentinel",
]
