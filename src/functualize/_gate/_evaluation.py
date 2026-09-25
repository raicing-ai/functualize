"""Gate evaluation text and submission verdicts — pure functions.

Two producers live here and nowhere else:

**``blocked_reason_from``** is the only writer of the text an operator reads
when a gate blocks. Byte-identity with the text the single-answer path has
always produced is a contract, not a preference: operators diagnose gates by
this string and the walk records it as ``blocked_reason``, so a rewording is
a behaviour change even when every fact in it survives.

**``evaluate_submission``** turns one submitted payload into its recorded
verdict. One validation, exactly as many as the answer path performs today —
a second validation to *read back* a recorded answer is what this module's
existence prevents. On failure the ``ValidationError``'s ``loc``/``msg``
pairs are carried structurally, because a surface that wants to highlight
the offending field should not parse prose to find it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._gate._strategy import missing_strategy_hint
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import BaseModel


def _unregistered_message(names: list[str]) -> str:
    """Name the unregistered strategies, and the package each one needs.

    This is the string that reaches ``GateResolutionError.last_error``, and
    from there the walk's ``blocked_reason`` -- so it is what an operator
    actually reads when a gate blocks for this cause. The bare name alone
    ("unregistered gate strategy 'ai_inbound'") is not enough to act on;
    which package registers it is the missing half.
    """
    described = []
    for name in names:
        hint = missing_strategy_hint(name)
        described.append(f"'{name}' ({hint})" if hint else f"'{name}'")
    plural = "strategies" if len(described) > 1 else "strategy"
    return f"unregistered gate {plural} {', '.join(described)}"


def blocked_reason_from(
    rungs: Sequence[tuple[str, CandidateEvaluation, Any]],
) -> str:
    """The blocked text for a ladder's rungs — this module's, and no other.

    Unregistered names come first, because "install functualize-ai" is
    actionable whereas a resolver error is usually a downstream symptom of
    having fallen this far in the first place. Then every failed rung as
    ``"<name>: <detail>"``, joined with ``"; "``. An empty ladder is its own
    sentence. The composition is the one ``resolve_gate`` has always built;
    a character moving here is a behaviour change (see the module docstring).
    """
    unregistered = [
        name
        for name, evaluation, _ in rungs
        if evaluation.outcome is EvaluationOutcome.UNAVAILABLE
    ]
    parts: list[str] = []
    if unregistered:
        parts.append(_unregistered_message(unregistered))
    parts.extend(
        f"{name}: {evaluation.detail}"
        for name, evaluation, _ in rungs
        if evaluation.outcome is EvaluationOutcome.FAILED
    )
    return "; ".join(parts) if parts else "no strategies attempted"


def evaluate_submission(
    model_class: type[BaseModel], payload: Mapping[str, Any] | None
) -> tuple[CandidateEvaluation, dict[str, Any] | None]:
    """One validation of a submitted payload, as a recorded verdict.

    Accepted returns the validated dump alongside the evaluation — the dump
    is what gets stored as the candidate's payload, so the record and the
    verdict cannot disagree about what was accepted. Invalid returns
    ``(field, message)`` pairs from the validation errors and ``None``:
    nothing was accepted, and the caller keeps the gate open rather than
    storing a payload that never validated.
    """
    from pydantic import ValidationError

    try:
        model = model_class.model_validate(payload)
    except ValidationError as exc:
        errors = tuple(
            (
                str(entry.get("loc", ("",))[0]) if entry.get("loc") else "",
                str(entry.get("msg", "")),
            )
            for entry in exc.errors()
        )
        return (
            CandidateEvaluation(
                EvaluationOutcome.INVALID, detail=str(exc), errors=errors
            ),
            None,
        )
    return CandidateEvaluation(EvaluationOutcome.ACCEPTED), model.model_dump()
