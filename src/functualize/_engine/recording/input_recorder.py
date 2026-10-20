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
not a state of the request. Evidence is refused the same way when it is not
a reference plus a ``sha256:`` digest (:meth:`InputRecorder.evidence`).

**Provenance is derived here, once.** Resolver class and channel come from
the surface or the strategy that produced a candidate; schema identity and
version from the gate's model; the payload hash from the payload as
submitted. A decision (``decided``) names its policy and the exact candidate
ids it observed, and ``accepted_effect`` is the outbox intent that rides in
the same unit on a store with an outbox.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from functualize._types.gate_resolution import (
    GATE_ACCEPTED_TOPIC,
    EvidenceRef,
    GateCandidate,
    GateDecision,
)
from functualize._types.persistence import (
    ConsumeInput,
    EffectIntent,
    SupersedeRequest,
    SuspendAtGate,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from functualize._types.gate_resolution import (
        CandidateEvaluation,
        LadderOutcome,
    )

__all__ = [
    "LADDER_POLICY",
    "VALIDATION_POLICY",
    "InputRecorder",
    "content_digest",
    "schema_identity",
]

#: Source attribution bounds: an audit field, recorded permanently.
_SOURCE_MAX = 128

#: The policy that accepts a surface answer: it validated against the gate's
#: model, so its version is that model's schema version.
VALIDATION_POLICY = "gate.validate"
#: The policy that accepts a ladder rung: the gate's strategy ladder, versioned
#: by the digest of the rung names it ran.
LADDER_POLICY = "gate.ladder"

#: Who stands behind a surface. A surface not named here is a program.
_RESOLVER_FOR_SURFACE = {"cli": "human", "tui": "human", "mcp": "agent"}
#: Who stands behind a strategy rung. A rung not named here is a policy.
_RESOLVER_FOR_STRATEGY = {"prompt": "human", "decision": "agent", "ai_inbound": "agent"}

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

#: The namespace an accepted gate's intent is recorded under — the aggregate
#: kind the intent is about.
_GATE_NAMESPACE = "input_request"


def _canonical(value: Any) -> bytes:
    """One byte form per value: sorted keys, no whitespace, ``str`` fallback.

    The fallback is deliberate: a validated dump can hold a ``datetime`` or a
    ``Decimal``, and a hash that refused them would leave a candidate with no
    hash rather than one over the value's text.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()


def content_digest(content: bytes) -> str:
    """``sha256:<hex>`` of ``content`` — the digest form evidence carries."""
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def schema_identity(model: Any) -> tuple[str, str]:
    """``(schema_id, schema_version)`` for a gate model, ``("", "")`` for none.

    The id is the model's import path; the version is the digest of its JSON
    schema, so two declarations that ask the same question read as the same
    version and an edited model reads as a new one — without the author
    numbering anything.
    """
    if model is None:
        return "", ""
    schema_id = (
        f"{getattr(model, '__module__', '')}.{getattr(model, '__qualname__', '')}"
    )
    render = getattr(model, "model_json_schema", None)
    if not callable(render):
        return schema_id, ""
    return schema_id, content_digest(_canonical(render()))


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
        scope_status: str = "blocked",
        run_id: str | None = None,
    ) -> SuspendAtGate:
        """Build the gate request with the status the walk reached.

        Mints the request's id. ``model`` and ``tools`` travel on the command
        so a surface that answers without the declaring module — MCP, a
        notification — learns the question from the record alone. ``run_id``
        is the causal run of every answer the request will collect.
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
            scope_status=scope_status,
            run_id=run_id,
        )

    def ladder_candidates(
        self,
        request_id: str,
        outcome: LadderOutcome,
        *,
        first_ordinal: int,
        now: datetime,
        schema_id: str = "",
        schema_version: str = "",
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
                resolver_class=_RESOLVER_FOR_STRATEGY.get(name, "policy"),
                channel=name,
                schema_id=schema_id,
                schema_version=schema_version,
                payload_hash=content_digest(_canonical(payload))
                if payload is not None
                else "",
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
        schema_id: str = "",
        schema_version: str = "",
        supersedes: str | None = None,
        evidence: Sequence[EvidenceRef] = (),
    ) -> GateCandidate:
        """A human or agent answer, as a candidate with its verdict attached.

        ``source`` is the surface (``cli``, ``mcp``, ``api``); it is both the
        attribution and the channel, and decides the resolver class.
        ``supersedes`` names the unaccepted candidate this one corrects.

        Raises:
            ValueError: ``source`` is empty or longer than 128 characters, or
                an evidence reference is not a reference plus a digest.
        """
        if not source or len(source) > _SOURCE_MAX:
            raise ValueError(
                f"candidate source must be 1-{_SOURCE_MAX} characters, "
                f"got {len(source)}"
            )
        refs = tuple(
            self.evidence(item.ref, item.digest, item.media_type, item.size)
            for item in evidence
        )
        return GateCandidate(
            candidate_id=f"cand_{uuid4().hex}",
            request_id=request_id,
            ordinal=ordinal,
            source=source,
            submitted_at=now,
            evaluation=evaluation,
            payload=payload,
            resolver_class=_RESOLVER_FOR_SURFACE.get(source, "program"),
            channel=source,
            schema_id=schema_id,
            schema_version=schema_version,
            payload_hash=content_digest(_canonical(payload)),
            supersedes_candidate_id=supersedes,
            evidence_refs=refs,
        )

    def evidence(
        self,
        ref: str,
        digest: str,
        media_type: str | None = None,
        size: int | None = None,
    ) -> EvidenceRef:
        """A checked evidence reference — a pointer and a digest, never bytes.

        Raises:
            ValueError: ``ref`` is empty, not a string, or a ``data:`` URI
                (inline bytes); or ``digest`` is not ``sha256:<64 hex>``.
        """
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("evidence needs a reference to where its bytes live")
        if ref.strip().lower().startswith("data:"):
            raise ValueError(
                "evidence is stored by reference and digest, never as bytes; "
                "a data: URI carries the bytes inline — store them elsewhere "
                "and pass where they are"
            )
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError(
                f"evidence digest must be 'sha256:' and 64 lowercase hex "
                f"characters, got {digest!r}"
            )
        return EvidenceRef(ref=ref, digest=digest, media_type=media_type, size=size)

    def decided(
        self,
        request_id: str,
        candidates: Sequence[GateCandidate],
        accepted_id: str,
        *,
        policy_id: str,
        policy_version: str,
        now: datetime,
    ) -> GateDecision:
        """The decision that accepted ``accepted_id``, over what it observed.

        ``candidates`` is the request's candidate set as the deciding unit
        sees it — those already recorded plus those it is recording — and the
        observed ids are every one of them up to and including the accepted
        candidate, in ordinal order. The ``not_reached`` rungs after it were
        never weighed, so they are not observed.
        """
        ordered = sorted(candidates, key=lambda candidate: candidate.ordinal)
        observed: list[str] = []
        for candidate in ordered:
            observed.append(candidate.candidate_id)
            if candidate.candidate_id == accepted_id:
                break
        else:
            raise ValueError(
                f"accepted candidate {accepted_id!r} is not among the "
                f"candidates of request {request_id!r}"
            )
        return GateDecision(
            request_id=request_id,
            accepted_id=accepted_id,
            policy_id=policy_id,
            policy_version=policy_version,
            observed_candidate_ids=tuple(observed),
            decided_at=now,
        )

    @staticmethod
    def ladder_policy(rung_names: Sequence[str]) -> tuple[str, str]:
        """``(policy_id, policy_version)`` for a ladder that ran these rungs."""
        return LADDER_POLICY, content_digest(_canonical(list(rung_names)))

    def accepted_effect(
        self, decision: GateDecision, *, scope_id: str, gate_name: str
    ) -> EffectIntent:
        """The outbox intent an acceptance publishes, keyed by its request.

        The key is the request's, so recording the same acceptance twice is
        one intent, and a receiver deduplicating on it applies the effect
        once however many times it is delivered.
        """
        return EffectIntent(
            namespace=_GATE_NAMESPACE,
            topic=GATE_ACCEPTED_TOPIC,
            payload={
                "request_id": decision.request_id,
                "scope_id": scope_id,
                "gate": gate_name,
                "accepted_id": decision.accepted_id,
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
            },
            idempotency_key=f"{GATE_ACCEPTED_TOPIC}:{decision.request_id}",
        )

    def superseding(
        self, *, scope_id: str, gate_name: str, request_id: str, now: datetime
    ) -> SupersedeRequest:
        """Withdraw ``request_id``'s answer and open a new request — new id."""
        return SupersedeRequest(
            scope_id=scope_id,
            gate_name=gate_name,
            request_id=request_id,
            new_request_id=f"req_{uuid4().hex}",
            now=now,
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
