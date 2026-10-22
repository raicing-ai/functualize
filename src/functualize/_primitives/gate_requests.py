"""Gate requests as document records — the document backend's representation.

On the document store a gate's request, its candidates and its decision live
inside ``scopes.json``, in the gate record itself. That is this backend's
shape, not a step towards another one: the store that keeps them as
independent, indexed records is the relational one, and a project that needs
interaction evidence readable without the scope document — or an outbox —
selects it (``runtime_store.url``). The document store declares
``durable_outbox=False`` and is refused for any configuration that needs one.

Everything here works through ``ScopeStore``'s **public** surface —
``get_gate``, ``put_gate``, ``get_scope`` and one ``batch()`` per atomic
step — and adds no method to it. The rules the module holds:

- **One live request per (scope, gate).** Reopening a gate does not rewrite
  the answered request: it cancels it, archives it under ``superseded``, and
  opens a new one seeded with the old answer as a draft. A walk asking the
  gate a new question after its last answer was consumed names that request
  as ``supersedes``: the spent request is archived the same way, unanswered
  by anything the new one inherits.
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
    payload, blocked_at, run_id?, position?, decision?, consumed_at?, draft?,
    superseded[]?

A candidate entry carries its provenance beside its evaluation —
``resolver_class``, ``channel``, ``schema_id``, ``schema_version``,
``payload_hash``, ``supersedes_candidate_id`` and ``evidence_refs`` — and
``decision`` is the recorded :class:`GateDecision`, written once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    EvidenceRef,
    GateCandidate,
    GateDecision,
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
    """The request's status — a deposited payload is an answer, whichever
    path wrote it.

    ``consumed_at`` first and the payload second, so the legacy deposit
    helper (``ScopeStore.deposit_gate_payload``, kept by member decision
    D-3 for its test call sites) keeps registering as an answered gate the
    moment it writes. For records this module writes the two derivations
    agree by construction — an accepted candidate sets the payload, and
    nothing else does — so this only widens what reads as accepted, never
    what stops being it.
    """
    if record.get("consumed_at"):
        return "consumed"
    if record.get("payload") is not None:
        return "accepted"
    status = record.get("status")
    if isinstance(status, str) and status:
        return status
    return "open"


def recorded_answer(store: ScopeStore, scope_id: str, gate_name: str) -> Any:
    """The answer sitting on a gate record that no candidate recorded.

    The read-only projection for the deposit path: a record written before
    requests existed, or answered through the legacy deposit helper, holds
    its answer as ``payload`` and has no candidates to read instead. This
    is what lets those files and tests keep answering gates exactly as they
    did — the payload is fed to replay without being re-validated.
    """
    record = store.get_gate(scope_id, gate_name)
    if record is None:
        return None
    # A candidate's accepted payload is also mirrored on the legacy gate
    # record. It is not an unrecorded deposit: replay reads its candidate.
    if record.get("candidates"):
        return None
    return record.get("payload")


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
    run_id: str | None = None,
    position: str | None = None,
    supersedes: str | None = None,
) -> str:
    """Open the gate's request, or return the id of the one already live.

    A request that is ``open``, ``accepted`` or ``consumed`` is returned
    unchanged — its ``blocked_at`` is not reset, because the moment the gate
    first blocked is a fact about the workflow, not about this call. Only a
    gate with no live request (never opened, or fully superseded) gets a new
    record, and a superseded history already on the record is carried
    forward rather than dropped.

    ``supersedes`` names a **consumed** request whose answer must not answer
    this ask: an answer used once is spent, and a later question on the same
    gate needs its own. That request is moved onto the gate's ``superseded``
    history (reason ``superseded``) and a fresh request opens in its place.
    Naming a request that is still open or accepted refuses — retiring an
    answer nobody used would lose it — and naming one already in the
    history is the replay of a supersede that landed, so the live request
    is reused as without it.
    """
    record = store.get_gate(scope_id, gate_name)
    if (
        supersedes is None
        and record is not None
        and _status(record) in (*_LIVE, "consumed")
    ):
        return _request_id(scope_id, gate_name, record)
    with store.batch():
        current = store.get_gate(scope_id, gate_name)
        if current is None and supersedes is not None:
            raise ValueError(
                f"gate {gate_name!r} has no request; {supersedes!r} cannot be "
                "superseded"
            )
        superseded = list(current.get("superseded", [])) if current else []
        if current is not None and _names(scope_id, gate_name, current, supersedes):
            if _status(current) != "consumed":
                raise ValueError(
                    f"request {supersedes!r} on gate {gate_name!r} is "
                    f"{_status(current)!r}, not consumed — only a spent answer "
                    "can be superseded"
                )
            archived = dict(current)
            archived.pop("superseded", None)
            archived["superseded_reason"] = "superseded"
            archived["superseded_at"] = _iso(now)
            superseded.append(archived)
        elif current is not None and _status(current) in (*_LIVE, "consumed"):
            if supersedes is not None and not _archived(
                scope_id, gate_name, superseded, supersedes
            ):
                raise ValueError(
                    f"gate {gate_name!r} holds request "
                    f"{_request_id(scope_id, gate_name, current)!r}; "
                    f"{supersedes!r} is not a request it recorded"
                )
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
            "run_id": run_id,
            "position": position,
        }
        if superseded:
            # A superseded history rides along with the next request — the
            # archive is the gate's, not any one request's.
            fresh["superseded"] = superseded
        store.put_gate(scope_id, gate_name, fresh)
    return request_id


def _names(
    scope_id: str, gate_name: str, record: dict[str, Any], request_id: str | None
) -> bool:
    """Whether ``request_id`` is the request this gate record currently holds."""
    return request_id is not None and (
        _request_id(scope_id, gate_name, record) == request_id
    )


def _archived(
    scope_id: str,
    gate_name: str,
    history: list[Any],
    request_id: str,
) -> bool:
    """Whether ``request_id`` is already on the gate's superseded history."""
    return any(
        isinstance(entry, dict) and _names(scope_id, gate_name, entry, request_id)
        for entry in history
    )


def append_candidate(
    store: ScopeStore, scope_id: str, gate_name: str, candidate: GateCandidate
) -> None:
    """Append one candidate, refusing a second answer.

    The status is re-read **inside** the batch, so a second writer — another
    process, another ``ScopeStore`` on the same substrate — that already
    landed an accepted candidate is seen here and refused with nothing
    written. An ``accepted`` candidate moves the request to ``accepted``
    and records the payload beside it, which is what the walk replays.

    One submission's tail lands: the ``not_reached`` rungs behind an
    accepted one belong to the same ladder — they change no answer, and
    refusing them would record a ladder that stopped one rung short of
    what ran. Everything else that is not an open request refuses.
    """
    with store.batch():
        record = store.get_gate(scope_id, gate_name)
        if record is None:
            raise InputRequestNotOpenError(candidate.request_id, "missing")
        status = _status(record)
        if status != "open" and not (
            status == "accepted"
            and candidate.evaluation.outcome is EvaluationOutcome.NOT_REACHED
        ):
            raise InputRequestNotOpenError(
                _request_id(scope_id, gate_name, record), status
            )
        entries = list(record.get("candidates", []))
        entry: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "request_id": _request_id(scope_id, gate_name, record),
            "ordinal": candidate.ordinal,
            "source": candidate.source,
            "submitted_at": _iso(candidate.submitted_at),
            "outcome": candidate.evaluation.outcome.value,
            "detail": candidate.evaluation.detail,
            "errors": [list(pair) for pair in candidate.evaluation.errors],
            "payload": candidate.payload,
            "resolver_class": candidate.resolver_class,
            "channel": candidate.channel,
            "schema_id": candidate.schema_id,
            "schema_version": candidate.schema_version,
            "payload_hash": candidate.payload_hash,
            "supersedes_candidate_id": candidate.supersedes_candidate_id,
            "evidence_refs": [
                {
                    "ref": ref.ref,
                    "digest": ref.digest,
                    "media_type": ref.media_type,
                    "size": ref.size,
                }
                for ref in candidate.evidence_refs
            ],
        }
        if candidate.evaluation.evidence is not None:
            entry["evidence"] = dict(candidate.evaluation.evidence)
        entries.append(entry)
        record["candidates"] = entries
        if candidate.evaluation.outcome is EvaluationOutcome.ACCEPTED:
            record["status"] = "accepted"
            record["payload"] = candidate.payload
        store.put_gate(scope_id, gate_name, record)


def record_decision(
    store: ScopeStore, scope_id: str, gate_name: str, decision: GateDecision
) -> None:
    """Write the request's decision onto its gate record, once.

    Refused when the record holds another request, when the request is not
    ``accepted`` (the accepted candidate is applied first, in the same unit),
    or when a decision is already recorded — a decision is a fact about one
    moment, and a second would rewrite it.
    """
    with store.batch():
        record = store.get_gate(scope_id, gate_name)
        if record is None:
            raise ValueError(f"no gate record for {gate_name!r} to decide")
        owner = _request_id(scope_id, gate_name, record)
        if owner != decision.request_id:
            raise ValueError(
                f"gate {gate_name!r} holds request {owner!r}, not "
                f"{decision.request_id!r}"
            )
        if _status(record) != "accepted":
            raise ValueError(
                f"request {owner!r} is {_status(record)!r}; a decision records "
                "an acceptance"
            )
        if record.get("decision") is not None:
            raise ValueError(f"request {owner!r} is already decided")
        record["decision"] = {
            "accepted_id": decision.accepted_id,
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
            "observed_candidate_ids": list(decision.observed_candidate_ids),
            "decided_at": _iso(decision.decided_at),
        }
        store.put_gate(scope_id, gate_name, record)


def decision_for(
    scope_id: str, gate_name: str, record: dict[str, Any]
) -> GateDecision | None:
    """The record's decision as a value, ``None`` when none was recorded."""
    entry = record.get("decision")
    if not isinstance(entry, dict):
        return None
    return GateDecision(
        request_id=_request_id(scope_id, gate_name, record),
        accepted_id=str(entry.get("accepted_id", "")),
        policy_id=str(entry.get("policy_id", "")),
        policy_version=str(entry.get("policy_version", "")),
        observed_candidate_ids=tuple(
            str(item) for item in entry.get("observed_candidate_ids") or ()
        ),
        decided_at=_at(entry.get("decided_at")),
    )


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
    request_id: str | None = None,
) -> None:
    """Cancel the answered request and open a fresh one in its place.

    Reopen, made honest: the accepted request is not rewound but archived —
    it moves to ``cancelled`` with reason ``reopened``, its record (answer,
    candidates and all) is pushed onto the gate's ``superseded`` history,
    and a new open request takes the slot seeded with the old answer as a
    draft. A reader asking "what was agreed before it was withdrawn" gets
    the real answer, not a hole.

    ``request_id``, when given, must be the request the gate holds — the port
    names the request it withdraws, and withdrawing a different one than the
    caller read would be a lost update.
    """
    with store.batch():
        record = store.get_gate(scope_id, gate_name)
        if record is None:
            raise ValueError(f"no gate record for {gate_name!r} to supersede")
        if request_id is not None and _request_id(scope_id, gate_name, record) != (
            request_id
        ):
            raise ValueError(
                f"gate {gate_name!r} holds request "
                f"{_request_id(scope_id, gate_name, record)!r}, not {request_id!r}"
            )
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
            "run_id": record.get("run_id"),
            "position": record.get("position"),
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
        run_id=_text(record.get("run_id")),
        position=_text(record.get("position")),
    )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _evidence_refs(entries: Any) -> tuple[EvidenceRef, ...]:
    if not isinstance(entries, list):
        return ()
    return tuple(
        EvidenceRef(
            ref=str(item.get("ref", "")),
            digest=str(item.get("digest", "")),
            media_type=_text(item.get("media_type")),
            size=item.get("size") if isinstance(item.get("size"), int) else None,
        )
        for item in entries
        if isinstance(item, dict)
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
                evidence=entry.get("evidence"),
            ),
            payload=entry.get("payload"),
            resolver_class=str(entry.get("resolver_class") or ""),
            channel=str(entry.get("channel") or ""),
            schema_id=str(entry.get("schema_id") or ""),
            schema_version=str(entry.get("schema_version") or ""),
            payload_hash=str(entry.get("payload_hash") or ""),
            supersedes_candidate_id=_text(entry.get("supersedes_candidate_id")),
            evidence_refs=_evidence_refs(entry.get("evidence_refs")),
        )
        for entry in entries
        if isinstance(entry, dict)
    ]
    return tuple(sorted(candidates, key=lambda candidate: candidate.ordinal))
