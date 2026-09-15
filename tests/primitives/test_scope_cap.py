"""`scopes.json` is bounded, and the bound cannot evict a live run.

`scope-record-lifecycle`/T2, AC-2. `scopes.json` was the only one of the three
stores with no cap — `state_format` has `HISTORY_LIMIT = 200` and `run_format`
has `RUNS_LIMIT = 500`. It reached 2,188 records on a real project, at 58 ms per
state write.

The half that needs the most care is the refusal: a workflow parked at a gate
must survive **any** amount of unrelated traffic. Evicting it spends a human's
approval on a run that no longer exists, which is the failure durable state
exists to prevent. So an over-cap file holding nothing finished stays over cap.
"""

from __future__ import annotations

from pathlib import Path

from functualize._primitives.scope_format import (
    SCOPES_KEY,
    SCOPES_LIMIT,
    TERMINAL_SCOPE_STATUSES,
    normalize_scopes,
    stamp_scopes,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate


def _envelope(records: dict[str, str]) -> dict[str, object]:
    """An envelope of `{scope_id: status}`, in the order given."""
    return {"scopes": {sid: {"status": status} for sid, status in records.items()}}


def _write(substrate: JsonFileSubstrate, records: dict[str, str]) -> dict[str, object]:
    substrate.write(SCOPES_KEY, stamp_scopes(_envelope(records)))
    stored = substrate.read(SCOPES_KEY)
    assert stored is not None
    return normalize_scopes(stored.data, where=substrate.describe(SCOPES_KEY))


class TestTheCapBounds:
    def test_a_file_under_the_cap_is_untouched(self, tmp_path: Path) -> None:
        path = JsonFileSubstrate(tmp_path)
        records = {f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT)}
        assert len(_write(path, records)["scopes"]) == SCOPES_LIMIT

    def test_going_over_evicts_down_to_the_cap(self, tmp_path: Path) -> None:
        path = JsonFileSubstrate(tmp_path)
        records = {f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT + 50)}
        assert len(_write(path, records)["scopes"]) == SCOPES_LIMIT

    def test_the_oldest_go_first(self, tmp_path: Path) -> None:
        """Oldest is insertion order — scope ids do not sort chronologically.

        Run ids are ULIDs and sort by time; a scope id is `<job>-<hex8>` and
        does not. Dict order is the creation order, and JSON preserves it.
        """
        path = JsonFileSubstrate(tmp_path)
        records = {f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT + 10)}
        kept = _write(path, records)["scopes"]

        assert "done-0000" not in kept
        assert "done-0009" not in kept
        assert "done-0010" in kept
        assert f"done-{SCOPES_LIMIT + 9:04d}" in kept


class TestALiveScopeIsNeverEvicted:
    """The half that makes the cap safe. AC-2 states it as a requirement."""

    def test_a_blocked_scope_survives_the_cap_being_exceeded(
        self, tmp_path: Path
    ) -> None:
        """One parked workflow, buried under twice the cap in finished runs."""
        path = JsonFileSubstrate(tmp_path)
        records: dict[str, str] = {"parked": "blocked"}
        records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT * 2)})

        kept = _write(path, records)["scopes"]

        assert "parked" in kept, (
            "a workflow blocked at a gate was evicted by unrelated traffic — "
            "its resume point and any deposited approval are gone"
        )
        assert len(kept) == SCOPES_LIMIT

    def test_a_running_scope_survives_too(self, tmp_path: Path) -> None:
        """`running` is live as well — a run in flight is not a candidate."""
        path = JsonFileSubstrate(tmp_path)
        records: dict[str, str] = {"inflight": "running"}
        records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT + 5)})

        assert "inflight" in _write(path, records)["scopes"]

    def test_an_all_live_file_stays_over_the_cap(self, tmp_path: Path) -> None:
        """The deliberate non-guarantee, asserted so nobody "fixes" it.

        A file over the cap holding nothing finished stays over the cap. The
        alternative — evicting something live to satisfy a number — is the
        failure this whole feature exists to prevent.
        """
        path = JsonFileSubstrate(tmp_path)
        over = SCOPES_LIMIT + 25
        records = {f"live-{i:04d}": "blocked" for i in range(over)}

        assert len(_write(path, records)["scopes"]) == over

    def test_only_finished_statuses_are_evictable(self, tmp_path: Path) -> None:
        """Pins the vocabulary rather than trusting the constant's name.

        `_primitives` cannot import `app._workflow_view.TERMINAL_STATES`, so
        the two are written separately and could drift. This asserts each
        status this module calls terminal really is evicted, and that the two
        live ones really are not.
        """
        for status in sorted(TERMINAL_SCOPE_STATUSES):
            path = JsonFileSubstrate(tmp_path / status)
            records = {"candidate": status}
            records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT)})
            assert "candidate" not in _write(path, records)["scopes"], (
                f"{status!r} is in TERMINAL_SCOPE_STATUSES but was not evicted"
            )

        for status in ("running", "blocked"):
            path = JsonFileSubstrate(tmp_path / status)
            records = {"candidate": status}
            records.update({f"done-{i:04d}": "completed" for i in range(SCOPES_LIMIT)})
            assert "candidate" in _write(path, records)["scopes"], (
                f"{status!r} is live and must never be evicted"
            )


class TestTheCapAppliesThroughTheStore:
    """Not just the format helper — the object everything actually uses."""

    def test_writing_through_scopestore_trims(self, tmp_path: Path) -> None:
        path = JsonFileSubstrate(tmp_path)
        store = ScopeStore(path)
        with store.batch():
            for i in range(SCOPES_LIMIT + 20):
                store.ensure_scope(f"done-{i:04d}")
                store.set_scope_status(f"done-{i:04d}", "completed")

        stored = path.read(SCOPES_KEY)
        assert stored is not None
        on_disk = stored.data["scopes"]
        assert len(on_disk) == SCOPES_LIMIT
