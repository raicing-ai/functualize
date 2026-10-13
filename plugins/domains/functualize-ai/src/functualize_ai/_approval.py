"""Tool-call approval — the single decision point for gated tools.

A ``ToolDef`` that carries approval state is enforced by the tool-execution
wrapper (the translator's ``_wrapper``) calling :func:`evaluate_tool_approval`
before the tool function runs. The semantics are fixed by the approved
shape intent:

- only a gate returning exactly ``True`` admits (fail-closed against a
  gate that forgets to ``return``);
- approval required with no gate refuses every call;
- a refusal is the tool's *result* — the agent loop continues, the model
  is told the call was refused;
- a gate that raises ends the run with the gate's own exception, never
  relabelled ``AINotAvailableError`` by the generic handlers above it.

This module is provider-agnostic and pure: no imports beyond the shared
types, no state, no I/O. ``ToolScope`` and any provider share it so the
refusal text cannot drift between the producer and the event emitters.
"""

from __future__ import annotations

import contextlib
from typing import Any

from functualize_ai._types import ToolCallContext, ToolDef

__all__ = [
    "evaluate_tool_approval",
    "is_tool_refusal",
    "mark_gate_failure",
    "refusal_message",
    "unwrap_gate_failure",
]

# Set on a gate's exception so the generic ``except Exception`` relabelers
# in AI.run / run_agent_loop / run_with_history can recognize it and
# re-raise the original instead of wrapping it in AINotAvailableError.
# Verified against pydantic-ai 1.107.0: a tool exception escapes
# agent.run_sync unwrapped, so the marker survives to those handlers.
_GATE_FAILURE_ATTR = "_functualize_ai_approval_gate_failure"


def refusal_message(tool_name: str) -> str:
    """The fixed refusal text a denied tool call returns to the model."""
    return f"Tool call refused: approval required for '{tool_name}'."


def is_tool_refusal(result: Any, tool_name: str) -> bool:
    """Whether ``result`` is the refusal text for ``tool_name``.

    The event emitters use this to report ``status="denied"`` — a refusal
    must not be logged as a successful call. Exact-match on the shared
    helper's output, so producer and matcher cannot drift.
    """
    return result == refusal_message(tool_name)


def mark_gate_failure(exc: BaseException) -> BaseException:
    """Tag ``exc`` as raised by an approval gate (best effort).

    Exotic exception types without ``__dict__`` cannot carry the marker;
    the exception still propagates, the tool still does not run — the
    failure mode is a relabelled error, never an admitted call.
    """
    # Exotic exception types without __dict__ cannot carry the marker; the
    # exception still propagates and the tool still does not run.
    with contextlib.suppress(AttributeError, TypeError):  # pragma: no cover
        setattr(exc, _GATE_FAILURE_ATTR, True)
    return exc


def unwrap_gate_failure(exc: BaseException) -> BaseException | None:
    """Return the gate's original exception if ``exc`` carries the marker.

    Checks ``exc`` itself, then its ``__cause__`` chain one level deep for
    the case a provider library wraps tool exceptions. ``None`` means this
    is not a gate failure and normal error handling applies.
    """
    candidate: BaseException | None = exc
    for _ in range(2):
        if candidate is None:
            return None
        if getattr(candidate, _GATE_FAILURE_ATTR, False) is True:
            return candidate
        candidate = candidate.__cause__
    return None


def evaluate_tool_approval(tool_def: ToolDef, args: dict[str, Any]) -> str | None:
    """Decide one tool call against ``tool_def``'s approval state.

    Args:
        tool_def: The tool definition the call reached; only its approval
            members, name, job_name and description are read.
        args: The call's keyword arguments, handed to the gate verbatim.

    Returns:
        ``None`` when the call is admitted (or the tool is ungated) — run
        the tool. The refusal message when the call is denied — return it
        as the tool's result and continue the loop.

    Raises:
        BaseException: whatever the gate raised, marked as a gate failure;
            the tool does not run and the run ends with this exception.
    """
    if not tool_def.requires_approval:
        return None

    gate = tool_def.approval_gate
    if gate is None:
        # Approval required with no gate: deny every call (fail closed).
        return refusal_message(tool_def.name)

    context = ToolCallContext(
        job_name=tool_def.job_name,
        description=tool_def.description,
    )
    try:
        admitted = gate(tool_def.name, args, context)
    except BaseException as exc:
        raise mark_gate_failure(exc) from None
    if admitted is True:
        return None
    return refusal_message(tool_def.name)
