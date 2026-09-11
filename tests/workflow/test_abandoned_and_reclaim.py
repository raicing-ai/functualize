"""A dead runner's scope is visible, and taking it back is a verb.

`durable-run-layer`/T8. Spec AC-11, schema §6.

A scope whose runner died keeps `status: "running"` for ever, because nothing
reaps it — and a reader cannot tell that from a run genuinely in progress. The
lease is what distinguishes them: a live runner renews, a dead one stops.

**Ordering is load-bearing.** `abandoned` is derived *before* the plain
`running` branch. Tested the other way round, every dead scope reports as live,
which is the bug this names rather than a cosmetic detail — the same warning the
existing docstring already carries for the `completed`/`stalled` pair.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.lease import DEFAULT_LEASE_SECONDS
from functualize.app._workflow_control import cancel_scope, purge_scopes, reclaim_scope
from functualize.app._workflow_view import derived_state

PAST = datetime.now(UTC) - timedelta(seconds=DEFAULT_LEASE_SECONDS + 60)


@pytest.fixture
def store(tmp_path: Path) -> FreshStore:
    s = FreshStore(tmp_path / "fresh.json")
    s.ensure_scope("wf", "demo")
    s.set_scope_status("wf", "running")
    return s


def _expire_the_lease(store: FreshStore, scope_id: str = "wf") -> None:
    """Claim in the past, so the lease is already over."""
    store.claim_scope(scope_id, owner="dead-runner", seconds=1)
    scope = store.get_scope(scope_id)
    scope["lease"]["expires_at"] = PAST.isoformat()
    # Written back through the raw record: this is simulating a runner that
    # stopped, not an operation the system offers.
    store._scopes._mutate(  # noqa: SLF001
        lambda env: env["scopes"][scope_id].__setitem__("lease", scope["lease"])
    )


class TestAbandonedIsDerived:
    def test_a_running_scope_with_a_lapsed_lease_reads_as_abandoned(
        self, store: FreshStore
    ) -> None:
        _expire_the_lease(store)
        assert derived_state(store.get_scope("wf")) == "abandoned"

    def test_a_running_scope_with_a_live_lease_reads_as_running(
        self, store: FreshStore
    ) -> None:
        store.claim_scope("wf", owner="alive")
        assert derived_state(store.get_scope("wf")) == "running"

    def test_a_running_scope_with_no_lease_reads_as_running(
        self, store: FreshStore
    ) -> None:
        """Absence of evidence is not evidence, and here it is the common case.

        Most scopes have no lease — written by a plain job, or before leases
        existed. Calling those abandoned would make it the answer for most of
        the file.
        """
        assert store.get_lease("wf") is None
        assert derived_state(store.get_scope("wf")) == "running"

    def test_abandoned_is_tested_before_running(self, store: FreshStore) -> None:
        """The ordering, asserted as a property rather than read off the source.

        With the branches the other way round the lapsed-lease case above would
        return `running` and every dead scope would report as live. This states
        it once more in terms a reader can check without tracing the function.
        """
        _expire_the_lease(store)
        scope = store.get_scope("wf")
        assert scope["status"] == "running", "the stored status is still running"
        assert derived_state(scope) == "abandoned", (
            "the derivation returned the stored status — `abandoned` is being "
            "tested after `running`, so a dead runner's scope reads as live"
        )

    def test_a_terminal_status_wins_over_a_lapsed_lease(
        self, store: FreshStore
    ) -> None:
        """A finished scope is finished, whatever its lease says.

        `cancelled`, `failed` and `completed` are tested first and must stay
        first: a scope that completed and whose lease then lapsed is completed,
        not abandoned.
        """
        _expire_the_lease(store)
        store.set_scope_status("wf", "completed")
        assert derived_state(store.get_scope("wf")) == "completed"

    def test_a_blocked_scope_is_not_abandoned(self, store: FreshStore) -> None:
        """Blocked is waiting on a *human*, not on a runner.

        A workflow parked at a gate has no runner to renew a lease, and calling
        it abandoned would report every gate as a failure.
        """
        _expire_the_lease(store)
        store.set_scope_status("wf", "blocked")
        assert derived_state(store.get_scope("wf")) in {"waiting", "ready"}


class TestReclaimIsExplicit:
    def test_reclaiming_an_abandoned_scope_moves_the_generation(
        self, store: FreshStore
    ) -> None:
        _expire_the_lease(store)
        before = store.get_lease("wf")

        result = reclaim_scope(store, "wf")

        assert result["status"] == "reclaimed"
        assert store.get_lease("wf").generation > before.generation

    def test_the_previous_holders_writes_are_then_refused(
        self, store: FreshStore
    ) -> None:
        """What reclaiming is *for*, rather than what it records."""
        from functualize._primitives.lease import StaleGenerationError

        _expire_the_lease(store)
        stale = store.get_lease("wf").generation
        reclaim_scope(store, "wf")

        store.hold_scope_generation("wf", stale)
        with pytest.raises(StaleGenerationError):
            store.set_scope_status("wf", "completed")

    def test_reclaiming_a_live_scope_is_refused(self, store: FreshStore) -> None:
        """A live lease is not an abandoned scope — it is one someone is using.

        Cancel is the verb for taking a scope from a runner that is working;
        letting `reclaim` do it would make the two indistinguishable and remove
        the reason `cancel` announces itself.
        """
        store.claim_scope("wf", owner="busy")
        result = reclaim_scope(store, "wf")
        assert result["error"] == "workflow_held"
        assert "busy" in result["message"]

    def test_reclaiming_an_unknown_scope_is_refused(self, store: FreshStore) -> None:
        assert reclaim_scope(store, "nope")["error"] == "workflow_not_found"

    def test_reclaim_destroys_nothing(self, store: FreshStore) -> None:
        """AC-11's other half. Reclaiming a scope must leave the walk's work.

        Everything a resume needs — step records, the gate payload a human
        deposited, the position — survives. Only the generation moves.
        """
        store.record_step("wf", "n1", {"status": "success"})
        store.put_gate("wf", "approval", {"status": "answered"})
        store.deposit_gate_payload("wf", "approval", {"who": "a-human"})
        store.set_position("wf", "n2")
        _expire_the_lease(store)

        reclaim_scope(store, "wf")

        scope = store.get_scope("wf")
        assert store.get_step("wf", "n1") is not None
        assert store.get_position("wf") == "n2"
        assert scope["gates"]["approval"]["payload"] == {"who": "a-human"}


class TestNothingReclaimsOnItsOwn:
    def test_reading_a_scope_does_not_reclaim_it(self, store: FreshStore) -> None:
        """Derived on read, never repaired on read.

        An expired lease means *nothing has heard from that runner*, not *that
        runner is dead*. A read that quietly took the scope would make a slow
        step on a distant machine lose its work to whoever looked at a list.
        """
        _expire_the_lease(store)
        before = store.get_lease("wf")

        assert derived_state(store.get_scope("wf")) == "abandoned"

        assert store.get_lease("wf") == before, "reading the scope claimed it"

    def test_purge_is_still_the_only_verb_that_deletes(self, store: FreshStore) -> None:
        """An abandoned scope is not purgeable — it is not finished.

        Somebody has to decide what happened to it. Letting purge collect
        abandoned scopes would delete the evidence of the crash that made them.
        """
        _expire_the_lease(store)
        report = purge_scopes(store)
        assert report["removed"] == []
        assert store.get_scope("wf") is not None

    def test_cancelling_an_abandoned_scope_makes_it_purgeable(
        self, store: FreshStore
    ) -> None:
        """The path out: a human says what happened, then it can be collected."""
        _expire_the_lease(store)
        assert cancel_scope(store, "wf")["status"] == "cancelled"
        assert purge_scopes(store)["removed"] == ["wf"]
