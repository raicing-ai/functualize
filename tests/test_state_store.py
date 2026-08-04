"""Tests for the runtime state store accessors (S3/T16, schema.md §1).

Covers every record type in the envelope: fingerprints, per-scope records
(steps/branches/gates/position/epilogue), the history ring buffer, and the
session precondition cache.
"""

from __future__ import annotations

import pytest

from functualize._primitives.state_format import (
    HISTORY_LIMIT,
    STATE_FILENAME,
    load_state,
)
from functualize._primitives.state_store import StateStore


@pytest.fixture
def store(tmp_path) -> StateStore:
    return StateStore(tmp_path / STATE_FILENAME)


class TestConstruction:
    def test_for_project_resolves_beside_cache(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        store = StateStore.for_project(tmp_path)
        assert store.path == tmp_path / ".functualize" / STATE_FILENAME

    def test_reads_before_any_write(self, store: StateStore) -> None:
        assert store.get_fingerprint("missing") is None
        assert store.get_history() == []
        assert store.scope_ids() == []


class TestFingerprints:
    def test_round_trip(self, store: StateStore) -> None:
        record = {
            "sources": {"src/a.py": {"mtime": 1.0, "size": 10, "sha256": "ab"}},
            "generates": ["dist/a"],
            "return_value": None,
            "recorded_at": "2026-07-20T00:00:00",
            "job_version": "decl-hash",
        }
        store.put_fingerprint("build::h1::checksum", record)
        assert store.get_fingerprint("build::h1::checksum") == record

    def test_distinct_keys_are_independent(self, store: StateStore) -> None:
        # Fix 1: --env dev and --env prod hash differently, so both persist.
        store.put_fingerprint("build::dev::checksum", {"n": 1})
        store.put_fingerprint("build::prod::checksum", {"n": 2})
        assert store.get_fingerprint("build::dev::checksum") == {"n": 1}
        assert store.get_fingerprint("build::prod::checksum") == {"n": 2}

    def test_delete(self, store: StateStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.delete_fingerprint("k")
        assert store.get_fingerprint("k") is None

    def test_delete_missing_is_noop(self, store: StateStore) -> None:
        store.delete_fingerprint("never-existed")

    def test_keys_filtered_by_prefix(self, store: StateStore) -> None:
        store.put_fingerprint("build::a::checksum", {})
        store.put_fingerprint("test::b::checksum", {})
        assert store.fingerprint_keys("build::") == ["build::a::checksum"]


class TestScopeRecords:
    def test_ensure_scope_is_idempotent(self, store: StateStore) -> None:
        store.ensure_scope("s1", workflow="deploy")
        store.ensure_scope("s1")
        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["workflow"] == "deploy"  # not clobbered by the second call

    def test_unknown_scope_reads_none(self, store: StateStore) -> None:
        assert store.get_scope("nope") is None
        assert store.get_step("nope", "k") is None
        assert store.get_branch("nope", "src") is None
        assert store.get_gate("nope", "g") is None
        assert store.get_position("nope") is None
        assert store.get_epilogue("nope") is None

    def test_step_record_round_trip(self, store: StateStore) -> None:
        record = {
            "status": "success",
            "return_value": {"artifact": "x"},
            "completed_at": "2026-07-20T00:00:00",
        }
        store.record_step("s1", "build::h1", record)
        assert store.get_step("s1", "build::h1") == record

    def test_steps_are_scoped(self, store: StateStore) -> None:
        store.record_step("s1", "build::h1", {"status": "success"})
        assert store.get_step("s2", "build::h1") is None

    def test_status_transitions(self, store: StateStore) -> None:
        store.ensure_scope("s1")
        store.set_scope_status("s1", "blocked")
        assert store.get_scope("s1")["status"] == "blocked"
        store.set_scope_status("s1", "completed")
        assert store.get_scope("s1")["status"] == "completed"

    def test_branch_choice_round_trip(self, store: StateStore) -> None:
        store.record_branch("s1", "check", "deploy")
        assert store.get_branch("s1", "check") == "deploy"

    def test_epilogue_round_trip(self, store: StateStore) -> None:
        store.record_epilogue("s1", {"status": "success", "return_value": 7})
        assert store.get_epilogue("s1")["return_value"] == 7

    def test_scope_ids_sorted(self, store: StateStore) -> None:
        store.ensure_scope("b")
        store.ensure_scope("a")
        assert store.scope_ids() == ["a", "b"]


class TestGates:
    def test_gate_round_trip(self, store: StateStore) -> None:
        record = {
            "model": "Approval",
            "input_schema": {"type": "object"},
            "payload": None,
            "blocked_at": "2026-07-20T00:00:00",
        }
        store.put_gate("s1", "approve", record)
        assert store.get_gate("s1", "approve") == record

    def test_deposit_payload(self, store: StateStore) -> None:
        store.put_gate("s1", "approve", {"model": "Approval", "payload": None})
        assert store.deposit_gate_payload("s1", "approve", {"ok": True}) is True
        assert store.get_gate("s1", "approve")["payload"] == {"ok": True}

    def test_deposit_to_unknown_gate_reports_false(self, store: StateStore) -> None:
        assert store.deposit_gate_payload("s1", "nope", {"ok": True}) is False

    def test_position_round_trip(self, store: StateStore) -> None:
        store.set_position("s1", "approve")
        assert store.get_position("s1") == "approve"
        store.set_position("s1", None)
        assert store.get_position("s1") is None


class TestHistory:
    def test_append_and_read_newest_first(self, store: StateStore) -> None:
        store.append_history({"job": "a"})
        store.append_history({"job": "b"})
        assert [r["job"] for r in store.get_history()] == ["b", "a"]

    def test_limit(self, store: StateStore) -> None:
        for i in range(5):
            store.append_history({"job": str(i)})
        assert len(store.get_history(limit=2)) == 2

    def test_ring_buffer_bounds(self, store: StateStore) -> None:
        with store.batch():
            for i in range(HISTORY_LIMIT + 10):
                store.append_history({"job": str(i)})
        history = store.get_history()
        assert len(history) == HISTORY_LIMIT
        # Oldest entries dropped; newest retained.
        assert history[0]["job"] == str(HISTORY_LIMIT + 9)


class TestSessionPreconditions:
    def test_unseen_is_none(self, store: StateStore) -> None:
        assert store.get_precondition("docker --version") is None

    def test_round_trip_true_and_false(self, store: StateStore) -> None:
        store.set_precondition("docker --version", True)
        store.set_precondition("nope --version", False)
        assert store.get_precondition("docker --version") is True
        assert store.get_precondition("nope --version") is False

    def test_clear_session_drops_cache(self, store: StateStore) -> None:
        store.set_precondition("docker --version", True)
        store.clear_session()
        assert store.get_precondition("docker --version") is None

    def test_clear_session_keeps_fingerprints(self, store: StateStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.set_precondition("p", True)
        store.clear_session()
        assert store.get_fingerprint("k") == {"n": 1}


class TestBatch:
    def test_batch_writes_once_and_persists(self, store: StateStore) -> None:
        with store.batch():
            store.put_fingerprint("a", {"n": 1})
            store.put_fingerprint("b", {"n": 2})
        reloaded = StateStore(store.path)
        assert reloaded.get_fingerprint("a") == {"n": 1}
        assert reloaded.get_fingerprint("b") == {"n": 2}

    def test_reads_inside_batch_see_pending_writes(self, store: StateStore) -> None:
        with store.batch():
            store.put_fingerprint("a", {"n": 1})
            assert store.get_fingerprint("a") == {"n": 1}

    def test_nested_batch_reuses_outer(self, store: StateStore) -> None:
        with store.batch(), store.batch():
            store.put_fingerprint("a", {"n": 1})
        assert StateStore(store.path).get_fingerprint("a") == {"n": 1}

    def test_batch_preserves_existing_records(self, store: StateStore) -> None:
        store.put_fingerprint("pre", {"n": 0})
        with store.batch():
            store.put_fingerprint("new", {"n": 1})
        assert store.get_fingerprint("pre") == {"n": 0}


class TestClear:
    def test_clear_resets_everything(self, store: StateStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.ensure_scope("s1")
        store.append_history({"job": "a"})
        store.set_precondition("p", True)
        store.clear()
        assert store.get_fingerprint("k") is None
        assert store.scope_ids() == []
        assert store.get_history() == []
        assert store.get_precondition("p") is None

    def test_clear_leaves_a_valid_envelope(self, store: StateStore) -> None:
        store.put_fingerprint("k", {"n": 1})
        store.clear()
        from functualize._primitives.state_format import empty_state

        assert load_state(store.path) == empty_state()
