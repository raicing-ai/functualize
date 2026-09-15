"""Run-log file format: the third sibling, and the one that discards.

`fresh.json`, `scopes.json` and now `runs.json`. Three files, three version
numbers, and — the part that matters — **three different answers to a version
this build does not understand**:

============  =====================  ===============================  ==================
condition     ``fresh.json``         ``scopes.json``                  ``runs.json``
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
So this file discards, like `fresh.json`, and the reasoning is worth stating
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

from typing import Any

#: Run-log format version. **Independent of `FRESH_VERSION` and
#: `SCOPES_VERSION`** — that independence is the reason for the third file.
#:
#: v1 (2026-09-11): {format_version, runs: {run_id: record}, events:
#: {run_id: [event, …]}}. Two mappings in one envelope because a run and its
#: events are written and discarded together; splitting them would create a
#: fourth file whose only relationship is that it is always read with the third.
RUNS_VERSION = 1

#: Run-log file name within the resolved directory (beside `fresh.json`).
RUNS_FILENAME = "runs.json"

#: Ring cap per run. Same reasoning the retired `HISTORY_LIMIT` had (it left
#: in `durable-run-layer`/T3b): an unbounded event
#: log on a long walk is the same defect the history cap exists to prevent, and
#: a workflow with a retry loop is exactly where it would bite.
EVENTS_PER_RUN_LIMIT = 200

#: Ring cap across runs. Sorted by `run_id`, which is a ULID, so "the newest N"
#: needs no index and no timestamp comparison.
RUNS_LIMIT = 500


def empty_runs() -> dict[str, Any]:
    """Return a fresh run envelope. Three keys, no more."""
    return {"format_version": RUNS_VERSION, "runs": {}, "events": {}}


#: The document name this envelope is stored under.
#:
#: A key, not a path. `JsonFileSubstrate.for_project` decides the one directory
#: every document lands in, so the three files can no longer disagree about
#: which project or which mode they are in — that used to be three copies of one
#: upward walk held in agreement by care.
RUNS_KEY = "runs"


def normalize_runs(data: Any) -> dict[str, Any]:
    """Coerce stored content into a run envelope, discarding anything unusable.

    **Never raises for content.** A truncated document, a version from a future
    build — all read as "no runs". That is the same rule `fresh.json` follows
    and the opposite of `scopes.json`, and the difference is deliberate: see
    this module's docstring.

    The document is left where it is either way. Discarding the *content* is not
    the same as destroying it, and a human debugging a bad write should still
    find the bytes.
    """
    if not isinstance(data, dict) or data.get("format_version") != RUNS_VERSION:
        return empty_runs()

    runs = data.get("runs")
    events = data.get("events")
    if not isinstance(runs, dict) or not isinstance(events, dict):
        return empty_runs()

    return {"format_version": RUNS_VERSION, "runs": runs, "events": events}


def stamp_runs(envelope: dict[str, Any]) -> dict[str, Any]:
    """The payload to store: the current version stamped on, and the cap applied.

    A copy rather than a mutation, so a caller holding an open batch does not
    find its own envelope trimmed underneath it.
    """
    payload = dict(envelope)
    payload["format_version"] = RUNS_VERSION
    _trim(payload)
    return payload


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
