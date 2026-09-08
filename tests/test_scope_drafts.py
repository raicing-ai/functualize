"""The gate draft slot — partial input that the walk cannot see.

A gate was all-or-nothing. `model(**payload)` raises on any missing required
field and nothing is stored on failure, so two actors could not fill different
fields of the same gate, and a typo in a deposited approval could only be fixed
by hand-editing `scopes.json`.

`draft` holds what has been supplied so far. The invariant that makes it safe:
**`payload` is only ever written by a complete, successful validation** — so a
partially-answered gate is indistinguishable, to the walk, from an unanswered
one, which is the correct meaning.

These tests cover the store half. The policy half — refusing to reopen a gate
the walk has already consumed — needs the graph and lives in the app layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._primitives.scope_format import SCOPES_FILENAME
from functualize._primitives.state_store import StateStore


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    (tmp_path / ".functualize").mkdir()
    s = StateStore.for_project(tmp_path)
    s.ensure_scope("rel-1", "release")
    s.put_gate("rel-1", "approve", {"model": "A", "input_schema": {}, "payload": None})
    return s


class TestTheDraftSlot:
    def test_a_gate_starts_with_no_draft(self, store: StateStore) -> None:
        assert store.get_gate_draft("rel-1", "approve") is None

    def test_values_round_trip(self, store: StateStore) -> None:
        assert store.put_gate_draft("rel-1", "approve", {"approved": True})
        draft = store.get_gate_draft("rel-1", "approve")
        assert draft is not None
        assert draft["values"] == {"approved": True}
        assert draft["updated_at"]

    def test_putting_replaces_rather_than_merges(self, store: StateStore) -> None:
        """Merging is the caller's decision. A store that merged silently would
        make `answer --replace` unimplementable."""
        store.put_gate_draft("rel-1", "approve", {"approved": True})
        store.put_gate_draft("rel-1", "approve", {"reason": "ok"})
        assert store.get_gate_draft("rel-1", "approve")["values"] == {"reason": "ok"}

    def test_clearing_removes_the_key(self, store: StateStore, tmp_path: Path) -> None:
        """Absent and "no draft" are the same fact; two spellings for it is how
        a reader ends up checking only one."""
        store.put_gate_draft("rel-1", "approve", {"approved": True})
        assert store.clear_gate_draft("rel-1", "approve")

        raw = json.loads((tmp_path / ".functualize" / SCOPES_FILENAME).read_text())
        assert "draft" not in raw["scopes"]["rel-1"]["gates"]["approve"]
        assert store.get_gate_draft("rel-1", "approve") is None

    def test_an_unknown_gate_is_false_not_a_crash(self, store: StateStore) -> None:
        assert store.put_gate_draft("rel-1", "nope", {"x": 1}) is False
        assert store.clear_gate_draft("rel-1", "nope") is False
        assert store.get_gate_draft("rel-1", "nope") is None
        assert store.get_gate_draft("nope", "approve") is None


class TestTheWalkCannotSeeADraft:
    def test_drafting_never_writes_the_payload(self, store: StateStore) -> None:
        """The whole invariant, as one assertion. A blocked walk stays blocked
        until the draft validates whole."""
        store.put_gate_draft("rel-1", "approve", {"approved": True})
        assert store.get_gate("rel-1", "approve")["payload"] is None


class TestReopen:
    def test_it_moves_the_payload_back_into_the_draft(self, store: StateStore) -> None:
        store.deposit_gate_payload("rel-1", "approve", {"approved": True})

        assert store.reopen_gate("rel-1", "approve")

        assert store.get_gate("rel-1", "approve")["payload"] is None
        assert store.get_gate_draft("rel-1", "approve")["values"] == {"approved": True}

    def test_reopening_an_unanswered_gate_is_false(self, store: StateStore) -> None:
        assert store.reopen_gate("rel-1", "approve") is False

    def test_reopening_an_unknown_gate_is_false(self, store: StateStore) -> None:
        assert store.reopen_gate("rel-1", "nope") is False

    def test_the_store_applies_no_policy(self, store: StateStore) -> None:
        """Whether reopening is *allowed* depends on the walk position, which
        needs the graph. The store moves; the app layer judges."""
        store.set_position("rel-1", "deploy")  # well past the gate
        store.deposit_gate_payload("rel-1", "approve", {"approved": True})

        assert store.reopen_gate("rel-1", "approve") is True


class TestDeleteScope:
    def test_it_removes_the_scope(self, store: StateStore) -> None:
        assert store.delete_scope("rel-1")
        assert store.scope_ids() == []

    def test_deleting_an_absent_scope_is_false(self, store: StateStore) -> None:
        assert store.delete_scope("nope") is False

    def test_it_is_a_hard_delete_with_no_backup(
        self, store: StateStore, tmp_path: Path
    ) -> None:
        """Unlike `clear`, which moves the whole file aside. That is why the
        only caller — `purge` — refuses live scopes."""
        store.delete_scope("rel-1")
        raw = json.loads((tmp_path / ".functualize" / SCOPES_FILENAME).read_text())
        assert raw["scopes"] == {}
        assert not list((tmp_path / ".functualize").glob("*.bak*"))


class TestTheFormatVersionIsUnchanged:
    def test_adding_a_draft_does_not_bump_the_version(
        self, store: StateStore, tmp_path: Path
    ) -> None:
        """`draft` is additive and its absence means "no draft", so every
        existing file is still readable and no bump is warranted."""
        from functualize._primitives.scope_format import SCOPES_VERSION

        store.put_gate_draft("rel-1", "approve", {"approved": True})
        raw = json.loads((tmp_path / ".functualize" / SCOPES_FILENAME).read_text())
        assert raw["format_version"] == SCOPES_VERSION

    def test_a_gate_written_before_drafts_existed_still_reads(
        self, store: StateStore
    ) -> None:
        store.put_gate("rel-1", "legacy", {"model": "A", "payload": None})
        assert store.get_gate_draft("rel-1", "legacy") is None
