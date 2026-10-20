"""Answering a gate: partial, whole, or corrected.

``answer`` **records**. ``resume`` **advances**. One meaning each, on every
surface — the two used to be the same word, and every "resume" verb in the
repository was in fact a deposit.

**Why a draft.** ``deposit_gate_input`` is all-or-nothing by construction:
``model(**payload)`` raises on any missing required field, and nothing is stored
on failure. So two actors could not fill different fields of one gate, and a
gate could not be corrected at all — once ``payload`` is non-``None``,
``pending_gates`` stops listing it and every addressing path answers
``gate_not_found``.

**The invariant that makes drafts safe:** a payload is written only by an
accepted candidate. Failed attempts stay in the candidate record; partial
input stays in ``draft`` until a complete answer is accepted.

Partial input lives in ``draft``; the walker never reads it. A blocked walk
stays blocked until the draft validates whole, so a partially-answered gate is
indistinguishable *to the walk* from an unanswered one — which is the correct
meaning. Nothing about resume, replay or memoization changes.

**Auto-commit is the default.** Every mutating call attempts a commit at the
end, so the existing one-shot flow is unchanged: supplying a complete object
answers the gate in one command, exactly as before. ``commit=False`` exists for
the case where a second actor must review before the gate opens.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._engine.recording import InputRecorder
from functualize._engine.recording.input_recorder import (
    VALIDATION_POLICY,
    schema_identity,
)
from functualize._gate._evaluation import evaluate_submission
from functualize._primitives import gate_requests
from functualize._types.errors import GateNotFoundError, InputRequestNotOpenError
from functualize._types.gate_resolution import EvaluationOutcome
from functualize._types.persistence import EPILOGUE_STEP_KEY
from functualize.app._workflow_resume import (
    _canonical_gate,
    _is_runtime_store,
    _port_resolution,
    _resolution_view,
    _resolve_gate_model,
    pending_gates,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._types.gate_resolution import EvidenceRef

__all__ = ["answer_gate", "gate_draft", "resolve_gate"]


def resolve_gate(
    store: Any,
    scope_id: str | None,
    gate: str | None,
    *,
    include_answered: bool = False,
) -> tuple[str, str] | dict[str, Any]:
    """Resolve ``(scope_id, gate)`` from whichever half the caller supplied.

    Joint addressing, each identifier optional when unambiguous. This closes
    the hole where the MCP ``resume_gate`` took a gate only, ``resume_workflow``
    took a scope only, and **each referred the caller to the other** on
    ambiguity — a caller holding both had no tool that would accept them.

    Ambiguity never guesses: zero candidates is an error naming the survey verb,
    exactly one is used, several are listed. Never "newest wins" — ``blocked_at``
    resets on every re-block, so it is not computable anyway.

    ``include_answered`` widens the search past the pending set. Correcting an
    answer means addressing a gate that is, by definition, no longer pending —
    without this, ``--reopen`` could never name its own target.

    Returns ``(scope_id, gate)`` or an error envelope. With both halves named,
    a gate the scope does not have raises rather than returning: the caller
    addressed one workflow and one gate, and a miss is a typo, not a survey
    result.
    """
    if _is_runtime_store(store):
        return _resolve_gate_port(
            store, scope_id, gate, include_answered=include_answered
        )
    if scope_id is not None and gate is not None:
        # Both named: there is nothing to disambiguate, so this path must not
        # consult the pending set at all. It did, and `--reopen` could not
        # address the answered gate it exists to correct.
        scope = store.get_scope(scope_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
        return scope_id, _canonical_gate(
            scope.get("gates") or {}, gate, scope_id=scope_id
        )

    candidates: list[tuple[str, str]] = []
    for sid in store.scope_ids():
        if scope_id is not None and sid != scope_id:
            continue
        scope = store.get_scope(sid)
        if scope is None:
            continue
        if scope_id is None and scope.get("status") not in ("running", "blocked"):
            continue
        names = (
            sorted(scope.get("gates") or {})
            if include_answered
            else [name for name, _record in pending_gates(scope)]
        )
        if gate is None:
            candidates.extend((sid, name) for name in names)
            continue
        # A survey never raises: a gate that does not match this scope may
        # exist elsewhere, or already be answered, and the caller asked a
        # question whose honest answer can be an empty list.
        try:
            resolved = _canonical_gate(names, gate, scope_id=sid)
        except GateNotFoundError:
            continue
        candidates.append((sid, resolved))

    if scope_id is not None and store.get_scope(scope_id) is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")

    if not candidates:
        where = f" in '{scope_id}'" if scope_id else ""
        what = f"'{gate}'" if gate else "any gate"
        return {
            "error": "gate_not_found",
            "message": (
                f"No workflow is awaiting {what}{where}. "
                "Run `func builtin workflow list` to see what is."
            ),
        }
    if len(candidates) > 1:
        return {
            "error": "ambiguous_gate",
            "message": (
                f"{len(candidates)} gates match. Name both the workflow id and "
                "the gate."
            ),
            "candidates": [
                {"workflow_id": sid, "gate": name} for sid, name in candidates
            ],
        }
    return candidates[0]


def gate_draft(app: Any, store: Any, scope_id: str, gate: str) -> dict[str, Any]:
    """What has been supplied, what is still missing, and what is invalid.

    The one genuinely new computation in this module, and it is a projection
    over ``model.model_fields`` plus a trial validation — not new state.
    ``missing`` and ``invalid`` come from the same ``ValidationError`` the commit
    path already produces, so the two can never describe the same draft
    differently.

    On a ``RuntimeStore`` the draft *is* the newest non-accepted candidate's
    payload (spec §3.5): a relational store records drafts only as
    submissions, so what has been supplied so far is read back off the
    candidate that supplied it.
    """
    if _is_runtime_store(store):
        return _gate_draft_port(app, store, scope_id, gate)
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
    gate = _canonical_gate(scope.get("gates") or {}, gate, scope_id=scope_id)
    model, error = _resolve_gate_model(app, scope, gate)
    if error is not None:
        return error

    record = store.get_gate(scope_id, gate) or {}
    draft = (store.get_gate_draft(scope_id, gate) or {}).get("values") or {}
    missing, invalid = _validation_report(model, draft)

    return {
        "workflow_id": scope_id,
        "gate": gate,
        "model": model.__name__,
        "input_schema": record.get("input_schema") or {},
        "draft": draft,
        "satisfied": sorted(k for k in draft if k not in {e["field"] for e in invalid}),
        "missing": missing,
        "invalid": invalid,
        "complete": not missing and not invalid,
        "answered": record.get("payload") is not None,
        "resolution": _resolution_view(store, scope_id, gate, record),
    }


def answer_gate(
    app: Any,
    store: Any,
    scope_id: str,
    gate: str,
    values: dict[str, Any] | None = None,
    *,
    mode: str = "merge",
    unset: list[str] | None = None,
    clear: bool = False,
    commit: bool = True,
    reopen: bool = False,
    source: str = "api",
    evidence: Sequence[EvidenceRef] = (),
) -> dict[str, Any]:
    """Record input for a gate. Never runs anything.

    One answer path, two record seams: over a scope document the candidate
    and its decision land on the gate record (``gate_requests``); over a
    ``RuntimeStore`` they land in one transaction unit as ``inputs.append``
    and ``inputs.decide``, with the outbox intent beside them on a store
    whose profile declares one — and the dispatcher drains **after** the unit
    commits, never before, so an effect is never dispatched against an
    uncommitted decision.

    Args:
        values: Fields to merge into (or replace) the draft.
        mode: ``"merge"`` (default) or ``"replace"``.
        unset: Field names to remove from the draft.
        clear: Discard the draft entirely, before applying ``values``.
        commit: Attempt to validate-and-answer at the end. On by default, so
            the one-shot flow is unchanged. Refused on a ``RuntimeStore``,
            which records drafts only as submissions.
        reopen: Move an answered payload back into the draft first.
        source: The surface answering (``cli``, ``mcp``, ``api``).
        evidence: References plus digests to attach to the submission —
            pointers to bytes stored elsewhere, never the bytes.

    Returns a flat result dict carrying the draft report, plus ``status``:
    ``"answered"`` when the gate was committed, ``"drafted"`` when it was not.
    """
    if _is_runtime_store(store):
        return _answer_gate_port(
            app,
            store,
            scope_id,
            gate,
            values,
            mode=mode,
            unset=unset,
            clear=clear,
            commit=commit,
            reopen=reopen,
            source=source,
            evidence=evidence,
        )
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")

    gate = _canonical_gate(scope.get("gates") or {}, gate, scope_id=scope_id)
    record = store.get_gate(scope_id, gate)

    model, error = _resolve_gate_model(app, scope, gate)
    if error is not None:
        return error

    if reopen:
        refusal = _reopen(app, store, scope, scope_id, gate, record)
        if refusal is not None:
            return refusal

    if store.get_gate(scope_id, gate).get("payload") is not None:
        # Not a silent overwrite. An answered gate is out of the pending set on
        # every surface, so a caller who thinks they are editing it is working
        # from a stale view; --reopen is the explicit way in.
        return _error(
            "gate_already_answered",
            f"Gate '{gate}' is already answered. Use --reopen to correct it.",
        )

    draft = (
        {}
        if clear
        else dict((store.get_gate_draft(scope_id, gate) or {}).get("values") or {})
    )
    if mode == "replace":
        draft = dict(values or {})
    elif values:
        draft.update(values)
    for key in unset or []:
        draft.pop(key, None)

    store.put_gate_draft(scope_id, gate, draft)

    report = gate_draft(app, store, scope_id, gate)
    if not commit or not report["complete"]:
        report["status"] = "drafted"
        report["message"] = _drafted_message(gate, report)
        return report

    evaluation, validated = evaluate_submission(model, draft)
    resolution = _resolution_view(
        store, scope_id, gate, store.get_gate(scope_id, gate) or {}
    )
    schema_id, schema_version = schema_identity(model)
    now = datetime.now(UTC)
    earlier = gate_requests.candidates_for(store.get_gate(scope_id, gate) or {})
    supersedes = _newest_unaccepted(earlier)
    candidate = InputRecorder().submitted(
        resolution["request_id"],
        source,
        evaluation,
        validated if validated is not None else dict(draft),
        ordinal=len(earlier),
        now=now,
        schema_id=schema_id,
        schema_version=schema_version,
        supersedes=supersedes,
        evidence=evidence,
    )
    decision = (
        InputRecorder().decided(
            resolution["request_id"],
            [*earlier, candidate],
            candidate.candidate_id,
            policy_id=VALIDATION_POLICY,
            policy_version=schema_version,
            now=now,
        )
        if evaluation.outcome is EvaluationOutcome.ACCEPTED
        else None
    )
    try:
        # One unit: the candidate, and — when it accepts — its decision. A
        # decision recorded beside the accepted candidate is what a later
        # reader reconciles the acceptance against (spec §3.2), so the two
        # never commit separately.
        with store.batch():
            gate_requests.append_candidate(store, scope_id, gate, candidate)
            if decision is not None:
                gate_requests.record_decision(store, scope_id, gate, decision)
    except InputRequestNotOpenError:
        return _error(
            "gate_already_answered",
            f"Gate '{gate}' is already answered. Use --reopen to correct it.",
        )
    if evaluation.outcome is EvaluationOutcome.INVALID:
        report = gate_draft(app, store, scope_id, gate)
        report["invalid"] = [
            {"field": field, "message": message} for field, message in evaluation.errors
        ]
        report["complete"] = False
        report["status"] = "drafted"
        report["message"] = _drafted_message(gate, report)
        return report
    store.clear_gate_draft(scope_id, gate)

    answered = gate_draft(app, store, scope_id, gate)
    answered["status"] = "answered"
    answered["message"] = (
        f"Gate '{gate}' answered. Continue with: "
        f"func builtin workflow resume {scope_id}"
    )
    return answered


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _newest_unaccepted(candidates: Any) -> str | None:
    """The newest candidate an accepted one does not supersede, by id.

    A surface submission supersedes the newest non-accepted candidate
    (spec §3.1) — that is the draft it corrects, on both seams.
    """
    for candidate in reversed(list(candidates)):
        if candidate.evaluation.outcome is not EvaluationOutcome.ACCEPTED:
            return str(candidate.candidate_id)
    return None


def _port_canonical_gate(
    app: Any, store: Any, scope_id: str, view: Any, gate: str
) -> str:
    """Resolve a gate reference against what the port knows of the scope.

    The request the walk recorded names the gate canonically; the declared
    workflow is the wider set a typo can be checked against. Between them a
    reference spelled the way Python spells it reaches the gate the walk
    recorded under its declared name, exactly as ``_canonical_gate`` does over
    a scope document's ``gates`` mapping.
    """
    known: list[str] = []
    request = store.inputs.for_gate(scope_id, gate)
    if request is not None:
        known.append(request.gate_name)
    try:
        entry = app.execution_engine.materialize_job(view.workflow)
        declaration = entry.function.__functualize_workflow__
        known.extend(
            node.name
            for node in declaration.nodes
            if getattr(node, "awaits", None) is not None and node.name not in known
        )
    except Exception:
        # The declaration is the wider set, not the authority: a scope whose
        # workflow module went missing still addresses its recorded gate.
        pass
    return _canonical_gate(sorted(known), gate, scope_id=scope_id)


def _resolve_gate_port(
    store: Any, scope_id: str | None, gate: str | None, *, include_answered: bool
) -> tuple[str, str] | dict[str, Any]:
    """`resolve_gate` over the port: joint addressing against open requests.

    The survey lists what ``inputs.awaiting`` answers — the open requests —
    and the both-named path resolves against the recorded request's own name,
    whatever the request's status, because that is how ``--reopen`` addresses
    the answered gate it exists to correct. ``resolve_gate``'s public
    signature carries no app, so the declared-graph typo check the
    app-carrying seams get is not available here; the recorded name is the
    authority for what the walk blocked on.
    """
    if scope_id is not None:
        view = store.workflows.workflow(scope_id)
        if view is None:
            return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
        if gate is not None:
            request = store.inputs.for_gate(scope_id, gate)
            known = [request.gate_name] if request is not None else []
            return scope_id, _canonical_gate(known, gate, scope_id=scope_id)

    candidates: list[tuple[str, str]] = []
    for request in store.inputs.awaiting():
        if scope_id is not None and request.scope_id != scope_id:
            continue
        if gate is None:
            candidates.append((request.scope_id, request.gate_name))
            continue
        try:
            resolved = _canonical_gate(
                [request.gate_name], gate, scope_id=request.scope_id
            )
        except GateNotFoundError:
            continue
        candidates.append((request.scope_id, resolved))

    if not candidates:
        where = f" in '{scope_id}'" if scope_id else ""
        what = f"'{gate}'" if gate else "any gate"
        return {
            "error": "gate_not_found",
            "message": (
                f"No workflow is awaiting {what}{where}. "
                "Run `func builtin workflow list` to see what is."
            ),
        }
    if len(candidates) > 1:
        return {
            "error": "ambiguous_gate",
            "message": (
                f"{len(candidates)} gates match. Name both the workflow id and "
                "the gate."
            ),
            "candidates": [
                {"workflow_id": sid, "gate": name} for sid, name in candidates
            ],
        }
    return candidates[0]


def _gate_draft_port(app: Any, store: Any, scope_id: str, gate: str) -> dict[str, Any]:
    """`gate_draft` over the port: the draft is the last submission's payload."""
    view = store.workflows.workflow(scope_id)
    if view is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
    gate = _port_canonical_gate(app, store, scope_id, view, gate)
    request = store.inputs.for_gate(scope_id, gate)
    if request is None:
        return _error(
            "gate_not_found",
            f"Workflow '{scope_id}' has no gate '{gate}' awaiting an answer.",
        )
    model, error = _resolve_gate_model(app, {"workflow": view.workflow}, gate)
    if error is not None:
        return error

    target = _newest_unaccepted_target(store.inputs.candidates_for(request.request_id))
    draft = (
        dict(target.payload)
        if target is not None and isinstance(target.payload, dict)
        else {}
    )
    missing, invalid = _validation_report(model, draft)
    schema = request.schema
    if schema is None and hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()

    return {
        "workflow_id": scope_id,
        "gate": gate,
        "model": model.__name__,
        "input_schema": schema or {},
        "draft": draft,
        "satisfied": sorted(k for k in draft if k not in {e["field"] for e in invalid}),
        "missing": missing,
        "invalid": invalid,
        "complete": not missing and not invalid,
        "answered": request.status in ("accepted", "consumed"),
        "resolution": _port_resolution(store, request),
    }


def _newest_unaccepted_target(candidates: Any) -> Any:
    """The newest non-accepted candidate — the submission a draft continues."""
    for candidate in reversed(list(candidates)):
        if candidate.evaluation.outcome is not EvaluationOutcome.ACCEPTED:
            return candidate
    return None


def _answer_gate_port(
    app: Any,
    store: Any,
    scope_id: str,
    gate: str,
    values: dict[str, Any] | None,
    *,
    mode: str,
    unset: list[str] | None,
    clear: bool,
    commit: bool,
    reopen: bool,
    source: str,
    evidence: Sequence[EvidenceRef],
) -> dict[str, Any]:
    """`answer_gate` over the port seam: one unit, then the drain.

    The submission, its decision and — on a store whose profile declares
    ``durable_outbox`` — its effect intent commit as **one** transaction unit
    (the same shape ``FrontierWalk.record_candidates`` gives a ladder
    acceptance), and the dispatcher drains only after that unit has committed.
    Every submission is recorded, valid or not (D-5): an invalid attempt is a
    candidate, and it is the draft the next submission continues.
    """
    view = store.workflows.workflow(scope_id)
    if view is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
    gate = _port_canonical_gate(app, store, scope_id, view, gate)
    model, error = _resolve_gate_model(app, {"workflow": view.workflow}, gate)
    if error is not None:
        return error

    request = store.inputs.for_gate(scope_id, gate)
    if not commit:
        # Refused before anything is written: a relational store records
        # drafts only as submissions, so there is no draft slot to hold an
        # uncommitted answer in (spec §3.5).
        return _error(
            "draft_requires_commit",
            f"A relational store records drafts only as submissions; answer "
            f"gate '{gate}' in one commit, or use --show to read the draft "
            "its last submission holds.",
        )
    if reopen:
        refusal = _reopen_port(app, store, view, scope_id, gate, request)
        if refusal is not None:
            return refusal
        request = store.inputs.for_gate(scope_id, gate)
    if request is None:
        return _error(
            "gate_not_found",
            f"Workflow '{scope_id}' has no gate '{gate}' awaiting an answer.",
        )
    if request.status != "open":
        return _error(
            "gate_already_answered",
            f"Gate '{gate}' is already answered. Use --reopen to correct it.",
        )

    # The draft is the newest non-accepted candidate's payload — the same
    # candidate this submission supersedes.
    recorded = list(store.inputs.candidates_for(request.request_id))
    target = _newest_unaccepted_target(recorded)
    draft = (
        {}
        if clear
        else (
            dict(target.payload)
            if target is not None and isinstance(target.payload, dict)
            else {}
        )
    )
    if mode == "replace":
        draft = dict(values or {})
    elif values:
        draft.update(values)
    for key in unset or []:
        draft.pop(key, None)

    evaluation, validated = evaluate_submission(model, draft)
    schema_id, schema_version = schema_identity(model)
    now = datetime.now(UTC)
    candidate = InputRecorder().submitted(
        request.request_id,
        source,
        evaluation,
        validated if validated is not None else dict(draft),
        ordinal=len(recorded),
        now=now,
        schema_id=schema_id,
        schema_version=schema_version,
        supersedes=target.candidate_id if target is not None else None,
        evidence=evidence,
    )
    if evaluation.outcome is EvaluationOutcome.INVALID:
        with store.transaction() as tx:
            tx.inputs.append(candidate)
        report = _gate_draft_port(app, store, scope_id, gate)
        report["invalid"] = [
            {"field": field, "message": message} for field, message in evaluation.errors
        ]
        report["complete"] = False
        report["status"] = "drafted"
        report["message"] = _drafted_message(gate, report)
        return report

    decision = InputRecorder().decided(
        request.request_id,
        [*recorded, candidate],
        candidate.candidate_id,
        policy_id=VALIDATION_POLICY,
        policy_version=schema_version,
        now=now,
    )
    effect = InputRecorder().accepted_effect(
        decision, scope_id=scope_id, gate_name=gate
    )
    durable = bool(store.profile.durable_outbox)
    with store.transaction() as tx:
        tx.inputs.append(candidate)
        tx.inputs.decide(decision)
        if durable:
            tx.effects.append(
                effect.namespace,
                effect.topic,
                effect.payload,
                effect.idempotency_key,
            )
    # After the commit — never before it. An effect dispatched against an
    # uncommitted decision is the failure mode the recovery proof (wave 4)
    # exists to show absent; on a store without an outbox this drains
    # nothing and the answer is none the less durable for it.
    from functualize._app.effects import drain

    drain(app, store)

    answered = _gate_draft_port(app, store, scope_id, gate)
    answered["status"] = "answered"
    answered["message"] = (
        f"Gate '{gate}' answered. Continue with: "
        f"func builtin workflow resume {scope_id}"
    )
    return answered


def _reopen_port(
    app: Any, store: Any, view: Any, scope_id: str, gate: str, request: Any
) -> dict[str, Any] | None:
    """Supersede the accepted answer over the port, or refuse. None on success.

    The same refusal `_reopen` gives a scope document, from the port's own
    facts: the walk having passed the gate is read off the recorded steps and
    position, not off a document.
    """
    if request is None or request.status not in ("accepted", "consumed"):
        return _error("gate_not_answered", f"Gate '{gate}' has no answer to reopen.")
    if _walk_has_passed_port(app, store, view, gate):
        return {
            "error": "gate_already_consumed",
            "message": (
                f"The walk has already passed gate '{gate}' (position: "
                f"{view.position}). Its answer produced the results "
                "recorded after it, so it cannot be corrected in place. Start a "
                "fresh run."
            ),
            "gate": gate,
            "position": view.position,
        }
    command = InputRecorder().superseding(
        scope_id=scope_id,
        gate_name=gate,
        request_id=request.request_id,
        now=datetime.now(UTC),
    )
    with store.transaction() as tx:
        tx.inputs.supersede(command)
    return None


def _walk_has_passed_port(app: Any, store: Any, view: Any, gate: str) -> bool:
    """`_walk_has_passed` over the port's steps and position.

    The epilogue is a step keyed ``__epilogue__`` here rather than a scope
    field; everything else — the downstream set from the declared graph, the
    position, any step record after the gate — is the same evidence read from
    the store the walk actually wrote.
    """
    steps = list(store.workflows.steps(view.scope_id))
    if any(step.step_key.split("::", 1)[0] == EPILOGUE_STEP_KEY for step in steps):
        return True

    downstream = _downstream_of(app, {"workflow": view.workflow}, gate)
    if not downstream:
        return False

    position = view.position
    if isinstance(position, str) and position in downstream:
        return True
    return any(step.step_key.split("::", 1)[0] in downstream for step in steps)


def _reopen(
    app: Any,
    store: Any,
    scope: dict[str, Any],
    scope_id: str,
    gate: str,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    """Supersede the answer and seed a fresh draft, or refuse. None on success.

    **Refused once the walk has consumed the answer.** The walker records the
    gate node as replayed and advances past it, so a scope whose position is
    past the gate has already used the input. Reopening then would leave the
    recorded step results downstream of an answer that no longer exists —
    silently, which is the failure mode worth refusing over. The recovery is a
    fresh scope, and the message names the position so the refusal is checkable
    rather than merely asserted.
    """
    if record.get("payload") is None:
        return _error(
            "gate_not_answered",
            f"Gate '{gate}' has no answer to reopen.",
        )
    if _walk_has_passed(app, scope, gate):
        return {
            "error": "gate_already_consumed",
            "message": (
                f"The walk has already passed gate '{gate}' (position: "
                f"{scope.get('position')}). Its answer produced the results "
                "recorded after it, so it cannot be corrected in place. Start a "
                "fresh run."
            ),
            "gate": gate,
            "position": scope.get("position"),
        }
    now = datetime.now(UTC)
    lease = store.get_lease(scope_id)
    opened = InputRecorder().opened(
        scope_id=scope_id,
        generation=lease.generation if lease else 0,
        gate_name=gate,
        position=gate,
        now=now,
        schema=record.get("input_schema"),
        prompt=record.get("prompt"),
        model=str(record.get("model") or ""),
        tools=tuple(record.get("tools") or ()),
    )
    gate_requests.supersede_request(
        store, scope_id, gate, new_request_id=opened.request_id, now=now
    )
    return None


def _walk_has_passed(app: Any, scope: dict[str, Any], gate: str) -> bool:
    """True when the walk is recorded as having gone *past* ``gate``.

    Three ways to have passed, and all three are needed:

    1. **The body ran.** An epilogue record means the walk reached ``END``, so
       every gate on the taken path was consumed. This is the case a
       position check alone misses entirely — a completed walk sets ``position``
       back to ``None``, which reads as "nowhere" rather than "past everything".
    2. **A node after the gate has a step record.** The most direct evidence:
       something downstream actually ran on this answer.
    3. **The position is a node after the gate.** A walk parked further along.

    "After" comes from the *declared graph*, not from guessing at the scope: it
    is a property of the edges, and reconstructing it from step records would be
    a reader rebuilding what the writer already knows
    (``contributor/reference/pitfalls.md`` §22).

    A scope still parked **at** the gate has not passed it — that is exactly the
    case reopening is for. A graph that can no longer be loaded yields an empty
    downstream set and so reads as *not passed*: refusing a correction because
    the workflow's declaration went missing would strand the run for a reason
    the user cannot act on.
    """
    if scope.get("epilogue") is not None:
        return True

    downstream = _downstream_of(app, scope, gate)
    if not downstream:
        return False

    position = scope.get("position")
    if isinstance(position, str) and position in downstream:
        return True

    steps = scope.get("steps") or {}
    return any(
        key.split("::", 1)[0] in downstream for key in steps if isinstance(key, str)
    )


def _downstream_of(app: Any, scope: dict[str, Any], gate: str) -> set[str]:
    """Every node reachable from ``gate``, excluding ``gate`` itself."""
    from functualize.app._workflow_view import _topology

    adjacency: dict[str, list[str]] = {}
    for edge in _topology(app, scope.get("workflow")).get("edges") or []:
        source = edge.get("from")
        if not isinstance(source, str):
            continue
        targets = (
            list(edge.get("targets", {}).values())
            if edge.get("conditional")
            else [edge.get("to")]
        )
        adjacency.setdefault(source, []).extend(
            t for t in targets if isinstance(t, str)
        )

    seen: set[str] = set()
    frontier = list(adjacency.get(gate, []))
    while frontier:
        node = frontier.pop()
        if node in seen or node == gate:
            continue
        seen.add(node)
        frontier.extend(adjacency.get(node, []))
    return seen


def _validation_report(
    model: Any, draft: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(missing, invalid)`` from one trial validation.

    Both come from the same ``ValidationError`` the commit path produces, so
    ``--show`` cannot describe a draft the commit would treat differently.
    """
    try:
        model(**draft)
    except Exception as exc:
        errors = getattr(exc, "errors", None)
        if not callable(errors):
            return [], [{"field": "", "message": str(exc)}]
        missing: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        fields = getattr(model, "model_fields", {})
        for item in errors():
            location = item.get("loc") or ()
            field = str(location[0]) if location else ""
            entry = {"field": field, "message": item.get("msg", "")}
            if item.get("type") == "missing":
                spec = fields.get(field)
                entry["type"] = str(getattr(spec, "annotation", "")) if spec else ""
                entry["description"] = getattr(spec, "description", "") or ""
                missing.append(entry)
            else:
                invalid.append(entry)
        return missing, invalid
    return [], []


def _drafted_message(gate: str, report: dict[str, Any]) -> str:
    """Say what is still needed, not merely that something is."""
    if report["invalid"]:
        problems = ", ".join(f"{e['field']}: {e['message']}" for e in report["invalid"])
        return f"Draft saved for '{gate}', but not valid — {problems}."
    if report["missing"]:
        names = ", ".join(
            f"{e['field']} ({e['type']})" if e.get("type") else e["field"]
            for e in report["missing"]
        )
        return f"Draft saved for '{gate}'. Still missing: {names}."
    return f"Draft saved for '{gate}'. Complete — pass --commit to answer the gate."


def _error(code: str, message: str) -> dict[str, Any]:
    """A flat error envelope — ``error`` is the machine-readable code."""
    return {"error": code, "message": message}
