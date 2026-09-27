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

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from functualize._engine.recording import InputRecorder

if TYPE_CHECKING:
    from functualize._engine.frontier import FrontierWalk
    from functualize._engine.workflow_walker import WalkReport, _Ledger, _NodeRun
    from functualize._types.gate_resolution import GateResolution, LadderOutcome
    from functualize._types.workflow import Gate

__all__ = ["GateService"]


def _gate_strategy_list(gate: Gate, prompt_gates: bool) -> list[str] | None:
    declared = gate.strategy if hasattr(gate, "strategy") else None
    if declared == "ai_outbound":
        return None  # always block for external AI
    if declared == "ai_inbound":
        return ["ai_inbound", "prompt", "resolve"]
    if declared == "prompt":
        return ["prompt", "resolve"] if prompt_gates else None
    if declared is not None:
        return [declared]  # unknown strategy → try it, fall through to block
    return ["prompt", "resolve"] if prompt_gates else None


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
        strategies = _gate_strategy_list(node, prompt_gates)
        outcome: LadderOutcome | None = None
        if strategies is not None and registry is not None:
            outcome = registry.evaluate(
                node.awaits, gate_strategy=strategies, gate_name=node.name
            )
            if resolution is not None:
                request_id = resolution.request.request_id
                if outcome.model is None:
                    self._open(walk, node)
            else:
                request_id = self._open(
                    walk,
                    node,
                    scope_status="running" if outcome.model is not None else "blocked",
                )
            candidates = self._recorder.ladder_candidates(
                request_id,
                outcome,
                first_ordinal=len(resolution.candidates)
                if resolution is not None
                else 0,
                now=datetime.now(UTC),
            )
            walk.record_candidates(candidates)
            if outcome.model is not None:
                walk.consume(request_id)
                return _NodeRun(outcome.model.model_dump(), replayed=True)
            blocked_reason = outcome.blocked_reason

        # 3. Block: open the request under a stable id and stop here.
        if outcome is None:
            self._open(walk, node)
        return WalkReport(
            WalkOutcome.BLOCKED,
            walk.scope_id,
            tuple(ledger.executed),
            tuple(ledger.replayed),
            blocked_reason=blocked_reason,
            blocked_on=node.name,
            results=ledger.results,
        )

    def _open(
        self, walk: FrontierWalk, node: Gate, *, scope_status: str = "blocked"
    ) -> str:
        """Record the request, position and lifecycle status in one unit."""
        return walk.open_request(
            node.name,
            position=node.name,
            schema=node.awaits.model_json_schema(),
            prompt=None,
            model=getattr(node.awaits, "__name__", ""),
            tools=[
                {"tool": spec.name, "bound": sorted(spec.bound)}
                for spec in node.tool_specs()
            ],
            scope_status=scope_status,
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
