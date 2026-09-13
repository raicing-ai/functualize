"""Which iteration of a loop a walk is on, and how a replayed step is keyed.

`workflow-graph-semantics`/T2.

## The problem this exists for

The walker keeps a `visited` set so a **diamond join** runs once when two
branches converge on it. Its side effect is that no node can run twice in one
walk — which is exactly what a loop needs to do. Replay compounds it: a step
recorded `success` is skipped on the next invocation, so a completed node stays
completed across processes too.

So loops need the walk to distinguish two things that look identical to a set of
names:

- *this node already ran **on this path*** — the join, which must keep pruning;
- *this node ran on a **previous iteration*** — the loop, which must not.

The distinction is an **iteration**, and both `visited` and the step-record key
carry it.

## The iteration is derived, never carried alongside

There is no counter in the store. The iteration is read back from the step
records that exist, the same way `workflow_depth` reads nesting out of a scope
id rather than threading a number through the walk — and for the same reason: a
resumed walk in a fresh process has the records and nothing else, and a counter
carried beside them could disagree with them.

## Iteration 0 is spelled as it always was

`_key(name, 0)` is byte-identical to the old `step_key(name, "")`. A workflow
with no `Loop` produces exactly the records it produced before, so nothing is
migrated and a graph that never loops cannot notice this feature happened.
"""

from __future__ import annotations

from typing import Any

from functualize._engine.frontier import step_key

__all__ = ["current_iteration", "iteration_step_key"]


def iteration_step_key(name: str, iteration: int) -> str:
    """The step-record key for ``name`` on ``iteration``.

    The args hash carries the iteration because that is the field already
    distinguishing two records of one node, and adding a third component to the
    key would change the shape of every record in the store — including the ones
    written before this feature.

    Iteration 0 uses the empty hash, so it is the key this node has always had.
    """
    return str(step_key(name, "" if iteration == 0 else f"loop{iteration}"))


def current_iteration(store: Any, scope_id: str, name: str, bound: int) -> int:
    """How many times ``name`` has already completed, capped at ``bound``.

    Derived by asking the store for each iteration's record in turn, stopping
    at the first one absent. Linear in the bound, which is a number a human
    wrote and is therefore small; a binary search would be faster and would
    also find a *gap* and call it the end, which is the wrong answer for a
    record set that a crash can leave with holes.

    Returns the iteration the walk should run **next**. A node with no record
    at all is on iteration 0.
    """
    for iteration in range(bound):
        record = store.get_step(scope_id, iteration_step_key(name, iteration))
        if record is None or record.get("status") != "success":
            return iteration
    return bound
