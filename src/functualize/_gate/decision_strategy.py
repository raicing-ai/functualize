"""DECISION gate strategy resolver — a provider proposes, the gate decides.

``DecisionGateResolver`` asks a ``DecisionProvider`` which of the declared
options fits the text a named step produced, then applies the thresholds the
workflow declared on the gate (``ChoiceDecision.accept_at`` and
``min_margin``). A proposal that clears both fills the decided field; one that
does not is refused with a message naming the proposal and the thresholds, so
the gate blocks for a person with the reason in front of them.

The acceptance rule reads the proposed option's probability and its lead over
the runner-up, and nothing else. The provider's own scalar self-assessment is
recorded on the result and deliberately never read here: an acceptance a
provider can raise by asserting certainty is not the workflow's rule.

The resolver is provider-neutral. It holds a ``DecisionProvider`` and knows
nothing of any particular one; a plugin constructs it with its provider and
registers it as the ``decision`` strategy. A provider failure propagates as the
``DecisionUnavailableError`` it is, and the ladder records it as a failed rung.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from functualize._gate.decision_evidence import build_decision_evidence
from functualize._types.decision import ChoiceRequest
from functualize._types.errors import DecisionUnavailableError

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._gate._context import GateContext
    from functualize._types.decision import DecisionProvider, DecisionResult

__all__ = [
    "DECISION_STRATEGY_NAME",
    "DecisionBelowThresholdError",
    "DecisionGateResolver",
]

#: Strategy name used for registration with the gate registry.
DECISION_STRATEGY_NAME = "decision"


class DecisionBelowThresholdError(ValueError):
    """A proposal that did not clear the thresholds the workflow declared.

    Its message is the detail of the failed rung and, through the ladder's
    blocked text, what the person answering the gate is shown.
    """


class DecisionGateResolver:
    """Gate resolver that fills one field from a decision provider's proposal.

    Satisfies ``GateResolver``. Performs at most one provider call per
    resolution and never retries: whether to try again is the workflow's
    business, and a below-threshold proposal is meant to reach a person.
    """

    def __init__(self, provider: DecisionProvider) -> None:
        self._provider = provider

    def resolve(self, ctx: GateContext) -> BaseModel:
        decision = ctx.decision
        if decision is None:
            raise ValueError("gate has no decision declared")

        step = decision.state.name
        if step not in ctx.workflow_context:
            raise ValueError(
                f"decision state step {step!r} has no recorded result in this "
                f"walk; it must run before the gate"
            )
        recorded = ctx.workflow_context[step]
        state = (
            recorded
            if isinstance(recorded, str)
            else json.dumps(recorded, sort_keys=True, default=str)
        )

        def record(
            latency_seconds: float,
            verdict: str,
            *,
            result: DecisionResult[str] | None = None,
            error: DecisionUnavailableError | None = None,
            probability: float | None = None,
            margin: float | None = None,
        ) -> None:
            if ctx.evidence is not None:
                ctx.evidence.record(
                    build_decision_evidence(
                        decision,
                        state=state,
                        latency_seconds=latency_seconds,
                        result=result,
                        error=error,
                        probability=probability,
                        margin=margin,
                        verdict=verdict,
                    )
                )

        started = time.monotonic()
        try:
            result = self._provider.choose(
                ChoiceRequest(
                    state=state,
                    instructions=decision.instructions,
                    options=decision.options,
                    model=decision.model,
                )
            )
        except DecisionUnavailableError as exc:
            record(time.monotonic() - started, "provider_failed", error=exc)
            raise
        latency_seconds = time.monotonic() - started

        distribution = result.distribution
        if distribution is None:
            record(latency_seconds, "no_distribution", result=result)
            raise ValueError(
                f"{result.provider}/{result.model} proposed {result.value!r} with "
                f"no distribution; the gate's thresholds need one"
            )
        value = result.value
        if value not in distribution:
            raise ValueError(
                f"{result.provider}/{result.model} proposed {value!r}, which its "
                f"distribution does not cover"
            )
        p = distribution[value]
        runner_up = max((v for k, v in distribution.items() if k != value), default=0.0)
        margin = p - runner_up

        if p >= decision.accept_at and margin >= decision.min_margin:
            record(
                latency_seconds,
                "accepted",
                result=result,
                probability=p,
                margin=margin,
            )
            return ctx.model_class(**{**ctx.resolved_fields, decision.field: value})
        record(
            latency_seconds,
            "below_threshold",
            result=result,
            probability=p,
            margin=margin,
        )
        raise DecisionBelowThresholdError(
            f"{result.provider}/{result.model} proposed '{value}' at {p:.2f} "
            f"(margin {margin:.2f}); workflow requires >= "
            f"{decision.accept_at:.2f}, margin >= {decision.min_margin:.2f}"
        )
