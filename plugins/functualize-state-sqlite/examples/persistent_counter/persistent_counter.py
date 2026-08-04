"""Durable state: a run counter that survives process restarts.

Run twice and watch the count keep climbing:
    func persistent_counter.py bump
    func persistent_counter.py bump
"""

from pathlib import Path

from functualize_state_sqlite import SQLiteStateBackend

from functualize.job import RunContext

DB_PATH = Path(__file__).parent / "counter.db"


def bump(rc: RunContext) -> int:
    """Increment a counter stored durably in SQLite."""
    with SQLiteStateBackend(db_path=str(DB_PATH)) as backend:
        count = backend.get("runs", 0) + 1
        backend.set("runs", count)
        backend.set("last_run_note", f"run #{count}")
        rc.log(f"Persistent run count: {count}")
        rc.log(f"Keys stored: {backend.keys()}")
    return count
