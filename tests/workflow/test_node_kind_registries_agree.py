"""Three places enumerate "what kind of node is this". They must agree.

- `workflow/_validation.py::_NODE_TYPES` — what the decorator accepts as a node.
- `_types/workflow.py::_node_kind` — the string a node is recorded under in the
  cache shape.
- `_engine/workflow_walker.py::_NODE_HANDLERS` — the handler that services it.

`_NODE_HANDLERS`' own comment claimed a fourth node kind is "a handler plus a
row", which is true of the walker and of nothing else: a fourth kind also edits
the other two, and nothing said so (asp A-1). Deriving all three from one
declaration would be the tidier answer — a `kind: ClassVar[str]` on each node
class — but it would still leave two class-keyed tables, because dispatch and
`isinstance` both need the class, not the name. So the three stay, and this file
is what makes them one decision: added to one and not the others, a fourth kind
fails here.

Both directions, deliberately. A test that only checks "every validated type has
a handler" passes when a handler exists for a type the decorator refuses, which
is dead dispatch nobody can reach.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._engine.workflow_walker import _NODE_HANDLERS
from functualize._types.workflow import AgentStep, Gate, Step, _node_kind
from functualize.workflow._validation import _NODE_TYPES


def test_the_declared_node_kinds_are_the_three_this_file_knows_about() -> None:
    """The premise. If a fourth kind lands, this fails first and names it."""
    assert set(_NODE_TYPES) == {Step, Gate, AgentStep}


def test_every_accepted_node_type_has_a_handler() -> None:
    """A node the decorator accepts must be servicable, or a valid graph
    reaches the walk and is refused by name mid-walk."""
    missing = [
        node_type.__name__
        for node_type in _NODE_TYPES
        if node_type not in _NODE_HANDLERS
    ]

    assert not missing, (
        f"node types accepted by @workflow with no handler in _NODE_HANDLERS: {missing}"
    )


def test_every_handler_services_an_accepted_node_type() -> None:
    """The other direction. A handler for a type the decorator refuses is
    dispatch nothing can reach."""
    stray = [
        node_type.__name__
        for node_type in _NODE_HANDLERS
        if node_type not in _NODE_TYPES
    ]

    assert not stray, (
        f"handlers registered for node types @workflow does not accept: {stray}"
    )


def test_every_accepted_node_type_has_a_recorded_kind() -> None:
    """`_node_kind` is an isinstance chain, so a fourth kind falls through it
    to a `TypeError` — at cache-write time, which is far from the edit."""
    kinds = {}
    for node_type in _NODE_TYPES:
        node = _a_node(node_type)
        kinds[node_type.__name__] = _node_kind(node)

    assert kinds == {"Step": "step", "Gate": "gate", "AgentStep": "agent"}


def test_the_kinds_are_distinct() -> None:
    """Two node types recorded under one string make a cached shape ambiguous
    on the way back in."""
    kinds = [_node_kind(_a_node(node_type)) for node_type in _NODE_TYPES]

    assert len(set(kinds)) == len(kinds), kinds


class _Approval(BaseModel):
    """The model a `Gate` waits on — any model will do; it is never resolved."""

    approved: bool = True


def _a_node(node_type: type) -> object:
    """One instance of each node kind, constructed the way a user would."""
    if node_type is Step:
        return Step("some-job")
    if node_type is Gate:
        return Gate("approve", awaits=_Approval)
    if node_type is AgentStep:
        return AgentStep(name="draft", instructions="write it")
    pytest.fail(
        f"{node_type.__name__} is a node kind this file does not know how to "
        f"construct. Add it here — that is the point of the test above."
    )
