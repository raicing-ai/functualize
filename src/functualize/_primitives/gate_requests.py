"""Gate requests as document records — the transitional home of the model.

A gate's request and its candidates live inside ``scopes.json``, in the gate
record itself, until the durable interaction slice replaces this module with
a store-backed table. # TRANSITIONAL(FUN-21): requests and candidates are
stored as sections of the gate record in ``scopes.json``; the durable,
independently readable storage lands with that slice and this module goes.

Everything here works through ``ScopeStore``'s **public** surface —
``get_gate``, ``put_gate``, ``get_scope`` and one ``batch()`` per atomic
step — and adds no method to it. The rules the module holds:

- **One live request per (scope, gate).** Reopening a gate does not rewrite
  the answered request: it cancels it, archives it under ``superseded``, and
  opens a new one seeded with the old answer as a draft.
- **Candidates are append-only.** Appending to a request that is not ``open``
  raises before anything is written, so a recorded answer is final.
- **Consumption has one writer.** Only the walk moving past the gate marks a
  request consumed, and consuming twice is a no-op rather than an error,
  because a replayed resume is a legitimate caller.
- **Legacy records are projected, never synthesised.** A gate record written
  before requests existed keeps reading as an answered gate with zero
  candidates, under the ``<scope>::<gate>`` id the document backend has
  always derived.

Record shape (the current request lives at ``scopes[<id>]["gates"][<name>]``):

    request_id, status, candidates[], input_schema, prompt, model, tools,
    payload, blocked_at, consumed_at?, draft?, superseded[]?
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize._types.persistence import InputRequest

if TYPE_CHECKING:
    from functualize._primitives.scope_store import ScopeStore

#: The statuses a request can rest in on the current record. ``cancelled``
#: never rests here — superseding archives the cancelled record under
#: ``superseded`` and writes the new request in its place — but a record
#: read mid-supersede or by hand can say it.
_LIVE = ("open", "accepted")


def _iso(when: datetime) -> str:
    return when.isoformat()


def _parse(value: Any) -> datetime | None:
    """An ISO timestamp from a record, or None when absent or junk.

    Tolerant for the same reason the document backend's readers are: a
    record whose timestamp cannot be parsed still happened, and refusing
    here would hide every good field beside it.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _at(value: Any) -> datetime:
    return _parse(value) or datetime.fromtimestamp(0, UTC)


def _legacy_status(record: dict[str, Any]) -> str:
    """The status of a record written before requests existed.

    Derived exactly as the document backend derives it today: consumed wins,
    a deposited payload means accepted, everything else is open.
    """
    if record.get("consumed_at"):
        return "consumed"
    if record.get("payload") is not None:
        return "accepted"
    return "open"


def _status(record: dict[str, Any]) -> str:
    """The request's status: stored when it was written by this module,
    derived when the record predates it."""
    status = record.get("status")
    if isinstance(status, str) and status:
        return status
    return _legacy_status(record)


def _request_id(scope_id: str, gate_name: str, record: dict[str, Any]) -> str:
    """The record's own id, or the legacy derived one when it has none."""
    request_id = record.get("request_id")
    if isinstance(request_id, str) and request_id:
        return request_id
    return f"{scope_id}::{gate_name}"


def open_request(
    store: ScopeStore,
    scope_id: str,
    gate_name: str,
    *,
    request_id: str,
    schema: Any,
    prompt: Any,
    model: str,
    tools: tuple[Any, ...],
    now: datetime,
) -> str:
    """Open the gate's request, or return the id of the one already live.

    A request that is ``open``, ``accepted`` or ``consumed`` is returned
    unchanged — its ``blocked_at`` is not reset, because the moment the gate
    first blocked is a fact about the workflow, not about this call. Only a
    gate with no live request (never opened, or fully superseded) gets a new
    record, and a superseded history already on the record is carried
    forward rather than dropped.
    """
    record = store.get_gate(scope_id, gate_name)
    if record is not None and _status(record) in (*_LIVE, "consumed"):
        return _request_id(scope_id, gate_name, record)
    with store.batch():
        current = store.get_gate(scope_id, gate_name)
        if current is not None and _status(current) in (*_LIVE, "consumed"):
            return _request_id(scope_id, gate_name, current)
        fresh: dict[str, Any] = {
            "request_id": request_id,
            "status": "open",
            "candidates": [],
            "input_schema": schema,
            "prompt": prompt,
            "model": model,
            "tools": list(tools),
            "payload": None,
            "blocked_at": _iso(now),
        }
        if current is not None and current.get("superseded"):
            # A superseded history rides along with the next request — the
            # archive is the gate's, not any one request's.
            fresh["superseded"] = list(current["superseded"])
        store.put_gate(scope_id, gate_name, fresh)
    return request_id


def append_candidate(
    store: ScopeStore, scope_id: str, gate_name: str, candidate: GateCandidate
) -> None:
    """Append one candidate, refusing anything but an open request.

    The status is re-read **inside** the batch, so a second writer — another
    process, another ``ScopeStore`` on the same substrate — that already
    landed an accepted candidate is seen here and refused with nothing
    written. An ``accepted`` candidate moves the request to ``accepted``
    and records the payload beside it, which is what the walk replays.
    """
    with store.batch():
        record = store.get_gate(scope_id, gate_name)
        if record is None:
            raise InputRequestNotOpenError(candidate.request_id, "missing")
        status = _status(record)
        if status != "open":
            raise InputRequestNotOpenError(
                _request_id(scope_id, gate_name, record), status
            )
        entries = list(record.get("candidates", []))
        entries.append(
            {
                "candidate_id": candidate.candidate_id,
                "request_id": _request_id(scope_id, gate_name, record),
                "ordinal": candidate.ordinal,
                "source": candidate.source,
                "submitted_at": _iso(candidate.submitted_at),
                "outcome": candidate.evaluation.outcome.value,
                "detail": candidate.evaluation.detail,
                "errors": [list(pair) for pair in candidate.evaluation.errors],
                "payload": candidate.payload,
            }
        )
        record["candidates"] = entries
        if candidate.evaluation.outcome is EvaluationOutcome.ACCEPTED:
            record["status"] = "accepted"
            record["payload"] = candidate.payload
        store.put_gate(scope_id, gate_name, record)


def consume_request(
    store: ScopeStore,
    scope_id: str,
    gate_name: str,
    request_id: str,
    now: datetime,
) -> None:
    """Mark the request's accepted answer consumed by the walk.

    The single writer of ``consumed``: a deposit records that an answer
    exists, this records that the workflow moved on it. Consuming a request
    that is already consumed is a no-op — a replayed resume has done its
    work, not made a mistake — and anything but ``accepted`` or ``consumed``
    refuses, because consuming an answer that was never given would leave a
    record claiming a walk used input nobody deposited.
    """
    with store.batch():
        record = store.get_gate(scope_id, gate_name)
        if record is None:
            raise ValueError(f"no gate record for {gate_name!r} to consume")
        if _request_id(scope_id, gate_name, record) != request_id:
            raise ValueError(
                f"gate {gate_name!r} holds request "
                f"{_request_id(scope_id, gate_name, record)!r}, not {request_id!r}"
            )
        status = _status(record)
        if status == "consumed":
            return
        if status != "accepted":
            raise ValueError(
                f"request {request_id!r} is {status!r}, not accepted — "
                "nothing to consume"
            )
        record["status"] = "consumed"
        record["consumed_at"] = _iso(now)
        store.put_gate(scope_id, gate_name, record)


def supersede_request(
    store: ScopeStore,
    scope_id: str,
    gate_name: str,
    *,
    new_request_id: str,
    now: datetime,
) -> None:
    """Cancel the answered request and open a fresh one in its place.

    Reopen, made honest: the accepted request is not rewound but archived —
    it moves to ``cancelled`` with reason ``reopened``, its record (answer,
    candidates and all) is pushed onto the gate's ``superseded`` history,
    and a new open request takes the slot seeded with the old answer as a
    draft. A reader asking "what was agreed before it was withdrawn" gets
    the real answer, not a hole.
    """
    with store.batch():
        record = store.get_gate(scope_id, gate_name)
        if record is None:
            raise ValueError(f"no gate record for {gate_name!r} to supersede")
        if _status(record) != "accepted":
            raise ValueError(
                f"gate {gate_name!r} is {_status(record)!r}, not accepted — "
                "only an answered gate can be reopened"
            )
        archived = dict(record)
        archived["status"] = "cancelled"
        archived["cancel_reason"] = "reopened"
        archived["cancelled_at"] = _iso(now)
        superseded = list(record.get("superseded", []))
        superseded.append(archived)
        payload = record.get("payload")
        fresh: dict[str, Any] = {
            "request_id": new_request_id,
            "status": "open",
            "candidates": [],
            "input_schema": record.get("input_schema"),
            "prompt": record.get("prompt"),
            "model": record.get("model", ""),
            "tools": list(record.get("tools", [])),
            "payload": None,
            "blocked_at": _iso(now),
            "superseded": superseded,
        }
        if isinstance(payload, dict):
            fresh["draft"] = {"values": dict(payload), "updated_at": _iso(now)}
        store.put_gate(scope_id, gate_name, fresh)


def request_for(
    scope_id: str, gate_name: str, record: dict[str, Any], generation: int
) -> InputRequest:
    """One gate record as an ``InputRequest`` — the read projection.

    Legacy records (no ``request_id``) are projected, not synthesised: they
    keep the derived id and status the document backend has always read
    them under, with zero candidates, because inventing a request where none
    was recorded would make a migration claim the file does not support.
    """
    return InputRequest(
        request_id=_request_id(scope_id, gate_name, record),
        scope_id=scope_id,
        gate_name=gate_name,
        generation=generation,
        status=_status(record),
        created_at=_at(record.get("blocked_at")),
        schema=record.get("input_schema"),
        prompt=record.get("prompt"),
        resolved_at=_parse(record.get("consumed_at")),
    )


def candidates_for(record: dict[str, Any]) -> tuple[GateCandidate, ...]:
    """The record's candidates as values, ordered by ordinal.

    Ordered rather than trusted: the ordinal is the recorder's sequence, and
    a hand-edited or partially merged file appending out of order is a shape
    a reader must survive. Payloads are carried as recorded — nothing here
    validates, because the evaluation is a fact about submission time.
    """
    entries = record.get("candidates")
    if not isinstance(entries, list):
        return ()
    candidates = [
        GateCandidate(
            candidate_id=str(entry.get("candidate_id", "")),
            request_id=str(entry.get("request_id", "")),
            ordinal=int(entry.get("ordinal", 0) or 0),
            source=str(entry.get("source", "")),
            submitted_at=_at(entry.get("submitted_at")),
            evaluation=CandidateEvaluation(
                outcome=EvaluationOutcome(entry.get("outcome", "failed")),
                detail=str(entry.get("detail", "")),
                errors=tuple(
                    (str(field), str(message))
                    for field, message in entry.get("errors", [])
                ),
            ),
            payload=entry.get("payload"),
        )
        for entry in entries
        if isinstance(entry, dict)
    ]
    return tuple(sorted(candidates, key=lambda candidate: candidate.ordinal))
