"""The one check every state change passes through.

`runtime-schema-migrations`/T4 (AC1). The four tables live in
`_types/lifecycle.py` as data; this is the refusal that reads them.

**Why here and not there.** `_types` is the vocabulary layer and holds no
logic (ADR-026, `_types/__init__.py`: "no logic"). A `Machine` that could answer
"is this legal?" would be a second place to change a rule whose whole point is
that it is spelled once, so the check lives in `_primitives`, where a refusal is
allowed to exist.

**Two stores call it, at three call sites.** `ScopeStore.set_scope_status` for the
scope machine and `RunStore.close_run` for the run machine; each reads the current
value inside the batch it is already writing, so the check audits the write rather
than a stale pre-read. `RunStore.open_run` is the third, for the run's creation
edge: it checks the pair against `None` *before* the write, so a refused open
touches nothing. Each lets the refusal propagate unchanged — the message a caller
sees is the one composed here:

    scope: 'cancelled' -> 'running' is not a legal transition

The other two machines have no stored writer yet: an attempt row is port
vocabulary the document backend never writes, and it derives an input request's
status rather than storing one, so `ATTEMPT` and `INPUT_REQUEST` are driven by the
tests below until the relational writer lands. This module stays the one place the
pair rule is written down outside the tables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._types.errors import IllegalTransition

if TYPE_CHECKING:
    from functualize._types.lifecycle import Machine


def require_transition(machine: Machine, current: str | None, target: str) -> str:
    """Return ``target`` if ``(current, target)`` is in the table, else refuse it.

    Args:
        machine: The table to check — `SCOPE`, `RUN`, `ATTEMPT` or
            `INPUT_REQUEST`.
        current: The state the record holds now, or ``None`` for a record that
            has not been written yet. ``None`` is a *state* in these tables
            rather than "no opinion": creation is the ``(None, "running")``
            edge, and a table is free to have no such edge at all.
        target: The state the caller wants to write.

    Returns:
        ``target``, so a writer assigns the answer instead of repeating the
        value it just checked: ``record["status"] = require_transition(...)``.

    Raises:
        IllegalTransition: The pair is not in the table, naming the machine,
            ``current`` and ``target``.

    **A target no vocabulary names needs no separate check.** Transitions are a
    subset of ``states × states`` — `tests/types/test_lifecycle_tables.py`
    asserts it — so an unknown target is outside the table by construction and
    is refused by the membership test below. A stored status outside the state
    set refuses on its next write the same way, which is what `contracts.md`
    promises for rows written before a vocabulary narrowed: not rewritten, but
    never silently moved on from either.

    **Membership is by value.** A `StrEnum` member and the text it stores are
    the same key (`ScopeStatus.BLOCKED == "blocked"`), so a caller may pass
    whichever it holds — the engine's `WalkState.RUNNING`, the store's parsed
    `ScopeStatus.RUNNING`, or the plain string off a record — and mixing them
    in one call is fine.
    """
    if (current, target) not in machine.transitions:
        raise IllegalTransition(machine.name, current, target)
    return target
