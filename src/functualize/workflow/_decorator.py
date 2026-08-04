"""@workflow decorator implementation.

Provides the ``@workflow(steps=..., edges=...)`` decorator that registers a
function as a declarative workflow. The decorator validates the graph structure
at decoration time and attaches a frozen
:class:`~functualize._types.workflow.WorkflowDeclaration` as
``__functualize_workflow__``, mirroring ``@job``'s ``__functualize_job__``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from functualize._types.workflow import WorkflowDeclaration
from functualize.workflow._validation import _validate_workflow_graph

if TYPE_CHECKING:
    from functualize._types.workflow import ConditionalEdge, Edge, Gate, Step


def workflow(
    *,
    steps: Sequence[Step | Gate],
    edges: Sequence[Edge | ConditionalEdge],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator registering a function as a declarative workflow.

    Validates the workflow graph at decoration time and attaches the frozen
    declaration to the decorated function. The function's own body is the
    workflow's epilogue: it runs when the walk reaches ``END``.

    Args:
        steps: Workflow nodes — `Step` (runs a registered job) or `Gate`
            (pauses for input).
        edges: List of Edge or ConditionalEdge objects defining connections.

    Returns:
        A decorator that attaches the workflow definition to the function.
        Identity-preserving: ``decorated is original`` always holds.

    Raises:
        TypeError: If a list entry is not a workflow node or edge type.
        ValueError: If the graph contains duplicate node names or unknown
            node references in edges.
    """
    _validate_workflow_graph(steps, edges)
    declaration = WorkflowDeclaration(nodes=tuple(steps), edges=tuple(edges))

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__functualize_workflow__ = declaration  # type: ignore[attr-defined]
        return fn

    return decorator
