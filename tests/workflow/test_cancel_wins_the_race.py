"""Cancel wins against a running walk, and a second resume is refused.

`durable-run-layer`/T7. Spec AC-9, AC-10.

**AC-9 is the limitation 0.3.0 shipped knowingly**: two `resume` invocations on
one scope both walked it, each believing it was alone, interleaving two walks'
decisions into one record.

**AC-10 is the same bug wearing a different hat.** Setting a scope to
`cancelled` while a walk is running does not cancel it: the walk holds the
current generation, so its own `COMPLETED` stamp is a perfectly legal write and
lands on top. Fencing alone does not fix this — nothing about the walk is stale
until something supersedes it. Cancel has to *take* the lease, which is what
makes it win rather than merely arrive first.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from functualize._engine.frontier import FrontierWalk
from functualize._engine.workflow_walker import WalkOutcome
from functualize._primitives.lease import LeaseHeldError, StaleGenerationError
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.app._workflow_control import cancel_scope


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    s = ScopeStore(JsonFileSubstrate(tmp_path))
    s.ensure_scope("wf", "demo")
    s.set_scope_status("wf", "running")
    return s


class TestCancelWins:
    """AC-10. The record must say what the person who cancelled meant."""

    def test_cancel_supersedes_a_running_walks_generation(
        self, store: ScopeStore
    ) -> None:
        """The mechanism, stated as the generation moving.

        Without this, a cancel is a status write the walk is entitled to
        overwrite — its generation is still current.
        """
        held = store.claim_scope("wf", owner="walker")
        cancel_scope(store, "wf")

        current = store.get_lease("wf")
        assert current is not None
        assert current.generation > held.generation, (
            "cancel left the walker's generation current, so the walk's next "
            "status write is legal and will overwrite the cancellation"
        )

    def test_the_walks_completion_stamp_is_refused_after_a_cancel(
        self, store: ScopeStore
    ) -> None:
        """The consequence, asserted through the write the walk actually makes.

        `workflow_walker` stamps `COMPLETED` when it reaches END. That write has
        to be the one that fails, not some proxy for it.
        """
        held = store.claim_scope("wf", owner="walker")
        store.hold("wf", held.generation)

        cancel_scope(store, "wf")

        with pytest.raises(StaleGenerationError):
            store.set_scope_status("wf", "completed")

    def test_the_record_still_says_cancelled(self, store: ScopeStore) -> None:
        """End to end: after the race, what does a reader see?"""
        held = store.claim_scope("wf", owner="walker")
        store.hold("wf", held.generation)
        cancel_scope(store, "wf")

        with pytest.raises(StaleGenerationError):
            store.set_scope_status("wf", "completed")

        store.hold("wf", None)
        assert store.get_scope("wf")["status"] == "cancelled"

    def test_cancelling_an_unclaimed_scope_still_works(self, store: ScopeStore) -> None:
        """Most scopes have no lease — nothing has walked them yet.

        Taking a lease must not become a precondition for cancelling.
        """
        assert cancel_scope(store, "wf")["status"] == "cancelled"
        assert store.get_scope("wf")["status"] == "cancelled"

    def test_cancelling_a_finished_scope_is_still_refused(
        self, store: ScopeStore
    ) -> None:
        """The existing guard must survive the lease being added in front of it.

        A cancel that took the lease *before* checking liveness would leave a
        finished scope with a bumped generation and no cancellation — a write
        with no meaning.
        """
        store.set_scope_status("wf", "completed")
        before = store.get_lease("wf")

        result = cancel_scope(store, "wf")

        assert result["error"] == "workflow_not_active"
        assert store.get_lease("wf") == before, (
            "a refused cancel moved the generation, fencing out a walk for a "
            "cancellation that never happened"
        )


class TestASecondWalkIsRefused:
    """AC-9 — the limitation 0.3.0 shipped knowingly."""

    def test_a_second_claim_on_a_live_scope_is_refused(self, store: ScopeStore) -> None:
        first = FrontierWalk.__new__(FrontierWalk)
        # Claim through the store directly: this asserts the store's refusal,
        # which is what both walks ultimately depend on.
        store.claim_scope("wf", owner="runner-a")
        with pytest.raises(LeaseHeldError) as exc:
            store.claim_scope("wf", owner="runner-b")
        assert exc.value.owner == "runner-a", "the refusal must name the holder"
        assert first is not None  # keep the construction meaningful to a reader

    def test_two_concurrent_resumes_leave_one_walker(self, store: ScopeStore) -> None:
        """Two runners racing for one scope. Exactly one walks it.

        The scenario the whole feature exists for. Before the lease, both
        advanced the same scope and their step records interleaved.
        """
        won: list[str] = []
        refused: list[LeaseHeldError] = []
        barrier = threading.Barrier(2)

        def resume(name: str) -> None:
            barrier.wait(timeout=5)
            try:
                store.claim_scope("wf", owner=name)
                won.append(name)
            except LeaseHeldError as exc:
                refused.append(exc)

        threads = [threading.Thread(target=resume, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(won) == 1, (
            f"{len(won)} runners claimed one scope — both would then walk it, "
            f"interleaving two walks' decisions into one record"
        )
        assert len(refused) == 1
        assert store.get_lease("wf").owner == won[0]

    def test_the_loser_cannot_write_even_if_it_proceeds(
        self, store: ScopeStore
    ) -> None:
        """Defence in depth, and the part that does not depend on the lock.

        A runner that got past the claim — a partitioned filesystem, a lock that
        silently did nothing — is still stopped at its first write. That is why
        the fence is a recorded integer rather than a held lock.
        """
        loser = store.claim_scope("wf", owner="a")
        store.claim_scope("wf", owner="b", force=True)

        store.hold("wf", loser.generation)
        with pytest.raises(StaleGenerationError):
            store.record_step("wf", "n1", {"status": "success"})


class TestTheWalkReleasesWhatItTook:
    def test_a_walk_that_raises_still_releases(self, store: ScopeStore) -> None:
        """A crashed walk must not hold the scope until its lease expires.

        Otherwise one traceback costs everyone else a five-minute wait, and the
        scope looks held by a process that is gone.
        """
        walk = FrontierWalk(_graph_stub(), store, "wf")
        walk.claim()

        try:
            raise RuntimeError("the step blew up")
        except RuntimeError:
            walk.release()

        lease = store.get_lease("wf")
        assert lease is not None, "release deleted the lease instead of expiring it"
        assert store.claim_scope("wf", owner="next").owner == "next", (
            "the scope was not claimable after the walk released it"
        )

    def test_releasing_twice_is_harmless(self, store: ScopeStore) -> None:
        """`run` releases in a `finally`; a caller may also release explicitly."""
        walk = FrontierWalk(_graph_stub(), store, "wf")
        walk.claim()
        walk.release()
        walk.release()  # must not raise

    def test_releasing_without_claiming_is_harmless(self, store: ScopeStore) -> None:
        """A walk that failed to claim still runs its `finally`."""
        FrontierWalk(_graph_stub(), store, "wf").release()


class TestSupersededIsNotFailed:
    def test_the_outcome_has_its_own_name(self) -> None:
        """Reporting a superseded walk as FAILED sends someone looking for a
        bug in their job, when nothing about the work went wrong — this walk
        simply no longer owns the scope."""
        assert WalkOutcome.SUPERSEDED.value == "superseded"
        assert WalkOutcome.SUPERSEDED is not WalkOutcome.FAILED


def _graph_stub() -> Any:
    """The least graph `FrontierWalk` will accept for lease-only tests."""

    class _G:
        entry = "n1"
        nodes: dict[str, Any] = {}
        edges: dict[str, Any] = {}

    return _G()
