"""Tests for workflow-as-job: the graph is a prelude, the body is the job (§A.7).

The point of this design is that a workflow is an *ordinary job* to everything
downstream — which is what buys chaining and nesting with no composition
feature. So these tests mostly check that nothing about a workflow job is
special: it returns a value, it can be a step of another workflow, and running
it twice does what running any job twice does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from functualize._engine.workflow_runner import WorkflowRunner, new_scope_id
from functualize._engine.workflow_walker import WalkOutcome
from functualize._primitives.state_store import StateStore
from functualize._types.enums import RunStatus
from functualize._types.workflow import (
    END,
    Edge,
    Gate,
    Step,
    WorkflowDeclaration,
)

if TYPE_CHECKING:
    from pathlib import Path


class TripPreferences(BaseModel):
    budget: str = "mid"


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "state.json")


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


def _linear() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("a"), Step("b")),
        edges=(Edge(source="a", target="b"), Edge(source="b", target=END)),
    )


def _noop(name: str) -> Any:
    return f"{name}-result"


class TestBlockedStatus:
    """RunStatus.BLOCKED — a pause is not a failure."""

    def test_blocked_is_resumable_and_failure_is_not(self) -> None:
        assert RunStatus.BLOCKED.resumable
        assert not RunStatus.FAILURE.resumable
        assert not RunStatus.SUCCESS.resumable

    def test_blocked_is_distinct_from_every_other_status(self) -> None:
        """Callers switch on identity; a duplicate value would collapse them."""
        values = [status.value for status in RunStatus]
        assert len(values) == len(set(values))


class TestPrelude:
    def test_a_completed_walk_lets_the_body_run(self, store: StateStore) -> None:
        runner = WorkflowRunner(store, run_step=_noop)
        run = runner.prelude("wf", _linear())

        assert run.outcome is WalkOutcome.COMPLETED
        assert run.should_run_body
        assert not run.body_done

    def test_a_blocked_walk_does_not_let_the_body_run(self, store: StateStore) -> None:
        """The body runs only on END — a gate-blocked walk never reaches it."""
        run = WorkflowRunner(store, run_step=_noop).prelude("wf", _gated())

        assert run.outcome is WalkOutcome.BLOCKED
        assert run.blocked_on == "preferences"
        assert not run.should_run_body

    def test_a_failed_walk_does_not_let_the_body_run(self, store: StateStore) -> None:
        def boom(name: str) -> Any:
            raise RuntimeError("no network")

        run = WorkflowRunner(store, run_step=boom).prelude("wf", _linear())

        assert run.outcome is WalkOutcome.FAILED
        assert not run.should_run_body
        assert "no network" in run.error


class TestScopeLifecycle:
    def test_each_invocation_gets_a_fresh_scope(self, store: StateStore) -> None:
        first = WorkflowRunner(store, run_step=_noop)
        second = WorkflowRunner(store, run_step=_noop)
        assert first.scope_id != second.scope_id

    def test_passing_a_scope_id_resumes_that_scope(self, store: StateStore) -> None:
        """This is the whole resume mechanism: same scope id, replayed walk."""
        first = WorkflowRunner(store, run_step=_noop)
        first.prelude("wf", _gated())
        store.deposit_gate_payload(first.scope_id, "preferences", {"budget": "hi"})

        resumed = WorkflowRunner(store, run_step=_noop, scope_id=first.scope_id)
        run = resumed.prelude("wf", _gated())

        assert run.scope_id == first.scope_id
        assert run.should_run_body

    def test_scope_ids_are_unique(self) -> None:
        assert len({new_scope_id() for _ in range(500)}) == 500


class TestBodyOncePerScope:
    """§A.7: the body runs once per scope, however often the scope replays."""

    def test_a_recorded_body_is_not_run_again(self, store: StateStore) -> None:
        runner = WorkflowRunner(store, run_step=_noop)
        runner.prelude("wf", _linear())
        runner.record_body("the answer")

        replay = WorkflowRunner(store, run_step=_noop, scope_id=runner.scope_id)
        run = replay.prelude("wf", _linear())

        assert run.body_done
        assert not run.should_run_body

    def test_the_replay_answers_with_the_recorded_value(
        self, store: StateStore
    ) -> None:
        """Not merely "don't re-run" — the same value comes back.

        A replay that skipped the body and returned None would be a silent
        wrong answer for anything consuming the workflow's result.
        """
        runner = WorkflowRunner(store, run_step=_noop)
        runner.prelude("wf", _linear())
        runner.record_body({"deployed": True})

        replay = WorkflowRunner(store, run_step=_noop, scope_id=runner.scope_id)
        assert replay.prelude("wf", _linear()).body_value == {"deployed": True}

    def test_a_fresh_scope_runs_the_body_again(self, store: StateStore) -> None:
        """Once-per-*scope*, not once ever."""
        first = WorkflowRunner(store, run_step=_noop)
        first.prelude("wf", _linear())
        first.record_body("x")

        second = WorkflowRunner(store, run_step=_noop)
        assert second.prelude("wf", _linear()).should_run_body

    def test_a_failed_body_is_recorded_as_failed(self, store: StateStore) -> None:
        runner = WorkflowRunner(store, run_step=_noop)
        runner.prelude("wf", _linear())
        runner.record_body(None, status="failed")

        record = store.get_epilogue(runner.scope_id)
        assert record is not None
        assert record["status"] == "failed"
        assert record["completed_at"]
