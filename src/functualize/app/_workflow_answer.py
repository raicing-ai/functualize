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

**The invariant that makes drafts safe:**

    ``payload`` is non-null **iff** it is the output of a complete, successful
    ``model(**draft.values).model_dump()``.

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

from typing import Any

from functualize.app._workflow_resume import _resolve_gate_model, pending_gates

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

    Returns ``(scope_id, gate)`` or an error envelope.
    """
    if scope_id is not None and gate is not None:
        # Both named: there is nothing to disambiguate, so this path must not
        # consult the pending set at all. It did, and `--reopen` could not
        # address the answered gate it exists to correct.
        scope = store.get_scope(scope_id)
        if scope is None:
            return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")
        if store.get_gate(scope_id, gate) is None:
            return _error(
                "gate_not_found", f"Workflow '{scope_id}' has no gate '{gate}'."
            )
        return scope_id, gate

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
        for name in names:
            if gate is None or name == gate:
                candidates.append((sid, name))

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
    """
    scope = store.get_scope(scope_id) or {}
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
) -> dict[str, Any]:
    """Record input for a gate. Never runs anything.

    Args:
        values: Fields to merge into (or replace) the draft.
        mode: ``"merge"`` (default) or ``"replace"``.
        unset: Field names to remove from the draft.
        clear: Discard the draft entirely, before applying ``values``.
        commit: Attempt to validate-and-answer at the end. On by default, so
            the one-shot flow is unchanged.
        reopen: Move an answered payload back into the draft first.

    Returns a flat result dict carrying the draft report, plus ``status``:
    ``"answered"`` when the gate was committed, ``"drafted"`` when it was not.
    """
    scope = store.get_scope(scope_id)
    if scope is None:
        return _error("workflow_not_found", f"No workflow scope '{scope_id}'.")

    record = store.get_gate(scope_id, gate)
    if record is None:
        return _error(
            "gate_not_found", f"Workflow '{scope_id}' has no gate '{gate}'."
        )

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

    draft = {} if clear else dict((store.get_gate_draft(scope_id, gate) or {}).get("values") or {})
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

    # The one place `payload` is ever written on this path, and it writes the
    # validated dump — the same object the walker's own strategy path stores.
    store.deposit_gate_payload(scope_id, gate, model(**draft).model_dump())
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


def _reopen(
    app: Any,
    store: Any,
    scope: dict[str, Any],
    scope_id: str,
    gate: str,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    """Move the payload back to the draft, or refuse. None on success.

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
    store.reopen_gate(scope_id, gate)
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
