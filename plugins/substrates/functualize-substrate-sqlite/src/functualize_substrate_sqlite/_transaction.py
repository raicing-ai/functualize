"""The buffered transaction: writers stage statements, ``__exit__`` sends one batch.

A transaction surrounds one short transition and nothing else. Writers issue
no SQL of their own: each call appends statements here, and the whole list is
applied as one `driver.batch()` when the ``with`` block exits cleanly — and
discarded, with nothing applied, when it raises. That single batch is why the
store declares ``cross_aggregate_atomicity=True`` (one ``BEGIN IMMEDIATE …
COMMIT`` locally) while needing no interactive transaction (AC-5).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from functualize.plugin import (
        EffectWriter,
        EventWriter,
        InputWriter,
        RunWriter,
        WorkflowWriter,
    )
    from functualize_substrate_sqlite._driver import SqlDriver, Statement

__all__ = ["BufferedTransaction", "NotYetImplemented"]


class NotYetImplemented:
    """A port member whose SQL lands in a later task; refuses every use loudly.

    Stands in so the store satisfies its port from the moment boot can select
    it, and so a call that arrives early raises rather than doing nothing.
    """

    def __init__(self, member: str, task: str) -> None:
        self._member = member
        self._task = task

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(
            f"SqliteRuntimeStore.{self._member}.{name} lands with {self._task}; "
            f"select the documents store until then."
        )


class BufferedTransaction:
    """The statements one transition stages, applied together or not at all."""

    def __init__(self) -> None:
        self._statements: list[Statement] = []
        # TRANSITIONAL(wave 2, tasks 8 and 9): the writers bind here; until then
        # each refuses with NotImplementedError rather than dropping a write.
        self.runs = cast("RunWriter", NotYetImplemented("transaction().runs", "task 9"))
        self.workflows = cast(
            "WorkflowWriter", NotYetImplemented("transaction().workflows", "task 8")
        )
        self.inputs = cast(
            "InputWriter", NotYetImplemented("transaction().inputs", "task 9")
        )
        self.events = cast(
            "EventWriter", NotYetImplemented("transaction().events", "task 9")
        )
        self.effects = cast(
            "EffectWriter", NotYetImplemented("transaction().effects", "task 9")
        )

    def stage(self, sql: str, parameters: Sequence[object] = ()) -> None:
        """Append one statement to this transition's batch. Issues nothing."""
        self._statements.append((sql, tuple(parameters)))

    def commit(self, driver: SqlDriver) -> None:
        """Send everything staged as one batch; an empty transaction sends nothing."""
        if self._statements:
            driver.batch(self._statements)
        self._statements = []
