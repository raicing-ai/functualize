"""ScopeStore: the accessors, and the two behaviours that are new.

The accessors are a move — they behaved this way when they lived on
``ScopeStore``, and `tests/test_state_store.py` keeps proving that through the
façade. What is new here is `batch()` and the fail-closed read reaching a
caller.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from functualize._primitives.fresh_format import FRESH_KEY
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.scope_format import (
    SCOPES_FILENAME,
    SCOPES_KEY,
    SCOPES_VERSION,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import ScopeStoreUnreadableError


@pytest.fixture
def store(tmp_path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _no_locking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the substrate's file lock with a no-op for one test.

    `JsonFileSubstrate.lock` is not re-entrant — a nested acquire on the same
    key spins to the ten-second timeout — so a test that interleaves a peer
    write *inside* an open batch would stall with real locking on, and would
    prove less rather than more: while the lock is held the peer cannot land at
    all, so the compare-and-swap never has to fire. `file_lock` also proceeds
    unlocked after that timeout and is a no-op where the OS offers no locking
    (`fresh_format.py`), so this is a deployment and not a hypothetical. The
    same statement `tests/primitives/test_lease_fencing.py`'s `_no_locking` and
    `test_scope_state_store.py`'s `no_locking` fixture make for their own
    harnesses.
    """

    @contextmanager
    def _nothing(self: object, *keys: str) -> Iterator[None]:
        yield

    monkeypatch.setattr(JsonFileSubstrate, "lock", _nothing)


class TestLocation:
    """`beside_fresh` is gone, and its absence is the point.

    It existed to apply the sibling rule to an explicit path so two stores
    could not land in different directories. With one substrate handed to both
    there is no second resolution to keep in agreement — the rule is not
    enforced any more, it is unsayable.
    """

    def test_the_scope_store_shares_the_fresh_store_substrate(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        fresh = FreshStore.for_project(tmp_path)
        assert fresh.scopes.substrate is fresh.substrate

    @pytest.mark.json_substrate
    def test_for_project_resolves_like_the_state_file(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        substrate = ScopeStore.for_project(tmp_path).substrate
        assert (
            substrate.path_for(SCOPES_KEY)
            == tmp_path / ".functualize" / SCOPES_FILENAME
        )
        assert (
            substrate.path_for(FRESH_KEY).parent
            == substrate.path_for(SCOPES_KEY).parent
        )


class TestScopeLifecycle:
    def test_unknown_scope_is_none(self, store: ScopeStore) -> None:
        assert store.get_scope("nope") is None

    def test_ensure_scope_is_idempotent(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "release")
        store.set_scope_status("s1", "blocked")
        store.ensure_scope("s1")
        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["workflow"] == "release"
        assert scope["status"] == "blocked"

    def test_blank_scope_has_every_section(self, store: ScopeStore) -> None:
        store.ensure_scope("s1")
        scope = store.get_scope("s1")
        assert scope is not None
        assert set(scope) == {
            "workflow",
            "status",
            "steps",
            "branches",
            "gates",
            "position",
            "epilogue",
            "tool_calls",
            # Added by workflow-graph-semantics/T5: what the walk emitted, for
            # a watcher to follow. On the scope and not in the run log because
            # a scope is advanced by several runs across a resume, and a log
            # flushed when a run ends is too late for anyone watching.
            "events",
        }

    def test_scope_ids_are_sorted(self, store: ScopeStore) -> None:
        for name in ("c", "a", "b"):
            store.ensure_scope(name)
        assert store.scope_ids() == ["a", "b", "c"]

    def test_status_round_trip(self, store: ScopeStore) -> None:
        store.set_scope_status("s1", "completed")
        scope = store.get_scope("s1")
        assert scope is not None and scope["status"] == "completed"


class TestSteps:
    def test_step_round_trip(self, store: ScopeStore) -> None:
        store.record_step("s1", "build::abc", {"status": "success"})
        assert store.get_step("s1", "build::abc") == {"status": "success"}

    def test_unknown_step_is_none(self, store: ScopeStore) -> None:
        store.ensure_scope("s1")
        assert store.get_step("s1", "nope::x") is None

    def test_step_in_unknown_scope_is_none(self, store: ScopeStore) -> None:
        assert store.get_step("nope", "build::abc") is None


class TestBranches:
    def test_branch_round_trip(self, store: ScopeStore) -> None:
        store.record_branch("s1", "check", "deploy")
        assert store.get_branch("s1", "check") == "deploy"

    def test_unknown_branch_is_none(self, store: ScopeStore) -> None:
        assert store.get_branch("nope", "check") is None


class TestGates:
    def test_gate_round_trip(self, store: ScopeStore) -> None:
        store.put_gate("s1", "approve", {"model": "", "payload": None})
        gate = store.get_gate("s1", "approve")
        assert gate is not None and gate["payload"] is None

    def test_deposit_payload(self, store: ScopeStore) -> None:
        store.put_gate("s1", "approve", {"payload": None})
        assert store.deposit_gate_payload("s1", "approve", {"ok": True}) is True
        gate = store.get_gate("s1", "approve")
        assert gate is not None and gate["payload"] == {"ok": True}

    def test_deposit_to_unknown_gate_reports_false(self, store: ScopeStore) -> None:
        assert store.deposit_gate_payload("s1", "nope", {"ok": True}) is False


class TestPositionAndEpilogue:
    def test_position_round_trip(self, store: ScopeStore) -> None:
        store.set_position("s1", "approve")
        assert store.get_position("s1") == "approve"
        store.set_position("s1", None)
        assert store.get_position("s1") is None

    def test_epilogue_round_trip(self, store: ScopeStore) -> None:
        assert store.get_epilogue("s1") is None
        store.record_epilogue("s1", {"return_value": 7})
        assert store.get_epilogue("s1") == {"return_value": 7}


class TestToolCalls:
    def test_tool_calls_are_append_only_and_never_memoized(
        self, store: ScopeStore
    ) -> None:
        """An agent that calls check_inventory three times meant to."""
        for i in range(3):
            store.record_tool_call("s1", {"tool": "check_inventory", "n": i})
        assert [c["n"] for c in store.get_tool_calls("s1")] == [0, 1, 2]

    def test_no_tool_calls_in_unknown_scope(self, store: ScopeStore) -> None:
        assert store.get_tool_calls("nope") == []


class TestBatch:
    def test_batch_writes_once(self, store: ScopeStore, monkeypatch) -> None:
        writes = []
        real = JsonFileSubstrate.write
        monkeypatch.setattr(
            JsonFileSubstrate,
            "write",
            lambda self, key, payload, **kw: (
                writes.append(key),
                real(self, key, payload, **kw),
            )[1],
        )

        with store.batch():
            store.ensure_scope("s1", "release")
            store.record_step("s1", "build::", {"status": "success"})
            store.set_position("s1", "deploy")
            store.set_scope_status("s1", "running")

        assert len(writes) == 1

    def test_batch_reads_its_own_writes(self, store: ScopeStore) -> None:
        with store.batch():
            store.record_branch("s1", "check", "deploy")
            assert store.get_branch("s1", "check") == "deploy"

    def test_batch_result_is_persisted(self, store: ScopeStore) -> None:
        with store.batch():
            store.ensure_scope("s1", "release")
            store.set_position("s1", "approve")
        assert store.get_position("s1") == "approve"

    def test_exception_discards_the_whole_block(self, store: ScopeStore) -> None:
        """All-or-nothing per block, rather than a torn half-written node."""
        store.ensure_scope("s1", "release")
        with pytest.raises(RuntimeError), store.batch():
            store.record_step("s1", "build::", {"status": "success"})
            store.set_position("s1", "deploy")
            raise RuntimeError("boom")

        assert store.get_step("s1", "build::") is None
        assert store.get_position("s1") is None

    def test_nested_batch_reuses_the_outer_one(self, store: ScopeStore) -> None:
        with store.batch(), store.batch():
            store.ensure_scope("s1")
        assert store.scope_ids() == ["s1"]


class TestBatchCompareAndSwap:
    """`batch`'s exit write is compare-and-swapped, not a blind last write.

    Found by this ticket's wave-3 verification, which removed
    `expect=revision` from that write — `scope_store.py:353`, the only CAS site
    in the ticket — and watched the entire suite stay green. The failure it
    prevents is silent by construction: `batch` reads the envelope when the
    block opens and writes it once at the end, so a peer that commits while the
    block is open is absent from that envelope, and without the expected
    revision the exit write replaces the file with it — dropping the peer's
    scope rather than replaying this batch's mutations onto the newer one.

    Locking is disabled, for the reason AC-1 and AC-2 disable it: while the
    lock works the peer cannot get in at all, so the two designs are
    indistinguishable and both look correct.
    """

    def test_a_peer_scope_committed_during_a_batch_survives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_locking(monkeypatch)
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.ensure_scope("mine", "release")

        committed: list[str] = []
        real_write = JsonFileSubstrate.write

        def write_with_one_peer_commit(
            self: JsonFileSubstrate,
            key: str,
            payload: dict,
            *,
            expect: object | None = None,
        ) -> bool:
            """Commit a peer's scope through the public API, once, first.

            Injected unconditionally rather than only when `expect` is set, so
            that the test still interleaves when the fix it guards is removed —
            otherwise the sabotage would simply never fire the injection, and
            the assertion that failed would say nothing about the clobber.
            """
            if not committed:
                # Marked before the peer writes: that write comes back through
                # this wrapper, and a second peer would recurse.
                committed.append("from-the-peer")
                ScopeStore(JsonFileSubstrate(tmp_path)).ensure_scope(
                    "from-the-peer", "release"
                )
            return real_write(self, key, payload, expect=expect)

        monkeypatch.setattr(JsonFileSubstrate, "write", write_with_one_peer_commit)

        with store.batch():
            store.set_position("mine", "approve")

        assert committed == ["from-the-peer"], "the interleave never happened"
        assert store.get_scope("from-the-peer") is not None, (
            "the batch's exit write clobbered a scope committed while it was "
            "open — the write is no longer compare-and-swapped"
        )
        assert store.get_position("mine") == "approve", (
            "the batch's own mutation was lost while retrying"
        )


class TestConcurrency:
    def test_two_stores_over_one_path_merge_by_scope(self, tmp_path) -> None:
        """Last-writer-wins per scope, not per file (AC-16)."""
        a = ScopeStore(JsonFileSubstrate(tmp_path))
        b = ScopeStore(JsonFileSubstrate(tmp_path))
        a.ensure_scope("run-a", "release")
        b.ensure_scope("run-b", "deploy")
        a.set_position("run-a", "approve")
        b.set_position("run-b", "build")

        assert a.scope_ids() == ["run-a", "run-b"]
        assert a.get_position("run-a") == "approve"
        assert b.get_position("run-b") == "build"


class TestFailClosed:
    """The read never degrades to "no scopes" — the reason this class exists."""

    def test_reading_an_unreadable_store_raises(self, tmp_path) -> None:
        sub = JsonFileSubstrate(tmp_path)
        path = sub.path_for(SCOPES_KEY)
        path.write_text(json.dumps({"format_version": 99, "scopes": {"a": {}}}))
        store = ScopeStore(sub)
        with pytest.raises(ScopeStoreUnreadableError):
            store.scope_ids()
        with pytest.raises(ScopeStoreUnreadableError):
            store.get_scope("a")

    def test_writing_to_an_unreadable_store_raises(self, tmp_path) -> None:
        sub = JsonFileSubstrate(tmp_path)
        path = sub.path_for(SCOPES_KEY)
        payload = json.dumps({"format_version": 99, "scopes": {"a": {}}})
        path.write_text(payload)
        with pytest.raises(ScopeStoreUnreadableError):
            ScopeStore(sub).ensure_scope("b")
        assert path.read_text() == payload

    def test_clear_is_the_escape_hatch(self, tmp_path) -> None:
        sub = JsonFileSubstrate(tmp_path)
        path = sub.path_for(SCOPES_KEY)
        path.write_text(json.dumps({"format_version": 99, "scopes": {"a": {}}}))
        store = ScopeStore(sub)

        backup = store.clear()

        assert backup is not None and Path(backup).exists()
        assert store.scope_ids() == []

    def test_clear_returns_none_when_there_was_nothing(self, store: ScopeStore) -> None:
        assert store.clear() is None


class TestOnDiskShape:
    def test_envelope_is_two_keys(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "release")
        stored = store.substrate.read(SCOPES_KEY)
        assert stored is not None
        raw = stored.data
        assert set(raw) == {"format_version", "scopes"}
        assert raw["format_version"] == SCOPES_VERSION

    def test_scopes_stay_a_flat_mapping(self, store: ScopeStore) -> None:
        """The shape StateBackend's KV protocol addresses — the sqlite seam."""
        store.ensure_scope("s1")
        store.ensure_scope("s2")
        stored = store.substrate.read(SCOPES_KEY)
        assert stored is not None
        raw = stored.data
        assert sorted(raw["scopes"]) == ["s1", "s2"]
        assert all(isinstance(v, dict) for v in raw["scopes"].values())


class TestBatchIsPerThread:
    """A batch is a transaction for the thread that opened it, and no other.

    `_batch` was one attribute on the instance, which was correct while one run
    owned one store. `invoke_parallel` gives all 32 workers the same
    `WorkflowScope` — so one `ScopeStore`, one `_batch` — and `_mutate` folded
    *any* write on the instance into whatever batch happened to be open. A
    sibling thread's write joined another thread's transaction, returned
    successfully, and vanished when that transaction raised.

    Found by an external review of the AFTER state, which reproduced it as
    `clean batch exit : {"main": 1, "sibling": 2}` / `batch raises : {}`.

    **Retargeted by `scope-record-lifecycle`/T3.** This was written with
    `set_state`, because job state was then a section of the scope record and
    `ScopeStore.batch` covered both. T3 moved state to a per-scope file with its
    own lock, so a state write is no longer inside a *record* batch at all —
    the original assertions became claims about two unrelated files. The
    thread-locality property is unchanged and is what this still tests, now
    through `record_step`, which is a record write. The state store's own
    equivalent is
    `tests/primitives/test_scope_state_store.py::TestBatching`.
    """

    def _run(self, tmp_path: Path, raise_inside: bool) -> dict:
        import threading

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.ensure_scope("s")
        started, done = threading.Event(), threading.Event()

        def sibling() -> None:
            started.wait(5)
            store.record_step("s", "sibling", {"status": "completed"})
            done.set()

        thread = threading.Thread(target=sibling)
        thread.start()
        try:
            with store.batch():
                store.record_step("s", "main", {"status": "completed"})
                started.set()
                done.wait(5)
                if raise_inside:
                    raise RuntimeError("boom")
        except RuntimeError:
            pass
        thread.join(5)
        record = ScopeStore(store.substrate).get_scope("s") or {}
        return record.get("steps") or {}

    def test_both_writes_land_on_a_clean_exit(self, tmp_path: Path) -> None:
        assert sorted(self._run(tmp_path, raise_inside=False)) == ["main", "sibling"]

    def test_a_siblings_write_survives_another_threads_failed_batch(
        self, tmp_path: Path
    ) -> None:
        """The lost write. This is the assertion that was false."""
        assert sorted(self._run(tmp_path, raise_inside=True)) == ["sibling"]

    def test_the_batching_threads_own_writes_are_still_discarded(
        self, tmp_path: Path
    ) -> None:
        """All-or-nothing still holds *within* the thread that opened it.

        Without this, the fix could have been "never discard anything", which
        would break the walk's node-level atomicity.
        """
        assert "main" not in self._run(tmp_path, raise_inside=True)
