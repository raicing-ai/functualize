"""A cycle in a step graph is refused at declaration, not run once in silence.

`workflow-graph-semantics`/T1. Spec AC-3.

**What this changes.** A declared cycle used to be *accepted*. The walk prunes
nodes it has already visited, so the second pass was dropped with no message at
all — and a loop that never looped is indistinguishable from a loop whose
condition was false. The declaration said one thing, the run did another, and
nothing said so.

Nothing validated it either: `_engine/workflow_validation.py` guards cycles
between **nested workflows**, on the grounds that *"ordinary jobs terminate a
chain and are already cycle-checked as deps"* — true of the job graph, and not
a statement about edges inside one workflow.

**The other half of this file is the legal shapes.** A cycle check that also
refuses a diamond, or a conditional whose branches rejoin, would be worse than
no check: those are the ordinary way to write a graph, and the refusal would
arrive at import time for a correct declaration. Every test below that builds a
*legal* graph is guarding against that, not padding.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._types.errors import WorkflowDeclarationError
from functualize._types.workflow import END, ConditionalEdge, Edge, Gate, Step
from functualize.workflow._validation import _validate_workflow_graph


class _Ask(BaseModel):
    """The smallest thing a gate can await."""

    text: str


def _steps(*names: str) -> list[Step]:
    return [Step(name) for name in names]


class TestACycleIsRefused:
    def test_two_nodes_pointing_at_each_other(self) -> None:
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("a", "b"),
                [Edge(source="a", target="b"), Edge(source="b", target="a")],
            )
        assert "cycle" in str(exc.value)

    def test_a_node_pointing_at_itself(self) -> None:
        """The smallest cycle, and the one most likely to be a typo."""
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(_steps("a"), [Edge(source="a", target="a")])

    def test_a_longer_ring(self) -> None:
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("a", "b", "c", "d"),
                [
                    Edge(source="a", target="b"),
                    Edge(source="b", target="c"),
                    Edge(source="c", target="d"),
                    Edge(source="d", target="b"),
                ],
            )

    def test_a_cycle_reached_through_a_conditional(self) -> None:
        """A `ConditionalEdge` has several targets and any of them can close it.

        Checking only `Edge.target` would miss this, and a conditional is the
        natural way somebody writes a retry — so it is the shape most likely to
        be hit in practice.
        """
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("a", "b"),
                [
                    Edge(source="a", target="b"),
                    ConditionalEdge(
                        source="b",
                        condition=lambda: "again",
                        targets={"again": "a", "done": END},
                    ),
                ],
            )

    def test_a_cycle_that_also_has_a_way_out(self) -> None:
        """Having an exit does not make it bounded.

        This is the one a reader will argue about: the graph *can* terminate,
        so is it really unbounded? Nothing in the declaration says how many
        times it goes round, and the walk has no counter — which is exactly the
        state where it silently ran once.
        """
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("work", "check"),
                [
                    Edge(source="work", target="check"),
                    ConditionalEdge(
                        source="check",
                        condition=lambda: "retry",
                        targets={"retry": "work", "ok": END},
                    ),
                ],
            )

    def test_a_gate_inside_the_cycle_does_not_excuse_it(self) -> None:
        """A pause is not a bound. It stops the run, not the repetition."""
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                [Step("a"), Gate(name="approve", awaits=_Ask), Step("b")],
                [
                    Edge(source="a", target="approve"),
                    Edge(source="approve", target="b"),
                    Edge(source="b", target="a"),
                ],
            )


class TestTheRefusalIsUsable:
    def test_it_names_the_cycle_it_found(self) -> None:
        """The reader's next act is to go and look at it."""
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("a", "b", "c"),
                [
                    Edge(source="a", target="b"),
                    Edge(source="b", target="c"),
                    Edge(source="c", target="b"),
                ],
            )
        message = str(exc.value)
        assert "b -> c -> b" in message, message

    def test_it_does_not_name_the_path_that_reached_the_cycle(self) -> None:
        """`a` leads to the loop but is not in it.

        Reporting the whole traversal would send a reader to the wrong edge —
        the one to delete is inside the ring.
        """
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("a", "b", "c"),
                [
                    Edge(source="a", target="b"),
                    Edge(source="b", target="c"),
                    Edge(source="c", target="b"),
                ],
            )
        assert "a ->" not in str(exc.value)

    def test_it_says_what_to_do(self) -> None:
        """A refusal with no remedy is a wall."""
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(_steps("a"), [Edge(source="a", target="a")])
        message = str(exc.value)
        assert "remove the edge" in message
        assert "bound" in message

    def test_it_explains_what_used_to_happen(self) -> None:
        """Because the reader's graph worked yesterday.

        Without this the message reads as a new restriction rather than a
        defect being surfaced, and the obvious response is to look for a way to
        turn it off.
        """
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(_steps("a"), [Edge(source="a", target="a")])
        assert "run once" in str(exc.value)


class TestLegalGraphsStillPass:
    """The half that stops the check from being worse than nothing."""

    def test_a_straight_line(self) -> None:
        _validate_workflow_graph(
            _steps("a", "b"),
            [Edge(source="a", target="b"), Edge(source="b", target=END)],
        )

    def test_a_diamond(self) -> None:
        """Two branches rejoining is not a cycle.

        `d` is reached twice by the traversal and both arrivals are legal. A
        check using a plain visited-set instead of three states would call this
        a cycle and refuse the most common non-linear graph there is.
        """
        _validate_workflow_graph(
            _steps("a", "left", "right", "d"),
            [
                Edge(source="a", target="left"),
                Edge(source="a", target="right"),
                Edge(source="left", target="d"),
                Edge(source="right", target="d"),
                Edge(source="d", target=END),
            ],
        )

    def test_a_conditional_whose_branches_rejoin(self) -> None:
        _validate_workflow_graph(
            _steps("check", "fast", "slow", "finish"),
            [
                ConditionalEdge(
                    source="check",
                    condition=lambda: "fast",
                    targets={"fast": "fast", "slow": "slow"},
                ),
                Edge(source="fast", target="finish"),
                Edge(source="slow", target="finish"),
                Edge(source="finish", target=END),
            ],
        )

    def test_two_nodes_both_ending(self) -> None:
        """END is not a vertex.

        Treating it as one would make every terminating graph share a sink,
        and two branches both ending would look like a join — harmless here,
        but it is the kind of thing that becomes a false cycle later.
        """
        _validate_workflow_graph(
            _steps("a", "b"),
            [Edge(source="a", target=END), Edge(source="b", target=END)],
        )

    def test_a_long_chain_does_not_hit_the_recursion_limit(self) -> None:
        """Iterative on purpose.

        A recursive walk turns a graph that is merely long into a
        `RecursionError` at decoration time — an unrelated failure, reported
        against a declaration that is perfectly legal.
        """
        names = [f"n{i}" for i in range(2000)]
        edges: list[Edge] = [
            Edge(source=a, target=b) for a, b in zip(names, names[1:], strict=False)
        ]
        edges.append(Edge(source=names[-1], target=END))

        _validate_workflow_graph(_steps(*names), edges)

    def test_a_disconnected_second_component_is_still_checked(self) -> None:
        """The search starts from every node, not from an entry point.

        A graph's entry is decided elsewhere, so a cycle in a component nothing
        reaches is still a cycle in the declaration — and a check that only
        walked from one root would miss it.
        """
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("a", "x", "y"),
                [
                    Edge(source="a", target=END),
                    Edge(source="x", target="y"),
                    Edge(source="y", target="x"),
                ],
            )
