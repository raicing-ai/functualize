"""The stores, running on a substrate that is not a filesystem.

`store-substrate`/T5. Spec AC-3, AC-5.

`JsonFileSubstrate` exists to change nothing, so its tests can only show that
the port *describes* today's behaviour. This file is the other half: the same
stores, the same typed methods, over SQLite — which is the first time anything
proves the port is a **port** rather than one implementation with an interface
drawn round it.

Two claims are specific to this implementation and are tested as behaviour,
not asserted in prose:

- **One lock, not many.** The lock-order inversion an external review found
  between the scope lock and the state lock cannot happen here, because a
  transaction covers every key. `JsonFileSubstrate` can only sort the locks it
  takes in one call, which does not help a caller that takes one, does
  something, and takes another.
- **Compare-and-swap without a lock.** The filesystem needs the caller to hold
  `flock` for `expect` to be exact. Here the compare and the write are one
  statement, which is the property a backend with no `flock` has to supply
  instead.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from functualize_state_sqlite.substrate import SQLiteSubstrate

from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.run_store import RunStore
from functualize._primitives.scope_store import ScopeStore
from functualize._types.errors import (
    ScopeStoreUnreadableError,
    SubstrateUnreadableError,
)
from functualize._types.protocols import StoreSubstrate


@pytest.fixture
def substrate(tmp_path: Path) -> SQLiteSubstrate:
    return SQLiteSubstrate(tmp_path / "state.db")


class TestItSatisfiesThePort:
    def test_it_is_a_substrate(self, substrate: SQLiteSubstrate) -> None:
        assert isinstance(substrate, StoreSubstrate)

    def test_round_trip(self, substrate: SQLiteSubstrate) -> None:
        substrate.write("scopes", {"scopes": {"a": {"status": "running"}}})
        stored = substrate.read("scopes")
        assert stored is not None
        assert stored.data == {"scopes": {"a": {"status": "running"}}}

    def test_an_unwritten_key_reads_as_none(self, substrate: SQLiteSubstrate) -> None:
        assert substrate.read("never-written") is None

    def test_an_empty_document_is_not_none(self, substrate: SQLiteSubstrate) -> None:
        substrate.write("empty", {})
        stored = substrate.read("empty")
        assert stored is not None and stored.data == {}

    def test_unparseable_raises_rather_than_deciding(
        self, substrate: SQLiteSubstrate
    ) -> None:
        """Same rule as the filesystem: the *store* decides whether it is fatal."""
        substrate.write("k", {"v": 1})
        substrate._conn().execute(  # noqa: SLF001
            "UPDATE documents SET payload = ? WHERE key = ?", ("{not json", "k")
        )
        with pytest.raises(SubstrateUnreadableError) as exc:
            substrate.read("k")
        assert exc.value.key == "k"

    def test_delete_reports_whether_there_was_one(
        self, substrate: SQLiteSubstrate
    ) -> None:
        substrate.write("k", {"v": 1})
        assert substrate.delete("k") is True
        assert substrate.delete("k") is False

    def test_clear_keeps_a_copy_without_reading_it(
        self, substrate: SQLiteSubstrate
    ) -> None:
        substrate.write("k", {"v": 1})
        substrate._conn().execute(  # noqa: SLF001
            "UPDATE documents SET payload = ? WHERE key = ?", ("{not json", "k")
        )

        where = substrate.clear("k")

        assert where is not None
        assert substrate.read("k") is None
        row = (
            substrate._conn()  # noqa: SLF001
            .execute("SELECT payload FROM documents WHERE key = 'k.bak'")
            .fetchone()
        )
        assert row[0] == "{not json", "clear decoded what it moved"

    def test_describe_aggregates_a_namespace(self, substrate: SQLiteSubstrate) -> None:
        """A trailing slash names every scope's state, not one document."""
        assert substrate.describe("scope-state/") == "empty"
        substrate.write("scope-state/a", {"state": {}})
        substrate.write("scope-state/b", {"state": {}})
        assert "2 document" in substrate.describe("scope-state/")


class TestCompareAndSwapNeedsNoLock:
    """The property a backend with no `flock` supplies instead of one."""

    def test_a_stale_revision_refuses(self, substrate: SQLiteSubstrate) -> None:
        substrate.write("k", {"v": 1})
        stored = substrate.read("k")
        assert stored is not None
        substrate.write("k", {"v": "someone else"})  # the interleaved writer

        assert substrate.write("k", {"v": 2}, expect=stored.revision) is False
        current = substrate.read("k")
        assert current is not None and current.data == {"v": "someone else"}

    def test_a_matching_revision_writes(self, substrate: SQLiteSubstrate) -> None:
        substrate.write("k", {"v": 1})
        stored = substrate.read("k")
        assert stored is not None
        assert substrate.write("k", {"v": 2}, expect=stored.revision) is True

    def test_expecting_a_document_that_never_existed_refuses(
        self, substrate: SQLiteSubstrate
    ) -> None:
        assert substrate.write("k", {"v": 1}, expect=1) is False
        assert substrate.read("k") is None

    def test_concurrent_writers_do_not_both_win(
        self, substrate: SQLiteSubstrate
    ) -> None:
        """Exactly one of two compare-and-swaps against one revision lands.

        Asserted without any lock, because that is the case this exists for:
        on a backend that cannot offer mutual exclusion, `expect` is the only
        thing standing between two writers and a lost update.
        """
        substrate.write("k", {"v": 0})
        stored = substrate.read("k")
        assert stored is not None

        results: list[bool] = []
        barrier = threading.Barrier(2)

        def contend(value: int) -> None:
            barrier.wait(timeout=10)
            results.append(substrate.write("k", {"v": value}, expect=stored.revision))

        threads = [threading.Thread(target=contend, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert sorted(results) == [False, True], (
            f"two compare-and-swaps against one revision: {results}"
        )


class TestOneLockCannotInvert:
    """The reason `lock` is variadic and this substrate exists.

    An external review of `scope-record-lifecycle` found a lock-order
    inversion: a record write inside `state.batch()` takes state then scopes,
    while a state write inside `store.batch()` takes scopes then state. No
    store can fix it, because the *caller* chooses which batch to open first.
    Sorting the keys inside one `lock()` call does not help — the two calls are
    separate. One lock does.
    """

    def test_the_two_orders_do_not_deadlock(self, substrate: SQLiteSubstrate) -> None:
        done: list[str] = []
        barrier = threading.Barrier(2)

        def state_then_scopes() -> None:
            barrier.wait(timeout=10)
            with substrate.lock("scope-state/wf"), substrate.lock("scopes"):
                substrate.write("scopes", {"scopes": {}})
            done.append("a")

        def scopes_then_state() -> None:
            barrier.wait(timeout=10)
            with substrate.lock("scopes"), substrate.lock("scope-state/wf"):
                substrate.write("scope-state/wf", {"state": {}})
            done.append("b")

        threads = [
            threading.Thread(target=state_then_scopes),
            threading.Thread(target=scopes_then_state),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert sorted(done) == ["a", "b"], (
            f"the inverted pair did not both finish: {done} — one lock should "
            f"make this impossible to deadlock"
        )

    def test_the_lock_is_re_entrant(self, substrate: SQLiteSubstrate) -> None:
        """A store takes it around a write a wider batch may already hold."""
        with substrate.lock("scopes"), substrate.lock("scopes"):
            substrate.write("scopes", {"scopes": {}})
        stored = substrate.read("scopes")
        assert stored is not None

    def test_an_exception_rolls_the_block_back(
        self, substrate: SQLiteSubstrate
    ) -> None:
        """All-or-nothing, which `JsonFileSubstrate` cannot offer across keys."""
        substrate.write("scopes", {"scopes": {"before": {}}})

        with pytest.raises(RuntimeError), substrate.lock("scopes", "runs"):
            substrate.write("scopes", {"scopes": {"after": {}}})
            substrate.write("runs", {"runs": {}})
            raise RuntimeError("boom")

        stored = substrate.read("scopes")
        assert stored is not None
        assert stored.data["scopes"] == {"before": {}}, "the block was not rolled back"
        assert substrate.read("runs") is None


class TestTheStoresRunOnIt:
    """The typed methods, unchanged, over a backend that is not a filesystem."""

    def test_a_scope_record_round_trips(self, substrate: SQLiteSubstrate) -> None:
        store = ScopeStore(substrate)
        store.ensure_scope("wf", "release")
        store.record_step("wf", "build::", {"status": "success"})
        store.set_position("wf", "deploy")

        reopened = ScopeStore(substrate)
        record = reopened.get_scope("wf")
        assert record is not None
        assert record["position"] == "deploy"
        assert reopened.get_step("wf", "build::")["status"] == "success"

    def test_job_state_lives_in_the_same_backend(
        self, substrate: SQLiteSubstrate
    ) -> None:
        """AC-4, over the implementation it actually matters for.

        On the filesystem a split brain would be two directories. Here it would
        be a scope record in SQLite and its state in a JSON file, which is the
        arrangement `replace_state_store` used to make possible.
        """
        store = ScopeStore(substrate)
        store.set_state("wf", "rows", 12)

        assert ScopeStore(substrate).get_state("wf", "rows") == 12
        assert substrate.read("scope-state/wf") is not None
        assert substrate.read("scopes") is not None

    def test_the_freshness_ledger_still_degrades(
        self, substrate: SQLiteSubstrate
    ) -> None:
        """The discard rules are the store's, so they are backend-independent."""
        store = FreshStore(substrate)
        store.put_fingerprint("k", {"n": 1})
        substrate._conn().execute(  # noqa: SLF001
            "UPDATE documents SET payload = ? WHERE key = ?", ("{not json", "fresh")
        )
        assert store.get_fingerprint("k") is None  # degraded, not raised

    def test_the_scope_store_still_refuses(self, substrate: SQLiteSubstrate) -> None:
        """The opposite rule, on the same backend. Neither moved into storage."""
        ScopeStore(substrate).ensure_scope("wf")
        substrate._conn().execute(  # noqa: SLF001
            "UPDATE documents SET payload = ? WHERE key = ?",
            (json.dumps({"format_version": 99, "scopes": {}}), "scopes"),
        )
        with pytest.raises(ScopeStoreUnreadableError):
            ScopeStore(substrate).scope_ids()

    def test_a_run_record_round_trips(self, substrate: SQLiteSubstrate) -> None:
        store = RunStore(substrate)
        run_id = store.open_run({"job": "build", "surface": "func.job"})
        store.close_run(run_id, "success")

        assert RunStore(substrate).get_run(run_id)["status"] == "success"

    def test_a_batch_is_still_all_or_nothing(self, substrate: SQLiteSubstrate) -> None:
        store = ScopeStore(substrate)
        store.ensure_scope("wf")

        with pytest.raises(RuntimeError), store.batch():
            store.set_scope_status("wf", "completed")
            raise RuntimeError("boom")

        record = ScopeStore(substrate).get_scope("wf")
        assert record is not None
        assert record.get("status") != "completed"


class TestItNeedsNoSharedDisk:
    """Spec AC-3, as far as one process can show it.

    The two-process version lives in the core suite's durability test; what is
    demonstrated here is the property that makes it possible — the substrate is
    addressed by a connection string, and nothing in the store stack touches a
    path.
    """

    def test_a_second_substrate_object_sees_the_first_ones_writes(
        self, tmp_path: Path
    ) -> None:
        first = SQLiteSubstrate(tmp_path / "state.db")
        ScopeStore(first).put_gate("wf", "approve", {"payload": {"by": "sam"}})

        second = SQLiteSubstrate(tmp_path / "state.db")
        gate = ScopeStore(second).get_gate("wf", "approve")
        assert gate is not None and gate["payload"] == {"by": "sam"}

    def test_no_store_asks_the_substrate_for_a_path(
        self, substrate: SQLiteSubstrate
    ) -> None:
        """`path_for` is a `JsonFileSubstrate` detail, not part of the port.

        A store that reached for it would work on a laptop and fail on any
        backend without a filesystem — the failure this feature exists to make
        impossible, arriving at the last moment.
        """
        seen: list[str] = []

        class NoPaths:
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def __getattr__(self, name: str) -> Any:
                if name in {"path_for", "root", "path"}:
                    seen.append(name)
                    raise AttributeError(name)
                return getattr(self._inner, name)

        wrapped = NoPaths(substrate)
        store = ScopeStore(wrapped)
        store.ensure_scope("wf")
        store.set_state("wf", "k", 1)
        store.get_scope("wf")
        FreshStore(wrapped).put_fingerprint("k", {"n": 1})
        RunStore(wrapped).open_run({"job": "b", "surface": "func.job"})

        assert seen == [], f"a store asked the substrate for {seen}"
