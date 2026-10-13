"""Harness hooks — how the suite observes what the port cannot.

Some capabilities cannot be observed through the port. ``durable_outbox`` has
a writer and no reader, ``versioned_migrations`` has no schema API, and
atomicity at the port can only fault *between* commands — a store that writes
its statements one after another passes the same check. The hooks give the
**suite** a way in: the backend's own test code hands the suite instruments
that build faulted stores, read committed intents and lay down historical
schemas. They are **not** port surface — ``functualize._types.persistence``
and ``functualize.plugin`` do not change (contracts §4a).

Everything here is a value or a ``Protocol``; nothing imports a test
framework, because a third-party backend runs the suite from whatever harness
it already has.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize.plugin import RuntimeStore

__all__ = [
    "CapabilityReport",
    "HarnessHooks",
    "MigrationHarness",
    "OutboxProbe",
    "RecordedIntent",
    "StatementFault",
    "StatementFaults",
    "TierRun",
]


class StatementFault(Exception):  # noqa: N818 — the name is the frozen contract (§4a)
    """Raised by a :class:`StatementFaults` hook inside a commit; the tier
    catches exactly this."""


@runtime_checkable
class StatementFaults(Protocol):
    """Builds stores whose atomic unit dies mid-flight, statement by statement."""

    def make_store(self, root: Path, fault_at: int | None) -> RuntimeStore:
        """A store over ``root``. Each commit raises :class:`StatementFault`
        immediately before statement ``fault_at`` (0-based) of its atomic
        unit, after the first ``fault_at`` statements have executed *inside*
        that unit; ``None`` = never. A unit with ≤ ``fault_at`` statements
        commits normally — that is how the tier learns the unit's length."""
        ...


@dataclass(frozen=True)
class RecordedIntent:
    """One committed, unpublished outbox intent, as a fresh handle reads it."""

    namespace: str
    topic: str
    payload: Any
    idempotency_key: str | None


@runtime_checkable
class OutboxProbe(Protocol):
    """Reads the outbox the way the dispatcher's restart will: cold."""

    def pending(self, root: Path) -> Sequence[RecordedIntent]:
        """Committed, unpublished intents of the store over ``root``, in
        commit order, read through a fresh handle — never through a store
        object a crashed process held."""
        ...


@runtime_checkable
class MigrationHarness(Protocol):
    """Lays down the schemas and the damage the migration tier needs."""

    #: The version a fully migrated store reports.
    latest_version: int
    #: schemas :meth:`lay_down` can produce; non-empty.
    historical: Sequence[str]
    #: damage :meth:`damage` can do; ⊇ ``{"checksum", "ahead"}``, ⊇
    #: ``{"gap"}`` once ``latest_version`` ≥ 2.
    refusals: Sequence[str]

    def lay_down(self, root: Path, schema: str) -> None: ...

    def damage(self, root: Path, refusal: str) -> None:
        """Damage the current-version store at ``root`` so the next open must
        refuse."""
        ...

    def version(self, root: Path) -> int: ...


@dataclass(frozen=True)
class HarnessHooks:
    """The instruments a backend's test code hands the suite; any may be
    absent, and a tier that needs an absent one refuses rather than skips."""

    statement_faults: StatementFaults | None = None
    outbox: OutboxProbe | None = None
    migrations: MigrationHarness | None = None


@dataclass(frozen=True)
class TierRun:
    """One tier that ran, and what it actually exercised."""

    name: str
    #: What was exercised, stated honestly — e.g. ``"statement faults at 7
    #: positions"`` — so a reader can tell a strong pass from a weak one.
    strength: str


@dataclass(frozen=True)
class CapabilityReport:
    """Every tier the profile switched on, with the strength of each run."""

    runs: tuple[TierRun, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(run.name for run in self.runs)
