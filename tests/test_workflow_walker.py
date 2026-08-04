"""Tests for the workflow walker (§A.7, §D.7).

The walker's job is to be boring on the happy path and *stable* on resume, so
most of these tests are about the second invocation rather than the first: what
must not run twice, and what must not change its mind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from functualize._engine.workflow_walker import (
    WalkOutcome,
    WorkflowWalker,
    graph_model_of,
)
from functualize._primitives.state_store import StateStore
from functualize._types.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    WorkflowDeclaration,
)

if TYPE_CHECKING:
    from pathlib import Path


class TripPreferences(BaseModel):
    """Gate schema used across these tests."""

    budget: str = "mid"


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.json")


class Recorder:
    """A run_step that records call order and returns canned values."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.calls: list[str] = []
        self._values = values or {}

    def __call__(self, name: str) -> Any:
        self.calls.append(name)
        return self._values.get(name, f"{name}-result")


def _linear() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("forecast"), Step("travel_plan")),
        edges=(
            Edge(source="forecast", target="travel_plan"),
            Edge(source="travel_plan", target=END),
        ),
    )


def _gated() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(
            Step("forecast"),
            Gate(name="preferences", awaits=TripPreferences),
            Step("travel_plan"),
        ),
        edges=(
            Edge(source="forecast", target="preferences"),
            Edge(source="preferences", target="travel_plan"),
            Edge(source="travel_plan", target=END),
        ),
    )


class TestGraphCompilation:
    """Declaration -> the shared GraphModel (§A.7 one-engine rule)."""

    def test_end_flattens_to_the_walk_marker(self) -> None:
        """The declaration's END sentinel is not the frontier's END string."""
        model = graph_model_of(_linear())
        assert model.entry == "forecast"
        assert model.successors("travel-plan") == ["__end__"]

    def test_conditional_edges_land_in_the_conditional_map(self) -> None:
        """Conditional sources route by choice, not by static successor list."""
        declaration = WorkflowDeclaration(
            nodes=(Step("check"), Step("deploy")),
            edges=(
                ConditionalEdge(
                    source="check",
                    condition=lambda _: "ok",
                    targets={"ok": "deploy", "stop": END},
                ),
            ),
        )
        model = graph_model_of(declaration)
        assert model.is_conditional("check")
        assert model.successors("check", "ok") == ["deploy"]
        assert model.successors("check", "stop") == ["__end__"]

    def test_an_empty_declaration_compiles(self) -> None:
        """Degenerate but must not raise — boot validates, the walker doesn't."""
        assert graph_model_of(WorkflowDeclaration()).entry == ""


class TestLinearWalk:
    def test_runs_every_step_in_order(self, store: StateStore) -> None:
        runner = Recorder()
        report = WorkflowWalker(_linear(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert report.ok
        assert runner.calls == ["forecast", "travel-plan"]
        assert report.executed == ("forecast", "travel-plan")
        assert report.replayed == ()

    def test_completion_is_persisted(self, store: StateStore) -> None:
        """A finished walk leaves no position and a completed status."""
        WorkflowWalker(_linear(), store, "s1", run_step=Recorder()).run()

        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["status"] == "completed"
        assert scope["position"] is None

    def test_workflow_name_is_recorded_for_observers(self, store: StateStore) -> None:
        """MCP lists scopes by the workflow they belong to."""
        WorkflowWalker(
            _linear(), store, "s1", run_step=Recorder(), workflow_name="trip_planner"
        ).run()
        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["workflow"] == "trip_planner"

    def test_an_empty_graph_completes_without_running_anything(
        self, store: StateStore
    ) -> None:
        runner = Recorder()
        report = WorkflowWalker(
            WorkflowDeclaration(), store, "s1", run_step=runner
        ).run()
        assert report.outcome is WalkOutcome.COMPLETED
        assert runner.calls == []


class TestGateBlocking:
    def test_walk_blocks_at_a_gate_with_no_input(self, store: StateStore) -> None:
        runner = Recorder()
        report = WorkflowWalker(_gated(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.BLOCKED
        assert report.blocked_on == "preferences"
        assert not report.ok
        # The step past the gate must not have run.
        assert runner.calls == ["forecast"]

    def test_block_persists_position_status_and_schema(self, store: StateStore) -> None:
        """Everything a different process needs to observe and resume the walk."""
        WorkflowWalker(_gated(), store, "s1", run_step=Recorder()).run()

        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["status"] == "blocked"
        assert scope["position"] == "preferences"

        gate = store.get_gate("s1", "preferences")
        assert gate is not None
        assert gate["model"] == "TripPreferences"
        assert gate["payload"] is None
        assert "budget" in gate["input_schema"]["properties"]
        assert gate["blocked_at"]


class TestResume:
    """Replay + memoization (§D.7): re-invoke, skip what is recorded."""

    def test_full_block_resume_complete_cycle(self, store: StateStore) -> None:
        first = Recorder()
        blocked = WorkflowWalker(_gated(), store, "s1", run_step=first).run()
        assert blocked.outcome is WalkOutcome.BLOCKED

        store.deposit_gate_payload("s1", "preferences", {"budget": "high"})

        second = Recorder()
        resumed = WorkflowWalker(_gated(), store, "s1", run_step=second).run()

        assert resumed.outcome is WalkOutcome.COMPLETED
        # The pre-gate step is memoized; only the post-gate step actually runs.
        assert second.calls == ["travel-plan"]
        assert resumed.replayed == ("forecast", "preferences")
        assert resumed.executed == ("travel-plan",)

    def test_resume_reuses_the_recorded_return_value(self, store: StateStore) -> None:
        """A replayed step's value must still be available downstream.

        Otherwise memoization would silently degrade the graph: the step is
        skipped, but everything reading its result sees None.
        """
        WorkflowWalker(
            _gated(), store, "s1", run_step=Recorder({"forecast": "sunny"})
        ).run()
        store.deposit_gate_payload("s1", "preferences", {"budget": "high"})

        resumed = WorkflowWalker(_gated(), store, "s1", run_step=Recorder()).run()
        assert resumed.results["forecast"] == "sunny"
        assert resumed.results["preferences"] == {"budget": "high"}

    def test_resuming_a_completed_scope_is_a_no_op(self, store: StateStore) -> None:
        """Body-once-per-scope depends on this (§A.7)."""
        WorkflowWalker(_linear(), store, "s1", run_step=Recorder()).run()

        again = Recorder()
        report = WorkflowWalker(_linear(), store, "s1", run_step=again).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert again.calls == []
        assert report.executed == ()

    def test_a_still_blocked_gate_blocks_again(self, store: StateStore) -> None:
        """Re-invoking without depositing input must not slip past the gate."""
        WorkflowWalker(_gated(), store, "s1", run_step=Recorder()).run()

        second = Recorder()
        report = WorkflowWalker(_gated(), store, "s1", run_step=second).run()

        assert report.outcome is WalkOutcome.BLOCKED
        assert second.calls == []

    def test_scopes_are_independent(self, store: StateStore) -> None:
        """A fresh invocation gets a fresh scope and re-runs everything."""
        WorkflowWalker(_linear(), store, "s1", run_step=Recorder()).run()

        other = Recorder()
        WorkflowWalker(_linear(), store, "s2", run_step=other).run()
        assert other.calls == ["forecast", "travel-plan"]


class TestBranchStability:
    """§D.7d: a non-deterministic condition must not move a resumed walk."""

    def _branching(self, condition: Any) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(
                Step("check"),
                Step("deploy"),
                Gate(name="approval", awaits=TripPreferences),
                Step("rollback"),
            ),
            edges=(
                ConditionalEdge(
                    source="check",
                    condition=condition,
                    targets={"go": "deploy", "stop": "approval"},
                ),
                Edge(source="deploy", target=END),
                Edge(source="approval", target="rollback"),
                Edge(source="rollback", target=END),
            ),
        )

    def test_branch_choice_is_recorded_on_first_evaluation(
        self, store: StateStore
    ) -> None:
        WorkflowWalker(
            self._branching(lambda _: "go"), store, "s1", run_step=Recorder()
        ).run()
        assert store.get_branch("s1", "check") == "go"

    def test_a_flipping_condition_does_not_move_a_resumed_walk(
        self, store: StateStore
    ) -> None:
        """The scenario §D.7d exists for: the condition answers differently
        on resume than it did when the walk paused."""
        answers = iter(["stop", "go", "go", "go"])
        declaration = self._branching(lambda _: next(answers))

        blocked = WorkflowWalker(declaration, store, "s1", run_step=Recorder()).run()
        assert blocked.blocked_on == "approval"

        store.deposit_gate_payload("s1", "approval", {"budget": "low"})

        runner = Recorder()
        resumed = WorkflowWalker(declaration, store, "s1", run_step=runner).run()

        assert resumed.outcome is WalkOutcome.COMPLETED
        # Followed "stop" again, despite the condition now saying "go".
        assert runner.calls == ["rollback"]
        assert "deploy" not in runner.calls

    def test_a_recorded_branch_does_not_call_the_condition_again(
        self, store: StateStore
    ) -> None:
        """Reading the recorded choice must skip the callable entirely.

        Calling it and discarding the answer would still fire its side effects
        and still pay whatever it costs.
        """
        calls: list[Any] = []

        def condition(value: Any) -> str:
            calls.append(value)
            return "stop"

        declaration = self._branching(condition)
        WorkflowWalker(declaration, store, "s1", run_step=Recorder()).run()
        assert len(calls) == 1

        store.deposit_gate_payload("s1", "approval", {"budget": "low"})
        WorkflowWalker(declaration, store, "s1", run_step=Recorder()).run()
        assert len(calls) == 1

    def test_the_condition_receives_the_source_return_value(
        self, store: StateStore
    ) -> None:
        seen: list[Any] = []

        def condition(value: Any) -> str:
            seen.append(value)
            return "go"

        WorkflowWalker(
            self._branching(condition),
            store,
            "s1",
            run_step=Recorder({"check": {"status": "green"}}),
        ).run()
        assert seen == [{"status": "green"}]

    def test_an_unmatched_choice_ends_the_walk(self, store: StateStore) -> None:
        """A condition returning a key with no target has nowhere to go."""
        runner = Recorder()
        report = WorkflowWalker(
            self._branching(lambda _: "nonsense"), store, "s1", run_step=runner
        ).run()
        assert report.outcome is WalkOutcome.COMPLETED
        assert runner.calls == ["check"]


class TestFailure:
    def test_a_raising_step_fails_the_walk(self, store: StateStore) -> None:
        def boom(name: str) -> Any:
            raise RuntimeError("no network")

        report = WorkflowWalker(_linear(), store, "s1", run_step=boom).run()

        assert report.outcome is WalkOutcome.FAILED
        assert report.failed_node == "forecast"
        assert "RuntimeError: no network" in report.error

    def test_failure_is_persisted_and_downstream_does_not_run(
        self, store: StateStore
    ) -> None:
        calls: list[str] = []

        def flaky(name: str) -> Any:
            calls.append(name)
            if name == "forecast":
                raise RuntimeError("boom")
            return None

        WorkflowWalker(_gated(), store, "s1", run_step=flaky).run()

        assert calls == ["forecast"]
        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["status"] == "failed"
        assert scope["position"] == "forecast"
        assert scope["steps"]["forecast::"]["status"] == "failed"

    def test_a_failed_step_is_retried_on_resume(self, store: StateStore) -> None:
        """Only *successful* steps memoize — a failure must be retryable."""
        attempts: list[str] = []

        def once(name: str) -> Any:
            attempts.append(name)
            if name == "forecast" and attempts.count("forecast") == 1:
                raise RuntimeError("transient")
            return None

        assert (
            WorkflowWalker(_linear(), store, "s1", run_step=once).run().outcome
            is WalkOutcome.FAILED
        )
        report = WorkflowWalker(_linear(), store, "s1", run_step=once).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert attempts == ["forecast", "forecast", "travel-plan"]


class TestFanOut:
    """Multiple edges out of one node."""

    def _diamond(self) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("start"), Step("left"), Step("right"), Step("join")),
            edges=(
                Edge(source="start", target="left"),
                Edge(source="start", target="right"),
                Edge(source="left", target="join"),
                Edge(source="right", target="join"),
                Edge(source="join", target=END),
            ),
        )

    def test_both_branches_run(self, store: StateStore) -> None:
        runner = Recorder()
        report = WorkflowWalker(self._diamond(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert set(runner.calls) == {"start", "left", "right", "join"}

    def test_a_join_does_not_wait_for_a_branch_never_taken(
        self, store: StateStore
    ) -> None:
        """A conditional skips one predecessor; the join must still run.

        No other test combines a branch with a join, and it is the shape most
        at risk: `join` declares two predecessors but only one of them is ever
        reachable, so a walker that waited for *every* declared predecessor
        would hang here rather than finish.

        This pins the contract — the join runs, the untaken branch does not —
        rather than any particular mechanism. `_ready` implements it as
        reachability from the queue, with a deferral counter behind it as a
        backstop; sabotaging either alone still passes, because the other
        covers it.

        It is also the concrete reason this frontier cannot become a plain
        `graphlib.TopologicalSorter`: that readiness is predecessor *count*
        over a graph fixed before the walk starts, and `right` here is an edge
        whose existence is only decided once `pick` returns.
        """
        declaration = WorkflowDeclaration(
            nodes=(Step("pick"), Step("left"), Step("right"), Step("join")),
            edges=(
                ConditionalEdge(
                    source="pick",
                    condition=lambda value: value,
                    targets={"left": "left", "right": "right"},
                ),
                Edge(source="left", target="join"),
                Edge(source="right", target="join"),
                Edge(source="join", target=END),
            ),
        )
        runner = Recorder({"pick": "left"})
        report = WorkflowWalker(declaration, store, "s-cond", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert "join" in runner.calls, "the join must not deadlock"
        assert "right" not in runner.calls, "the untaken branch must not run"

    def test_a_join_runs_once(self, store: StateStore) -> None:
        """Reached from both branches, but it is one node."""
        runner = Recorder()
        WorkflowWalker(self._diamond(), store, "s1", run_step=runner).run()
        assert runner.calls.count("join") == 1

    def test_a_join_waits_for_the_longer_branch(self, store: StateStore) -> None:
        """Breadth-first order is not a topological order.

        With one branch longer than the other, plain BFS reaches the join via
        the short branch and runs it while the long branch is still in flight.
        """
        declaration = WorkflowDeclaration(
            nodes=(
                Step("start"),
                Step("a1"),
                Step("a2"),
                Step("a3"),
                Step("short"),
                Step("join"),
            ),
            edges=(
                Edge(source="start", target="a1"),
                Edge(source="start", target="short"),
                Edge(source="a1", target="a2"),
                Edge(source="a2", target="a3"),
                Edge(source="a3", target="join"),
                Edge(source="short", target="join"),
                Edge(source="join", target=END),
            ),
        )
        runner = Recorder()
        report = WorkflowWalker(declaration, store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert runner.calls.index("join") > runner.calls.index("a3")
        assert runner.calls.index("join") > runner.calls.index("short")

    def test_a_loop_still_terminates(self, store: StateStore) -> None:
        """A cycle makes every node permanently "not ready".

        Deferring forever would hang the walk, so the deferral counter breaks
        the tie: one edge out of order beats spinning.
        """
        declaration = WorkflowDeclaration(
            nodes=(Step("a"), Step("b")),
            edges=(
                Edge(source="a", target="b"),
                Edge(source="b", target="a"),
            ),
        )
        runner = Recorder()
        report = WorkflowWalker(declaration, store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert set(runner.calls) == {"a", "b"}
