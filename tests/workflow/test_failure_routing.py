"""Failure becomes an edge — and without one, nothing changes.

`workflow-graph-semantics`/T3. Spec AC-5, AC-6, AC-7.

Today a step that raises stops the walk: one `except`, one exit, scope `failed`.
That is correct for a workflow that has not said otherwise, and **it stays
correct** — which is why the first class here is written before anything else
and asserts exactly today's behaviour. If `OnFailure` changes what an
undeclared failure does, it has broken every existing workflow silently.

The second property is the one that is easy to get wrong. A failure route,
once chosen, is **recorded and read back** on replay — never re-evaluated. The
walk already does this for `ConditionalEdge`, and the reason is in
`_choice_for`'s docstring: *"calling it and discarding the answer would still
run whatever side effects it has"*. A failure predicate is exactly the kind
that pages someone.

**These tests must also reach the validator.** `workflow-graph-semantics`/T2
found that building a `WorkflowDeclaration` directly bypasses
`_validate_workflow_graph` entirely, so the one line `Loop` rested on went
untested and a sabotage against it was inert. `TestTheValidatorSeesOnFailure`
below is that lesson applied here rather than relearned.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._engine.workflow_walker import (
    WalkOutcome,
    WorkflowWalker,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import WorkflowDeclarationError
from functualize._types.workflow import (
    END,
    Edge,
    Gate,
    OnFailure,
    Step,
    WorkflowDeclaration,
)
from functualize.workflow._validation import _validate_workflow_graph


class _Ask(BaseModel):
    text: str


class _Runner:
    """Runs steps, raising for the names it was told to fail."""

    def __init__(self, *failing: str) -> None:
        self.failing = set(failing)
        self.calls: list[str] = []

    def __call__(self, name: str) -> str:
        self.calls.append(name)
        if name in self.failing:
            raise RuntimeError(f"{name} blew up")
        return name

    def count(self, name: str) -> int:
        return self.calls.count(name)


@pytest.fixture
def store(tmp_path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


class TestAnUndeclaredFailureIsUnchanged:
    """AC-6, and the regression gate for the whole task.

    Written first and deliberately: this is the behaviour every workflow that
    exists today relies on. A failure-routing feature that quietly changes it
    has broken them all, and the change would be invisible — the walk would
    simply carry on somewhere instead of stopping.
    """

    @staticmethod
    def _graph() -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("first"), Step("boom"), Step("after")),
            edges=(
                Edge(source="first", target="boom"),
                Edge(source="boom", target="after"),
                Edge(source="after", target=END),
            ),
        )

    def test_a_raising_step_stops_the_walk(self, store: ScopeStore) -> None:
        runner = _Runner("boom")

        report = WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.FAILED, report
        assert report.failed_node == "boom"

    def test_nothing_downstream_runs(self, store: ScopeStore) -> None:
        runner = _Runner("boom")
        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()
        assert runner.count("after") == 0, (
            f"the walk continued past a failure it was never told how to "
            f"route: {runner.calls}"
        )

    def test_the_scope_is_marked_failed(self, store: ScopeStore) -> None:
        runner = _Runner("boom")
        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        record = store.get_scope("s1")
        assert record is not None
        assert record["status"] == "failed"

    def test_the_failing_step_is_recorded_as_failed(self, store: ScopeStore) -> None:
        """So a resume replays what succeeded and stops at the same place."""
        runner = _Runner("boom")
        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        assert store.get_step("s1", _key("boom"))["status"] == "failed"
        assert store.get_step("s1", _key("first"))["status"] == "success"

    def test_the_error_reaches_the_report(self, store: ScopeStore) -> None:
        runner = _Runner("boom")
        report = WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()
        assert "blew up" in (report.error or "")

    def test_the_position_is_the_failing_node(self, store: ScopeStore) -> None:
        runner = _Runner("boom")
        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        record = store.get_scope("s1")
        assert record is not None
        assert record["position"] == "boom"


class TestADeclaredFailureIsRouted:
    """AC-5. Control follows the declared edge and the walk continues."""

    @staticmethod
    def _graph(**kw: object) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("boom"), Step("cleanup"), Step("after")),
            edges=(
                Edge(source="boom", target="after"),
                OnFailure(source="boom", target="cleanup", **kw),  # type: ignore[arg-type]
                Edge(source="cleanup", target=END),
                Edge(source="after", target=END),
            ),
        )

    def test_the_route_is_taken(self, store: ScopeStore) -> None:
        runner = _Runner("boom")

        report = WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED, report
        assert runner.count("cleanup") == 1

    def test_the_success_path_is_not_taken(self, store: ScopeStore) -> None:
        """`boom` did not succeed, so nothing downstream of it is unblocked.

        A routed failure that also advanced the frontier would run both the
        recovery *and* the happy path, which is the worst of both.
        """
        runner = _Runner("boom")
        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()
        assert runner.count("after") == 0, runner.calls

    def test_the_scope_is_not_marked_failed(self, store: ScopeStore) -> None:
        """A workflow that recovers is not a failed workflow.

        **Asserted on a walk that blocks, not one that completes.** A completed
        walk stamps `completed` at the end, which overwrites anything the
        routing wrote — so this test passed even with the scope explicitly
        marked failed at the moment of routing, and a sabotage that did exactly
        that was inert. Blocking at a gate afterwards is what leaves the
        routing's own status visible.
        """
        runner = _Runner("boom")
        graph = WorkflowDeclaration(
            nodes=(Step("boom"), Step("cleanup"), Gate(name="hold", awaits=_Ask)),
            edges=(
                Edge(source="boom", target=END),
                OnFailure(source="boom", target="cleanup"),
                Edge(source="cleanup", target="hold"),
                Edge(source="hold", target=END),
            ),
        )

        report = WorkflowWalker(graph, store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.BLOCKED, report
        record = store.get_scope("s1")
        assert record is not None
        assert record["status"] != "failed", (
            "the walk routed the failure, recovered, and parked at a gate — "
            "but the scope reads failed, so nothing will resume it"
        )
        assert record["status"] == "blocked"

    def test_the_scope_is_not_failed_while_the_recovery_runs(
        self, store: ScopeStore
    ) -> None:
        """Observed **mid-walk**, which is the only place it can be.

        Two weaker versions of this were inert: the final status is rewritten
        by whatever the walk does next — `completed` at the end, `blocked` at a
        gate — so marking the scope failed at the moment of routing is
        invisible to any assertion made afterwards.

        It is not harmless, though. A crash between the routing and the next
        status write would leave the scope reading `failed`, and
        `advanceable_scopes` does not offer a failed scope for resume — so a
        workflow that was recovering would be unresumable. The recovery step
        reading the store as it runs is what makes that window observable.
        """
        seen: list[str] = []

        def runner(name: str) -> str:
            if name == "boom":
                raise RuntimeError("boom blew up")
            record = ScopeStore(store.substrate).get_scope("s1")
            seen.append((record or {}).get("status", "<none>"))
            return name

        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        assert seen and "failed" not in seen, (
            f"the scope read {seen} while the declared recovery was running — "
            f"a crash in that window leaves a recovering workflow unresumable"
        )

    def test_the_step_is_still_recorded_as_failed(self, store: ScopeStore) -> None:
        """It is what happened, and a resume replays to exactly this node."""
        runner = _Runner("boom")
        WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        assert store.get_step("s1", _key("boom"))["status"] == "failed"

    def test_a_route_to_end_finishes_without_failing(self, store: ScopeStore) -> None:
        """ "Swallow this one" is a legitimate thing to declare."""
        graph = WorkflowDeclaration(
            nodes=(Step("boom"),),
            edges=(
                Edge(source="boom", target=END),
                OnFailure(source="boom", target=END),
            ),
        )
        report = WorkflowWalker(graph, store, "s1", run_step=_Runner("boom")).run()

        assert report.outcome is WalkOutcome.COMPLETED, report

    def test_a_predicate_that_declines_leaves_the_failure_fatal(
        self, store: ScopeStore
    ) -> None:
        """`when` narrows the route; it does not turn every failure into one."""
        runner = _Runner("boom")
        graph = self._graph(when=lambda exc: isinstance(exc, KeyError))

        report = WorkflowWalker(graph, store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.FAILED, report
        assert runner.count("cleanup") == 0

    def test_a_predicate_that_matches_routes(self, store: ScopeStore) -> None:
        runner = _Runner("boom")
        graph = self._graph(when=lambda exc: isinstance(exc, RuntimeError))

        report = WorkflowWalker(graph, store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED, report
        assert runner.count("cleanup") == 1

    def test_the_predicate_is_given_the_exception(self, store: ScopeStore) -> None:
        seen: list[BaseException] = []
        graph = self._graph(when=lambda exc: seen.append(exc) or True)

        WorkflowWalker(graph, store, "s1", run_step=_Runner("boom")).run()

        assert len(seen) == 1
        assert "boom blew up" in str(seen[0])


class TestTheRouteIsRecordedNotReEvaluated:
    """AC-7, and the reason is sharper than it is for a conditional.

    `_choice_for` already refuses to call a branch condition twice, because
    *"calling it and discarding the answer would still run whatever side
    effects it has"*. A failure predicate is exactly the kind that pages
    somebody — re-evaluating on every resume pages them again for a decision
    that was already made.
    """

    @staticmethod
    def _graph(calls: list[str]) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("boom"), Step("cleanup"), Gate(name="hold", awaits=_Ask)),
            edges=(
                Edge(source="boom", target="hold"),
                OnFailure(
                    source="boom",
                    target="cleanup",
                    when=lambda _exc: calls.append("asked") or True,
                ),
                Edge(source="cleanup", target="hold"),
                Edge(source="hold", target=END),
            ),
        )

    def test_the_predicate_runs_once_across_a_resume(self, store: ScopeStore) -> None:
        asked: list[str] = []
        runner = _Runner("boom")

        first = WorkflowWalker(self._graph(asked), store, "s1", run_step=runner).run()
        assert first.outcome is WalkOutcome.BLOCKED, first
        assert asked == ["asked"], asked

        store.deposit_gate_payload("s1", "hold", {"text": "go"})
        WorkflowWalker(
            self._graph(asked), ScopeStore(store.substrate), "s1", run_step=runner
        ).run()

        assert asked == ["asked"], (
            f"the failure predicate was evaluated again on resume ({asked}) — "
            f"a predicate that pages would page twice for one decision"
        )

    def test_the_recorded_route_is_followed_on_resume(self, store: ScopeStore) -> None:
        """Read, not merely skipped: the walk still goes where it decided."""
        asked: list[str] = []
        runner = _Runner("boom")
        WorkflowWalker(self._graph(asked), store, "s1", run_step=runner).run()
        store.deposit_gate_payload("s1", "hold", {"text": "go"})

        second = WorkflowWalker(
            self._graph(asked), ScopeStore(store.substrate), "s1", run_step=runner
        ).run()

        assert second.outcome is WalkOutcome.COMPLETED, second

    def test_a_route_to_end_is_recorded_distinctly_from_no_route(
        self, store: ScopeStore
    ) -> None:
        """`END` and "never decided" must not read as the same record.

        Stored as `None` they would be indistinguishable, and a resume would
        re-evaluate the predicate every time for a workflow that routes to END.
        """
        asked: list[str] = []
        graph = WorkflowDeclaration(
            nodes=(Step("boom"),),
            edges=(
                Edge(source="boom", target=END),
                OnFailure(
                    source="boom",
                    target=END,
                    when=lambda _exc: asked.append("asked") or True,
                ),
            ),
        )
        WorkflowWalker(graph, store, "s1", run_step=_Runner("boom")).run()
        WorkflowWalker(
            graph, ScopeStore(store.substrate), "s1", run_step=_Runner("boom")
        ).run()

        assert asked == ["asked"], asked

    def test_an_undeclared_failure_records_no_route(self, store: ScopeStore) -> None:
        """A node that made no decision must not have one written for it.

        Recording "no route" would put a fact in the store that a later
        declaration change should have been free to alter.
        """
        graph = WorkflowDeclaration(
            nodes=(Step("boom"),), edges=(Edge(source="boom", target=END),)
        )
        WorkflowWalker(graph, store, "s1", run_step=_Runner("boom")).run()

        record = store.get_scope("s1")
        assert record is not None
        assert not record.get("branches"), record.get("branches")


class TestTheValidatorSeesOnFailure:
    """The blind spot `workflow-graph-semantics`/T2 found, applied here.

    Every other test in this file builds a `WorkflowDeclaration` and hands it
    straight to the walker, which **never runs validation**. T2 discovered that
    the hard way: nothing exercised the one line `Loop` rested on, and a
    sabotage against it was inert. These call the validator directly.
    """

    def test_an_unknown_target_is_refused(self) -> None:
        with pytest.raises(ValueError, match="OnFailure target"):
            _validate_workflow_graph(
                [Step("boom")],
                [OnFailure(source="boom", target="nowhere")],
            )

    def test_an_unknown_source_is_refused(self) -> None:
        """The same check every other edge kind gets."""
        with pytest.raises(ValueError, match="Edge source"):
            _validate_workflow_graph(
                [Step("boom")],
                [OnFailure(source="nowhere", target="boom")],
            )

    def test_a_route_to_end_is_accepted(self) -> None:
        _validate_workflow_graph(
            [Step("boom")],
            [Edge(source="boom", target=END), OnFailure(source="boom", target=END)],
        )

    def test_a_failure_route_backwards_is_not_a_cycle(self) -> None:
        """Deliberate: "on failure, go back and clean up" is an ordinary shape.

        A failure route can only be taken once — it is recorded on first
        evaluation and read on replay — so counting it as a cycle would refuse
        a legal graph for a loop that cannot run.
        """
        _validate_workflow_graph(
            [Step("setup"), Step("work")],
            [
                Edge(source="setup", target="work"),
                OnFailure(source="work", target="setup"),
                Edge(source="work", target=END),
            ],
        )

    def test_an_ordinary_cycle_beside_one_is_still_refused(self) -> None:
        """The exemption is the edge, not the graph."""
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                [Step("setup"), Step("work"), Step("x"), Step("y")],
                [
                    Edge(source="setup", target="work"),
                    OnFailure(source="work", target="setup"),
                    Edge(source="x", target="y"),
                    Edge(source="y", target="x"),
                ],
            )

    def test_a_non_edge_is_still_refused_by_type(self) -> None:
        with pytest.raises(TypeError, match="Edge, ConditionalEdge, Loop or OnFailure"):
            _validate_workflow_graph([Step("a")], [("a", "b")])  # type: ignore[list-item]


def _key(name: str) -> str:
    from functualize._engine.frontier import step_key

    return step_key(name, "")
