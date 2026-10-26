"""The decision-key encoding — written and read in one place.

A walk records three kinds of decision in one branch record, keyed by string:

- a ``ConditionalEdge``'s choice, under the source node's name;
- an ``OnFailure``'s route, under ``<node>\\x00onfailure``;
- a ``Notify``'s delivery, under ``\\x00notify\\x00<key>``.

The kind lives *inside the key*, NUL-separated, because the record is one
string→string map on every store (``scopes.json``'s ``branches`` object, the
``workflow_branches`` table). That is a surviving smell — primitive obsession —
accepted on purpose: replacing it with a typed column is a migration of what is
recorded. What this module buys instead is **confinement**: the walker encodes
through it and the operator projection decodes through it, so nothing else ever
parses a NUL, and a later typed encoding touches this file only.

A node name cannot contain NUL — ``Step``, ``Gate`` and ``AgentStep`` refuse
one at declaration — so no node can forge a failure route or a marker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from functualize._types.workflow import Notify

__all__ = [
    "ROUTED_TO_END",
    "RecordedRoute",
    "failure_key",
    "notify_key",
    "recorded_route",
]

#: Recorded when an `OnFailure` routes to `END`.
#:
#: A sentinel string rather than `None`, because the branch record has to tell
#: "this failure was routed, and the route was to finish" apart from "no route
#: was ever recorded" — and a resume reads that record instead of calling the
#: predicate again. Collapsing the two made a declared `OnFailure(target=END)`
#: fail the walk, which the test for it caught.
#:
#: A NUL prefix so it cannot collide with a node name: node names are
#: identifier-ish, and nothing that reaches a graph can contain one.
ROUTED_TO_END = "\x00end"

#: How a failure route to `END` reads on an operator surface. Node names are
#: lowercased at declaration, so no node can be called this.
_END_LABEL = "END"

_FAILURE_SUFFIX = "\x00onfailure"


def notify_key(declared: Notify) -> str:
    """The branch-record key one notification's delivery is recorded under.

    NUL-namespaced away from node names for `failure_key`'s reason, and keyed by
    the declaration's **content** rather than its position: a workflow that
    gains a second `Notify` must not make the first one fire again by shifting
    an index.
    """
    return f"\x00notify\x00{declared.key}"


def failure_key(name: str) -> str:
    """The branch-record key a node's failure route is stored under.

    Namespaced away from the node's own name so a node that has *both* a
    `ConditionalEdge` and an `OnFailure` keeps two distinct records — one for
    which branch it took when it succeeded, one for where it went when it did
    not.
    """
    return f"{name}{_FAILURE_SUFFIX}"


@dataclass(frozen=True)
class RecordedRoute:
    """A scope's decision records, sorted by kind, in recording order.

    Attributes:
        branches: ``{source node: chosen label}`` — conditional choices only.
        failure_routes: ``{failed node: target node}`` — a route to `END`
            reads ``"END"``.
    """

    branches: dict[str, str] = field(default_factory=dict)
    failure_routes: dict[str, str] = field(default_factory=dict)


def recorded_route(raw: Mapping[str, str]) -> RecordedRoute:
    """Sort raw decision records into what an operator reads.

    One record at a time, keeping the input order:

    - a key with no NUL is a conditional choice;
    - ``<node>\\x00onfailure`` is a failure route from ``<node>``, with
      :data:`ROUTED_TO_END` read as ``"END"``;
    - any other key holding NUL is bookkeeping (a notification marker, or a
      kind this build does not know) and is dropped rather than shown raw.
    """
    route = RecordedRoute()
    for key, target in raw.items():
        if "\x00" not in key:
            route.branches[key] = target
            continue
        node = key.removesuffix(_FAILURE_SUFFIX)
        if node == key or not node or "\x00" in node:
            continue
        route.failure_routes[node] = _END_LABEL if target == ROUTED_TO_END else target
    return route
