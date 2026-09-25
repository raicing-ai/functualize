"""The input recorder — gate moments as input commands.

The same contract as ``workflow_recorder``: facts in, command values out, and
nothing else — no store, no clock reads, no conditionals beyond the one the
source rule needs. The walk issues what these methods return inside
``RuntimeStore.transaction()`` units.

**This module is where ids are minted**, and nowhere else: ``req_`` and
``cand_`` prefixes over ``uuid4().hex``. The store cannot mint them, because
the port accumulates — a buffered command cannot reference an id the store
would only assign at commit, and the engine is the party that knows a
request's identity must stay stable across the resumes that re-open it.

``ladder_candidates`` turns a :class:`LadderOutcome
<functualize._types.gate_resolution.LadderOutcome>` into one candidate per
rung, ``source`` attributing each to ``strategy:<name>``. The ordinal
continues from the count the caller read off the request, so a second ladder
run on one request appends to one sequence rather than starting a parallel
one.

``submitted`` validates its ``source`` — non-empty, at most 128 characters —
because attribution is the field an audit reads first, and an unbounded or
blank string there is a defect recorded permanently if it lands. The
refusal is a ``ValueError``: it is a programming mistake at the call site,
not a state of the request.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from functualize._types.gate_resolution import GateCandidate
from functualize._types.persistence import ConsumeInput, SuspendAtGate

if TYPE_CHECKING:
    from collections.abc import Mapping

    from functualize._types.gate_resolution import (
        CandidateEvaluation,
        LadderOutcome,
    )

__all__ = ["InputRecorder"]

#: Source attribution bounds: an audit field, recorded permanently.
_SOURCE_MAX = 128


class InputRecorder:
    """Gate input moments, as the commands that record them."""

    def opened(
        self,
        *,
        scope_id: str,
        generation: int,
        gate_name: str,
        position: str,
        now: datetime,
        schema: Any = None,
        prompt: Any = None,
        model: str = "",
        tools: tuple[Mapping[str, Any], ...] = (),
    ) -> SuspendAtGate:
        """The walk stopped at a gate; this is the request that pauses it.

        Mints the request's id. ``model`` and ``tools`` travel on the command
        so a surface that answers without the declaring module — MCP, a
        notification — learns the question from the record alone.
        """
        return SuspendAtGate(
            scope_id=scope_id,
            generation=generation,
            gate_name=gate_name,
            request_id=f"req_{uuid4().hex}",
            position=position,
            now=now,
            schema=schema,
            prompt=prompt,
            model=model,
            tools=tools,
        )

    def ladder_candidates(
        self,
        request_id: str,
        outcome: LadderOutcome,
        *,
        first_ordinal: int,
        now: datetime,
    ) -> tuple[GateCandidate, ...]:
        """One candidate per ladder rung, in ladder order.

        Every rung is recorded — the failures and the unregistered names are
        the evaluation data, and the ``not_reached`` tail is what makes a
        stopped-early ladder readable as one. Payloads ride only on the
        accepted rung, exactly as the outcome carries them.
        """
        return tuple(
            GateCandidate(
                candidate_id=f"cand_{uuid4().hex}",
                request_id=request_id,
                ordinal=first_ordinal + index,
                source=f"strategy:{name}",
                submitted_at=now,
                evaluation=evaluation,
                payload=payload,
            )
            for index, (name, evaluation, payload) in enumerate(outcome.rungs)
        )

    def submitted(
        self,
        request_id: str,
        source: str,
        evaluation: CandidateEvaluation,
        payload: Any,
        *,
        ordinal: int,
        now: datetime,
    ) -> GateCandidate:
        """A human or agent answer, as a candidate with its verdict attached.

        Raises:
            ValueError: ``source`` is empty or longer than 128 characters.
        """
        if not source or len(source) > _SOURCE_MAX:
            raise ValueError(
                f"candidate source must be 1-{_SOURCE_MAX} characters, "
                f"got {len(source)}"
            )
        return GateCandidate(
            candidate_id=f"cand_{uuid4().hex}",
            request_id=request_id,
            ordinal=ordinal,
            source=source,
            submitted_at=now,
            evaluation=evaluation,
            payload=payload,
        )

    def consumed(
        self,
        *,
        scope_id: str,
        generation: int,
        request_id: str,
        now: datetime,
    ) -> ConsumeInput:
        """The walk is moving past the gate; retire the answer it used."""
        return ConsumeInput(
            scope_id=scope_id,
            generation=generation,
            request_id=request_id,
            now=now,
        )
