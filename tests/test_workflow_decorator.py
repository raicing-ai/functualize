"""Unit tests for the @workflow decorator and graph validation."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize.workflow import END, ConditionalEdge, Edge, Gate, Step, workflow
from functualize.workflow._validation import _validate_workflow_graph


class Approval(BaseModel):
    """Gate input schema used across these tests."""

    approved: bool = False


class TestWorkflowDecorator:
    """Tests for the @workflow decorator."""

    def test_attaches_declaration(self) -> None:
        """Decorator attaches the declared graph to the function."""
        steps = [Step("a"), Step("b")]
        edges = [Edge(source="a", target="b")]

        @workflow(steps=steps, edges=edges)
        def my_flow():
            pass

        declaration = my_flow.__functualize_workflow__
        assert list(declaration.nodes) == steps
        assert list(declaration.edges) == edges

    def test_preserves_function_identity(self) -> None:
        """Decorator returns the same function object."""

        @workflow(steps=[Step("x")], edges=[])
        def my_flow():
            """Docstring."""
            return 42

        assert my_flow() == 42
        assert my_flow.__doc__ == "Docstring."

    def test_empty_edges_valid(self) -> None:
        """A workflow with a node but no edges is valid."""

        @workflow(steps=[Step("solo")], edges=[])
        def solo_flow():
            pass

        assert solo_flow.__functualize_workflow__.nodes[0].name == "solo"
        assert solo_flow.__functualize_workflow__.edges == ()

    def test_multiple_edges(self) -> None:
        """Workflow can have multiple edges."""
        steps = [Step("a"), Step("b"), Step("c")]
        edges = [Edge(source="a", target="b"), Edge(source="b", target="c")]

        @workflow(steps=steps, edges=edges)
        def multi_flow():
            pass

        assert len(multi_flow.__functualize_workflow__.edges) == 2

    def test_end_target_allowed(self) -> None:
        """END sentinel is accepted as a valid edge target."""

        @workflow(steps=[Step("final")], edges=[Edge(source="final", target=END)])
        def end_flow():
            pass

        assert end_flow.__functualize_workflow__.edges[0].target is END

    def test_conditional_edge_with_end(self) -> None:
        """ConditionalEdge targets can include END."""

        @workflow(
            steps=[Step("check"), Step("next")],
            edges=[
                ConditionalEdge(
                    source="check",
                    condition=lambda _: "done",
                    targets={"done": END, "continue": "next"},
                )
            ],
        )
        def cond_flow():
            pass

        assert cond_flow.__functualize_workflow__.edges[0].targets["done"] is END

    def test_gate_node_in_graph(self) -> None:
        """A Gate is a node like any other and wires up by name."""

        @workflow(
            steps=[Step("build"), Gate(name="approval", awaits=Approval)],
            edges=[
                Edge(source="build", target="approval"),
                Edge(source="approval", target=END),
            ],
        )
        def gated_flow():
            pass

        nodes = gated_flow.__functualize_workflow__.nodes
        assert [n.name for n in nodes] == ["build", "approval"]

    def test_callable_step_ref_wires_by_job_name(self) -> None:
        """A callable Step ref resolves to the same name edges use."""

        def build() -> None: ...

        @workflow(steps=[Step(build)], edges=[Edge(source="build", target=END)])
        def callable_flow():
            pass

        assert callable_flow.__functualize_workflow__.nodes[0].name == "build"


class TestValidateWorkflowGraph:
    """Tests for _validate_workflow_graph."""

    def test_duplicate_node_names_raises(self) -> None:
        """Duplicate node names raise ValueError."""
        with pytest.raises(ValueError, match="Duplicate workflow node name 'dup'"):
            _validate_workflow_graph([Step("dup"), Step("dup")], [])

    def test_step_and_gate_share_one_namespace(self) -> None:
        """A Gate may not reuse a Step's name.

        Nodes are addressed by name in edges and in resume calls; two nodes
        answering to one name would make the resume target ambiguous.
        """
        with pytest.raises(ValueError, match="Duplicate workflow node name 'x'"):
            _validate_workflow_graph([Step("x"), Gate(name="x", awaits=Approval)], [])

    def test_unknown_edge_source_raises(self) -> None:
        """Edge with unknown source raises ValueError."""
        with pytest.raises(ValueError, match="Edge source 'ghost' not found"):
            _validate_workflow_graph([Step("a")], [Edge(source="ghost", target="a")])

    def test_unknown_edge_target_raises(self) -> None:
        """Edge with unknown target raises ValueError."""
        with pytest.raises(ValueError, match="Edge target 'ghost' not found"):
            _validate_workflow_graph([Step("a")], [Edge(source="a", target="ghost")])

    def test_conditional_edge_unknown_source_raises(self) -> None:
        """ConditionalEdge with unknown source raises ValueError."""
        with pytest.raises(ValueError, match="Edge source 'ghost' not found"):
            _validate_workflow_graph(
                [Step("a")],
                [
                    ConditionalEdge(
                        source="ghost", condition=lambda _: "a", targets={"k": "a"}
                    )
                ],
            )

    def test_conditional_edge_unknown_target_raises(self) -> None:
        """ConditionalEdge with unknown target in mapping raises ValueError."""
        with pytest.raises(
            ValueError,
            match=r"ConditionalEdge target 'ghost' \(key='k'\) not found",
        ):
            _validate_workflow_graph(
                [Step("a")],
                [
                    ConditionalEdge(
                        source="a", condition=lambda _: "k", targets={"k": "ghost"}
                    )
                ],
            )

    def test_conditional_edge_end_target_allowed(self) -> None:
        """ConditionalEdge END target does not raise."""
        _validate_workflow_graph(
            [Step("a")],
            [
                ConditionalEdge(
                    source="a", condition=lambda _: "done", targets={"done": END}
                )
            ],
        )

    def test_edge_end_target_allowed(self) -> None:
        """Edge END target does not raise."""
        _validate_workflow_graph([Step("a")], [Edge(source="a", target=END)])

    def test_valid_graph_passes(self) -> None:
        """A fully valid graph does not raise."""
        _validate_workflow_graph(
            [Step("a"), Step("b"), Step("c")],
            [
                Edge(source="a", target="b"),
                Edge(source="b", target="c"),
                Edge(source="c", target=END),
            ],
        )

    def test_mixed_edges_valid(self) -> None:
        """Graph with both Edge and ConditionalEdge is valid."""
        _validate_workflow_graph(
            [Step("start"), Step("yes"), Step("no")],
            [
                ConditionalEdge(
                    source="start",
                    condition=lambda x: "yes" if x else "no",
                    targets={"yes": "yes", "no": "no"},
                ),
                Edge(source="yes", target=END),
                Edge(source="no", target=END),
            ],
        )

    def test_non_node_entry_rejected(self) -> None:
        """A stray value in the node list is a mistake, not a silent no-op."""
        with pytest.raises(TypeError, match="must be Step or Gate"):
            _validate_workflow_graph(["build"], [])  # type: ignore[list-item]

    def test_non_edge_entry_rejected(self) -> None:
        """A stray value in the edge list is a mistake, not a silent no-op."""
        with pytest.raises(TypeError, match="must be Edge or ConditionalEdge"):
            _validate_workflow_graph([Step("a")], [("a", "b")])  # type: ignore[list-item]
