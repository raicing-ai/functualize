"""Revision-6 feasibility experiment: widen runs.status to admit 'invalid' on a populated v5 db.

Run from the repository root:
    uv run --frozen python .spec/features/parameter-contract/matrix/rev6_experiment.py
Each recipe runs on a fresh copy of the same populated revision-5 database built by the
plugin's own migrate().
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._migrations import SHIPPED_MIGRATIONS, _CREATED, migrate

RUNS_V6 = """CREATE TABLE {name} (
    namespace_id  TEXT    NOT NULL REFERENCES namespaces (id),
    id            TEXT    NOT NULL,
    scope_id      TEXT,
    parent_run_id TEXT,
    job           TEXT    NOT NULL,
    surface       TEXT,
    status        TEXT    NOT NULL CHECK (status IN (
        'blocked', 'cancelled', 'failure', 'invalid', 'refused', 'running',
        'skipped', 'success', 'timeout', 'unknown')),
    args_hash     TEXT,
    invoke_depth  INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    PRIMARY KEY (namespace_id, id)
)"""
INDEXES = [
    "CREATE INDEX runs_recent ON runs (namespace_id, started_at DESC)",
    "CREATE INDEX runs_job    ON runs (job)",
    "CREATE INDEX runs_scope  ON runs (scope_id)",
    "CREATE INDEX runs_parent ON runs (parent_run_id)",
]
TRIGGER = """CREATE TRIGGER run_tags_fixed_on_delete BEFORE DELETE ON run_tags
WHEN EXISTS (
    SELECT 1 FROM runs WHERE namespace_id = OLD.namespace_id AND id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'run tags are fixed when the run opens');
END"""
COPY = "INSERT INTO {dst} SELECT namespace_id, id, scope_id, parent_run_id, job, surface, status, args_hash, invoke_depth, started_at, ended_at FROM {src}"


def build_v5(path: Path) -> None:
    d = LocalSqliteDriver(str(path))
    migrate(d)
    d.batch([
        ("INSERT INTO namespaces VALUES ('ns', 'project', 'now')", ()),
        ("INSERT INTO runs (namespace_id, id, job, status, started_at) VALUES ('ns','r1','j','success','t')", ()),
        ("INSERT INTO run_tags VALUES ('ns','r1','k','v')", ()),
        ("INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, status, started_at) VALUES ('a1','ns','r1',1,'succeeded','t')", ()),
        ("INSERT INTO run_events (namespace_id, run_id, seq, type, payload, occurred_at) VALUES ('ns','r1',1,'k','{}','t')", ()),
        ("INSERT INTO artifact_refs (id, namespace_id, run_id, kind, uri, created_at) VALUES ('f1','ns','r1','k','u','t')", ()),
    ])
    d.close()


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("runs", "run_attempts", "run_events", "artifact_refs", "run_tags")}


def probe(conn: sqlite3.Connection) -> dict[str, object]:
    out: dict[str, object] = {"rows": counts(conn)}
    out["fk_check"] = conn.execute("PRAGMA foreign_key_check").fetchall()
    out["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("INSERT INTO runs (namespace_id, id, job, status, started_at) VALUES ('ns','r2','j','invalid','t')")
        out["insert_invalid"] = "ok"
    except sqlite3.DatabaseError as e:
        out["insert_invalid"] = f"refused: {e}"
    try:
        conn.execute("UPDATE run_tags SET value='x'")
        out["run_tags_trigger"] = "NOT FIRED"
    except sqlite3.DatabaseError as e:
        out["run_tags_trigger"] = f"fires: {e}"
    conn.rollback()
    return out


def recipe(path: Path, name: str) -> None:
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        fk = "ON" if "FKs ON" in name else "OFF"
        conn.execute(f"PRAGMA foreign_keys={fk}")
        conn.execute("BEGIN IMMEDIATE")
        if not name.startswith("naive"):
            conn.execute("DROP TRIGGER run_tags_fixed_on_delete")
        conn.execute(RUNS_V6.format(name="runs_rebuild"))
        conn.execute(COPY.format(dst="runs_rebuild", src="runs"))
        conn.execute("DROP TABLE runs")
        conn.execute("ALTER TABLE runs_rebuild RENAME TO runs")
        for s_ in INDEXES:
            conn.execute(s_)
        if not name.startswith("naive"):
            conn.execute(TRIGGER)
        conn.execute("COMMIT")
        print(f"\n### {name}\n  applied")
        conn.execute("BEGIN")
        for k, v in probe(conn).items():
            print(f"  {k}: {v}")
    except sqlite3.DatabaseError as e:
        print(f"\n### {name}\n  FAILED during the recipe: {type(e).__name__}: {e}")
    finally:
        conn.close()


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    v5 = tmp / "v5.db"
    build_v5(v5)
    print("sqlite", sqlite3.sqlite_version, "· shipped revisions", [m.version for m in SHIPPED_MIGRATIONS])
    c = sqlite3.connect(v5)
    print("v5 rows:", counts(c))
    c.close()
    for name in ("naive rebuild, trigger left in place, FKs OFF",
                 "trigger-aware rebuild, FKs ON (as the runner applies a revision today)",
                 "trigger-aware rebuild, FKs OFF outside the batch (SQLite's 12-step procedure)"):
        db = tmp / "x.db"
        shutil.copy(v5, db)
        recipe(db, name)
    sql = "\n".join(["DROP TRIGGER run_tags_fixed_on_delete", RUNS_V6.format(name="runs_rebuild"), "DROP TABLE runs", "ALTER TABLE runs_rebuild RENAME TO runs", *INDEXES, TRIGGER])
    print("\n### the runner's partial-state check on this revision text")
    print("  _CREATED finds:", _CREATED.findall(sql), "— 'runs_rebuild' no longer exists after the rename,")
    print("  so _check_objects would refuse the NEXT boot unless it subtracts objects the same revision renames away")


if __name__ == "__main__":
    main()
