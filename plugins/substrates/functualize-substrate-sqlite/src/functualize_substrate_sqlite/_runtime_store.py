"""`SqliteRuntimeStore`: the runtime store over the relational schema.

A facade and nothing more — the SQL lives beside it, split by job (writers in
`_workflow_sql.py` / `_run_sql.py`, readers in `_readers.py`), so no class
here grows past the 500-line limit. It owns the driver, hands out buffered
transactions, and declares what it can do in :data:`SQLITE_PROFILE`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from functualize.plugin import StoreProfile
from functualize_substrate_sqlite._readers import (
    SqlInputReader,
    SqlRunReader,
    SqlWorkflowReader,
)
from functualize_substrate_sqlite._transaction import (
    BufferedTransaction,
    iso,
)

if TYPE_CHECKING:
    from functualize.plugin import (
        InputReader,
        RunReader,
        RuntimeTransaction,
        WorkflowReader,
    )
    from functualize_substrate_sqlite._driver import SqlDriver

__all__ = ["DEFAULT_NAMESPACE", "SQLITE_PROFILE", "SqliteRuntimeStore"]

#: One database file holds one project, so its rows share one namespace. Two
#: processes in two directories that point at the same file are the same
#: project — the cross-process case the file exists for — and must not be
#: split by where they were started. The table is there for a network store
#: (FUN-22) that serves many projects from one database.
DEFAULT_NAMESPACE = "default"

#: `spec.md` §1, *The SQLite profile*. Each value is a promise this store keeps,
#: under-declared and never over-declared.
SQLITE_PROFILE = StoreProfile(
    name="sqlite",
    cross_aggregate_atomicity=True,
    fencing="cross-process",
    multi_process=True,
    multi_machine=False,
    durable_outbox=True,
    versioned_migrations=True,
    interactive_transaction=False,
    remote=False,
    max_document_bytes=None,
    offline_capable=True,
    description=(
        "Relational tables in one local SQLite file: WAL, a bounded busy "
        "timeout, every transition one batch. One machine only."
    ),
)


class SqliteRuntimeStore:
    """The selected runtime store when ``runtime_store.url`` names ``sqlite``."""

    profile: StoreProfile = SQLITE_PROFILE

    def __init__(self, driver: SqlDriver, namespace: str = DEFAULT_NAMESPACE) -> None:
        self._driver = driver
        self._namespace = namespace
        # Every runtime row references its namespace; the row is the store's.
        driver.batch(
            [
                (
                    "INSERT INTO namespaces (id, project_key, created_at) "
                    "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    (namespace, namespace, iso(datetime.now(UTC))),
                )
            ]
        )
        self.runs: RunReader = SqlRunReader(driver, namespace)
        self.workflows: WorkflowReader = SqlWorkflowReader(driver, namespace)
        self.inputs: InputReader = SqlInputReader(driver, namespace)

    @property
    def driver(self) -> SqlDriver:
        return self._driver

    @contextmanager
    def transaction(self) -> Iterator[RuntimeTransaction]:
        """One transition: staged by the writers, one batch on a clean exit."""
        tx = BufferedTransaction(self._driver, self._namespace)
        yield tx
        tx.commit(self._driver)

    def close(self) -> None:
        self._driver.close()
