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

``EvidenceRef``, ``GateDecision`` and ``GATE_ACCEPTED_TOPIC`` are exported
from ``functualize.plugin``: an outbox receiver reads them (ADR-034). The rest
waits for the first consumer outside the engine that needs it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from functualize._types.persistence import InputRequest

__all__ = [
    "GATE_ACCEPTED_TOPIC",
    "CandidateEvaluation",
    "EvaluationOutcome",
    "EvidenceRef",
    "GateCandidate",
    "GateDecision",
    "GateResolution",
    "LadderOutcome",
]

#: The outbox topic an accepted gate answer publishes, on a store that has an
#: outbox. One topic for every resolver — person, agent or policy — because a
#: receiver cares that the gate was decided, not who decided it; the payload
#: says who.
GATE_ACCEPTED_TOPIC: Final = "gate.accepted"


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

    ``evidence`` is JSON-safe context a strategy rung records beside its
    verdict — what it saw, and what it cost to see it. Written by a rung,
    never by an answer surface: a person or an agent answering a gate records
    a candidate, and fabricating rung evidence beside it would be a forgery.
    ``None`` for every candidate a rung did not produce.
    """

    outcome: EvaluationOutcome
    detail: str = ""
    errors: tuple[tuple[str, str], ...] = ()
    evidence: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class EvidenceRef:
    """Evidence attached to an answer: where its bytes live, and their digest.

    A reference, never the bytes. A runtime row is the wrong home for an
    attachment — it is copied into every read of the request, and a store
    that keeps rows in one file grows with every screenshot — so the record
    carries only what identifies the bytes and what proves they are the ones
    that were attached. ``ref`` is opaque here (a path, a URI, an artifact
    id); ``digest`` is ``sha256:<64 hex>``, checked by the recorder.

    A matching digest proves the bytes at ``ref`` are the attached ones. It
    cannot prove who produced them — that is the candidate's attribution.
    """

    ref: str
    digest: str
    media_type: str | None = None
    size: int | None = None


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

    The provenance fields answer an audit's questions without a second
    lookup, and the recorder fills them all; they default to empty only so a
    record written before they existed still reads. ``resolver_class`` is
    ``human``, ``agent``, ``program`` or ``policy``; ``channel`` is the
    surface (``cli``, ``mcp``) or the strategy that produced the candidate.
    ``schema_id``/``schema_version`` name the model the payload was evaluated
    against, the version being the digest of its JSON schema, and
    ``payload_hash`` the digest of the payload as submitted.
    ``supersedes_candidate_id`` names the earlier, unaccepted candidate this
    one corrects — the correction is a new row, the earlier one is untouched.
    """

    candidate_id: str
    request_id: str
    ordinal: int
    source: str
    submitted_at: datetime
    evaluation: CandidateEvaluation
    payload: Any = None
    resolver_class: str = ""
    channel: str = ""
    schema_id: str = ""
    schema_version: str = ""
    payload_hash: str = ""
    supersedes_candidate_id: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()


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
class GateDecision:
    """Why a request was accepted: the policy, and exactly what it looked at.

    Recorded once, in the unit that records the accepted candidate, and never
    recomputed. ``observed_candidate_ids`` is the candidate set as it stood
    at that moment, in ordinal order and including the accepted one — a
    reader asking "what did the gate weigh" gets that list, not whichever
    rows happen to exist when the question is asked.

    ``policy_id`` names the rule that accepted (``gate.validate`` for a
    surface answer, ``gate.ladder`` for a strategy rung) and
    ``policy_version`` pins which version of it.
    """

    request_id: str
    accepted_id: str
    policy_id: str
    policy_version: str
    observed_candidate_ids: tuple[str, ...]
    decided_at: datetime


@dataclass(frozen=True)
class GateResolution:
    """A request and every candidate it collected, as a reader finds them.

    The read-side projection of a resolved (or still-open) gate: nothing in
    it was validated to build it. Outcomes are as recorded at submission —
    re-evaluating a candidate on read would make the record a cache of the
    model classes' current behaviour rather than a record of what happened.

    ``accepted_id`` names the accepted candidate when there is one, ``None``
    while the request is open and unanswered. ``decision`` is the recorded
    :class:`GateDecision`, ``None`` while undecided or for a record written
    before decisions were.
    """

    request: InputRequest
    candidates: tuple[GateCandidate, ...] = ()
    accepted_id: str | None = None
    decision: GateDecision | None = None
