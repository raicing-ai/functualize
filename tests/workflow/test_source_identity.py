"""A resume refuses a changed **graph**, and tolerates a changed file.

`durable-run-layer`/T11. Spec AC-16, AC-17. Decision K3, risk R-g.

Both halves matter, and the second is the one that fails if the digest is taken
over the source file:

* editing the **graph** — adding a node, moving an edge — must refuse a resume,
  because replaying step records against a different shape is what produces a
  walk nobody declared.
* editing an **unrelated job in the same file** must succeed. A file digest
  refuses here, and would also refuse for a reformat, a docstring, or a new
  import. That is not a safety property; it is a permanent annoyance that
  teaches people to bypass the check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from functualize._engine.workflow_validation import (
    WorkflowGraphChangedError,
    graph_digest,
)
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.fresh_store import FreshStore
from functualize._types.workflow import (
    END,
    Edge,
    Gate,
    Step,
    WorkflowDeclaration,
)


class Approval(BaseModel):
    ok: bool = True


def _two_steps() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("a"), Step("b")),
        edges=(Edge(source="a", target="b"), Edge(source="b", target=END)),
    )


def _three_steps() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("a"), Step("c"), Step("b")),
        edges=(
            Edge(source="a", target="c"),
            Edge(source="c", target="b"),
            Edge(source="b", target=END),
        ),
    )


def _rerouted() -> WorkflowDeclaration:
    """Same nodes, different edges — the change a node list cannot see."""
    return WorkflowDeclaration(
        nodes=(Step("a"), Step("b")),
        edges=(Edge(source="a", target=END), Edge(source="b", target=END)),
    )


@pytest.fixture
def store(tmp_path: Path) -> FreshStore:
    return FreshStore(tmp_path / "fresh.json")


def _walk(declaration: WorkflowDeclaration, store: FreshStore) -> WorkflowWalker:
    return WorkflowWalker(declaration, store, "wf", run_step=lambda name: name)


class TestTheDigestIsOverTheGraph:
    def test_the_same_graph_digests_the_same(self) -> None:
        assert graph_digest(_two_steps()) == graph_digest(_two_steps())

    def test_adding_a_node_changes_it(self) -> None:
        assert graph_digest(_two_steps()) != graph_digest(_three_steps())

    def test_moving_an_edge_changes_it(self) -> None:
        """The case a node-name comparison would miss.

        Same nodes, different routing: a walk parked at `a` would resume into a
        graph where `a` now leads to END.
        """
        assert graph_digest(_two_steps()) != graph_digest(_rerouted())

    def test_a_gate_is_part_of_the_shape(self) -> None:
        gated = WorkflowDeclaration(
            nodes=(Step("a"), Gate(name="approval", awaits=Approval), Step("b")),
            edges=(
                Edge(source="a", target="approval"),
                Edge(source="approval", target="b"),
                Edge(source="b", target=END),
            ),
        )
        assert graph_digest(gated) != graph_digest(_two_steps())

    def test_a_non_workflow_digests_to_empty(self) -> None:
        """So a caller can compare unconditionally.

        Two empty digests are equal, which is the right answer for a scope that
        never had a graph.
        """
        assert graph_digest(object()) == ""


class TestResumeRefusesAChangedGraph:
    """AC-16, first half."""

    def test_a_second_walk_against_a_changed_graph_is_refused(
        self, store: FreshStore
    ) -> None:
        _walk(_two_steps(), store).run()

        with pytest.raises(WorkflowGraphChangedError) as exc:
            _walk(_three_steps(), store).run()

        assert exc.value.recorded != exc.value.current
        assert exc.value.scope_id == "wf"

    def test_the_refusal_names_both_digests(self, store: FreshStore) -> None:
        """ "Your workflow changed" is not an answer to "what changed"."""
        _walk(_two_steps(), store).run()
        with pytest.raises(WorkflowGraphChangedError) as exc:
            _walk(_rerouted(), store).run()

        message = str(exc.value)
        assert exc.value.recorded in message
        assert exc.value.current in message

    def test_the_refusal_destroys_nothing(self, store: FreshStore) -> None:
        """Only *advancing* is refused. The records stay readable.

        A refusal that also cleared the scope would make the safety check more
        destructive than the unsafe resume it prevents.
        """
        _walk(_two_steps(), store).run()
        before = store.get_scope("wf")

        with pytest.raises(WorkflowGraphChangedError):
            _walk(_three_steps(), store).run()

        after = store.get_scope("wf")
        assert after["steps"] == before["steps"]
        assert after["graph_digest"] == before["graph_digest"]

    def test_the_same_graph_resumes_fine(self, store: FreshStore) -> None:
        _walk(_two_steps(), store).run()
        _walk(_two_steps(), store).run()  # must not raise


class TestAnUnrelatedChangeInTheSameFileIsFine:
    """AC-16, second half — **the test that fails if the digest is the file**.

    Every declaration below lives in this module, alongside every other test,
    fixture and import here. A file digest would change on any edit to this
    file at all; the graph digest does not move unless the graph does.
    """

    def test_an_unrelated_job_changing_does_not_refuse(self, store: FreshStore) -> None:
        """The graph is identical; what the *steps do* is not part of it.

        A step names a job. Changing that job's body is exactly the edit people
        make while a workflow is parked — fixing the bug that made them park it.
        """
        _walk(_two_steps(), store).run()

        rebuilt = WorkflowWalker(
            _two_steps(),
            store,
            "wf",
            run_step=lambda name: f"{name}-rewritten-implementation",
        )
        rebuilt.run()  # must not raise

    def test_the_digest_ignores_everything_but_the_shape(self) -> None:
        """Stated directly: two declarations with one shape share one digest,
        however they were built."""
        by_literal = WorkflowDeclaration(
            nodes=(Step("a"), Step("b")),
            edges=(Edge(source="a", target="b"), Edge(source="b", target=END)),
        )
        built = WorkflowDeclaration(
            nodes=tuple(Step(n) for n in ("a", "b")),
            edges=tuple(Edge(source=s, target=t) for s, t in (("a", "b"), ("b", END))),
        )
        assert graph_digest(by_literal) == graph_digest(built)


class TestTheLegacyPath:
    """AC-17. A scope parked before this check existed must still resume."""

    def test_an_unrecorded_digest_resumes_and_is_recorded(
        self, store: FreshStore
    ) -> None:
        """Refusing here would strand every walk that was already waiting."""
        store.ensure_scope("wf", "demo")
        store.set_scope_status("wf", "blocked")
        assert store.get_graph_digest("wf") == ""

        _walk(_two_steps(), store).run()

        assert store.get_graph_digest("wf") == graph_digest(_two_steps())

    def test_the_digest_is_written_once_and_not_overwritten(
        self, store: FreshStore
    ) -> None:
        """Or it would always agree with itself.

        A digest that followed the current declaration would be updated on
        every entry, and the comparison would be between a value and itself.
        """
        _walk(_two_steps(), store).run()
        recorded = store.get_graph_digest("wf")

        with pytest.raises(WorkflowGraphChangedError):
            _walk(_three_steps(), store).run()

        assert store.get_graph_digest("wf") == recorded, (
            "the digest was overwritten by the very walk it refused — the "
            "next resume would compare the new graph against itself and pass"
        )
