"""Shared workflow-gate resume logic (D2b lift).

Lifted out of the MCP plugin (``_workflow_tools`` — ``_deposit``, ``_gate_model``,
``_pending_gates``) so the CLI ``func builtin workflow resume`` and the MCP
``resume_gate`` tool call **one** implementation rather than the CLI
re-implementing plugin-local logic. Re-exported through
``functualize.app.utils`` — the public door both ``_cli`` and the plugin use.

The result dicts match what the MCP ``_deposit`` returned before the lift, so
re-pointing the tool at these functions is behaviour-preserving.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._engine.recording import InputRecorder
from functualize._gate._evaluation import evaluate_submission
from functualize._primitives import gate_requests
from functualize._types.errors import GateNotFoundError, InputRequestNotOpenError
from functualize._types.gate_resolution import EvaluationOutcome
from functualize._types.naming import resolve_name

if TYPE_CHECKING:
    from collections.abc import Iterable


def _is_runtime_store(store: Any) -> bool:
    """True when ``store`` is the selected ``RuntimeStore`` port.

    ``selected_workflow_store`` hands the answer path either a scope document
    (``ScopeStore``) or the runtime store itself, and the two record seams are
    chosen on exactly this: the port carries the ``inputs`` reader, the
    document does not. Probing anything else — ``profile``, ``transaction`` —
    would make the seam choice a capability survey rather than one question
    with one answer.
    """
    return hasattr(store, "inputs")


def _candidate_entry(candidate: Any) -> dict[str, Any]:
    """One candidate as every surface renders it, provenance included.

    The same projection for both seams, because the same value backs it: the
    document backend stores these fields on the gate record and the
    relational backend in ``input_candidates`` rows, and a reader comparing
    two projects' answers must not see the storage shape.
    """
    entry: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "ordinal": candidate.ordinal,
        "source": candidate.source,
        "submitted_at": candidate.submitted_at.isoformat(),
        "outcome": candidate.evaluation.outcome.value,
        "detail": candidate.evaluation.detail,
        "errors": [list(pair) for pair in candidate.evaluation.errors],
        "resolver_class": candidate.resolver_class,
        "channel": candidate.channel,
        "schema": {"id": candidate.schema_id, "version": candidate.schema_version},
        "payload_hash": candidate.payload_hash,
        "supersedes_candidate_id": candidate.supersedes_candidate_id,
        # Attached evidence: references plus digests, never bytes. Rendered
        # beside — not inside — ``evidence``, which a strategy rung's own
        # evaluation mapping already owns (spec §3.3: that mapping is not
        # attached evidence and is unchanged).
        "evidence_refs": [
            {"ref": ref.ref, "digest": ref.digest} for ref in candidate.evidence_refs
        ],
    }
    if candidate.evaluation.evidence is not None:
        entry["evidence"] = dict(candidate.evaluation.evidence)
    return entry


def _decision_entry(decision: Any) -> dict[str, Any]:
    """One decision as every surface renders it."""
    return {
        "accepted_id": decision.accepted_id,
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "observed_candidate_ids": list(decision.observed_candidate_ids),
        "decided_at": decision.decided_at.isoformat(),
    }


def _resolution_view(
    store: Any, scope_id: str, gate: str, record: dict[str, Any]
) -> dict[str, Any]:
    """Read recorded evaluations without validating or exposing payloads.

    The candidate entries keep the shape document projects have always seen
    (pinned by the draft suite); the provenance the record now carries rides
    the port flavour's projection (:func:`_candidate_entry`) and the record
    itself, and the top level gains the acceptance's identity and decision —
    additive keys, read by key.
    """
    lease = store.get_lease(scope_id)
    request = gate_requests.request_for(
        scope_id, gate, record, lease.generation if lease else 0
    )
    candidates = gate_requests.candidates_for(record)
    decision = gate_requests.decision_for(scope_id, gate, record)
    projected: list[dict[str, Any]] = []
    for candidate in candidates:
        entry: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "ordinal": candidate.ordinal,
            "source": candidate.source,
            "submitted_at": candidate.submitted_at.isoformat(),
            "outcome": candidate.evaluation.outcome.value,
            "detail": candidate.evaluation.detail,
            "errors": [list(pair) for pair in candidate.evaluation.errors],
        }
        if candidate.evaluation.evidence is not None:
            entry["evidence"] = dict(candidate.evaluation.evidence)
        projected.append(entry)
    return {
        "request_id": request.request_id,
        "request_status": request.status,
        "accepted_id": decision.accepted_id if decision is not None else None,
        "causal": {
            "run_id": request.run_id,
            "workflow_id": scope_id,
            "step": request.position,
            "generation": request.generation,
        },
        "candidates": projected,
        "decision": _decision_entry(decision) if decision is not None else None,
    }


def _port_resolution(store: Any, request: Any) -> dict[str, Any]:
    """The resolution view over the ``InputReader`` — no scope document read.

    The same shape :func:`_resolution_view` renders from the gate record,
    answered by the port instead: the request with its causal identity, its
    candidates with provenance, and the decision the acceptance recorded.
    """
    candidates = store.inputs.candidates_for(request.request_id)
    decision = store.inputs.decision(request.request_id)
    return {
        "request_id": request.request_id,
        "request_status": request.status,
        "accepted_id": decision.accepted_id if decision is not None else None,
        "causal": {
            "run_id": request.run_id,
            "workflow_id": request.scope_id,
            "step": request.position,
            "generation": request.generation,
        },
        "candidates": [_candidate_entry(candidate) for candidate in candidates],
        "decision": _decision_entry(decision) if decision is not None else None,
    }


def pending_gates(scope: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Gates in this scope with an empty payload slot, in name order.

    Pure: reads only the scope dict, so both surfaces can call it without an
    app or a store.
    """
    gates = scope.get("gates", {})
    if not isinstance(gates, dict):
        return []
    return [
        (name, record)
        for name, record in sorted(gates.items())
        if isinstance(record, dict) and record.get("payload") is None
    ]


def _canonical_gate(known: Iterable[str], gate: str, *, scope_id: str) -> str:
    """The canonical spelling of a gate reference, against the gates that exist.

    The one resolver every public gate entry calls first: an exact match wins,
    then the canonical form, so a reference spelled the way Python spells it
    (`approve_refund`) reaches the gate declared under `approve-refund`. A
    reference that matches nothing is a caller error the caller cannot
    ignore: it raises, naming the workflow and the gates that do exist.
    """
    names = sorted(known)
    try:
        return resolve_name(gate, names)
    except LookupError:
        raise GateNotFoundError(gate, scope_id=scope_id, known=names) from None


def _resolve_gate_model(
    app: Any, scope: dict[str, Any], gate: str
) -> tuple[Any, dict[str, Any] | None]:
    """Materialize the gate's Pydantic model from the live workflow.

    The one place that imports the declaring module. A persisted JSON schema is
    enough to *describe* a gate but not to *validate* against it — re-implementing
    Pydantic over the schema would accept inputs the workflow then rejects, which
    is worse than not validating at all.
    """
    workflow_name = scope.get("workflow")
    try:
        entry = app.execution_engine.materialize_job(workflow_name)
        declaration = entry.function.__functualize_workflow__
        node = declaration.node(gate)
        if node is None:
            return None, {
                "error": "gate_unresolvable",
                "message": (
                    f"Workflow '{workflow_name}' no longer declares gate "
                    f"'{gate}'; the run was parked under an older declaration."
                ),
            }
        return node.awaits, None
    except Exception as exc:
        return None, {
            "error": "gate_unresolvable",
            "message": (
                f"Cannot load the model for gate '{gate}' from workflow "
                f"'{workflow_name}': {type(exc).__name__}: {exc}"
            ),
        }


def deposit_gate_input(
    app: Any,
    store: Any,
    scope_id: str,
    gate: str,
    payload: dict[str, Any],
    *,
    source: str = "api",
) -> dict[str, Any]:
    """Evaluate and record one submitted candidate for the gate.

    The shared resume path: the MCP ``resume_gate`` tool and the CLI
    ``func builtin workflow resume`` both call this, so there is one notion of
    "accept input for a gate". An invalid attempt is recorded while the
    request remains open; only an accepted candidate writes a payload.

    Returns a flat result dict:
    - ``{"status": "input_accepted", "gate", "workflow_id", "message"}`` on success
    - ``{"error": "gate_unresolvable", "message"}`` if the model won't load
    - ``{"error": "validation_error", "message", "gate"}`` if the input is invalid
    """
    scope = store.get_scope(scope_id) or {}
    gate = _canonical_gate(scope.get("gates") or {}, gate, scope_id=scope_id)
    model, error = _resolve_gate_model(app, scope, gate)
    if error is not None:
        return error

    evaluation, validated = evaluate_submission(model, payload)
    record = store.get_gate(scope_id, gate)
    if record is None:
        return {
            "error": "gate_already_answered",
            "message": f"Gate '{gate}' has no open request.",
        }
    resolution = _resolution_view(store, scope_id, gate, record)
    candidate = InputRecorder().submitted(
        resolution["request_id"],
        source,
        evaluation,
        validated if validated is not None else payload,
        ordinal=len(resolution["candidates"]),
        now=datetime.now(UTC),
    )
    try:
        # TRANSITIONAL(FUN-21): this candidate still lands in the scope document.
        gate_requests.append_candidate(store, scope_id, gate, candidate)
    except InputRequestNotOpenError:
        return {
            "error": "gate_already_answered",
            "message": f"Gate '{gate}' is already answered.",
        }

    if evaluation.outcome is EvaluationOutcome.INVALID:
        return {
            "error": "validation_error",
            "message": f"Input does not satisfy '{model.__name__}': {evaluation.detail}",
            "gate": gate,
        }
    # Name the command, not the concept. "Run the workflow job with scope_id
    # 'X'" named neither the flag nor its position, and the audit that found
    # this got both wrong twice before reading `dispatch.py`. The job address
    # is dotted (`audit.audit-run`) and the command path is not
    # (`audit audit-run`), so the dotted form would print something that
    # answers `No such command`.
    #
    # `--wf-resume` replaces `--scope-id`, and it does more than rename: this
    # hint is now a command that *finishes the run*, where the old one only
    # started another attempt at it.
    workflow_name = str(scope.get("workflow") or "")
    resume_hint = (
        f" Continue with: <your entry point> {workflow_name.replace('.', ' ')} "
        f"--wf-resume {scope_id}"
        if workflow_name
        else f" Re-run the workflow job with --wf-resume {scope_id}."
    )
    return {
        "status": "input_accepted",
        "gate": gate,
        "workflow_id": scope_id,
        "request_id": resolution["request_id"],
        "message": f"Input accepted for gate '{gate}'.{resume_hint}",
    }
