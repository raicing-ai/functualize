"""Workflow-scope file format: the record half of the runtime state store.

Scopes were kept in ``fresh.json`` beside fingerprints, history and the session
precondition cache. They do not belong there, and the difference is not
organisational — it is the discard rule:

- ``state_format`` holds **derived** data. It is recomputable from the source
  tree, so an unreadable or stale file degrades to an empty envelope and the
  worst case is one extra run. That is correct for a cache.
- This module holds a **record**. A scope is the only trace of an in-flight run:
  which steps have completed, which branch the walk took, where it stopped, and
  the gate payload a human deposited when they approved something. None of it is
  recomputable, and losing it is not "one extra run" — it is an approval spent
  on a run that no longer exists.

So the two rules are opposites, and each file states its own:

============  =====================  ===============================
condition     ``fresh.json``         ``scopes.json``
============  =====================  ===============================
absent        empty envelope         empty — "no scopes"
unparseable   empty envelope         **refuse**, file left in place
bad version   empty envelope         **refuse**, file left in place
============  =====================  ===============================

**The refusal never moves the file.** It has to be a repeatable state: if the
read renamed the file aside, the *next* run would find nothing, read it as "no
scopes", and start the workflow over — silently, which is the exact failure this
module exists to prevent. The file moves only when a human asks, at
``func builtin state clear --scopes``, which the error message names.

**Location is not this module's business any more.** It used to derive the
scope file as the state file's sibling, so the two could not end up in different
directories. `JsonFileSubstrate.for_project` now makes that structural — one
walk, one root, every document under it — and what is left here is the
*format*: the version, the cap, and the refusal rule above.

Lives in ``_primitives/``: stdlib plus ``_types`` for the error, which is shared
with the CLI, the adapters and the MCP plugin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._types.errors import ScopeStoreUnreadableError
from functualize._types.lifecycle import SCOPE
from functualize._types.retention import DEFAULT_RETENTION

if TYPE_CHECKING:
    from functualize._types.retention import RetentionPolicy

# Scope file format version. **Independent of FRESH_VERSION** — that is the
# whole point of the split. Bumping one says nothing about the other, and
# bumping this one refuses rather than discards.
# v1 (2026-09-09): {format_version, scopes: {scope_id: record}}. The record
# shape is unchanged from when it lived in the freshness ledger.
SCOPES_VERSION = 1

# Scope file name within the resolved directory (beside fresh.json).
SCOPES_FILENAME = "scopes.json"


def empty_scopes() -> dict[str, Any]:
    """Return a fresh scope envelope. Two keys, no more."""
    return {"format_version": SCOPES_VERSION, "scopes": {}}


#: The document name this envelope is stored under.
#:
#: A key, not a path. `JsonFileSubstrate` turns it back into `scopes.json` in
#: the project directory; another substrate is free to make it a table row.
SCOPES_KEY = "scopes"


def _count_scopes(data: Any) -> int | None:
    """Scopes visible in loaded data, or None if it is not shaped like an
    envelope. A **count**: never the records, which may hold secrets."""
    if not isinstance(data, dict):
        return None
    scopes = data.get("scopes")
    return len(scopes) if isinstance(scopes, dict) else None


def _found_version(data: Any) -> int | None:
    if isinstance(data, dict):
        version = data.get("format_version")
        if isinstance(version, int) and not isinstance(version, bool):
            return version
    return None


def normalize_scopes(data: Any, *, where: str) -> dict[str, Any]:
    """Accept the envelope, or refuse it. **Never** degrade to "no scopes".

    The half of the old `load_scopes` that is about *meaning*: whether this
    content can be honoured. Reading the bytes is the substrate's job, and
    "missing" never reaches here — a substrate reports that as None and the
    store turns it into :func:`empty_scopes`, exactly as a missing state file
    reads as "no fingerprints".

    Args:
        data: What the substrate returned.
        where: A human-readable account of where it came from, for the error.
            A description rather than a path, because a substrate over a table
            has none.

    Raises:
        ScopeStoreUnreadableError: The document is not an envelope, or carries
            a format version this build does not understand.
    """
    found = _found_version(data)
    if not isinstance(data, dict) or found != SCOPES_VERSION:
        raise ScopeStoreUnreadableError(
            where,
            scope_count=_count_scopes(data),
            found_version=found,
            expected_version=SCOPES_VERSION,
        )

    scopes = data.get("scopes")
    if not isinstance(scopes, dict):
        raise ScopeStoreUnreadableError(
            where, found_version=found, expected_version=SCOPES_VERSION
        )

    return {"format_version": SCOPES_VERSION, "scopes": scopes}


#: Raw ``status`` values the cap may drop — the scope machine's *evictable* set.
#:
#: Derived from `SCOPE.evictable` rather than written out here, because the
#: three values are a property of the scope machine and this file is not where
#: that machine is described (`_types/lifecycle.py`, `schema.md` §1.1). The name
#: is kept for the callers that had it. What it *means* changed when D1 = A
#: separated the two sets: `completed` and `failed` are evictable and are not
#: absorbing any more, since a plain `resume <id>` re-enters both, so this set
#: answers "may a cap drop it?" and not "is it finished for good?" — only
#: `cancelled` answers the second, which is `SCOPE.absorbing`.
#:
#: These are the values the *store* writes, not the richer set
#: `app/_workflow_view.derived_state` computes for display — a "stalled" scope
#: has raw status ``"completed"`` and so is covered here. `_primitives` cannot
#: import from `app`, and duplicating the derived vocabulary would be worse than
#: naming the three raw ones: this file's job is the three values it writes.
TERMINAL_SCOPE_STATUSES = SCOPE.evictable

#: Ring cap on scope records, the third of three — `state_format` has
#: ``EVENTS_PER_RUN_LIMIT`` and `run_format` has its own count. This file
#: had none, which is how it reached 2,188 records and 58 ms per state write on
#: a real project (as confirmed by external review).
#:
#: It is the default policy's count rather than a number of its own: the
#: horizon is `DEFAULT_RETENTION.max_records` (`_types/retention.py`), shared
#: with the run log so the two files hold the same horizon. Higher than the run
#: log's would be pointless — a scope outliving every run that could reference
#: it is unreachable — and much lower risks evicting records a user could still
#: resume.
SCOPES_LIMIT = DEFAULT_RETENTION.max_records

#: Ring cap on the events one scope keeps.
#:
#: A scope's event log is what `func builtin workflow watch` follows, and a walk
#: emits a handful per node — so this bounds a *long* workflow, not a chatty
#: one. The same default policy's count, for the reason above: two logs with
#: different horizons disagree about what happened, and the reader has no way to
#: know which one was trimmed.
#:
#: Not the same number as `run_format.EVENTS_PER_RUN_LIMIT` (200): a run's log
#: is flushed when the run ends, and one run is a slice of the walk whose events
#: this list has to hold.
EVENTS_PER_SCOPE_LIMIT = DEFAULT_RETENTION.max_records


def _trim(
    envelope: dict[str, Any], policy: RetentionPolicy = DEFAULT_RETENTION
) -> None:
    """Evict the oldest **finished** scopes until the file fits the policy.

    What leaves is the policy's question, not this function's: ``max_records``
    is the count, and ``evictable_only`` (true by default) restricts candidates
    to `SCOPE.evictable`. A policy that turns that off may drop a live scope as
    readily as a finished one — see `RetentionPolicy`, where the default is
    explained as the safety property it is rather than a preference.

    Two things make this different from `run_format._trim`, and both are the
    point rather than incidental:

    **It never evicts a live scope.** A workflow parked at a gate is the one
    record that must survive any amount of unrelated traffic — losing it spends
    a human's approval on a run that no longer exists, which is the failure
    durable state exists to prevent. So a file that is over the cap *and* holds
    nothing finished stays over the cap. An oversized file of live runs is
    correct behaviour, not a bug to fix by deleting something.

    **Oldest means insertion order, not id order.** Run ids are ULIDs and sort
    chronologically; scope ids are ``<job>-<hex8>`` and do not. Python dicts
    preserve insertion order and JSON round-trips it, so the order records were
    created in is already on disk — and updating a record leaves its position
    alone, which is exactly the property needed here.
    """
    scopes = envelope.get("scopes")
    if not isinstance(scopes, dict) or len(scopes) <= policy.max_records:
        return
    excess = len(scopes) - policy.max_records
    evictable = [
        scope_id
        for scope_id, record in scopes.items()
        if not policy.evictable_only
        or (isinstance(record, dict) and record.get("status") in SCOPE.evictable)
    ]
    for scope_id in evictable[:excess]:
        del scopes[scope_id]


def stamp_scopes(
    envelope: dict[str, Any], policy: RetentionPolicy = DEFAULT_RETENTION
) -> dict[str, Any]:
    """The payload to store: the current version stamped on, and the cap applied.

    Returns a copy rather than mutating, so a caller holding an open batch does
    not find its own envelope trimmed underneath it.
    """
    payload = dict(envelope)
    payload["format_version"] = SCOPES_VERSION
    _trim(payload, policy)
    return payload
