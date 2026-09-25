"""The gate resolution vocabulary — requests, candidates, evaluations.

Values only, frozen dataclasses and one enum, exactly as
``_types/persistence.py`` is: a candidate is data a recorder hands to a store,
not a call. The import direction is one-way — this module names
``InputRequest`` from ``_types/persistence.py``, and that module names
``GateCandidate`` back only under ``TYPE_CHECKING``, so no runtime cycle can
grow between two vocabulary modules every layer may import.

What these values replace: a gate's answer used to be one ``payload`` field on
the gate record, so the *question* had no identity of its own and only the
winning answer survived. Here the question is a request with an id, every
proposed answer is a candidate carrying its evaluation, and the evaluation is
recorded once at submission rather than recomputed on read.

Nothing here is exported from a public package yet: the first consumer that
needs these names outside the engine is the Slack gate resolver, and the export
decision waits for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._types.persistence import InputRequest

__all__ = [
    "CandidateEvaluation",
    "EvaluationOutcome",
    "GateCandidate",
    "GateResolution",
    "LadderOutcome",
]


class EvaluationOutcome(StrEnum):
    """How one candidate fared. Recorded once, never recomputed.

    Five outcomes, and the difference between them is the whole point of
    recording candidates at all:

    - ``accepted`` — the payload validated and was taken as the answer. At
      most one candidate per request ends here.
    - ``invalid`` — a human or agent submitted a payload that failed
      validation. The gate stays open; the attempt is kept because "who tried
      and why it failed" is the question an audit or an agent evaluation asks
      first.
    - ``failed`` — a strategy ran and raised. The detail is the error.
    - ``unavailable`` — a strategy named in the ladder is not registered. A
      missing package is a fact about the environment, not an attempt that
      went wrong, and the outcome says which it is.
    - ``not_reached`` — the ladder never got this far because an earlier rung
      was accepted. Distinguishing "did not run" from "ran and failed" is what
      makes a recorded ladder readable.
    """

    ACCEPTED = "accepted"
    INVALID = "invalid"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_REACHED = "not_reached"


@dataclass(frozen=True)
class CandidateEvaluation:
    """One candidate's verdict, frozen at the moment it was made.

    ``errors`` is ``(field, message)`` pairs from the validation failure, not
    a rendered string: a caller that wants to highlight the offending field in
    a UI should not have to parse prose to find it. Empty for every outcome
    but ``invalid`` — a strategy failure's text lives in ``detail``.
    """

    outcome: EvaluationOutcome
    detail: str = ""
    errors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class GateCandidate:
    """One proposed answer to a gate request.

    Append-only by contract: a second candidate never overwrites the first,
    and the store refuses an :meth:`append
    <functualize._types.persistence.InputWriter.append>` against a request
    that is no longer open rather than silently replacing an earlier answer.

    ``source`` attributes the candidate — ``strategy:<name>`` for a ladder
    rung, ``cli``/``mcp``/``api`` for a surface, whatever an answering agent
    names itself. It is recorded, not parsed: attribution is for the reader of
    a resolution, never for a decision.

    ``ordinal`` orders the candidates within one request. The recorder mints
    it and continues it across ladders, so two strategy runs on one request
    read as one sequence rather than two unrelated lists.
    """

    candidate_id: str
    request_id: str
    ordinal: int
    source: str
    submitted_at: datetime
    evaluation: CandidateEvaluation
    payload: Any = None


@dataclass(frozen=True)
class LadderOutcome:
    """What running a gate's strategy ladder produced, rung by rung.

    One rung per expanded strategy entry, in ladder order: a ``(name,
    evaluation, payload)`` triple where ``payload`` is the resolved value on
    the accepted rung and ``None`` on every other. The rungs after an accepted
    one are ``not_reached``, recorded rather than omitted — a ladder that ran
    three strategies and one that stopped at the first are different facts.

    ``model`` is the accepted rung's validated model instance, or ``None``
    when no rung was accepted. ``blocked_reason`` is the operator-facing text
    naming every rung that failed and why — byte-identical to the text the
    single-answer path has always produced, because operators diagnose gates
    by it.
    """

    rungs: tuple[tuple[str, CandidateEvaluation, Any], ...]
    model: Any = None
    blocked_reason: str = ""


@dataclass(frozen=True)
class GateResolution:
    """A request and every candidate it collected, as a reader finds them.

    The read-side projection of a resolved (or still-open) gate: nothing in
    it was validated to build it. Outcomes are as recorded at submission —
    re-evaluating a candidate on read would make the record a cache of the
    model classes' current behaviour rather than a record of what happened.

    ``accepted_id`` names the accepted candidate when there is one, ``None``
    while the request is open and unanswered.
    """

    request: InputRequest
    candidates: tuple[GateCandidate, ...] = ()
    accepted_id: str | None = None
