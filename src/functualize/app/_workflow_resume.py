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

from typing import Any


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
    app: Any, store: Any, scope_id: str, gate: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Validate ``payload`` against the gate's model, then deposit it.

    The shared resume path: the MCP ``resume_gate`` tool and the CLI
    ``func builtin workflow resume`` both call this, so there is one notion of
    "accept input for a gate". Nothing is stored if validation fails.

    Returns a flat result dict:
    - ``{"status": "input_accepted", "gate", "workflow_id", "message"}`` on success
    - ``{"error": "gate_unresolvable", "message"}`` if the model won't load
    - ``{"error": "validation_error", "message", "gate"}`` if the input is invalid
    """
    scope = store.get_scope(scope_id) or {}
    model, error = _resolve_gate_model(app, scope, gate)
    if error is not None:
        return error

    try:
        model(**payload)
    except Exception as exc:
        return {
            "error": "validation_error",
            "message": f"Input does not satisfy '{model.__name__}': {exc}",
            "gate": gate,
        }

    store.deposit_gate_payload(scope_id, gate, payload)
    # Name the command, not the concept. "Run the workflow job with scope_id
    # 'X'" named neither the flag nor its position, and the audit that found
    # this got both wrong twice before reading `dispatch.py`. The job address
    # is dotted (`audit.audit-run`) and the command path is not
    # (`audit audit-run`), so the dotted form would print something that
    # answers `No such command`.
    workflow_name = str(scope.get("workflow") or "")
    resume_hint = (
        f" Continue with: <your entry point> {workflow_name.replace('.', ' ')} "
        f"--scope-id {scope_id}"
        if workflow_name
        else f" Re-run the workflow job with --scope-id {scope_id}."
    )
    return {
        "status": "input_accepted",
        "gate": gate,
        "workflow_id": scope_id,
        "message": f"Input accepted for gate '{gate}'.{resume_hint}",
    }
