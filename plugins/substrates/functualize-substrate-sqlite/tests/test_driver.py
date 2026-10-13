"""`LocalSqliteDriver`: one batch is one atomic unit, and busy is a typed error."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from functualize_substrate_sqlite._driver import (
    LocalSqliteDriver,
    SqlDriver,
    SqliteBusyError,
)

_PARENT_CHILD = [
    ("CREATE TABLE parent (id INTEGER PRIMARY KEY)", ()),
    (
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES parent (id))",
        (),
    ),
]


def test_it_satisfies_the_driver_port(tmp_path: Path) -> None:
    assert isinstance(LocalSqliteDriver(tmp_path / "db.sqlite"), SqlDriver)


def test_a_foreign_key_violation_is_refused(tmp_path: Path) -> None:
    driver = LocalSqliteDriver(tmp_path / "db.sqlite")
    driver.batch(_PARENT_CHILD)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        driver.batch([("INSERT INTO child (id, parent_id) VALUES (1, 99)", ())])


def test_a_file_runs_in_wal_and_memory_does_not(tmp_path: Path) -> None:
    on_file = LocalSqliteDriver(tmp_path / "db.sqlite")
    in_memory = LocalSqliteDriver(":memory:")

    assert on_file.query("PRAGMA journal_mode") == [("wal",)]
    assert in_memory.query("PRAGMA journal_mode") == [("memory",)]


def test_a_failing_statement_rolls_the_whole_batch_back(tmp_path: Path) -> None:
    driver = LocalSqliteDriver(tmp_path / "db.sqlite")
    driver.batch(_PARENT_CHILD)

    with pytest.raises(sqlite3.IntegrityError):
        driver.batch(
            [
                ("INSERT INTO parent (id) VALUES (1)", ()),
                ("INSERT INTO parent (id) VALUES (2)", ()),
                ("INSERT INTO child (id, parent_id) VALUES (1, 99)", ()),
            ]
        )

    assert driver.query("SELECT count(*) FROM parent") == [(0,)]


def test_a_batch_reports_rows_affected_per_statement(tmp_path: Path) -> None:
    driver = LocalSqliteDriver(tmp_path / "db.sqlite")
    driver.batch(_PARENT_CHILD)

    counts = driver.batch(
        [
            ("INSERT INTO parent (id) VALUES (1)", ()),
            ("UPDATE parent SET id = 1 WHERE id = 42", ()),
        ]
    )

    assert counts == (1, 0)


def test_a_write_lock_held_past_the_timeout_is_a_busy_error(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    LocalSqliteDriver(path).batch(_PARENT_CHILD)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        driver = LocalSqliteDriver(path, busy_timeout_s=0.05)
        with pytest.raises(SqliteBusyError) as busy:
            driver.batch([("INSERT INTO parent (id) VALUES (1)", ())])
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert busy.value.retryable is True
    assert not isinstance(busy.value, sqlite3.OperationalError)
    assert driver.query("SELECT count(*) FROM parent") == [(0,)]


def test_close_closes_every_threads_connection(tmp_path: Path) -> None:
    driver = LocalSqliteDriver(tmp_path / "db.sqlite")

    def read() -> None:
        driver.query("SELECT 1")

    threads = [threading.Thread(target=read) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert driver.open_connections() == 4  # the constructor's, and one per thread

    driver.close()

    assert driver.open_connections() == 0
    with pytest.raises(sqlite3.ProgrammingError):
        driver.query("SELECT 1")


def test_an_unopenable_path_fails_at_construction(tmp_path: Path) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")

    with pytest.raises((sqlite3.Error, OSError)):
        LocalSqliteDriver(blocker / "db.sqlite")
