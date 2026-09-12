"""Step outcomes are a named vocabulary, and two of them are not failures.

`workflow-graph-semantics`/T4. Spec AC-8, AC-9.

Two claims, and they pull in opposite directions, which is why they are pinned
together.

**AC-8** — `timed_out` and `cancelled` are recorded *distinctly from* `failed`.
Both already happen today and both are written down as `failed`, which is how a
person ends up debugging a job that did nothing wrong: a nested workflow
somebody cancelled, and a step whose scope went claimable while it was still
working.

**AC-9** — replay-skip keys on the **set** of terminal-success outcomes, not on
the literal `"success"`. This one cannot be proved by behaviour alone, and
saying so is better than a test that looks like it does: with exactly one value
in the set, `status in TERMINAL_SUCCESS` and `status == "success"` agree on every
input that exists. The difference only appears the day a *second* success-like
outcome is added — which is precisely the day nobody re-reads the comparison.
So the set membership is pinned **structurally** here
(`TestNoConsumerSpellsTheOutcomeItself`), the way `test_the_port_is_not_leaked`
bounds the substrate exemption, and the behaviour of each outcome is pinned
beside it.

There is no `timed_out` by preemption. `_engine/exec_policy` refused every
mechanism that could deliver one and `tests/engine/test_timeout_is_lease_expiry`
holds it to that; a step's only budget is its lease, so the sole party that can
record a timeout is whoever takes the scope over.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from functualize._engine.frontier import (
    TERMINAL_SUCCESS,
    FrontierWalk,
    GraphModel,
    StepStatus,
    step_key,
)
from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import ScopeCancelledError
from functualize._types.workflow import END, Edge, Step, WorkflowDeclaration

SRC = Path(__file__).resolve().parents[2] / "src" / "functualize"


class _Runner:
    """Runs steps, raising whatever it was told to raise for a name."""

    def __init__(self, **raises: BaseException) -> None:
        self.raises = raises
        self.calls: list[str] = []

    def __call__(self, name: str) -> str:
        self.calls.append(name)
        exc = self.raises.get(name)
        if exc is not None:
            raise exc
        return name

    def count(self, name: str) -> int:
        return self.calls.count(name)


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _line() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("first"), Step("second")),
        edges=(
            Edge(source="first", target="second"),
            Edge(source="second", target=END),
        ),
    )


def _abandon(store: ScopeStore, scope_id: str, *, at: str) -> None:
    """Leave the scope looking like a runner that stopped mid-step.

    Claimed, still `running`, positioned on a node, and the lease expired —
    the two facts `derived_state` already joins to say `abandoned`. Written
    through the raw record because this is simulating a process that died,
    not an operation the system offers.
    """
    store.ensure_scope(scope_id, "demo")
    store.set_scope_status(scope_id, "running")
    store.set_position(scope_id, at)
    store.claim_scope(scope_id, owner="dead-runner", seconds=1)
    scope = store.get_scope(scope_id)
    past = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    lease = {**scope["lease"], "expires_at": past}
    store._mutate(  # noqa: SLF001
        lambda env: env["scopes"][scope_id].__setitem__("lease", lease)
    )


def _status_of(store: ScopeStore, scope_id: str, node: str) -> Any:
    record = store.get_step(scope_id, step_key(node, ""))
    return None if record is None else record.get("status")


# ----------------------------------------------------------------------
# AC-9 — the vocabulary is named, not spelled
# ----------------------------------------------------------------------


class TestTheVocabulary:
    def test_the_four_outcomes_are_named(self) -> None:
        assert {
            StepStatus.SUCCESS,
            StepStatus.FAILED,
            StepStatus.TIMED_OUT,
            StepStatus.CANCELLED,
        } == {"success", "failed", "timed_out", "cancelled"}

    def test_only_success_is_terminal_success(self) -> None:
        assert frozenset({StepStatus.SUCCESS}) == TERMINAL_SUCCESS

    @pytest.mark.parametrize(
        "outcome", [StepStatus.FAILED, StepStatus.TIMED_OUT, StepStatus.CANCELLED]
    )
    def test_no_other_outcome_is_replayable(self, outcome: str) -> None:
        assert outcome not in TERMINAL_SUCCESS


class TestNoConsumerSpellsTheOutcomeItself:
    """Every replay-skip asks the set. None of them compares a string.

    The structural half of AC-9, and the only half that can fail while the set
    has one member. It is an AST walk rather than a grep because a grep for
    `"success"` is satisfied by the docstring above it — the hazard this
    feature's own task list names, and one this branch has already been caught
    by twice.
    """

    CONSUMERS = (
        "_engine/frontier.py",
        "_engine/workflow_walker.py",
        "_engine/dependency_runner.py",
    )

    @staticmethod
    def _status_literal_comparisons(path: Path) -> list[str]:
        """Every `<something>.get("status") == "<literal>"` in a file."""
        found: list[str] = []
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, ast.Eq) for op in node.ops):
                continue
            source = ast.unparse(node)
            if '"status"' not in source and "'status'" not in source:
                continue
            if "['status']" not in source and ".get" not in source:
                continue
            found.append(source)
        return found

    @pytest.mark.parametrize("relative", CONSUMERS)
    def test_the_replay_skip_does_not_compare_a_step_status_literal(
        self, relative: str
    ) -> None:
        offending = [
            source
            for source in self._status_literal_comparisons(SRC / relative)
            if "success" in source
        ]
        assert not offending, (
            f"{relative} compares a step status to a literal: {offending}. "
            f"Replay-skip keys on TERMINAL_SUCCESS so that a future outcome "
            f"cannot silently become replayable (AC-9)."
        )

    def test_the_walk_is_findable(self) -> None:
        """The guard: an AST walk that finds nothing cannot fail.

        `is_blocked` compares a *scope* status to `WalkState.BLOCKED`, which is
        the shape this check looks for and deliberately does not forbid — so
        the comparison it does find proves the parser reached real code.
        """
        found = self._status_literal_comparisons(SRC / "_engine/frontier.py")
        assert found, "the AST walk matched nothing; it cannot fail"


# ----------------------------------------------------------------------
# AC-9 — behaviour, outcome by outcome
# ----------------------------------------------------------------------


class TestOnlySuccessIsSkippedOnReplay:
    @pytest.mark.parametrize(
        "outcome", [StepStatus.FAILED, StepStatus.TIMED_OUT, StepStatus.CANCELLED]
    )
    def test_a_step_that_did_not_succeed_runs_again(
        self, store: ScopeStore, outcome: str
    ) -> None:
        store.ensure_scope("s1", "demo")
        store.record_step(
            "s1", step_key("first", ""), {"status": outcome, "return_value": None}
        )
        runner = _Runner()

        WorkflowWalker(_line(), store, "s1", run_step=runner).run()

        assert runner.count("first") == 1, (
            f"a step recorded {outcome!r} was skipped as though it had "
            f"succeeded: {runner.calls}"
        )

    def test_a_successful_step_is_still_skipped(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "demo")
        store.record_step(
            "s1",
            step_key("first", ""),
            {"status": StepStatus.SUCCESS, "return_value": "done"},
        )
        runner = _Runner()

        WorkflowWalker(_line(), store, "s1", run_step=runner).run()

        assert runner.count("first") == 0, runner.calls


# ----------------------------------------------------------------------
# AC-8 — `timed_out`
# ----------------------------------------------------------------------


class TestAnAbandonedStepTimedOut:
    """A step whose scope went claimable while it held it.

    The only meaning `timed_out` has here: nothing preempts a running step, so
    the fact is recorded by whoever takes the scope over, from the two things
    that are actually observable — the scope still says `running`, and its
    lease has expired.
    """

    def test_taking_over_records_the_in_flight_step(self, store: ScopeStore) -> None:
        _abandon(store, "s1", at="first")

        FrontierWalk(GraphModel(entry="first"), store, "s1").claim()

        assert _status_of(store, "s1", "first") == StepStatus.TIMED_OUT

    def test_taking_over_does_not_stamp_the_scope(self, store: ScopeStore) -> None:
        """The step is noted; the scope is left for the walk to decide.

        Taking over is not a verdict on the workflow — the walk that claims is
        about to carry it forward, and a scope stamped `failed` here would be
        refused by the resume that was on its way.
        """
        _abandon(store, "s1", at="first")
        FrontierWalk(GraphModel(entry="first"), store, "s1").claim()
        assert store.get_scope("s1")["status"] == "running"

    def test_the_step_runs_again_when_the_walk_resumes(self, store: ScopeStore) -> None:
        _abandon(store, "s1", at="first")
        runner = _Runner()

        WorkflowWalker(_line(), store, "s1", run_step=runner).run()

        assert runner.count("first") == 1, (
            f"the timed-out step was never retried: {runner.calls}"
        )
        assert _status_of(store, "s1", "first") == StepStatus.SUCCESS

    def test_a_step_that_reported_keeps_the_reason_it_gave(
        self, store: ScopeStore
    ) -> None:
        """A `failed` record is a step's own account of itself.

        Overwriting it with `timed_out` would replace the reason with the
        observation that it stopped — which is true of every failure.
        """
        _abandon(store, "s1", at="first")
        store.record_step(
            "s1", step_key("first", ""), {"status": StepStatus.FAILED, "x": 1}
        )

        FrontierWalk(GraphModel(entry="first"), store, "s1").claim()

        assert _status_of(store, "s1", "first") == StepStatus.FAILED

    def test_a_fresh_scope_records_nothing(self, store: ScopeStore) -> None:
        walk = FrontierWalk(GraphModel(entry="first"), store, "s1")
        walk.claim()
        assert store.get_scope("s1")["steps"] == {}

    def test_a_clean_release_is_not_a_timeout(self, store: ScopeStore) -> None:
        """The regression that decides the whole rule.

        `lease.release` **expires the lease in place** rather than deleting it,
        so "the lease is expired" is true of every scope that ever finished. A
        check that looked only at the lease would mark the gate node of every
        resumed workflow as timed out. The scope status is what separates them:
        a walk that stopped cleanly stamped `blocked`, `completed` or `failed`
        first, and only a walk that stopped without stamping anything leaves
        `running` behind.
        """
        store.ensure_scope("s1", "demo")
        store.set_position("s1", "first")
        walk = FrontierWalk(GraphModel(entry="first"), store, "s1")
        walk.claim()
        store.set_scope_status("s1", "blocked")
        walk.release()

        FrontierWalk(GraphModel(entry="first"), store, "s1").claim()

        assert _status_of(store, "s1", "first") is None, (
            "resuming a workflow that blocked at a gate recorded its gate "
            "node as timed out"
        )

    def test_a_completed_scope_is_not_a_timeout(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "demo")
        store.set_position("s1", "first")
        walk = FrontierWalk(GraphModel(entry="first"), store, "s1")
        walk.claim()
        store.set_scope_status("s1", "completed")
        walk.release()

        FrontierWalk(GraphModel(entry="first"), store, "s1").claim()

        assert _status_of(store, "s1", "first") is None


# ----------------------------------------------------------------------
# AC-8 — `cancelled`
# ----------------------------------------------------------------------


class TestACancelledChildIsNotAFailedParent:
    """Cancelling a nested workflow must not read as a defect in the parent.

    `ScopeCancelledError` is terminal by design — its own docstring says there
    is no `--force` and no un-cancel. Recorded as `failed`, the parent invites
    exactly the retry that can never work, and sends someone looking for a bug
    in a job that did nothing wrong.
    """

    @staticmethod
    def _walk(store: ScopeStore, runner: _Runner) -> Any:
        return WorkflowWalker(_line(), store, "s1", run_step=runner).run()

    def test_the_step_is_recorded_cancelled(self, store: ScopeStore) -> None:
        runner = _Runner(first=ScopeCancelledError("s1::first", workflow="child"))
        self._walk(store, runner)
        assert _status_of(store, "s1", "first") == StepStatus.CANCELLED

    def test_the_parent_scope_is_cancelled_not_failed(self, store: ScopeStore) -> None:
        runner = _Runner(first=ScopeCancelledError("s1::first", workflow="child"))
        self._walk(store, runner)
        assert store.get_scope("s1")["status"] == "cancelled"

    def test_the_walk_still_stops(self, store: ScopeStore) -> None:
        runner = _Runner(first=ScopeCancelledError("s1::first", workflow="child"))
        report = self._walk(store, runner)
        assert report.outcome is WalkOutcome.FAILED
        assert report.failed_node == "first"
        assert runner.count("second") == 0, runner.calls

    def test_resuming_the_parent_is_refused_as_cancelled(
        self, store: ScopeStore
    ) -> None:
        """The consequence, and the reason the scope status is the fix.

        `WorkflowRunner.prelude` refuses a cancelled scope by reading exactly
        this field. Left as `failed`, the parent looks like a run worth
        retrying — and every retry re-raises the child's cancellation.
        """
        runner = _Runner(first=ScopeCancelledError("s1::first", workflow="child"))
        self._walk(store, runner)

        from functualize._engine.workflow_runner import WorkflowRunner

        again = WorkflowRunner(store, run_step=_Runner(), scope_id="s1")
        with pytest.raises(ScopeCancelledError):
            again.prelude("parent", _line())


class TestAnOrdinaryFailureIsUnchanged:
    """The regression gate. Written to today's behaviour, not to the change."""

    def test_a_raising_step_is_still_failed(self, store: ScopeStore) -> None:
        runner = _Runner(first=RuntimeError("boom"))
        report = WorkflowWalker(_line(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.FAILED
        assert _status_of(store, "s1", "first") == StepStatus.FAILED
        assert store.get_scope("s1")["status"] == "failed"

    def test_a_clean_walk_records_success(self, store: ScopeStore) -> None:
        runner = _Runner()
        report = WorkflowWalker(_line(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED
        assert _status_of(store, "s1", "first") == StepStatus.SUCCESS
        assert _status_of(store, "s1", "second") == StepStatus.SUCCESS
