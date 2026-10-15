"""The walk claims through the port, and the fence survives the move.

FUN-17/T14 (acceptance criterion 6, walk half; design ruling R-14.1/R-14.2).
`FrontierWalk.claim()` no longer calls `ScopeStore.claim_scope` on the walk's
own store: it issues `ClaimWorkflow` through the `RuntimeStore` the engine was
handed, and branches on `Claimed | Conflict`.

That move has one way to go silently wrong, and the first case exists for it.
The port claims through the `ScopeStore` inside its own `DocumentRuntimeStore`,
while the walk writes through a different `ScopeStore` object — and a hold
fences only the object it is set on (`scope_store.py`, `hold`). So the walk has
to carry the generation across by hand. If it did not, every write it made
would go out with `held is None` and the generation fence would simply not run:
no error, no log line, and two runners interleaving one scope again.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from threading import enumerate as live_threads
from typing import Any

import pytest
from tests._support.engine_storage import port_for

from functualize._app.state import AppState
from functualize._engine.frontier import RenewalOutcome
from functualize._engine.workflow_walker import WalkOutcome, WalkReport, WorkflowWalker
from functualize._primitives import lease
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.enums import RunStatus
from functualize._types.workflow import END, Edge, Step, WorkflowDeclaration
from functualize.app.core import FunctualizeApp
from functualize.types import RunRequest
from functualize.workflow import workflow


def _linear() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("a"), Step("b")),
        edges=(Edge(source="a", target="b"), Edge(source="b", target=END)),
    )


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


class TestClaimedKeepsTheFenceOn:
    """The hold the walk installs is what makes a stale walk stop."""

    def test_a_walk_superseded_mid_run_stops_at_its_next_write(
        self, store: ScopeStore
    ) -> None:
        """Another runner force-reclaims while step `a` runs; `b` never runs.

        The reclaim goes through a third `ScopeStore` over the same files — a
        different process, as far as either object can tell. The walk's next
        write is the record of step `a`, and it must be refused: the walk holds
        generation 1 and the file now says 2.

        **Sabotage (T14's own):** delete `self._store.hold(...)` from
        `FrontierWalk.claim()`. The walk then writes with no hold, the fence
        check never runs, `b` executes and the walk completes — this case goes
        red. That is the `self._generation is None` hazard made loud.
        """
        ran: list[str] = []

        def run_step(name: str) -> Any:
            ran.append(name)
            if name == "a":
                ScopeStore(store.substrate).claim_scope(
                    "s1", owner="usurper", force=True
                )
            return name

        report = WorkflowWalker(
            _linear(), "s1", run_step=run_step, runtime_store=port_for(store)
        ).run()

        assert report.outcome is WalkOutcome.SUPERSEDED
        assert ran == ["a"]
        lease = store.get_lease("s1")
        assert lease is not None
        assert (lease.owner, lease.generation) == ("usurper", 2)

    def test_the_claim_lands_through_the_port_at_generation_one(
        self, store: ScopeStore
    ) -> None:
        """The port's lease is the lease the walk's own store reads.

        Both sit on one substrate (`port_for`), so what the port wrote is on
        disk where the walk looks — and the walk, having released on
        completion, leaves the lease expired rather than deleted.
        """
        report = WorkflowWalker(
            _linear(),
            "s1",
            run_step=lambda name: name,
            runtime_store=port_for(store),
        ).run()

        assert report.outcome is WalkOutcome.COMPLETED
        lease = store.get_lease("s1")
        assert lease is not None
        assert lease.generation == 1


class TestConflictNeverStarts:
    """R-14.2: refused at the door is `HELD`, not `SUPERSEDED`."""

    def test_a_live_holder_means_held_and_nothing_runs(self, store: ScopeStore) -> None:
        """The holder is named, no node runs, and the holder's lease is untouched.

        Untouched matters as much as the outcome. `SUPERSEDED` would have run
        the walk's `finally: release()` — a write by a runner that never held
        the scope, expiring someone else's live claim.
        """
        ScopeStore(store.substrate).claim_scope(
            "s1", owner="holder-1", now=datetime.now(UTC)
        )
        before = store.get_lease("s1")
        ran: list[str] = []

        report = WorkflowWalker(
            _linear(),
            "s1",
            run_step=lambda name: ran.append(name),
            runtime_store=port_for(store),
        ).run()

        assert report.outcome is WalkOutcome.HELD
        assert report.error is not None
        assert "holder-1" in report.error
        assert ran == []
        assert store.get_lease("s1") == before

    def test_held_is_its_own_outcome(self) -> None:
        """Callers switch on identity; `HELD` must not collapse into another."""
        assert WalkOutcome.HELD.value == "held"
        assert WalkOutcome.HELD is not WalkOutcome.SUPERSEDED
        assert WalkOutcome.HELD is not WalkOutcome.FAILED

    def test_a_second_walker_cannot_claim_during_a_long_live_step(
        self, store: ScopeStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first claim survives its original expiry while its step is blocked."""
        monkeypatch.setattr(lease, "DEFAULT_LEASE_SECONDS", 0.3)
        entered = Event()
        finish = Event()
        renewed = Event()
        first_steps: list[str] = []
        second_steps: list[str] = []
        first_reports: list[WalkReport] = []
        renewals: list[RenewalOutcome] = []

        def first_step(name: str) -> str:
            first_steps.append(name)
            if name == "a":
                entered.set()
                assert finish.wait(5), "the first step was not released"
            return name

        first = WorkflowWalker(
            _linear(),
            "s1",
            run_step=first_step,
            runtime_store=port_for(store),
            _heartbeat_interval_seconds=0.02,
        )
        real_claim = first._walk.claim
        real_renew = first._walk.renew
        claimed: list[lease.Lease] = []

        def record_claim(**kwargs: Any) -> Any:
            outcome = real_claim(**kwargs)
            held = store.get_lease("s1")
            assert held is not None
            claimed.append(held)
            return outcome

        def observe_renewal() -> RenewalOutcome:
            outcome = real_renew()
            renewals.append(outcome)
            if entered.is_set():
                renewed.set()
            return outcome

        first._walk.claim = record_claim  # type: ignore[method-assign]
        first._walk.renew = observe_renewal  # type: ignore[method-assign]
        runner = Thread(target=lambda: first_reports.append(first.run()))
        try:
            runner.start()
            assert entered.wait(5), "the first walker never reached its step"
            initial = claimed[0]
            assert renewed.wait(2), "the live walk never renewed during its step"
            past_initial_expiry = (
                datetime.fromisoformat(initial.expires_at) - datetime.now(UTC)
            ).total_seconds() + 0.05
            assert not finish.wait(max(0, past_initial_expiry))
            assert datetime.now(UTC) > datetime.fromisoformat(initial.expires_at)

            other_store = ScopeStore(store.substrate)
            second = WorkflowWalker(
                _linear(),
                "s1",
                run_step=lambda name: second_steps.append(name),
                runtime_store=port_for(other_store),
            )
            refused = second.run()
            assert refused.outcome is WalkOutcome.HELD
            assert second_steps == []
            current = store.get_lease("s1")
            assert current is not None
            assert current.generation == initial.generation
        finally:
            finish.set()
            runner.join(5)

        assert not runner.is_alive()
        assert len(first_reports) == 1
        assert first_reports[0].outcome is WalkOutcome.COMPLETED
        assert first_steps == ["a", "b"]
        assert set(renewals) == {RenewalOutcome.RENEWED}
        assert len(renewals) < 100, "the heartbeat spun instead of waiting"
        assert not any(t.name == "lease-heartbeat:s1" for t in live_threads())

    def test_a_slow_claim_does_not_leave_the_first_step_claimable(
        self, store: ScopeStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The walk confirms its claim before its first step, not one interval in.

        The claim's expiry is computed before its durable write, and the claim
        path does bookkeeping after it. Measured on a loaded host, the write
        alone took 0.256 s of a 0.3 s compressed lease, and the first renewal
        then waited a full interval and queued for the lock behind the walk's
        own writes — a second walker claimed the scope while step `a` ran.
        Here the claim is made to outlive its whole lease, and the heartbeat
        interval is longer than the test, so only the walk's start can renew.
        """
        monkeypatch.setattr(lease, "DEFAULT_LEASE_SECONDS", 0.3)
        entered = Event()
        finish = Event()
        first_steps: list[str] = []
        second_steps: list[str] = []
        first_reports: list[WalkReport] = []

        def first_step(name: str) -> str:
            first_steps.append(name)
            if name == "a":
                entered.set()
                assert finish.wait(5), "the first step was not released"
            return name

        first = WorkflowWalker(
            _linear(),
            "s1",
            run_step=first_step,
            runtime_store=port_for(store),
            _heartbeat_interval_seconds=30,
        )
        real_claim = first._walk.claim
        claimed_until: list[datetime] = []

        def slow_claim(**kwargs: Any) -> Any:
            outcome = real_claim(**kwargs)
            held = store.get_lease("s1")
            assert held is not None
            claimed_until.append(datetime.fromisoformat(held.expires_at))
            while datetime.now(UTC) <= claimed_until[0]:
                finish.wait(0.01)
            return outcome

        first._walk.claim = slow_claim  # type: ignore[method-assign]
        runner = Thread(target=lambda: first_reports.append(first.run()))
        try:
            runner.start()
            assert entered.wait(5), "the first walker never reached its step"
            assert datetime.now(UTC) > claimed_until[0]

            other_store = ScopeStore(store.substrate)
            second = WorkflowWalker(
                _linear(),
                "s1",
                run_step=lambda name: second_steps.append(name),
                runtime_store=port_for(other_store),
            )
            assert second.run().outcome is WalkOutcome.HELD
            assert second_steps == []
        finally:
            finish.set()
            runner.join(5)

        assert not runner.is_alive()
        assert first_reports[0].outcome is WalkOutcome.COMPLETED
        assert first_steps == ["a", "b"]
        assert not any(t.name == "lease-heartbeat:s1" for t in live_threads())

    def test_a_scope_taken_before_the_first_step_runs_nothing(
        self, store: ScopeStore
    ) -> None:
        """A claim lost before any work starts runs no step.

        Another runner takes the scope between this walk's claim and its first
        step. The renewal that confirms the claim at walk start reports the
        takeover, and the walk returns before `a` or any other write.
        """
        steps: list[str] = []
        walker = WorkflowWalker(
            _linear(),
            "s1",
            run_step=lambda name: steps.append(name),
            runtime_store=port_for(store),
            _heartbeat_interval_seconds=30,
        )
        real_claim = walker._walk.claim

        def claim_then_lose_it(**kwargs: Any) -> Any:
            outcome = real_claim(**kwargs)
            ScopeStore(store.substrate).claim_scope("s1", owner="other", force=True)
            return outcome

        walker._walk.claim = claim_then_lose_it  # type: ignore[method-assign]

        assert walker.run().outcome is WalkOutcome.SUPERSEDED
        assert steps == []
        assert not any(t.name == "lease-heartbeat:s1" for t in live_threads())


# ----------------------------------------------------------------------
# Reachability: the production call path, not "a test calls it".
# ----------------------------------------------------------------------


@pytest.fixture
def _reset() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


@pytest.mark.usefixtures("_reset")
class TestTheBootedEngineHandsItsStoreToTheWalk:
    """App → engine → orchestrator → runner → walker → `FrontierWalk.claim()`.

    **Sabotage:** break `runtime_store=self._engine._runtime_store` at
    `workflow_orchestrator.py` — pass `None`, or a store over another
    substrate — and this goes red: with `None` the claim has nothing to issue
    through; with a foreign store the lease lands in a document the walk never
    reads, and the walk's first fenced write is refused.
    """

    def test_a_workflow_job_runs_to_completion_through_boot(
        self, project: Path
    ) -> None:
        app = FunctualizeApp(name="testapp")
        ran: list[str] = []

        def build() -> str:
            ran.append("build")
            return "artifact"

        def ship() -> str:
            ran.append("ship")
            return "shipped"

        @workflow(
            steps=[Step("build"), Step("ship")],
            edges=[
                Edge(source="build", target="ship"),
                Edge(source="ship", target=END),
            ],
        )
        def release() -> str:
            return "released"

        app.register_dynamic_job("build", build)
        app.register_dynamic_job("ship", ship)
        app.register_dynamic_job("release", release)

        result = app.execute(
            RunRequest(
                job_name="release", surface="app.execute", workflow_scope_id="rel-1"
            )
        )

        assert result.status is RunStatus.SUCCESS, result
        assert result.return_value == "released"
        assert ran == ["build", "ship"]
        # Read back through the store boot selected: the lease the walk took
        # is visible through the engine's own port.
        view = app.execution_engine._runtime_store.workflows.workflow("rel-1")
        assert view is not None
        assert view.generation == 1
