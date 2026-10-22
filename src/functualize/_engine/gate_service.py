"""The gate service — what the walk does at a gate, extracted from the walker.

One responsibility (the extraction's whole point): decide, at a gate node,
whether its answer already exists, whether the strategy ladder can produce
one now, or whether the walk blocks — and record every step of that through
the runtime store's input port. The walker keeps the loop; this owns the
gate.

The order of the three questions is the contract:

1. **Replay** — a request that is ``accepted`` or ``consumed`` and carries an
   accepted candidate already *has* its answer: feed the recorded payload and
   never re-evaluate. An ``accepted`` one is consumed on the way past, which
   is the single write of ``consumed``. A record that predates requests — or
   an answer deposited by the legacy path — has no candidates; its payload
   is read off the record and feeds replay the same way.
2. **The ladder** — an unanswered gate with a strategy list runs
   ``registry.evaluate`` and records **every** rung as a candidate, ordinal
   continuing from what the request already holds. A rung that was accepted
   is consumed and the walk proceeds; a ladder with no accepted rung blocks,
   carrying the outcome's ``blocked_reason`` byte-for-byte.
3. **Block** — nothing produced an answer: open the request (a stable id,
   reused across resumes) and stop.

``_engine`` never imports ``_gate``: the registry arrives injected, the
ladder's shape is the ``_types`` ``LadderOutcome``, and the strategies table
is a pure function of the node's declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from functualize._engine.recording import InputRecorder
from functualize._engine.recording.input_recorder import schema_identity
from functualize._events.run_log import current_run_id
from functualize._types.gate_resolution import EvaluationOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._engine.frontier import FrontierWalk
    from functualize._engine.workflow_walker import WalkReport, _Ledger, _NodeRun
    from functualize._types.gate_resolution import (
        GateCandidate,
        GateResolution,
        LadderOutcome,
    )
    from functualize._types.workflow import Gate

__all__ = ["GateAsk", "GateService"]


class _Default(Enum):
    """The ladder a gate declares, as opposed to ``None`` — no ladder at all."""

    LADDER = "declared"


_DEFAULT: Final = _Default.LADDER


@dataclass(frozen=True)
class GateAsk:
    """How the walk asks a gate this time, when that is not the gate's own way.

    The default reproduces a declared gate exactly: the request stands at the
    gate's own node with no prompt, and the ladder is the one its strategy
    declares. A caller asking on another node's behalf overrides the parts
    that differ — ``position`` (the node the scope stops at), ``prompt``
    (what the asker is told), ``ladder`` (the strategies tried; ``None``
    tries none and blocks) and ``supersedes`` (a consumed request whose
    answer was for an earlier question: it is neither replayed nor reused).
    """

    position: str | None = None
    prompt: Any = None
    ladder: Sequence[str] | None | _Default = _DEFAULT
    supersedes: str | None = None


def _gate_strategy_list(gate: Gate, prompt_gates: bool) -> list[str] | None:
    declared = gate.strategy if hasattr(gate, "strategy") else None
    if declared == "ai_outbound":
        return None  # always block for external AI
    if declared == "ai_inbound":
        return ["ai_inbound", "prompt", "resolve"]
    if declared == "decision":
        decide = getattr(gate, "decide", None)
        if decide is not None and decide.fallback is not None:
            # A declared fallback means the router never blocks; `resolve`
            # takes the fallback when the decision rung does not accept.
            return ["decision", "resolve"]
        # A below-threshold or failed proposal falls through to a person, the
        # same ladder an inbound AI answer has.
        return ["decision", "prompt", "resolve"]
    if declared == "prompt":
        return ["prompt", "resolve"] if prompt_gates else None
    if declared is not None:
        return [declared]  # unknown strategy → try it, fall through to block
    return ["prompt", "resolve"] if prompt_gates else None


def _ladder(gate: Gate, prompt_gates: bool, ask: GateAsk) -> list[str] | None:
    """The strategies to try: the ask's when it names them, else the gate's."""
    if ask.ladder is _DEFAULT:
        return _gate_strategy_list(gate, prompt_gates)
    return None if ask.ladder is None else list(ask.ladder)


class GateService:
    """Services gate nodes: replay, ladder, block — recorded, not recomputed."""

    def __init__(self) -> None:
        self._recorder = InputRecorder()

    def service(
        self,
        node: Gate,
        walk: FrontierWalk,
        registry: Any,
        prompt_gates: bool,
        *,
        ledger: _Ledger,
        ask: GateAsk = GateAsk(),  # noqa: B008 — frozen, so one shared default is safe
    ) -> _NodeRun | WalkReport:
        """Answer a gate node for the walk: run, replay, or block it.

        Returns the node's run when the gate produced (or had) an answer,
        or the BLOCKED report when the walk stops here — the walker's loop
        treats the two exactly as it treats any other handler's.
        """
        from functualize._engine.workflow_walker import (
            WalkOutcome,
            WalkReport,
            _NodeRun,
        )

        resolution = walk.resolution(node.name)
        if resolution is not None and (resolution.request.request_id == ask.supersedes):
            resolution = None  # a spent answer to an earlier question
        blocked_reason = ""

        # 1. Replay: the recorded answer is the answer — never re-evaluated.
        if resolution is not None and resolution.request.status in (
            "accepted",
            "consumed",
        ):
            payload = self._recorded_payload(resolution, walk, node.name)
            if payload is not None:
                if resolution.request.status == "accepted":
                    walk.consume(resolution.request.request_id)
                return _NodeRun(payload, replayed=True)

        # 2. The ladder: one candidate per rung, ordinals continuing.
        strategies = _ladder(node, prompt_gates, ask)
        outcome: LadderOutcome | None = None
        if strategies is not None and registry is not None:
            # The walk's results so far, and the gate's declared decision: a
            # decision reads the text a named step produced, so a strategy
            # cannot see this walk unless the walk hands it over.
            outcome = registry.evaluate(
                node.awaits,
                gate_strategy=strategies,
                gate_name=node.name,
                workflow_context=dict(ledger.results),
                decision=node.decide,
            )
            if resolution is not None:
                request_id = resolution.request.request_id
                if outcome.model is None:
                    self._open(walk, node, ask)
            else:
                request_id = self._open(
                    walk,
                    node,
                    ask,
                    scope_status="running" if outcome.model is not None else "blocked",
                )
            schema_id, schema_version = schema_identity(node.awaits)
            now = datetime.now(UTC)
            earlier = resolution.candidates if resolution is not None else ()
            candidates = self._recorder.ladder_candidates(
                request_id,
                outcome,
                first_ordinal=len(earlier),
                now=now,
                schema_id=schema_id,
                schema_version=schema_version,
            )
            self._record(walk, node, request_id, earlier, candidates, outcome, now)
            if outcome.model is not None:
                walk.consume(request_id)
                return _NodeRun(outcome.model.model_dump(), replayed=True)
            blocked_reason = outcome.blocked_reason

        # 3. Block: open the request under a stable id and stop here.
        if outcome is None:
            self._open(walk, node, ask)
        return WalkReport(
            WalkOutcome.BLOCKED,
            walk.scope_id,
            tuple(ledger.executed),
            tuple(ledger.replayed),
            blocked_reason=blocked_reason,
            blocked_on=node.name,
            results=ledger.results,
        )

    def _record(
        self,
        walk: FrontierWalk,
        node: Gate,
        request_id: str,
        earlier: Sequence[GateCandidate],
        candidates: Sequence[GateCandidate],
        outcome: LadderOutcome,
        now: datetime,
    ) -> None:
        """Record the rungs; an accepted rung brings its decision and intent.

        The decision observes every candidate the request held before this
        ladder plus the rungs up to the accepted one; its policy is the
        ladder, versioned by the rungs it ran. All of it is one unit.
        """
        accepted = next(
            (
                candidate
                for candidate in candidates
                if candidate.evaluation.outcome is EvaluationOutcome.ACCEPTED
            ),
            None,
        )
        if accepted is None:
            walk.record_candidates(candidates)
            return
        policy_id, policy_version = self._recorder.ladder_policy(
            [name for name, _evaluation, _payload in outcome.rungs]
        )
        decision = self._recorder.decided(
            request_id,
            [*earlier, *candidates],
            accepted.candidate_id,
            policy_id=policy_id,
            policy_version=policy_version,
            now=now,
        )
        walk.record_candidates(
            candidates,
            decision=decision,
            effect=self._recorder.accepted_effect(
                decision, scope_id=walk.scope_id, gate_name=node.name
            ),
        )

    def _open(
        self,
        walk: FrontierWalk,
        node: Gate,
        ask: GateAsk,
        *,
        scope_status: str = "blocked",
    ) -> str:
        """Record the request, position and lifecycle status in one unit.

        The run executing now is the request's causal run: every answer the
        request collects traces back to it.
        """
        return walk.open_request(
            node.name,
            position=node.name if ask.position is None else ask.position,
            schema=node.awaits.model_json_schema(),
            prompt=ask.prompt,
            model=getattr(node.awaits, "__name__", ""),
            tools=[
                {"tool": spec.name, "bound": sorted(spec.bound)}
                for spec in node.tool_specs()
            ],
            scope_status=scope_status,
            run_id=current_run_id(),
            supersedes=ask.supersedes,
        )

    def _recorded_payload(
        self, resolution: GateResolution, walk: FrontierWalk, gate_name: str
    ) -> Any:
        """The payload a resolved request feeds replay with.

        The accepted candidate's when there is one; otherwise the answer an
        older path deposited on the record — the read-only projection that
        keeps pre-change files and the legacy deposit helper answering
        gates exactly as they did before requests existed.
        """
        if resolution.accepted_id is not None:
            for candidate in resolution.candidates:
                if candidate.candidate_id == resolution.accepted_id:
                    return candidate.payload
            return None
        return walk.gate_payload(gate_name)
