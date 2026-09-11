"""Tests for the runtime state store accessors (S3/T16, schema.md §1).

Covers every record type in the envelope: fingerprints, per-scope records
(steps/branches/gates/position/epilogue), the history ring buffer, and the
session precondition cache.
"""

from __future__ import annotations

import pytest

from functualize._primitives.fresh_format import (
    FRESH_FILENAME,
    load_fresh,
)
from functualize._primitives.fresh_store import FreshStore


@pytest.fixture
def store(tmp_path) -> FreshStore:
    return FreshStore(tmp_path / FRESH_FILENAME)


class TestConstruction:
    def test_for_project_resolves_beside_cache(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        store = FreshStore.for_project(tmp_path)
        assert store.path == tmp_path / ".functualize" / FRESH_FILENAME

    def test_reads_before_any_write(self, store: FreshStore) -> None:
        assert store.get_fingerprint("missing") is None
        assert store.scope_ids() == []


class TestFingerprints:
    def test_round_trip(self, store: FreshStore) -> None:
        record = {
            "sources": {"src/a.py": {"mtime": 1.0, "size": 10, "sha256": "ab"}},
            "generates": ["dist/a"],
            "return_value": None,
            "recorded_at": "2026-07-20T00:00:00",
            "job_version": "decl-hash",
        }
        store.put_fingerprint("build::h1::checksum", record)
        assert store.get_fingerprint("build::h1::checksum") == record

    def test_distinct_keys_are_independent(self, store: FreshStore) -> None:
        # Fix 1: --env dev and --env prod hash differently, so both persist.
        store.put_fingerprint("build::dev::checksum", {"n": 1})
        store.put_fingerprint("build::prod::checksum", {"n": 2})
        assert store.get_fingerprint("build::dev::checksum") == {"n": 1}
        assert store.get_fingerprint("build::prod::checksum") == {"n": 2}

    def test_delete(self, store: FreshStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.delete_fingerprint("k")
        assert store.get_fingerprint("k") is None

    def test_delete_missing_is_noop(self, store: FreshStore) -> None:
        store.delete_fingerprint("never-existed")

    def test_keys_filtered_by_prefix(self, store: FreshStore) -> None:
        store.put_fingerprint("build::a::checksum", {})
        store.put_fingerprint("test::b::checksum", {})
        assert store.fingerprint_keys("build::") == ["build::a::checksum"]


class TestScopeRecords:
    def test_ensure_scope_is_idempotent(self, store: FreshStore) -> None:
        store.ensure_scope("s1", workflow="deploy")
        store.ensure_scope("s1")
        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["workflow"] == "deploy"  # not clobbered by the second call

    def test_unknown_scope_reads_none(self, store: FreshStore) -> None:
        assert store.get_scope("nope") is None
        assert store.get_step("nope", "k") is None
        assert store.get_branch("nope", "src") is None
        assert store.get_gate("nope", "g") is None
        assert store.get_position("nope") is None
        assert store.get_epilogue("nope") is None

    def test_step_record_round_trip(self, store: FreshStore) -> None:
        record = {
            "status": "success",
            "return_value": {"artifact": "x"},
            "completed_at": "2026-07-20T00:00:00",
        }
        store.record_step("s1", "build::h1", record)
        assert store.get_step("s1", "build::h1") == record

    def test_steps_are_scoped(self, store: FreshStore) -> None:
        store.record_step("s1", "build::h1", {"status": "success"})
        assert store.get_step("s2", "build::h1") is None

    def test_status_transitions(self, store: FreshStore) -> None:
        store.ensure_scope("s1")
        store.set_scope_status("s1", "blocked")
        assert store.get_scope("s1")["status"] == "blocked"
        store.set_scope_status("s1", "completed")
        assert store.get_scope("s1")["status"] == "completed"

    def test_branch_choice_round_trip(self, store: FreshStore) -> None:
        store.record_branch("s1", "check", "deploy")
        assert store.get_branch("s1", "check") == "deploy"

    def test_epilogue_round_trip(self, store: FreshStore) -> None:
        store.record_epilogue("s1", {"status": "success", "return_value": 7})
        assert store.get_epilogue("s1")["return_value"] == 7

    def test_scope_ids_sorted(self, store: FreshStore) -> None:
        store.ensure_scope("b")
        store.ensure_scope("a")
        assert store.scope_ids() == ["a", "b"]


class TestGates:
    def test_gate_round_trip(self, store: FreshStore) -> None:
        record = {
            "model": "Approval",
            "input_schema": {"type": "object"},
            "payload": None,
            "blocked_at": "2026-07-20T00:00:00",
        }
        store.put_gate("s1", "approve", record)
        assert store.get_gate("s1", "approve") == record

    def test_deposit_payload(self, store: FreshStore) -> None:
        store.put_gate("s1", "approve", {"model": "Approval", "payload": None})
        assert store.deposit_gate_payload("s1", "approve", {"ok": True}) is True
        assert store.get_gate("s1", "approve")["payload"] == {"ok": True}

    def test_deposit_to_unknown_gate_reports_false(self, store: FreshStore) -> None:
        assert store.deposit_gate_payload("s1", "nope", {"ok": True}) is False

    def test_position_round_trip(self, store: FreshStore) -> None:
        store.set_position("s1", "approve")
        assert store.get_position("s1") == "approve"
        store.set_position("s1", None)
        assert store.get_position("s1") is None


class TestHistoryIsGone:
    """`durable-run-layer`/T3b removed the ring this class used to exercise.

    Not deleted silently: the ring held two kinds of record and they went to
    two different places. Job history is derived from the run log
    (`app/_run_view.job_history`), which recorded the same runs plus the nested
    ones plus who invoked them — the ring was a poorer copy of a subset. Shell
    history moved to `_primitives/shell_history.py`, because a command typed in
    shell mode was never a run and the log has nowhere to hold one.

    Asserted rather than assumed, because a store that quietly kept the methods
    would leave two writers for one fact, which is the drift the move removes.
    """

    def test_the_store_no_longer_records_history(self, store: FreshStore) -> None:
        assert not hasattr(store, "append_history")
        assert not hasattr(store, "get_history")


class TestSessionPreconditions:
    def test_unseen_is_none(self, store: FreshStore) -> None:
        assert store.get_precondition("docker --version") is None

    def test_round_trip_true_and_false(self, store: FreshStore) -> None:
        store.set_precondition("docker --version", True)
        store.set_precondition("nope --version", False)
        assert store.get_precondition("docker --version") is True
        assert store.get_precondition("nope --version") is False

    def test_clear_session_drops_cache(self, store: FreshStore) -> None:
        store.set_precondition("docker --version", True)
        store.clear_session()
        assert store.get_precondition("docker --version") is None

    def test_clear_session_keeps_fingerprints(self, store: FreshStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.set_precondition("p", True)
        store.clear_session()
        assert store.get_fingerprint("k") == {"n": 1}


class TestScopeBatch:
    """`batch()` is gone: nothing in src/ or plugins/ ever called it, while the
    module docstring told callers to. `scope_batch()` replaces it and the walk
    does call it."""

    def test_the_unused_whole_envelope_batch_is_gone(self, store: FreshStore) -> None:
        assert not hasattr(store, "batch")

    def test_scope_batch_writes_once_and_persists(self, store: FreshStore) -> None:
        with store.scope_batch():
            store.ensure_scope("s1", "release")
            store.set_position("s1", "approve")
        reloaded = FreshStore(store.path)
        assert reloaded.get_position("s1") == "approve"

    def test_reads_inside_batch_see_pending_writes(self, store: FreshStore) -> None:
        with store.scope_batch():
            store.record_branch("s1", "check", "deploy")
            assert store.get_branch("s1", "check") == "deploy"

    def test_nested_batch_reuses_outer(self, store: FreshStore) -> None:
        with store.scope_batch(), store.scope_batch():
            store.ensure_scope("s1")
        assert FreshStore(store.path).scope_ids() == ["s1"]

    def test_batch_preserves_existing_records(self, store: FreshStore) -> None:
        store.ensure_scope("pre")
        with store.scope_batch():
            store.ensure_scope("new")
        assert store.scope_ids() == ["new", "pre"]


class TestTwoFiles:
    """The split, from the façade's side: one store, two files, and nothing
    outside `_primitives` needs to know which is which."""

    def test_scope_file_is_the_state_file_sibling(self, store: FreshStore) -> None:
        assert store.scopes_path == store.path.with_name("scopes.json")

    def test_scopes_are_not_in_the_state_envelope(self, store: FreshStore) -> None:
        store.ensure_scope("s1", "release")
        assert "scopes" not in load_fresh(store.path)

    def test_a_state_version_bump_leaves_scopes_intact(self, store: FreshStore) -> None:
        """The defect this feature exists to remove, as a unit test. The
        end-to-end version lives in tests/test_state_split_regression.py."""
        import json

        store.ensure_scope("s1", "release")
        store.put_gate("s1", "approve", {"payload": {"approved_by": "sam"}})
        store.put_fingerprint("k", {"n": 1})

        raw = json.loads(store.path.read_text())
        raw["format_version"] = 999
        store.path.write_text(json.dumps(raw))
        store.put_fingerprint("other", {"n": 2})  # one unrelated write

        assert store.get_fingerprint("k") is None  # derived state: discarded
        gate = store.get_gate("s1", "approve")  # the record: survives
        assert gate is not None
        assert gate["payload"] == {"approved_by": "sam"}


class TestClear:
    def test_clear_resets_derived_state_but_keeps_scopes(
        self, store: FreshStore
    ) -> None:
        """Renamed from `test_clear_resets_everything`: "everything" stops
        including scopes, and the rename is what records that decision."""
        store.put_fingerprint("k", {"n": 1})
        store.ensure_scope("s1")
        store.set_precondition("p", True)

        assert store.clear() is None

        assert store.get_fingerprint("k") is None
        assert store.get_precondition("p") is None
        assert store.scope_ids() == ["s1"]

    def test_clear_with_scopes_discards_them(self, store: FreshStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.ensure_scope("s1")

        moved = store.clear(scopes=True)

        assert store.get_fingerprint("k") is None
        assert store.scope_ids() == []
        assert moved is not None and moved.exists()

    def test_discarded_scopes_are_moved_aside_not_deleted(
        self, store: FreshStore
    ) -> None:
        """A run discarded by mistake is still recoverable."""
        store.put_gate("s1", "approve", {"payload": {"approved_by": "sam"}})
        moved = store.clear(scopes=True)
        assert moved is not None
        import json

        assert json.loads(moved.read_text())["scopes"]["s1"]["gates"]["approve"][
            "payload"
        ] == {"approved_by": "sam"}

    def test_clear_returns_none_when_there_were_no_scopes(
        self, store: FreshStore
    ) -> None:
        assert store.clear(scopes=True) is None

    def test_clear_leaves_a_valid_envelope(self, store: FreshStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.clear()
        from functualize._primitives.fresh_format import empty_fresh

        assert load_fresh(store.path) == empty_fresh()
