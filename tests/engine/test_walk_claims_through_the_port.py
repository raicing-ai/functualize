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
from typing import Any

import pytest
from tests._support.engine_storage import port_for

from functualize._app.state import AppState
from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
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
            _linear(), store, "s1", run_step=run_step, runtime_store=port_for(store)
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
            store,
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
            store,
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
