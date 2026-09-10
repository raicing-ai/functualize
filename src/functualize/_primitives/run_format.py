"""Run-log file format: the third sibling, and the one that discards.

`state.json`, `scopes.json` and now `runs.json`. Three files, three version
numbers, and — the part that matters — **three different answers to a version
this build does not understand**:

============  =====================  ===============================  ==================
condition     ``state.json``         ``scopes.json``                  ``runs.json``
============  =====================  ===============================  ==================
absent        empty envelope         empty — "no scopes"              empty — "no runs"
unparseable   empty envelope         **refuse**, file left in place   empty envelope
bad version   empty envelope         **refuse**, file left in place   empty envelope
============  =====================  ===============================  ==================

`scopes.json` refuses because a scope is the only trace of an in-flight run: the
steps that completed, the branch taken, the gate payload a human deposited.
Losing it spends an approval on a run that no longer exists.

A **run record is an observation of something that already happened.** It is
derived in the same sense a fingerprint is: losing it costs history, not work.
So this file discards, like `state.json`, and the reasoning is worth stating
because the wrong choice here is expensive in a way that is easy to miss —
putting run records in `scopes.json` would force the *strictest* policy onto the
*most voluminous* data, and one corrupt run log would then block every workflow
in the project.

**Why a third file at all**, rather than a section of either: sharing a file
means sharing a version number, and a bump then says something about data it was
never about. The three-file split is PR #34's precedent, followed exactly.

Lives in ``_primitives/``: stdlib only, reusing `state_format`'s atomic write
and lock rather than repeating either.
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

if TYPE_CHECKING:
    from collections.abc import Callable

#: Run-log format version. **Independent of `STATE_VERSION` and
#: `SCOPES_VERSION`** — that independence is the reason for the third file.
#:
#: v1 (2026-09-11): {format_version, runs: {run_id: record}, events:
#: {run_id: [event, …]}}. Two mappings in one envelope because a run and its
#: events are written and discarded together; splitting them would create a
#: fourth file whose only relationship is that it is always read with the third.
RUNS_VERSION = 1

#: Run-log file name within the resolved directory (beside `state.json`).
RUNS_FILENAME = "runs.json"

#: Ring cap per run, matching `HISTORY_LIMIT`'s reasoning: an unbounded event
#: log on a long walk is the same defect the history cap exists to prevent, and
#: a workflow with a retry loop is exactly where it would bite.
EVENTS_PER_RUN_LIMIT = 200

#: Ring cap across runs. Sorted by `run_id`, which is a ULID, so "the newest N"
#: needs no index and no timestamp comparison.
RUNS_LIMIT = 500


def empty_runs() -> dict[str, Any]:
    """Return a fresh run envelope. Three keys, no more."""
    return {"format_version": RUNS_VERSION, "runs": {}, "events": {}}


def resolve_runs_path(start: Path | str) -> Path:
    """Resolve the run-log path — always the state file's sibling.

    Derived from :func:`state_format.resolve_state_location` rather than
    repeating its upward walk, so the three files cannot disagree about which
    project or which mode they are in. A reader must not reconstruct a key the
    writer computed.
    """
    return resolve_state_location(Path(start))[0].with_name(RUNS_FILENAME)


def runs_lock(path: Path | str, timeout: float = 10.0) -> Any:
    """Advisory lock on the run log, using the state store's ``.lock`` sidecar
    discipline. Separate file, separate lock — the three stores never block one
    another."""
    return state_lock(path, timeout)


def load_runs(path: Path | str) -> dict[str, Any]:
    """Load the run envelope, discarding anything unusable.

    **Never raises for content.** A missing file, a truncated one, a version
    from a future build — all read as "no runs". That is the same rule
    `state.json` follows and the opposite of `scopes.json`, and the difference
    is deliberate: see this module's docstring.

    The file is left in place either way. Discarding the *content* is not the
    same as destroying it, and a human debugging a bad write should still find
    the bytes.
    """
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return empty_runs()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return empty_runs()

    if not isinstance(data, dict) or data.get("format_version") != RUNS_VERSION:
        return empty_runs()

    runs = data.get("runs")
    events = data.get("events")
    if not isinstance(runs, dict) or not isinstance(events, dict):
        return empty_runs()

    return {"format_version": RUNS_VERSION, "runs": runs, "events": events}


def save_runs(path: Path | str, envelope: dict[str, Any]) -> None:
    """Write the run envelope atomically, stamping the current version.

    Callers that read-modify-write must hold :func:`runs_lock` — or better, use
    :func:`update_runs`.
    """
    payload = dict(envelope)
    payload["format_version"] = RUNS_VERSION
    atomic_write_json(path, payload)


def update_runs(
    path: Path | str, mutate: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    """Read-modify-write the run envelope under one lock.

    Re-reads inside the lock, so two processes recording *different* runs merge
    instead of clobbering each other — last-writer-wins per run, not per file.
    That matters more here than for scopes: every run writes, including the
    nested and parallel ones history excludes.
    """
    target = Path(path)
    with state_lock(target):
        envelope = load_runs(target)
        mutate(envelope)
        _trim(envelope)
        save_runs(target, envelope)
        return envelope


def _trim(envelope: dict[str, Any]) -> None:
    """Hold both rings to their caps, newest kept.

    Runs are sorted by id, which is a **ULID** — lexicographic order is
    chronological order, so this needs no timestamp parsing and cannot be
    confused by two runs starting in the same millisecond on different clocks.

    **An evicted run takes its events with it**, because events outliving the
    run they describe are a leak that only shows up on a long-lived project —
    the worst place to find one.

    **An event whose run was never opened is kept.** The distinction matters and
    the first draft of this function did not make it: the subscriber that writes
    events and the code that opens records are deliberately uncoordinated (the
    bus does no file I/O, spec AC-5), so an event can legitimately arrive for a
    run this file has never seen. Deleting it would make the log lie about what
    it observed. Those lists are bounded by the key cap below rather than by
    membership, so "keep what you saw" does not become "grow forever".
    """
    runs = envelope.get("runs")
    events = envelope.get("events")
    if not isinstance(runs, dict) or not isinstance(events, dict):
        return

    evicted: set[str] = set()
    if len(runs) > RUNS_LIMIT:
        keep = set(sorted(runs)[-RUNS_LIMIT:])
        evicted = {r for r in runs if r not in keep}
        for run_id in evicted:
            del runs[run_id]

    for run_id in evicted:
        events.pop(run_id, None)

    # Orphans — events for runs never opened here — are bounded as a group, by
    # the same cap and the same ULID ordering.
    orphans = sorted(r for r in events if r not in runs)
    for run_id in orphans[:-RUNS_LIMIT] if len(orphans) > RUNS_LIMIT else []:
        del events[run_id]

    for run_id, entries in events.items():
        if isinstance(entries, list) and len(entries) > EVENTS_PER_RUN_LIMIT:
            events[run_id] = entries[-EVENTS_PER_RUN_LIMIT:]


def clear_runs(path: Path | str) -> Path | None:
    """Move the run log aside, returning where it went, or None if absent.

    Present for symmetry with `clear_scopes` and for one real case: a run log so
    large that reading it is slow. Unlike scopes there is no *refusal* to escape
    from — :func:`load_runs` already degrades — so this is a convenience rather
    than the only way out. **Never reads the file.**
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
