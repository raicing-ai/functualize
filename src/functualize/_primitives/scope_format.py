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

from typing import Any

from functualize._types.errors import ScopeStoreUnreadableError

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


#: Raw ``status`` values a scope can never leave. The cap evicts only these.
#:
#: These are the values the *store* writes, not the richer set
#: `app/_workflow_view.derived_state` computes for display — a "stalled" scope
#: has raw status ``"completed"`` and so is covered here. `_primitives` cannot
#: import from `app`, and duplicating the derived vocabulary would be worse
#: than naming the three raw ones: this file's job is the three values it
#: writes.
TERMINAL_SCOPE_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: Ring cap on scope records, the third of three — `state_format` has
#: ``EVENTS_PER_RUN_LIMIT`` and `run_format` has ``RUNS_LIMIT = 500``. This file
#: had none, which is how it reached 2,188 records and 58 ms per state write on
#: a real project (`.spec/reviews/omp-after-review.md` F1).
#:
#: Higher than `RUNS_LIMIT` would be pointless — a scope outliving every run
#: that could reference it is unreachable — and much lower risks evicting
#: records a user could still resume. 500 matches the run log so the two files
#: hold the same horizon.
SCOPES_LIMIT = 500

#: Ring cap on the events one scope keeps.
#:
#: A scope's event log is what `func builtin workflow watch` follows, and a walk
#: emits a handful per node — so this bounds a *long* workflow, not a chatty
#: one. Matched to `EVENTS_PER_RUN_LIMIT` for the same reason `SCOPES_LIMIT`
#: matches `RUNS_LIMIT`: two logs with different horizons disagree about what
#: happened, and the reader has no way to know which one was trimmed.
EVENTS_PER_SCOPE_LIMIT = 500


def _trim(envelope: dict[str, Any]) -> None:
    """Evict the oldest **finished** scopes until the file fits the cap.

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
    if not isinstance(scopes, dict) or len(scopes) <= SCOPES_LIMIT:
        return
    excess = len(scopes) - SCOPES_LIMIT
    evictable = [
        scope_id
        for scope_id, record in scopes.items()
        if isinstance(record, dict) and record.get("status") in TERMINAL_SCOPE_STATUSES
    ]
    for scope_id in evictable[:excess]:
        del scopes[scope_id]


def stamp_scopes(envelope: dict[str, Any]) -> dict[str, Any]:
    """The payload to store: the current version stamped on, and the cap applied.

    Returns a copy rather than mutating, so a caller holding an open batch does
    not find its own envelope trimmed underneath it.
    """
    payload = dict(envelope)
    payload["format_version"] = SCOPES_VERSION
    _trim(payload)
    return payload
