"""The fencing token, and the thing it must not depend on.

`durable-run-layer`/T5. Spec AC-7, risk R-a.

0.3.0 shipped a known limitation: two `resume` invocations both walk one scope,
each believing it is alone. A lease with an owner and an expiry does not fix it,
because each runner's evidence about the expiry is its own clock — and two
clocks disagree. A **monotonically increasing generation** does, without
trusting any clock.

**The class of test that would miss the bug** is one that runs with locking
working: an owner-plus-expiry design and a fencing design behave identically
there, so such a test cannot tell them apart. `TestFencingHoldsWithoutLocking`
is the one that can, and it is why this file exists rather than a few cases
appended to the scope-store tests.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from functualize._primitives.lease import (
    DEFAULT_LEASE_SECONDS,
    Lease,
    LeaseHeldError,
    StaleGenerationError,
    claim,
    is_expired,
    read_lease,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)
LATER = NOW + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    s = ScopeStore(JsonFileSubstrate(tmp_path))
    s.ensure_scope("wf")
    return s


class TestClaiming:
    def test_a_fresh_scope_claims_at_generation_one(self, store: ScopeStore) -> None:
        lease = store.claim_scope("wf", owner="a", now=NOW)
        assert lease.generation == 1
        assert lease.owner == "a"

    def test_a_live_holder_refuses_a_second_claim(self, store: ScopeStore) -> None:
        store.claim_scope("wf", owner="a", now=NOW)
        with pytest.raises(LeaseHeldError) as exc:
            store.claim_scope("wf", owner="b", now=NOW)
        assert exc.value.owner == "a", "the refusal must name who holds it"

    def test_the_same_owner_is_also_refused(self, store: ScopeStore) -> None:
        """A second walk in one process is the bug, not a renewal.

        `renew` is the verb for extending a claim you hold; letting `claim`
        double as it would make the concurrent-resume case look legal whenever
        both runners happened to share an identity.
        """
        store.claim_scope("wf", owner="a", now=NOW)
        with pytest.raises(LeaseHeldError):
            store.claim_scope("wf", owner="a", now=NOW)

    def test_an_expired_lease_is_claimable(self, store: ScopeStore) -> None:
        store.claim_scope("wf", owner="a", now=NOW)
        lease = store.claim_scope("wf", owner="b", now=LATER)
        assert lease.owner == "b"

    def test_reclaiming_still_increments_the_generation(
        self, store: ScopeStore
    ) -> None:
        """The property that makes it a fencing token rather than a label.

        If a reclaim reused the generation, the previous holder's in-flight
        writes would be accepted — which is precisely the case the lease exists
        to refuse.
        """
        first = store.claim_scope("wf", owner="a", now=NOW)
        second = store.claim_scope("wf", owner="b", now=LATER)
        assert second.generation == first.generation + 1

    def test_force_takes_it_from_a_live_holder(self, store: ScopeStore) -> None:
        """For an explicit reclaim, where a human decided the holder is gone."""
        store.claim_scope("wf", owner="a", now=NOW)
        lease = store.claim_scope("wf", owner="b", now=NOW, force=True)
        assert lease.owner == "b"
        assert lease.generation == 2


class TestFencing:
    def test_a_stale_generation_is_refused(self, store: ScopeStore) -> None:
        old = store.claim_scope("wf", owner="a", now=NOW)
        store.claim_scope("wf", owner="b", now=LATER)

        with pytest.raises(StaleGenerationError) as exc:
            store.check_scope_generation("wf", old.generation)
        assert exc.value.held == 2
        assert exc.value.offered == 1
        assert exc.value.owner == "b", "the refusal must name the current holder"

    def test_the_current_generation_passes(self, store: ScopeStore) -> None:
        lease = store.claim_scope("wf", owner="a", now=NOW)
        store.check_scope_generation("wf", lease.generation)  # must not raise

    def test_an_unclaimed_scope_refuses_any_generation(self, store: ScopeStore) -> None:
        """A write fenced under generation 3 against a scope with no lease
        means the lease was released or the record reset — either way this
        writer's view predates that."""
        with pytest.raises(StaleGenerationError):
            store.check_scope_generation("wf", 3)

    def test_a_renewal_does_not_move_the_generation(self, store: ScopeStore) -> None:
        """Moving it would fence the renewer's own in-flight writes — every
        heartbeat would invalidate the work it exists to protect."""
        lease = store.claim_scope("wf", owner="a", now=NOW)
        renewed = store.renew_scope(
            "wf", owner="a", generation=lease.generation, now=NOW
        )
        assert renewed.generation == lease.generation
        assert renewed.expires_at >= lease.expires_at

    def test_renewing_after_someone_else_claimed_is_refused(
        self, store: ScopeStore
    ) -> None:
        """Fires even though the first holder's own clock says it still holds.

        This is the case an owner-plus-expiry design gets wrong: A's evidence is
        its clock, and its clock says the lease is live.
        """
        old = store.claim_scope("wf", owner="a", now=NOW)
        store.claim_scope("wf", owner="b", now=LATER)

        with pytest.raises(StaleGenerationError):
            store.renew_scope("wf", owner="a", generation=old.generation, now=NOW)

    def test_releasing_someone_elses_lease_is_refused(self, store: ScopeStore) -> None:
        """Clearing theirs would hand the scope to a third runner mid-walk."""
        old = store.claim_scope("wf", owner="a", now=NOW)
        store.claim_scope("wf", owner="b", now=LATER)

        with pytest.raises(StaleGenerationError):
            store.release_scope("wf", generation=old.generation)
        assert store.get_lease("wf") is not None, "b's lease was cleared"

    def test_release_makes_it_claimable_again(self, store: ScopeStore) -> None:
        lease = store.claim_scope("wf", owner="a", now=NOW)
        store.release_scope("wf", generation=lease.generation, now=NOW)
        assert store.claim_scope("wf", owner="b", now=NOW).owner == "b"

    def test_release_expires_the_lease_rather_than_deleting_it(
        self, store: ScopeStore
    ) -> None:
        """Deleting looks tidier and hands out the fence it exists to raise.

        With the record gone the generation resets to 0, so the next claim is
        generation 1 again — and the releasing runner's own in-flight writes,
        carrying generation 1, would be accepted by a *different* holder. Found
        by this test failing on the first implementation, which deleted.
        """
        lease = store.claim_scope("wf", owner="a", now=NOW)
        store.release_scope("wf", generation=lease.generation, now=NOW)

        released = store.get_lease("wf")
        assert released is not None, "the lease was deleted, not expired"
        assert released.generation == lease.generation
        assert is_expired(released, NOW), "a released lease must be claimable"

        assert store.claim_scope("wf", owner="b", now=NOW).generation == 2, (
            "the generation reset on release — a's in-flight writes would now "
            "be accepted under b's claim"
        )

    def test_a_released_holders_writes_are_still_fenced(
        self, store: ScopeStore
    ) -> None:
        """The consequence, asserted rather than inferred from the number."""
        first = store.claim_scope("wf", owner="a", now=NOW)
        store.release_scope("wf", generation=first.generation, now=NOW)
        store.claim_scope("wf", owner="b", now=NOW)

        with pytest.raises(StaleGenerationError):
            store.check_scope_generation("wf", first.generation)


@contextmanager
def _no_locking() -> Iterator[None]:
    """Replace the file lock with a no-op, for the length of the block.

    Not a hypothetical. `file_lock` proceeds **unlocked** after its 10-second
    timeout, and is a no-op on a platform with neither `fcntl` nor `msvcrt`. A
    design that leaned on it would be correct only where locking happens to
    work — and silently wrong on a network filesystem, which is exactly where
    two runners are most likely to meet.

    Patched on the **substrate** since `store-substrate`/T2, which is a
    stronger statement than before: locking used to be three per-format
    functions, so disabling one left the others real. There is now one
    `lock`, and this disables all of it.
    """
    real = JsonFileSubstrate.lock

    @contextmanager
    def _nothing(self: Any, *keys: str) -> Iterator[None]:
        yield

    JsonFileSubstrate.lock = _nothing  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        JsonFileSubstrate.lock = real  # type: ignore[assignment,method-assign]


class TestFencingHoldsWithoutLocking:
    """Risk R-a. **The lock is not the mechanism.**

    Everything here runs with locking disabled entirely. A test that ran with
    locking working could not distinguish a fencing design from an
    owner-plus-expiry one, because both behave identically when writes are
    serialised.
    """

    def test_a_stale_write_is_still_refused(self, store: ScopeStore) -> None:
        with _no_locking():
            old = store.claim_scope("wf", owner="a", now=NOW)
            store.claim_scope("wf", owner="b", now=LATER)

            with pytest.raises(StaleGenerationError):
                store.check_scope_generation("wf", old.generation)

    def test_a_stale_renewal_is_still_refused(self, store: ScopeStore) -> None:
        with _no_locking():
            old = store.claim_scope("wf", owner="a", now=NOW)
            store.claim_scope("wf", owner="b", now=LATER)

            with pytest.raises(StaleGenerationError):
                store.renew_scope("wf", owner="a", generation=old.generation, now=NOW)

    def test_the_generation_still_increments(self, store: ScopeStore) -> None:
        with _no_locking():
            first = store.claim_scope("wf", owner="a", now=NOW)
            second = store.claim_scope("wf", owner="b", now=LATER)
        assert second.generation == first.generation + 1

    def test_the_no_op_lock_is_really_in_effect(self, store: ScopeStore) -> None:
        """Guards the three tests above against proving nothing.

        If the patch missed, they would run with real locking and pass for the
        wrong reason — a green suite asserting the opposite of what it claims.
        """
        entered: list[str] = []
        patched = None
        with _no_locking():
            patched = JsonFileSubstrate.lock
            # A key nothing has touched, so any sidecar found must have been
            # made by this acquisition — the fixture's own `ensure_scope` ran
            # before the patch and left one beside `scopes`.
            with store.substrate.lock("never-locked"):
                entered.append("no-op")
            assert (
                not store.substrate.path_for("never-locked")
                .with_suffix(".json.lock")
                .exists()
            ), "a real lock was taken while locking was disabled"
        assert entered == ["no-op"]
        assert JsonFileSubstrate.lock is not patched, "the lock was not restored"


class TestExpiry:
    def test_an_absent_lease_is_expired(self) -> None:
        assert is_expired(None, NOW)

    def test_an_unparseable_expiry_is_expired(self) -> None:
        """A claim nobody can evaluate must not become permanent.

        The alternative is a scope nobody can ever take, which needs a human
        with a text editor — worse than one taken twice, which the fencing
        check refuses at the next write.
        """
        assert is_expired(Lease("a", 1, "not-a-date"), NOW)

    def test_a_naive_timestamp_is_read_as_utc(self) -> None:
        """Rather than raising. Every writer here stamps UTC; a naive value can
        only come from an edited file, and guessing local time would make the
        answer depend on the reader's machine."""
        naive = (NOW + timedelta(seconds=60)).replace(tzinfo=None).isoformat()
        assert not is_expired(Lease("a", 1, naive), NOW)

    def test_expiry_is_inclusive(self) -> None:
        """At exactly the expiry instant the lease is over, not still live."""
        assert is_expired(Lease("a", 1, NOW.isoformat()), NOW)


class TestMalformedRecords:
    @pytest.mark.parametrize(
        "raw",
        [
            {"lease": "not a dict"},
            {"lease": {"owner": "a"}},
            {"lease": {"owner": "a", "generation": "seven", "expires_at": "x"}},
            {"lease": {"generation": 1, "expires_at": "x"}},
            {},
        ],
    )
    def test_a_broken_lease_reads_as_absent(self, raw: dict[str, Any]) -> None:
        """Which makes the scope claimable, deliberately.

        A scope nobody can take needs a human with a text editor; a scope taken
        twice is refused at the next write. Given a damaged record, the second
        failure is the recoverable one.
        """
        assert read_lease(raw) is None

    def test_a_claim_over_a_broken_lease_starts_at_one(self) -> None:
        assert (
            claim("wf", read_lease({"lease": "junk"}), owner="a", now=NOW).generation
            == 1
        )


class TestTwoRunnersRacing:
    def test_exactly_one_of_two_racing_claims_wins(self, store: ScopeStore) -> None:
        """The scenario the whole feature exists for, at the store level.

        Both threads find an expired lease and race. The read-modify-write
        happens inside the lock, so the loser sees the winner's **live** lease
        and is refused — which is a stronger outcome than two generations being
        handed out, and is what closes 0.3.0's concurrent-`resume` limitation.

        Asserted as "exactly one", not "both succeed": an earlier version of
        this test expected two claims and was wrong about the guarantee.
        """
        store.claim_scope("wf", owner="stale", now=NOW)
        won: list[Lease] = []
        refused: list[LeaseHeldError] = []
        barrier = threading.Barrier(2)

        def take(name: str) -> None:
            barrier.wait(timeout=5)
            try:
                won.append(store.claim_scope("wf", owner=name, now=LATER))
            except LeaseHeldError as exc:
                refused.append(exc)

        threads = [threading.Thread(target=take, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(won) == 1, (
            f"{len(won)} runners claimed one scope — both would then walk it, "
            f"which is the bug the lease exists to close"
        )
        assert len(refused) == 1

        current = store.get_lease("wf")
        assert current is not None
        assert current.owner == won[0].owner
        assert current.generation == 2, "the reclaim must increment past `stale`"
