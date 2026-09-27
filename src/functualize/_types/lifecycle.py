"""The four runtime state machines, as data.

`runtime-schema-migrations`/T1, from `schema.md` §1. The relational writer
(`sqlite-runtime-provider`) generates its `CHECK (status IN (...))` clauses from
these state sets, the transition check (T4, `_primitives/transitions.py`) reads
the tables, and the retention policy (T5) reads `SCOPE.evictable` — so the four
vocabularies are spelled once, here, rather than once per consumer.

**Data, not behaviour.** `_types` is the stdlib-only vocabulary layer (ADR-026;
`_types/__init__.py` says "no logic"), so this module holds the tables and
nothing that reads them. `require_transition` lives one layer up, in
`_primitives`, which is where a refusal is allowed to exist. A `Machine` that
could answer "is this legal?" would be a second place to change the rule, which
is the drift this package exists to end.

**Three stored vocabularies, one adopted.** `ScopeStatus`, `AttemptStatus` and
`InputRequestStatus` are `StrEnum`s because the text the store writes *is* the
member: `row["status"] == ScopeStatus.RUNNING` is true of the string on disk, so
a choke point can parse `str -> ScopeStatus` without a lookup table. The run
machine gets no enum of its own — `RunStatus` already exists in
`_types/enums.py` and the schema adopts it, lower-cased, so only its state set
is derived here instead of declared.

**States are derived; the rows are written.** Each machine's `states` comes from
its vocabulary, so a status that exists is a state and cannot be forgotten. The
legal pairs are written out against `schema.md` §1, and
`tests/types/test_lifecycle_tables.py` is what keeps a row from naming a state
its own vocabulary does not have.

**Two sets, two names — "terminal" is not used for a scope.** *Absorbing* is
what `IllegalTransition` protects: nothing leaves it. *Evictable* is what the
ring cap may drop. They coincided under the old four-state diagram and D1 = A
separated them, by making `completed → running` reachable through a plain
`resume <id>`: a completed scope is evictable and is not absorbing anymore.

**Stored values only.** `stalled`, `waiting`, `ready` and `abandoned` are
derived for display in `app/_workflow_view.py` and never written.

**Absent is a state.** A machine's first column is `None`: a record that has
never been written. It is in the type rather than implied by "any target is
legal when unspecified", because the two are different claims and only the first
can be checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from functualize._types.enums import RunStatus


class ScopeStatus(StrEnum):
    """What a scope row's `status` column may hold (`schema.md` §1.1)."""

    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    """What an attempt row's `status` column may hold (`schema.md` §1.3)."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class InputRequestStatus(StrEnum):
    """What an input-request row may hold (`schema.md` §1.4)."""

    OPEN = "open"
    ACCEPTED = "accepted"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Machine:
    """A closed state set, its legal-transition table, and its named subsets.

    Attributes:
        name: What an :class:`~functualize._types.errors.IllegalTransition`
            names, so a refusal reads as *which* machine refused the pair.
        states: Every state the machine can hold, including any absorbing one.
        transitions: The legal ``(current, target)`` pairs. ``current`` is
            ``None`` for the absent-record case. Anything not in here is
            refused — the table is closed, not a sample of what works.
        absorbing: States nothing leaves. Required even when empty, so "this
            machine has no absorbing state" is a sentence someone wrote rather
            than a field that was skipped.
        evictable: States a retention policy may drop, on the same terms. Scope
            is the only machine with one (`schema.md` §1.1); the field is here
            rather than in a scope-only type because a second machine acquiring
            one must not need a second shape.
    """

    name: str
    states: frozenset[str]
    transitions: frozenset[tuple[str | None, str]]
    absorbing: frozenset[str]
    evictable: frozenset[str]


# ----------------------------------------------------------------------
# Scope (`schema.md` §1.1)
# ----------------------------------------------------------------------

SCOPE: Final[Machine] = Machine(
    name="scope",
    states=frozenset(s.value for s in ScopeStatus),
    transitions=frozenset(
        {
            # A blank record is `running` the moment it is written, so creation
            # and first entry are two edges.
            (None, "running"),
            # First entry stamps over the blank record; `complete_step` writes
            # mid-walk. A self-edge, not a change — and legal so neither write
            # has to know which one it is.
            ("running", "running"),
            ("running", "blocked"),
            ("running", "completed"),
            ("running", "failed"),
            ("running", "cancelled"),
            # Resume through the gate (T3: every entry stamps `running`).
            ("blocked", "running"),
            ("blocked", "cancelled"),
            # `resume` refuses only `cancelled`, so a failed scope re-enters
            # where it stopped.
            # TRANSITIONAL(workflow-persistence-atomic): not final — when that
            # step lands, a retry may mint a fresh attempt instead of
            # re-entering the scope, and this edge goes with it.
            ("failed", "running"),
            # Completion clears the position, so a re-run takes the first-entry
            # branch; that is how a plain `resume <id>` and `--retry-epilogue`
            # both work.
            # TRANSITIONAL(workflow-persistence-atomic): not final — the same
            # fresh-attempt question, on the same terms.
            ("completed", "running"),
            # The end-of-walk stamp fires twice (`frontier.complete` at END,
            # then the walker after the loop). A self-edge, not a change, and
            # legal so the second stamp does not refuse the first.
            ("completed", "completed"),
        }
    ),
    absorbing=frozenset({ScopeStatus.CANCELLED}),
    evictable=frozenset(
        {ScopeStatus.COMPLETED, ScopeStatus.FAILED, ScopeStatus.CANCELLED}
    ),
)


# ----------------------------------------------------------------------
# Run (`schema.md` §1.2)
# ----------------------------------------------------------------------

_RUN_STATES: Final[frozenset[str]] = frozenset(s.value.lower() for s in RunStatus)
_RUN_TERMINAL: Final[frozenset[str]] = frozenset(
    s.value.lower() for s in RunStatus if s.terminal
)

RUN: Final[Machine] = Machine(
    name="run",
    states=_RUN_STATES,
    transitions=frozenset(
        # A run opens at `running`, and every state that has not finished may go
        # anywhere: a run is reported by what ends it, and the set it may end as
        # is the whole vocabulary.
        {(None, "running")}
        | {
            (current, target)
            for current in _RUN_STATES - _RUN_TERMINAL
            for target in _RUN_STATES
        }
    ),
    absorbing=_RUN_TERMINAL,
    evictable=frozenset(),
)


# ----------------------------------------------------------------------
# Attempt (`schema.md` §1.3)
# ----------------------------------------------------------------------

ATTEMPT: Final[Machine] = Machine(
    name="attempt",
    states=frozenset(s.value for s in AttemptStatus),
    transitions=frozenset(
        {
            (None, "running"),
            ("running", "succeeded"),
            ("running", "failed"),
            ("running", "skipped"),
            ("running", "cancelled"),
        }
    ),
    # A retry inserts attempt `n + 1`; it never moves attempt `n` again.
    absorbing=frozenset(
        {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.SKIPPED,
            AttemptStatus.CANCELLED,
        }
    ),
    evictable=frozenset(),
)


# ----------------------------------------------------------------------
# InputRequest (`schema.md` §1.4)
# ----------------------------------------------------------------------

INPUT_REQUEST: Final[Machine] = Machine(
    name="input_request",
    states=frozenset(s.value for s in InputRequestStatus),
    transitions=frozenset(
        {
            (None, "open"),
            ("open", "accepted"),
            ("open", "cancelled"),
            ("open", "expired"),
            # Accepted is not settled: the answer is consumed when the walk that
            # asked for it reads it.
            ("accepted", "consumed"),
        }
    ),
    absorbing=frozenset(
        {
            InputRequestStatus.CONSUMED,
            InputRequestStatus.CANCELLED,
            InputRequestStatus.EXPIRED,
        }
    ),
    evictable=frozenset(),
)
