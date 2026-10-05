"""`SqliteRuntimeStore`: the runtime store over the relational schema.

A facade and nothing more — the SQL lives beside it, split by job (writers in
`_workflow_sql.py` / `_run_sql.py`, readers in `_readers.py`), so no class
here grows past the 500-line limit. It owns the driver, hands out buffered
transactions, and declares what it can do in :data:`SQLITE_PROFILE`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from functualize.plugin import StoreProfile
from functualize_substrate_sqlite._transaction import (
    BufferedTransaction,
    NotYetImplemented,
)

if TYPE_CHECKING:
    from functualize.plugin import (
        InputReader,
        RunReader,
        RuntimeTransaction,
        WorkflowReader,
    )
    from functualize_substrate_sqlite._driver import SqlDriver

__all__ = ["SQLITE_PROFILE", "SqliteRuntimeStore"]

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

    def __init__(self, driver: SqlDriver) -> None:
        self._driver = driver
        # TRANSITIONAL(wave 3, task 10): the readers bind here; until then each
        # refuses with NotImplementedError rather than answering "nothing".
        self.runs = cast("RunReader", NotYetImplemented("runs", "task 10"))
        self.workflows = cast(
            "WorkflowReader", NotYetImplemented("workflows", "task 10")
        )
        self.inputs = cast("InputReader", NotYetImplemented("inputs", "task 10"))

    @property
    def driver(self) -> SqlDriver:
        return self._driver

    @contextmanager
    def transaction(self) -> Iterator[RuntimeTransaction]:
        """One transition: staged by the writers, one batch on a clean exit."""
        tx = BufferedTransaction()
        yield cast("RuntimeTransaction", tx)
        tx.commit(self._driver)

    def close(self) -> None:
        self._driver.close()
