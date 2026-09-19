"""Tests for the persistent counter example."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

import persistent_counter  # noqa: E402
from functualize_substrate_sqlite import SQLiteSubstrate  # noqa: E402


def test_counter_persists_across_substrate_instances(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The point of the example: a *new* substrate object — a fresh "process" —
    reads what the last one wrote."""
    db = tmp_path / "counter.db"
    monkeypatch.setattr(persistent_counter, "DB_PATH", db)

    rc = MagicMock()
    assert persistent_counter.bump(rc) == 1
    assert persistent_counter.bump(rc) == 2

    stored = SQLiteSubstrate(db).read(persistent_counter.KEY)
    assert stored is not None
    assert stored.data["runs"] == 2
    assert stored.data["last_run_note"] == "run #2"


def test_the_revision_moves_with_every_write(tmp_path: Path, monkeypatch: Any) -> None:
    """What makes the read-modify-write safe, asserted rather than assumed.

    If the revision did not change, `expect=` would accept a stale write and the
    example would be teaching a race.
    """
    db = tmp_path / "counter.db"
    monkeypatch.setattr(persistent_counter, "DB_PATH", db)
    substrate = SQLiteSubstrate(db)

    persistent_counter.bump(MagicMock())
    first = substrate.read(persistent_counter.KEY)
    persistent_counter.bump(MagicMock())
    second = substrate.read(persistent_counter.KEY)

    assert first is not None and second is not None
    assert second.revision != first.revision


def test_a_stale_write_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    """The refusal the retry loop exists to handle — an ordinary outcome, not an
    error, which is why `write` returns a bool."""
    db = tmp_path / "counter.db"
    monkeypatch.setattr(persistent_counter, "DB_PATH", db)
    substrate = SQLiteSubstrate(db)

    persistent_counter.bump(MagicMock())
    stale = substrate.read(persistent_counter.KEY)
    assert stale is not None

    persistent_counter.bump(MagicMock())  # somebody else counts

    assert (
        substrate.write(persistent_counter.KEY, {"runs": 99}, expect=stale.revision)
        is False
    )
