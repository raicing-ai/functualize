"""Workflow graph validation, run at decoration time.

Structural checks only — everything provable from the declaration alone, with
no registry and no I/O, so a malformed graph fails at import rather than
halfway through a walk:

- duplicate node names (a `Step` and a `Gate` share one namespace)
- edges whose source or target names no node
- conditional targets naming no node

Resolving `Step` job refs against the registry and detecting workflow-nesting
cycles both need the boot-time registry and live in discovery, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

from functualize._types.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    _EndSentinel,
)

_NODE_TYPES = (Step, Gate)


def _validate_workflow_graph(
    nodes: Sequence[Step | Gate], edges: Sequence[Edge | ConditionalEdge]
) -> None:
    """Validate the workflow graph structure at decoration time.

    Args:
        nodes: Workflow nodes — `Step` (runs a job) or `Gate` (pauses).
        edges: `Edge` / `ConditionalEdge` connections between nodes.

    Raises:
        TypeError: If a list entry is not a workflow node or edge type.
        ValueError: On duplicate node names or references to unknown nodes.
    """
    node_names: set[str] = set()
    for node in nodes:
        if not isinstance(node, _NODE_TYPES):
            raise TypeError(
                f"Workflow steps must be Step or Gate objects, "
                f"got {type(node).__name__}"
            )
        name = node.name
        if name in node_names:
            raise ValueError(f"Duplicate workflow node name '{name}'")
        node_names.add(name)

    for edge in edges:
        if not isinstance(edge, (Edge, ConditionalEdge)):
            raise TypeError(
                f"Workflow edges must be Edge or ConditionalEdge objects, "
                f"got {type(edge).__name__}"
            )
        if edge.source not in node_names:
            raise ValueError(f"Edge source '{edge.source}' not found in steps")

        if isinstance(edge, ConditionalEdge):
            for key, target in edge.targets.items():
                if _is_end(target):
                    continue
                if target not in node_names:
                    raise ValueError(
                        f"ConditionalEdge target '{target}' "
                        f"(key='{key}') not found in steps"
                    )
        elif not _is_end(edge.target) and edge.target not in node_names:
            raise ValueError(f"Edge target '{edge.target}' not found in steps")


def _is_end(target: str | _EndSentinel) -> bool:
    """True if a target is the END sentinel rather than a node name."""
    return target is END or isinstance(target, _EndSentinel)
