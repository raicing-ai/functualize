"""Workflow graph validation, run at decoration time.

Structural checks only — everything provable from the declaration alone, with
no registry and no I/O, so a malformed graph fails at import rather than
halfway through a walk:

- duplicate node names (every node kind shares one namespace)
- edges whose source or target names no node
- conditional targets naming no node
- a **cycle in the step graph** with no declared bound

Resolving `Step` job refs against the registry and detecting cycles *between
nested workflows* both need the boot-time registry and live in discovery, not
here. The cycle check below is about edges within one graph, which the
declaration alone settles.
"""

from __future__ import annotations

from collections.abc import Sequence

from functualize._types.errors import WorkflowDeclarationError
from functualize._types.workflow import (
    END,
    AgentStep,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    _EndSentinel,
)

_NODE_TYPES = (Step, Gate, AgentStep)


def _validate_workflow_graph(
    nodes: Sequence[Step | Gate | AgentStep],
    edges: Sequence[Edge | ConditionalEdge],
) -> None:
    """Validate the workflow graph structure at decoration time.

    Args:
        nodes: Workflow nodes — `Step` (runs a job), `Gate` (pauses), or
            `AgentStep` (delegates to a registered agent executor).
        edges: `Edge` / `ConditionalEdge` connections between nodes.

    Raises:
        TypeError: If a list entry is not a workflow node or edge type.
        ValueError: On duplicate node names or references to unknown nodes.
        WorkflowDeclarationError: On a cycle with no declared bound.

    Only what the declaration alone can prove is checked here. Whether an
    `AgentStep` has an executor, and whether that executor can honour what the
    step requires, needs the live registry and is refused before the walk
    (``_engine.agent_step``) — the same split that puts `Step` job resolution
    at boot rather than at decoration.
    """
    node_names: set[str] = set()
    for node in nodes:
        if not isinstance(node, _NODE_TYPES):
            raise TypeError(
                f"Workflow steps must be Step, Gate or AgentStep objects, "
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

    _refuse_unbounded_cycle(edges)


def _is_end(target: str | _EndSentinel) -> bool:
    """True if a target is the END sentinel rather than a node name."""
    return target is END or isinstance(target, _EndSentinel)


def _targets_of(edge: Edge | ConditionalEdge) -> list[str]:
    """Every node an edge can lead to, END excluded.

    END terminates, so it is not a vertex: including it would make every graph
    that ends look like it has an extra sink and would not change any answer.
    """
    if isinstance(edge, ConditionalEdge):
        return [str(t) for t in edge.targets.values() if not _is_end(t)]
    return [] if _is_end(edge.target) else [str(edge.target)]


def _find_cycle(edges: Sequence[Edge | ConditionalEdge]) -> list[str] | None:
    """One cycle in the step graph as a node path, or None.

    Iterative depth-first search with an explicit stack: a workflow graph is
    small, but a recursive walk would turn a deep chain into a
    `RecursionError` — an unrelated failure at decoration time for a graph
    that is merely long.

    Returns the **actual cycle**, trimmed to the loop itself rather than the
    path that reached it, because the message names it to a reader who has to
    find it in their own declaration.
    """
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).extend(_targets_of(edge))

    #: 0 unvisited, 1 on the current path, 2 finished. Three states rather than
    #: a visited set: a node reached twice by different branches is a diamond,
    #: which is legal, and only a node reached *while still on the path* is a
    #: cycle.
    state: dict[str, int] = {}
    path: list[str] = []

    for start in adjacency:
        if state.get(start, 0) != 0:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        state[start] = 1
        path.append(start)
        while stack:
            node, index = stack[-1]
            successors = adjacency.get(node, ())
            if index < len(successors):
                stack[-1] = (node, index + 1)
                nxt = successors[index]
                if state.get(nxt, 0) == 1:
                    return [*path[path.index(nxt) :], nxt]
                if state.get(nxt, 0) == 0:
                    state[nxt] = 1
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                state[node] = 2
                path.pop()
                stack.pop()
    return None


def _refuse_unbounded_cycle(edges: Sequence[Edge | ConditionalEdge]) -> None:
    """Refuse a graph that can return to a node it has already run.

    **This is a breaking change, and the point of it is that it is loud.**
    A cycle used to be accepted and then quietly run *once*: the walk prunes
    nodes it has visited, so the second pass was dropped with no message. That
    reads exactly like a loop condition that was false, which is the worst
    available failure — the declaration says one thing, the run does another,
    and nothing says so.

    The message names the cycle it found, because a reader's next act is to go
    and look at it.

    # TRANSITIONAL(workflow-graph-semantics/T2): the message tells the reader
    # to declare a bound, and `Loop` is what will carry one. It does not exist
    # yet — T2 adds it. Landing the refusal first is deliberate: while there is
    # no way to satisfy it except by removing the cycle, nobody can mistake it
    # for a lint that has an escape hatch. Update the wording, not the rule,
    # when `Loop` lands.
    """
    cycle = _find_cycle(edges)
    if cycle is None:
        return
    raise WorkflowDeclarationError(
        f"Workflow graph has a cycle with no declared bound: "
        f"{' -> '.join(cycle)}.\n"
        f"A cycle used to be accepted and then run once, silently, because the "
        f"walk prunes nodes it has already visited — so a loop that never "
        f"looped looked the same as a condition that was false.\n"
        f"Either remove the edge that closes the cycle, or declare the "
        f"repetition with an explicit bound."
    )
