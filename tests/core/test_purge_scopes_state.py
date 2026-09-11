"""Purging a scope takes its state file with it.

`scope-record-lifecycle`/T5, AC-5. T3 moved a run's job state out of the scope
record and into its own file. That fixed the cost and created a new way to
leak: `purge_scopes` walks **records**, so a state file whose record is gone is
invisible to the only thing that could ever remove it.

The ordering is asserted, not just the outcome. Record first, state second: a
record pointing at state that is already gone reads as corruption, while a
state file with no record reads as nothing at all. If the process dies between
the two, this order leaves the recoverable half.
"""

from __future__ import annotations

from pathlib import Path

from functualize._primitives.scope_state_store import scope_state_dir, scope_state_path
from functualize._primitives.scope_store import ScopeStore
from functualize.app._workflow_control import purge_scopes


def _finished_scope(store: ScopeStore, scope_id: str) -> None:
    """A scope that stored something and then finished."""
    store.set_state(scope_id, "payload", {"rows": 12})
    store.set_scope_status(scope_id, "completed")


class TestPurgeRemovesBothHalves:
    def test_the_state_file_goes_with_the_record(self, tmp_path: Path) -> None:
        scopes = tmp_path / "scopes.json"
        store = ScopeStore(scopes)
        _finished_scope(store, "done")
        assert scope_state_path(scopes, "done").exists()

        report = purge_scopes(store)

        assert report["removed"] == ["done"]
        assert store.get_scope("done") is None
        assert not scope_state_path(scopes, "done").exists(), (
            "the record was purged but its state file survives — nothing "
            "walks state files, so it can never be collected"
        )

    def test_purging_leaves_no_orphans_at_all(self, tmp_path: Path) -> None:
        """The property, over several scopes rather than one.

        A per-scope check can pass while a loop that purges the *last* record
        only cleans up one file.
        """
        scopes = tmp_path / "scopes.json"
        store = ScopeStore(scopes)
        for i in range(5):
            _finished_scope(store, f"done-{i}")

        purge_scopes(store)

        leftovers = sorted(p.name for p in scope_state_dir(scopes).glob("*.json"))
        assert leftovers == [], f"orphaned state files: {leftovers}"


class TestALiveScopeKeepsItsState:
    """AC-5's other half: purge must leave in-flight runs alone, both halves."""

    def test_a_running_scope_keeps_record_and_state(self, tmp_path: Path) -> None:
        scopes = tmp_path / "scopes.json"
        store = ScopeStore(scopes)
        store.set_state("live", "progress", "half")
        store.set_scope_status("live", "running")
        _finished_scope(store, "done")

        report = purge_scopes(store)

        assert report["removed"] == ["done"]
        assert store.get_scope("live") is not None
        assert store.get_state("live", "progress") == "half", (
            "a running scope lost its state to a purge aimed at finished ones"
        )

    def test_a_blocked_scope_keeps_its_deposited_state(self, tmp_path: Path) -> None:
        """The case the whole feature is careful about.

        A workflow parked at a gate is the record that must survive, and its
        state is what a human's approval is spent on.
        """
        scopes = tmp_path / "scopes.json"
        store = ScopeStore(scopes)
        store.set_state("parked", "approved_by", "a-human")
        store.set_scope_status("parked", "blocked")

        purge_scopes(store)

        assert store.get_state("parked", "approved_by") == "a-human"
        assert scope_state_path(scopes, "parked").exists()


class TestPurgeIsStillSelective:
    def test_a_state_filter_still_applies(self, tmp_path: Path) -> None:
        """The state file follows whichever records the filter chose.

        Guards against the fix deleting every state file rather than the ones
        belonging to purged records.
        """
        scopes = tmp_path / "scopes.json"
        store = ScopeStore(scopes)
        _finished_scope(store, "ok")
        store.set_state("bad", "why", "crashed")
        store.set_scope_status("bad", "failed")

        report = purge_scopes(store, state="failed")

        assert report["removed"] == ["bad"]
        assert not scope_state_path(scopes, "bad").exists()
        assert scope_state_path(scopes, "ok").exists(), (
            "a scope the filter did not select lost its state file"
        )
