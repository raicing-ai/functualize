"""ScopeStore: the accessors, and the two behaviours that are new.

The accessors are a move — they behaved this way when they lived on
``FreshStore``, and `tests/test_state_store.py` keeps proving that through the
façade. What is new here is `batch()` and the fail-closed read reaching a
caller.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._primitives.fresh_format import FRESH_FILENAME
from functualize._primitives.scope_format import SCOPES_FILENAME, SCOPES_VERSION
from functualize._primitives.scope_store import ScopeStore
from functualize._types.errors import ScopeStoreUnreadableError


@pytest.fixture
def store(tmp_path) -> ScopeStore:
    return ScopeStore(tmp_path / SCOPES_FILENAME)


class TestLocation:
    def test_beside_state_finds_the_sibling(self, tmp_path) -> None:
        store = ScopeStore.beside_fresh(tmp_path / FRESH_FILENAME)
        assert store.path == tmp_path / SCOPES_FILENAME

    def test_for_project_resolves_like_the_state_file(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        assert (
            ScopeStore.for_project(tmp_path).path
            == tmp_path / ".functualize" / SCOPES_FILENAME
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
            # Added by capability-duality/T2: what a job stored through
            # `rc.state` is a record like the rest of these, and belongs in the
            # file whose rule is "refuse rather than discard".
            "state",
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
        import functualize._primitives.scope_store as module

        writes = []
        real = module.save_scopes
        monkeypatch.setattr(
            module,
            "save_scopes",
            lambda p, e: (writes.append(p), real(p, e))[1],
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


class TestConcurrency:
    def test_two_stores_over_one_path_merge_by_scope(self, tmp_path) -> None:
        """Last-writer-wins per scope, not per file (AC-16)."""
        a = ScopeStore(tmp_path / SCOPES_FILENAME)
        b = ScopeStore(tmp_path / SCOPES_FILENAME)
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
        path = tmp_path / SCOPES_FILENAME
        path.write_text(json.dumps({"format_version": 99, "scopes": {"a": {}}}))
        store = ScopeStore(path)
        with pytest.raises(ScopeStoreUnreadableError):
            store.scope_ids()
        with pytest.raises(ScopeStoreUnreadableError):
            store.get_scope("a")

    def test_writing_to_an_unreadable_store_raises(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        payload = json.dumps({"format_version": 99, "scopes": {"a": {}}})
        path.write_text(payload)
        with pytest.raises(ScopeStoreUnreadableError):
            ScopeStore(path).ensure_scope("b")
        assert path.read_text() == payload

    def test_clear_is_the_escape_hatch(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text(json.dumps({"format_version": 99, "scopes": {"a": {}}}))
        store = ScopeStore(path)

        backup = store.clear()

        assert backup is not None and backup.exists()
        assert store.scope_ids() == []

    def test_clear_returns_none_when_there_was_nothing(self, store: ScopeStore) -> None:
        assert store.clear() is None


class TestOnDiskShape:
    def test_envelope_is_two_keys(self, store: ScopeStore) -> None:
        store.ensure_scope("s1", "release")
        raw = json.loads(store.path.read_text())
        assert set(raw) == {"format_version", "scopes"}
        assert raw["format_version"] == SCOPES_VERSION

    def test_scopes_stay_a_flat_mapping(self, store: ScopeStore) -> None:
        """The shape StateBackend's KV protocol addresses — the sqlite seam."""
        store.ensure_scope("s1")
        store.ensure_scope("s2")
        raw = json.loads(store.path.read_text())
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

        store = ScopeStore(tmp_path / f"scopes-{raise_inside}.json")
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
        record = ScopeStore(store.path).get_scope("s") or {}
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
