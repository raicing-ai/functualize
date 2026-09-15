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

from functualize._types.workflow import Notify, WorkflowDeclaration
from functualize.workflow._validation import _validate_workflow_graph

if TYPE_CHECKING:
    from functualize._types.workflow import (
        AgentStep,
        ConditionalEdge,
        Edge,
        Gate,
        Step,
    )


def workflow(
    *,
    steps: Sequence[Step | Gate | AgentStep],
    edges: Sequence[Edge | ConditionalEdge],
    notify: Sequence[Notify] = (),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator registering a function as a declarative workflow.

    Validates the workflow graph at decoration time and attaches the frozen
    declaration to the decorated function. The function's own body is the
    workflow's epilogue: it runs when the walk reaches ``END``.

    Args:
        steps: Workflow nodes — `Step` (runs a registered job), `Gate`
            (pauses for input), or `AgentStep` (delegates to a registered
            agent executor).
        edges: List of Edge or ConditionalEdge objects defining connections.
        notify: Notifications to fire when the walk ends in a declared state.
            A separate argument rather than an entry in ``edges``: a `Notify`
            has no source and no target in the graph — it is about the walk's
            outcome, not about control moving between nodes — and putting it
            there would make every edge consumer test for a kind that has
            neither.

    Returns:
        A decorator that attaches the workflow definition to the function.
        Identity-preserving: ``decorated is original`` always holds.

    Raises:
        TypeError: If a list entry is not a workflow node or edge type.
        ValueError: If the graph contains duplicate node names or unknown
            node references in edges.
    """
    _validate_workflow_graph(steps, edges, notify)
    declaration = WorkflowDeclaration(
        nodes=tuple(steps), edges=tuple(edges), notify=tuple(notify)
    )

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__functualize_workflow__ = declaration  # type: ignore[attr-defined]
        return fn

    return decorator
