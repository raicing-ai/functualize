"""Workflow-scope file format: the record half of the runtime state store.

Scopes were kept in ``state.json`` beside fingerprints, history and the session
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
condition     ``state.json``         ``scopes.json``
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

**Location is derived, never resolved.** The scope file is always the sibling of
the state file, so the two cannot end up in different modes (project vs.
standalone) or different directories. One upward walk lives in
``state_format.resolve_state_location``; this module calls it rather than
repeating it, because two walks can disagree and a reader must not reconstruct a
key the writer computed.

Lives in ``_primitives/``: stdlib plus ``_types`` for the error, which is shared
with the CLI, the adapters and the MCP plugin.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.state_format import (
    atomic_write_json,
    resolve_state_location,
    state_lock,
)
from functualize._types.errors import ScopeStoreUnreadableError

if TYPE_CHECKING:
    from collections.abc import Callable

# Scope file format version. **Independent of STATE_VERSION** — that is the
# whole point of the split. Bumping one says nothing about the other, and
# bumping this one refuses rather than discards.
# v1 (2026-09-09): {format_version, scopes: {scope_id: record}}. The record
# shape is unchanged from when it lived in state.json.
SCOPES_VERSION = 1

# Scope file name within the resolved directory (beside state.json).
SCOPES_FILENAME = "scopes.json"


def empty_scopes() -> dict[str, Any]:
    """Return a fresh scope envelope. Two keys, no more."""
    return {"format_version": SCOPES_VERSION, "scopes": {}}


def resolve_scopes_path(start: Path | str) -> Path:
    """Resolve the scope file path — always the state file's sibling.

    Derived from :func:`state_format.resolve_state_location` rather than
    repeating its upward walk, so the two files cannot disagree about which
    project or which mode they are in.

    Args:
        start: Project root (or cwd) to resolve from.

    Returns:
        Absolute path where the scope file lives (may not exist yet).
    """
    return resolve_state_location(Path(start))[0].with_name(SCOPES_FILENAME)


def scopes_lock(path: Path | str, timeout: float = 10.0) -> Any:
    """Advisory lock on the scope file, using the state store's ``.lock`` sidecar
    discipline. Separate lock, separate file — the two stores never block each
    other."""
    return state_lock(path, timeout)


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


def load_scopes(path: Path | str) -> dict[str, Any]:
    """Load the scope envelope, or refuse.

    A missing file is not an error — it reads as "no scopes", exactly as a
    missing state file reads as "no fingerprints". Anything *else* that cannot
    be honoured raises, leaving the file untouched.

    Raises:
        ScopeStoreUnreadableError: The file exists but is unparseable, is not an
            envelope, or carries a format version this build does not
            understand.
    """
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_scopes()
    except (OSError, UnicodeDecodeError) as exc:
        # A file that exists but cannot be read — a permission problem, a
        # directory, undecodable bytes. Not "no scopes".
        raise ScopeStoreUnreadableError(
            target, expected_version=SCOPES_VERSION
        ) from exc

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ScopeStoreUnreadableError(
            target, expected_version=SCOPES_VERSION
        ) from exc

    found = _found_version(data)
    if not isinstance(data, dict) or found != SCOPES_VERSION:
        raise ScopeStoreUnreadableError(
            target,
            scope_count=_count_scopes(data),
            found_version=found,
            expected_version=SCOPES_VERSION,
        )

    scopes = data.get("scopes")
    if not isinstance(scopes, dict):
        raise ScopeStoreUnreadableError(
            target, found_version=found, expected_version=SCOPES_VERSION
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
#: ``HISTORY_LIMIT = 200`` and `run_format` has ``RUNS_LIMIT = 500``. This file
#: had none, which is how it reached 2,188 records and 58 ms per state write on
#: a real project (`.spec/reviews/omp-after-review.md` F1).
#:
#: Higher than `RUNS_LIMIT` would be pointless — a scope outliving every run
#: that could reference it is unreachable — and much lower risks evicting
#: records a user could still resume. 500 matches the run log so the two files
#: hold the same horizon.
SCOPES_LIMIT = 500


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


def save_scopes(path: Path | str, envelope: dict[str, Any]) -> None:
    """Write the scope envelope atomically, stamping the current version.

    Callers that read-modify-write must hold :func:`scopes_lock` — or better,
    use :func:`update_scopes`.
    """
    payload = dict(envelope)
    payload["format_version"] = SCOPES_VERSION
    _trim(payload)
    atomic_write_json(path, payload)


def update_scopes(
    path: Path | str, mutate: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    """Read-modify-write the scope envelope under one lock.

    Re-reads inside the lock, so two runs touching *different* scope ids merge
    instead of clobbering each other — last-writer-wins per scope, not per file.

    Raises:
        ScopeStoreUnreadableError: propagated from :func:`load_scopes`. A writer
            must not be allowed to overwrite a file it could not read.
    """
    target = Path(path)
    with state_lock(target):
        envelope = load_scopes(target)
        mutate(envelope)
        save_scopes(target, envelope)
        return envelope


def clear_scopes(path: Path | str) -> Path | None:
    """Move the scope file aside, returning where it went, or None if absent.

    Moved rather than deleted: this is the escape hatch from a file
    :func:`load_scopes` refuses, and the runs inside it may still be wanted.
    **Never reads the file** — it has to work on exactly the content that cannot
    be parsed.
    """
    target = Path(path)
    if not target.exists():
        return None
    backup = target.with_name(target.name + ".bak")
    index = 1
    while backup.exists():
        backup = target.with_name(f"{target.name}.bak.{index}")
        index += 1
    target.rename(backup)
    return backup
