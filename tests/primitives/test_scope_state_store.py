"""A run's state lives in its own file, and costs what the run stored.

`scope-record-lifecycle`/T3, AC-1. `capability-duality` made state durable by
putting it in the scope record — right about durability, wrong about cost. The
state then lived in a **project-wide** file, so writing one key parsed and
rewrote every record the project had ever made: measured at **116×** slower
than an empty store on 2,001 records, and 58 ms per write on a real project.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize._primitives.lease import StaleGenerationError
from functualize._primitives.scope_format import SCOPES_KEY, SCOPES_LIMIT
from functualize._primitives.scope_state_store import (
    ScopeStateStore,
    ScopeStateUnreadableError,
    scope_state_key,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from functualize._types.protocols import Revision


class _OneConflictSubstrate(JsonFileSubstrate):
    """Inject one interleaved write so the store must retry its CAS."""

    conflict = False

    def write(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        expect: Revision | None = None,
    ) -> bool:
        if self.conflict and expect is not None:
            self.conflict = False
            assert super().write(key, {"state": {"concurrent": True}}, expect=expect)
        return super().write(key, payload, expect=expect)


class TestStateRoundTrips:
    def test_set_then_get(self, tmp_path: Path) -> None:
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "k", {"nested": [1, 2]})
        assert store.get_state("s1", "k") == {"nested": [1, 2]}

    def test_a_missing_key_returns_the_default(self, tmp_path: Path) -> None:
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "other", 1)
        assert store.get_state("s1", "k", "fallback") == "fallback"

    def test_a_missing_scope_returns_the_default(self, tmp_path: Path) -> None:
        """No file is "no state" — the absence of a run, not a lost one."""
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        assert store.get_state("never-ran", "k", "fallback") == "fallback"

    def test_delete_reports_whether_the_key_was_there(self, tmp_path: Path) -> None:
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "k", 1)
        assert store.delete_state("s1", "k") is True
        assert store.delete_state("s1", "k") is False

    def test_a_stored_none_is_not_a_missing_key(self, tmp_path: Path) -> None:
        """`None` is a value. Distinguished by `delete`'s sentinel."""
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "k", None)
        assert store.get_state("s1", "k", "fallback") is None
        assert store.delete_state("s1", "k") is True

    def test_snapshot_and_clear(self, tmp_path: Path) -> None:
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "a", 1)
        store.set_state("s1", "b", 2)
        assert store.state_snapshot("s1") == {"a": 1, "b": 2}
        store.clear_state("s1")
        assert store.state_snapshot("s1") == {}

    def test_it_survives_a_new_store_object(self, tmp_path: Path) -> None:
        """Durability is the thing this must not lose while fixing the cost."""
        ScopeStore(JsonFileSubstrate(tmp_path)).set_state("s1", "k", "durable")
        assert ScopeStore(JsonFileSubstrate(tmp_path)).get_state("s1", "k") == "durable"


class TestScopesAreIsolated:
    def test_two_scopes_do_not_see_each_other(self, tmp_path: Path) -> None:
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("a", "k", "from-a")
        store.set_state("b", "k", "from-b")
        assert store.get_state("a", "k") == "from-a"
        assert store.get_state("b", "k") == "from-b"

    def test_each_scope_gets_its_own_file(self, tmp_path: Path) -> None:
        """The mechanism, asserted so the isolation above is not a coincidence.

        Separate files are also separate locks, which is the second win: two
        unrelated runs used to serialize on one `fcntl.flock` sidecar.
        """
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        store.set_state("a", "k", 1)
        store.set_state("b", "k", 2)

        assert scopes.path_for(scope_state_key("a")).exists()
        assert scopes.path_for(scope_state_key("b")).exists()
        assert scopes.path_for(scope_state_key("a")) != scopes.path_for(
            scope_state_key("b")
        )

    def test_state_is_not_in_the_scope_record(self, tmp_path: Path) -> None:
        """The move itself. Reading the record must not find job state."""
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        store.set_state("a", "secret", "value")

        stored = scopes.read(SCOPES_KEY)
        assert stored is not None
        record = stored.data["scopes"]["a"]
        assert "value" not in json.dumps(record), (
            "job state is still being written into the scope record — the "
            "whole-file read-modify-write is back"
        )


class TestTheCostDoesNotGrowWithTheProject:
    """AC-1, stated as a measurement rather than a feeling."""

    @staticmethod
    def _store_with(n: int) -> ScopeStore:
        store = ScopeStore(JsonFileSubstrate(Path(tempfile.mkdtemp())))
        if n:
            with store.batch():
                for i in range(n):
                    store.ensure_scope(f"noise-{i:05d}")
                    store.set_scope_status(f"noise-{i:05d}", "completed")
        return store

    @pytest.mark.slow
    def test_steady_state_writes_are_at_parity(self) -> None:
        """A `set` on a full store costs what a `set` on an empty one costs.

        "Steady state" means after the scope's record exists. The *first*
        state access for a scope also ensures that record — one whole-envelope
        write, bounded by `SCOPES_LIMIT` — because `purge_scopes` walks records
        and state with no record could never be collected. That cost is once
        per scope per process, not once per operation, which is the thing AC-1
        is actually about.
        """
        big, small = self._store_with(2000), self._store_with(0)
        for store in (big, small):
            store.set_state("mine", "warm", 0)  # pay the record ensure

        def timed(store: ScopeStore, key: str) -> float:
            start = time.perf_counter()
            store.set_state("mine", key, 1)
            return time.perf_counter() - start

        # Best of several: this is a filesystem measurement on a shared
        # machine, and a single sample picks up unrelated I/O.
        big_t = min(timed(big, f"k{i}") for i in range(7))
        small_t = min(timed(small, f"k{i}") for i in range(7))

        assert big_t < small_t * 2, (
            f"a write against a project with 2,000 past runs took "
            f"{big_t * 1000:.2f}ms versus {small_t * 1000:.2f}ms on an empty "
            f"one ({big_t / small_t:.1f}x) — the cost is growing with project "
            f"history again"
        )

    @pytest.mark.slow
    def test_reads_are_at_parity(self) -> None:
        big, small = self._store_with(2000), self._store_with(0)
        for store in (big, small):
            store.set_state("mine", "k", 1)

        def timed(store: ScopeStore) -> float:
            start = time.perf_counter()
            store.get_state("mine", "k")
            return time.perf_counter() - start

        big_t = min(timed(big) for _ in range(7))
        small_t = min(timed(small) for _ in range(7))

        assert big_t < small_t * 2, (
            f"a read took {big_t * 1000:.2f}ms versus {small_t * 1000:.2f}ms "
            f"({big_t / small_t:.1f}x)"
        )

    def test_the_noise_store_really_is_full(self) -> None:
        """Guards the two measurements above against measuring nothing.

        If the cap evicted the noise, both stores would be empty and the
        comparison would pass while proving nothing.
        """
        store = self._store_with(2000)
        assert len(store.scope_ids()) == SCOPES_LIMIT
        assert store.substrate.path_for(SCOPES_KEY).stat().st_size > 50_000


class TestStateImpliesARecord:
    """State with no record is state nothing can ever purge."""

    def test_writing_state_creates_the_scope_record(self, tmp_path: Path) -> None:
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        store.set_state("s1", "k", 1)

        assert store.get_scope("s1") is not None, (
            "a state file with no scope record is an orphan — purge_scopes "
            "walks records, so nothing would ever collect it"
        )

    def test_reading_state_does_not_create_a_record(self, tmp_path: Path) -> None:
        """A read of a scope that never ran must not mint anything."""
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        assert store.get_state("never-ran", "k") is None
        assert store.get_scope("never-ran") is None


class TestBatching:
    def test_a_batch_writes_once(self, tmp_path: Path) -> None:
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        with store.state_batch("s1"):
            store.set_state("s1", "a", 1)
            store.set_state("s1", "b", 2)
        assert store.state_snapshot("s1") == {"a": 1, "b": 2}

    def test_an_exception_discards_the_block(self, tmp_path: Path) -> None:
        """All-or-nothing, as `ScopeStore.batch` is."""
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "kept", "yes")
        with pytest.raises(RuntimeError), store.state_batch("s1"):
            store.set_state("s1", "discarded", "no")
            raise RuntimeError("boom")
        assert store.state_snapshot("s1") == {"kept": "yes"}

    def test_a_batch_replays_after_a_compare_and_swap_conflict(
        self, tmp_path: Path
    ) -> None:
        substrate = _OneConflictSubstrate(tmp_path)
        state = ScopeStateStore(substrate, "s1")
        state.set("seed", True)
        substrate.conflict = True

        with state.batch():
            state.set("mine", True)

        assert state.snapshot() == {"concurrent": True, "mine": True}

    def test_an_open_batch_is_invisible_to_another_thread(self, tmp_path: Path) -> None:
        """`_batch` is thread-local, and this is why it has to be.

        A parallel walk runs items on worker threads. If the open payload were
        shared, a second thread's write would land in a dict the first thread
        is about to overwrite wholesale — the lost-write shape that
        `ScopeStore.batch` already had once.

        Asserted by observation rather than by timing: the other thread is
        asked whether it can see a batch, not raced against one. A timing test
        here deadlocks by construction, because a second writer to the *same*
        scope correctly blocks on the file lock the batch is holding.
        """
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        inner = store._state_store("s1")
        seen: dict[str, object] = {}

        def look() -> None:
            seen["batch"] = inner._batch

        with store.state_batch("s1"):
            store.set_state("s1", "from_batch", "a")
            assert inner._batch is not None, "this thread should see its batch"
            t = threading.Thread(target=look)
            t.start()
            t.join(timeout=5)

        assert seen["batch"] is None, (
            "another thread saw this thread's open batch payload — a write "
            "from there would be discarded when the batch writes"
        )
        assert store.state_snapshot("s1") == {"from_batch": "a"}

    def test_two_scopes_do_not_block_each_other(self, tmp_path: Path) -> None:
        """The contention win, asserted as a wall-clock fact.

        One shared file meant one lock: two unrelated runs serialized on every
        `set`. With a file per scope, a batch held open on one scope must not
        delay a write to another.
        """
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("a", "seed", 0)
        store.set_state("b", "seed", 0)
        done = threading.Event()

        def write_other() -> None:
            store.set_state("b", "k", "written")
            done.set()

        with store.state_batch("a"):
            store.set_state("a", "k", 1)
            t = threading.Thread(target=write_other)
            t.start()
            assert done.wait(timeout=5), (
                "a write to scope 'b' blocked while scope 'a' held its batch "
                "— the two scopes are sharing a lock"
            )
            t.join(timeout=5)

        assert store.get_state("b", "k") == "written"


class TestCompareAndSwap:
    def test_a_mutation_retries_against_the_latest_revision(
        self, tmp_path: Path
    ) -> None:
        substrate = _OneConflictSubstrate(tmp_path)
        state = ScopeStateStore(substrate, "s1")
        state.set("seed", True)
        substrate.conflict = True

        state.set("mine", True)

        assert state.snapshot() == {"concurrent": True, "mine": True}


class TestACorruptFileRefuses:
    """A record is not a cache — it must not degrade to empty."""

    def test_unparseable_state_raises(self, tmp_path: Path) -> None:
        scopes = JsonFileSubstrate(tmp_path)
        path = scopes.path_for(scope_state_key("s1"))
        path.parent.mkdir(parents=True)
        path.write_text("{not json")

        with pytest.raises(ScopeStateUnreadableError):
            ScopeStore(scopes).get_state("s1", "k")

    def test_the_file_is_left_in_place(self, tmp_path: Path) -> None:
        """Repeatable, like `load_scopes`' refusal.

        If the read moved the file aside, the next run would find nothing, read
        it as "no state", and carry on — silently, which is the failure this
        refusal exists to prevent.
        """
        scopes = JsonFileSubstrate(tmp_path)
        path = scopes.path_for(scope_state_key("s1"))
        path.parent.mkdir(parents=True)
        path.write_text("{not json")

        with pytest.raises(ScopeStateUnreadableError):
            ScopeStore(scopes).get_state("s1", "k")
        assert path.exists() and path.read_text() == "{not json"


class TestAScopeIdCannotEscapeTheDirectory:
    @pytest.mark.parametrize("bad", ["../outside", "a/b", "", ".", "..", "a\\b"])
    def test_separators_are_rejected(self, tmp_path: Path, bad: str) -> None:
        """Rejected rather than escaped.

        A scope id that could name a path outside the state directory is a bug
        at its source; quietly rewriting it would hide that.
        """
        with pytest.raises(ValueError, match="scope id"):
            JsonFileSubstrate(tmp_path).path_for(scope_state_key(bad))


class TestDiscard:
    def test_discard_removes_the_file(self, tmp_path: Path) -> None:
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        store.set_state("s1", "k", 1)
        assert store.discard_state("s1") is True
        assert not scopes.path_for(scope_state_key("s1")).exists()

    def test_discarding_nothing_is_not_an_error(self, tmp_path: Path) -> None:
        assert ScopeStore(JsonFileSubstrate(tmp_path)).discard_state("never") is False

    def test_a_direct_store_discards_too(self, tmp_path: Path) -> None:
        store = ScopeStateStore(JsonFileSubstrate(tmp_path), "s1")
        store.set("k", 1)
        assert store.discard() is True
        assert store.discard() is False


class TestReviewFindings:
    """Regressions for findings from the external scope-state review.

    Each was found by external review after the feature was implemented and
    passing. They are grouped here so the finding that motivated each is
    findable from the test, not only from the commit.
    """

    def test_deleting_a_scope_forgets_that_its_record_exists(
        self, tmp_path: Path
    ) -> None:
        """Q1.4. `_ensured` outliving the record produced an uncollectable orphan.

        `set_state` ensures the record once per scope per process and memoises
        it. After `delete_scope` that memo is a lie, so the next `set_state`
        wrote state with **no record** — and `purge_scopes` walks records, so
        nothing could ever find it again.
        """
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        store.set_state("s1", "k", 1)
        assert store.delete_scope("s1") is True

        store.set_state("s1", "k", 2)

        assert store.get_scope("s1") is not None, (
            "writing state after the record was deleted did not recreate it — "
            "the state file is an orphan nothing can collect"
        )

    def test_discard_refuses_while_a_batch_is_open(self, tmp_path: Path) -> None:
        """Q1.1 / Q2.1a. Unlinking under an open batch is incoherent either way.

        If the batch commits after the unlink the file is **resurrected** — a
        reset that never happened. If the unlink lands inside a `_mutate`'s
        load-write window it is **lost**. An error beats picking a winner.
        """
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.set_state("s1", "k", 1)

        with (
            pytest.raises(RuntimeError, match="batch is open"),
            store.state_batch("s1"),
        ):
            store.discard_state("s1")

    def test_discard_does_not_resurrect_the_file(self, tmp_path: Path) -> None:
        """The outcome the refusal above protects, asserted directly."""
        scopes = JsonFileSubstrate(tmp_path)
        store = ScopeStore(scopes)
        store.set_state("s1", "k", 1)
        with store.state_batch("s1"):
            store.set_state("s1", "k", 2)
        assert store.discard_state("s1") is True
        assert not scopes.path_for(scope_state_key("s1")).exists()

    def test_one_store_object_per_path(self, tmp_path: Path) -> None:
        """Q1.5 / Q2.2. Two objects over one path self-deadlock on `flock`.

        They also split the batch: a batch opened on one is invisible to the
        other, so writes through the second bypass it entirely.
        """
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        assert store._state_store("s1") is store._state_store("s1")
        assert store._state_store("s1") is not store._state_store("s2")

    @pytest.mark.parametrize("bad_state", ["[]", "null", '"text"', "3"])
    def test_a_non_object_state_refuses_rather_than_reading_empty(
        self, tmp_path: Path, bad_state: str
    ) -> None:
        """Q1.6. Reading it as `{}` let the next write drop the file's contents.

        The module promises a record is not a cache. `{"state": []}` read as
        empty and the next `set` replaced the file wholesale, which is exactly
        the silent loss the promise rules out.
        """
        scopes = JsonFileSubstrate(tmp_path)
        path = scopes.path_for(scope_state_key("s1"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"state": ' + bad_state + "}")

        with pytest.raises(ScopeStateUnreadableError):
            ScopeStore(scopes).get_state("s1", "k")

    def test_a_file_with_no_state_key_is_still_empty_not_broken(
        self, tmp_path: Path
    ) -> None:
        """The boundary the refusal must not cross.

        An envelope that simply has no `state` key yet is "no state", which is
        the absence of a run rather than a damaged one.
        """
        scopes = JsonFileSubstrate(tmp_path)
        path = scopes.path_for(scope_state_key("s1"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")

        assert ScopeStore(scopes).get_state("s1", "k", "default") == "default"


@pytest.fixture
def no_locking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the substrate's file lock with a no-op for this test.

    AC-2 is asserted with locking **disabled** because a test that runs with
    locking working cannot tell a fencing design from an owner-plus-expiry one:
    both serialise the writes, so both look correct. `file_lock` also proceeds
    unlocked after its timeout and is a no-op where neither `fcntl` nor
    `msvcrt` exists, so this is the real deployment, not a hypothetical.
    `tests/primitives/test_lease_fencing.py` makes the same statement for
    *record* writes with a block-scoped `_no_locking`; this is the fixture form
    of it, patched on the one `lock` the substrate now owns.
    """

    @contextmanager
    def _nothing(self: Any, *keys: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(JsonFileSubstrate, "lock", _nothing)


def _superseded_holder(
    substrate: JsonFileSubstrate, scope_id: str = "wf"
) -> ScopeStore:
    """A store still holding a generation another runner has taken from it.

    Seeds one live key first, so a refusal can be told apart from a write that
    landed on an empty file.
    """
    store = ScopeStore(substrate)
    store.ensure_scope(scope_id)
    mine = store.claim_scope(scope_id, owner="runner-A")
    store.hold(scope_id, mine.generation)
    store.set_state(scope_id, "k", "live")
    ScopeStore(substrate).claim_scope(scope_id, owner="runner-B", force=True)
    return store


def _write_in_a_state_batch(store: ScopeStore) -> None:
    with store.state_batch("wf") as batch:
        batch.set("k", "written-by-stale-A")


class TestAStaleRunnersStateWriteIsRefused:
    """AC-2. A superseded runner cannot overwrite the live holder's job state.

    Record writes have been fenced since `durable-run-layer`/T6, and T3 then
    moved job state out of the record into `scope-state/<id>` — so the fence
    stopped covering the half a job actually writes, and nothing said so. The
    research pass that opened this ticket wrote a script to check the suspected
    consequence; it showed the same stale runner correctly refused on its
    record write and overwriting the live holder's state in the next line.
    That sequence is what `test_the_defect_b1_shape` asserts, and "defect B1"
    is the name it keeps.

    The script was never committed, and the research notes that carried it were
    a branch artifact cleared before merge, so this docstring is the defect's
    provenance rather than a pointer into a directory that no longer exists.
    """

    def test_the_defect_b1_shape(self, tmp_path: Path) -> None:
        """The reproduction's own sequence, asserted.

        Both halves are the gate. A refusal that still rewrote the file would
        satisfy the first and fail the second, and the second is what a reader
        of the state would have seen.
        """
        substrate = JsonFileSubstrate(tmp_path)
        a = ScopeStore(substrate)
        a.ensure_scope("wf")
        la = a.claim_scope("wf", owner="runner-A")
        a.hold("wf", la.generation)
        a.set_state("wf", "rows", "written-by-A-while-holder")

        b = ScopeStore(substrate)
        lb = b.claim_scope("wf", owner="runner-B", force=True)
        b.hold("wf", lb.generation)
        assert lb.generation > la.generation

        with pytest.raises(StaleGenerationError):
            a.set_position("wf", "step-by-stale-A")
        with pytest.raises(StaleGenerationError):
            a.set_state("wf", "rows", "OVERWRITTEN-BY-STALE-A")

        assert b.get_state("wf", "rows") == "written-by-A-while-holder"

    @pytest.mark.parametrize(
        ("path", "write"),
        [
            ("set_state", lambda s: s.set_state("wf", "k", "written-by-stale-A")),
            ("delete_state", lambda s: s.delete_state("wf", "k")),
            ("clear_state", lambda s: s.clear_state("wf")),
            ("state_batch", _write_in_a_state_batch),
            ("discard_state", lambda s: s.discard_state("wf")),
        ],
    )
    def test_every_state_write_path_is_refused(
        self, tmp_path: Path, path: str, write: Callable[[ScopeStore], None]
    ) -> None:
        """All five write paths, named one by one.

        Enumerated as behaviour rather than by reading the source: a method can
        route through the seam and still be reachable by a path that skips it,
        which only running it shows.
        """
        store = _superseded_holder(JsonFileSubstrate(tmp_path))

        with pytest.raises(StaleGenerationError):
            write(store)

    @pytest.mark.parametrize(
        ("path", "write"),
        [
            ("set_state", lambda s: s.set_state("wf", "k", "written-by-stale-A")),
            ("delete_state", lambda s: s.delete_state("wf", "k")),
            ("clear_state", lambda s: s.clear_state("wf")),
            ("state_batch", _write_in_a_state_batch),
        ],
    )
    def test_the_state_file_is_unchanged_after_a_refusal(
        self, tmp_path: Path, path: str, write: Callable[[ScopeStore], None]
    ) -> None:
        """Refused means nothing was written, not written and then flagged.

        Read back through a *different* store so the assertion cannot be
        satisfied by a cached object.
        """
        substrate = JsonFileSubstrate(tmp_path)
        store = _superseded_holder(substrate)

        with pytest.raises(StaleGenerationError):
            write(store)

        assert ScopeStore(substrate).state_snapshot("wf") == {"k": "live"}

    def test_the_file_still_exists_after_a_refused_discard(
        self, tmp_path: Path
    ) -> None:
        """`discard_state` is fenced because it is the destructive one."""
        substrate = JsonFileSubstrate(tmp_path)
        store = _superseded_holder(substrate)

        with pytest.raises(StaleGenerationError):
            store.discard_state("wf")

        assert substrate.path_for(scope_state_key("wf")).exists()

    def test_the_reads_are_not_fenced(self, tmp_path: Path) -> None:
        """The narrow fence, stated: writes are refused, reads are not.

        `_mutate` fences record *writes* and leaves `get_scope` alone; state
        follows the same line. A stale runner reading its own scope's state —
        while logging, while deciding to stop — gets an answer rather than an
        exception.
        """
        store = _superseded_holder(JsonFileSubstrate(tmp_path))

        assert store.get_state("wf", "k") == "live"
        assert store.state_snapshot("wf") == {"k": "live"}

    def test_a_batch_superseded_while_open_writes_nothing(self, tmp_path: Path) -> None:
        """The exit check, and why the entry one is not enough.

        A `state_batch` block writes once, on clean exit, so the window in
        which its holder can be superseded is the whole block. Checked only on
        entry, a claim landing mid-block would be overwritten by a commit that
        was authorised before it existed.
        """
        substrate = JsonFileSubstrate(tmp_path)
        store = ScopeStore(substrate)
        store.ensure_scope("wf")
        mine = store.claim_scope("wf", owner="runner-A")
        store.hold("wf", mine.generation)
        store.set_state("wf", "k", "live")

        with (
            pytest.raises(StaleGenerationError),
            store.state_batch("wf") as batch,
        ):
            batch.set("k", "written-in-the-block")
            ScopeStore(substrate).claim_scope("wf", owner="runner-B", force=True)

        assert ScopeStore(substrate).state_snapshot("wf") == {"k": "live"}

    def test_the_generation_is_read_at_write_time(self, tmp_path: Path) -> None:
        """Not at construction — the design this one rules out.

        `_state_store` memoises one `ScopeStateStore` per scope, so the object
        that performs the write is built on the **first** state access. Here
        that is a read taken before any claim exists, so a generation handed to
        its constructor would stay `None` for the rest of the process and every
        later write would go through unfenced.

        The write under test is the **second** one, deliberately. The first
        state write to a scope also ensures its record, and `ensure_scope` is
        fenced already — so a test that refused there would pass with this
        seam removed entirely. Found by sabotaging the seam: an earlier version
        of this test survived it.
        """
        substrate = JsonFileSubstrate(tmp_path)
        store = ScopeStore(substrate)
        store.ensure_scope("wf")
        assert store.get_state("wf", "k") is None

        mine = store.claim_scope("wf", owner="runner-A")
        store.hold("wf", mine.generation)
        store.set_state("wf", "k", "live")  # pays the record ensure while current
        ScopeStore(substrate).claim_scope("wf", owner="runner-B", force=True)

        with pytest.raises(StaleGenerationError):
            store.set_state("wf", "k", "written-by-stale-A")

    def test_locking_is_not_the_mechanism(
        self, tmp_path: Path, no_locking: None
    ) -> None:
        """AC-2 with the file lock disabled entirely.

        The fence is a comparison of two integers read from the record, so it
        holds where the lock does not — a network filesystem, a timed-out
        `flock`, a substrate whose lock is a no-op. That is exactly where two
        runners are most likely to meet.
        """
        substrate = JsonFileSubstrate(tmp_path)
        store = _superseded_holder(substrate)

        with pytest.raises(StaleGenerationError):
            store.set_state("wf", "k", "OVERWRITTEN-BY-STALE-A")

        assert ScopeStore(substrate).get_state("wf", "k") == "live"

    def test_the_fixture_really_disables_locking(
        self, tmp_path: Path, no_locking: None
    ) -> None:
        """Guards the test above against proving nothing.

        `tests/primitives/test_lease_fencing.py::TestFencingHoldsWithoutLocking`
        `::test_the_no_op_lock_is_really_in_effect` makes this statement for its
        own harness; this fixture had nothing proving the patch landed. If it
        missed, the test above would run with real locking and pass for the
        wrong reason — which is the failure mode AC-2 is about, a locking
        implementation and a fencing one being indistinguishable while the lock
        works.
        """
        substrate = JsonFileSubstrate(tmp_path)

        # A key nothing has touched, so any sidecar found must have been made
        # by this acquisition — the real `lock` opens the `.lock` file whether
        # or not it goes on to win the `flock`.
        with substrate.lock("never-locked"):
            pass

        assert (
            not substrate.path_for("never-locked").with_suffix(".json.lock").exists()
        ), "a real lock was taken while locking was supposed to be disabled"


class TestTheFenceDoesNotRefuseTheLiveHolder:
    """The other half of AC-2: a fence that refused everything would pass above.

    Every test here would fail if the seam read the wrong generation, checked a
    scope it was not asked about, or fenced a store that holds no lease at all.
    """

    def test_the_current_holder_still_writes(self, tmp_path: Path) -> None:
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.ensure_scope("wf")
        mine = store.claim_scope("wf", owner="runner-A")
        store.hold("wf", mine.generation)

        store.set_state("wf", "k", "mine")
        with store.state_batch("wf") as batch:
            batch.set("in-a-batch", True)

        assert store.state_snapshot("wf") == {"k": "mine", "in-a-batch": True}

    def test_a_renewed_lease_does_not_move_the_generation(self, tmp_path: Path) -> None:
        """Renewal extends the claim without minting a generation, so the
        holder's writes must survive it."""
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.ensure_scope("wf")
        mine = store.claim_scope("wf", owner="runner-A")
        store.hold("wf", mine.generation)
        store.renew_scope("wf", owner="runner-A", generation=mine.generation)

        store.set_state("wf", "k", "still-mine")

        assert store.get_state("wf", "k") == "still-mine"

    def test_a_store_with_no_hold_writes_freely(self, tmp_path: Path) -> None:
        """Most callers have no lease: the CLI reading and clearing, a purge, a
        job running outside a walk. Requiring one would break all of them."""
        substrate = JsonFileSubstrate(tmp_path)
        walker = ScopeStore(substrate)
        walker.ensure_scope("wf")
        walker.hold("wf", walker.claim_scope("wf", owner="runner-A").generation)
        walker.set_state("wf", "k", "live")

        unleased = ScopeStore(substrate)
        unleased.set_state("wf", "k", "by-the-cli")
        assert unleased.get_state("wf", "k") == "by-the-cli"
        assert unleased.discard_state("wf") is True

    def test_holding_one_scope_does_not_fence_anothers_state(
        self, tmp_path: Path
    ) -> None:
        """Per scope, not per store — `hold`'s reason, applied to state.

        A nested workflow claims its own scope through the **same** store
        object. One generation for the whole store fenced the child's writes to
        a different scope and stopped it creating its own record at all; the
        integration statement of that property is
        `test_a_nested_workflow_still_owns_its_own_scope`.
        """
        store = _superseded_holder(JsonFileSubstrate(tmp_path))

        store.set_state("wf::child", "k", "by-the-child")

        assert store.get_state("wf::child", "k") == "by-the-child"
