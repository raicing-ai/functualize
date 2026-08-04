"""Tests for WorkflowDeclaration and its boot-time resolution (§A.7).

Splits cleanly in two: what a declaration knows on its own (readable with no
live app, which is what lets discovery cache the graph shape), and what only
the registry can settle (unknown step refs, workflow nesting cycles).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._types.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    WorkflowDeclaration,
)
from functualize.workflow import workflow


class Approval(BaseModel):
    """Gate schema used across these tests."""

    approved: bool = False


class TestDeclarationAttachment:
    """The dunder contract, mirroring @job's __functualize_job__."""

    def test_attaches_frozen_declaration(self) -> None:
        """@workflow attaches a WorkflowDeclaration, not a raw dict."""

        @workflow(steps=[Step("a")], edges=[Edge(source="a", target=END)])
        def flow() -> None: ...

        declaration = flow.__functualize_workflow__
        assert isinstance(declaration, WorkflowDeclaration)
        assert declaration.nodes[0].name == "a"

    def test_old_dunder_is_gone(self) -> None:
        """__workflow_def__ is deleted, not kept alongside.

        Leaving both would let a stale reader silently keep working against
        the pre-narrowing shape.
        """

        @workflow(steps=[Step("a")], edges=[])
        def flow() -> None: ...

        assert not hasattr(flow, "__workflow_def__")

    def test_identity_preserving(self) -> None:
        """The decorated function is the original object."""

        def flow() -> str:
            return "body"

        decorated = workflow(steps=[Step("a")], edges=[])(flow)
        assert decorated is flow
        assert decorated() == "body"

    def test_sequences_are_frozen_to_tuples(self) -> None:
        """Mutating the caller's list must not mutate the declaration."""
        steps = [Step("a")]
        edges: list[Edge] = []

        @workflow(steps=steps, edges=edges)
        def flow() -> None: ...

        steps.append(Step("b"))
        assert len(flow.__functualize_workflow__.nodes) == 1


class TestDeclarationQueries:
    """What a declaration answers without a live app."""

    def _declaration(self) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("build"), Gate(name="approve", awaits=Approval), Step("ship")),
            edges=(
                Edge(source="build", target="approve"),
                Edge(source="approve", target="ship"),
                Edge(source="ship", target=END),
            ),
        )

    def test_entry_is_first_declared_node(self) -> None:
        """Declaration order defines the entry point."""
        assert self._declaration().entry == "build"

    def test_entry_of_empty_graph(self) -> None:
        """An empty graph has no entry rather than raising."""
        assert WorkflowDeclaration().entry is None

    def test_entry_survives_a_loop_back_to_the_first_node(self) -> None:
        """Entry is not "the node with no inbound edge".

        A graph that loops back to its first node has no such node, which
        would leave that rule with no answer at all.
        """
        declaration = WorkflowDeclaration(
            nodes=(Step("a"), Step("b")),
            edges=(Edge(source="a", target="b"), Edge(source="b", target="a")),
        )
        assert declaration.entry == "a"

    def test_node_lookup(self) -> None:
        """Nodes are addressable by graph key; misses return None."""
        declaration = self._declaration()
        assert declaration.node("approve") == Gate(name="approve", awaits=Approval)
        assert declaration.node("nope") is None

    def test_step_refs_excludes_gates(self) -> None:
        """Only steps have a job to resolve."""
        assert self._declaration().step_refs() == ("build", "ship")

    def test_gates(self) -> None:
        """Gates are enumerable for schema publication."""
        assert [g.name for g in self._declaration().gates()] == ["approve"]

    def test_successors_follow_edges(self) -> None:
        """One-hop successors come from outgoing edges."""
        assert self._declaration().successors("build") == ("approve",)

    def test_successors_omits_end(self) -> None:
        """END terminates a walk; it is not a node."""
        assert self._declaration().successors("ship") == ()

    def test_successors_include_every_conditional_branch(self) -> None:
        """All possible targets count — which one is taken is a runtime fact.

        Static analysis (nesting cycles, cache shape) must consider branches
        it will not necessarily take.
        """
        declaration = WorkflowDeclaration(
            nodes=(Step("check"), Step("yes"), Step("no")),
            edges=(
                ConditionalEdge(
                    source="check",
                    condition=lambda _: "yes",
                    targets={"yes": "yes", "no": "no", "stop": END},
                ),
            ),
        )
        assert sorted(declaration.successors("check")) == ["no", "yes"]


class TestBootResolution:
    """What only the live registry can settle."""

    def _validate(self, jobs: dict[str, object]) -> None:
        """Run boot validation against a minimal fake registry."""
        from types import SimpleNamespace

        from functualize._app.boot import validate_workflow_declarations

        registered = {name: SimpleNamespace(function=fn) for name, fn in jobs.items()}
        app = SimpleNamespace(job_registry=SimpleNamespace(_registered_jobs=registered))
        validate_workflow_declarations(app)

    def test_known_step_refs_pass(self) -> None:
        """A workflow whose steps are all registered validates."""

        def build() -> None: ...

        @workflow(steps=[Step("build")], edges=[Edge(source="build", target=END)])
        def flow() -> None: ...

        self._validate({"build": build, "flow": flow})

    def test_unknown_step_ref_raises_at_boot(self) -> None:
        """An unregistered step ref fails at boot, not mid-walk.

        Discovering it mid-walk would mean failing with a scope already open
        and earlier steps already run.
        """
        from functualize._types.errors import WorkflowDeclarationError

        @workflow(steps=[Step("ghost")], edges=[])
        def flow() -> None: ...

        with pytest.raises(WorkflowDeclarationError, match="unknown job 'ghost'"):
            self._validate({"flow": flow})

    def test_callable_ref_resolves_by_identity(self) -> None:
        """A callable step ref resolves through the registry by identity."""

        def build() -> None: ...

        @workflow(steps=[Step(build)], edges=[])
        def flow() -> None: ...

        self._validate({"infra.build": build, "flow": flow})

    def test_gate_only_workflow_needs_no_jobs(self) -> None:
        """Gates have no job ref, so they never fail resolution."""

        @workflow(steps=[Gate(name="approve", awaits=Approval)], edges=[])
        def flow() -> None: ...

        self._validate({"flow": flow})

    def test_nesting_cycle_raises(self) -> None:
        """Two workflows nesting each other is a cycle and must fail at boot."""
        from functualize._types.errors import WorkflowDeclarationError

        @workflow(steps=[Step("beta")], edges=[])
        def alpha() -> None: ...

        @workflow(steps=[Step("alpha")], edges=[])
        def beta() -> None: ...

        with pytest.raises(WorkflowDeclarationError, match="nesting cycle"):
            self._validate({"alpha": alpha, "beta": beta})

    def test_self_nesting_raises(self) -> None:
        """A workflow that steps on itself is the degenerate cycle."""
        from functualize._types.errors import WorkflowDeclarationError

        @workflow(steps=[Step("loop")], edges=[])
        def loop() -> None: ...

        with pytest.raises(WorkflowDeclarationError, match="nesting cycle"):
            self._validate({"loop": loop})

    def test_legal_nesting_passes(self) -> None:
        """Nesting is allowed — only cycles are not."""

        def build() -> None: ...

        @workflow(steps=[Step("build")], edges=[])
        def inner() -> None: ...

        @workflow(steps=[Step("inner")], edges=[])
        def outer() -> None: ...

        self._validate({"build": build, "inner": inner, "outer": outer})

    def test_diamond_nesting_is_not_a_cycle(self) -> None:
        """Two workflows nesting the same child is a diamond, not a cycle.

        A naive "already seen this node" check would reject this.
        """

        @workflow(steps=[], edges=[])
        def shared() -> None: ...

        @workflow(steps=[Step("shared")], edges=[])
        def left() -> None: ...

        @workflow(steps=[Step("shared")], edges=[])
        def right() -> None: ...

        @workflow(steps=[Step("left"), Step("right")], edges=[])
        def top() -> None: ...

        self._validate({"shared": shared, "left": left, "right": right, "top": top})

    def test_no_workflows_is_a_no_op(self) -> None:
        """An app with no workflows validates trivially."""

        def build() -> None: ...

        self._validate({"build": build})
