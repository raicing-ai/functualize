"""Tests for the persistent counter example."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent))

import persistent_counter
from functualize_state_sqlite import SQLiteStateBackend


def test_counter_persists_across_backend_instances(tmp_path, monkeypatch):
    db = tmp_path / "counter.db"
    monkeypatch.setattr(persistent_counter, "DB_PATH", db)

    rc = MagicMock()
    assert persistent_counter.bump(rc) == 1
    # New backend instance (fresh "process") still sees the stored value
    assert persistent_counter.bump(rc) == 2

    with SQLiteStateBackend(db_path=str(db)) as backend:
        assert backend.get("runs") == 2
