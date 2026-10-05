"""The hermetic router — one reference workflow for a decision gate.

A router, not a model caller. The workflow declares four routes, the
thresholds a proposal must clear before it is taken, and the fallback that
answers when nothing clears them; the framework decides, records its
evidence, takes the fallback, and blocks for a person — whatever the
declaration says happens, happens inside the walk.

It runs with no provider at all: without one, the declared fallback routes
every request to ``human_review``. Register any ``DecisionProvider`` as the
``decision`` strategy (``app.gates.register_gate_strategy``) and the same
workflow starts routing on proposals. Nothing here makes a network call,
and no step performs a consequential side effect — the example routes a string and
records what happened.

Read a run back with ``decision_record`` (``functualize.app.utils``): who
took the gate, which route, the decision's evidence, and — when the
fallback took it — why the decision did not.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from functualize.workflow import (
    END,
    ChoiceDecision,
    ConditionalEdge,
    Edge,
    FromStep,
    Gate,
    Step,
    workflow,
)

if TYPE_CHECKING:
    from functualize.app import FunctualizeApp

Route = Literal["deterministic", "cheap_model", "frontier_agent", "human_review"]


class RouteChoice(BaseModel):
    route: Route  # required — a default would bypass the decision


class Review(BaseModel):
    handled: bool


ROUTER = ChoiceDecision(
    field="route",
    instructions="Choose how this request should be handled.",
    options={
        "deterministic": "a fixed rule or lookup answers it; no model needed",
        "cheap_model": "a short, low-risk text task a small model can do",
        "frontier_agent": "multi-step reasoning or tool use is required",
        "human_review": "risky, ambiguous, or needs a person's judgement",
    },
    state=FromStep("intake"),
    accept_at=0.70,
    min_margin=0.10,
    fallback="human_review",
)


def build_router(app: FunctualizeApp, text: str) -> list[str]:
    """Register workflow ``router`` and its jobs on ``app``; return the list stubs append to."""
    ran: list[str] = []

    def _stub(route: str) -> Callable[[], str]:
        def job() -> str:
            ran.append(route)
            return route

        return job

    def intake() -> str:
        return text

    @workflow(
        steps=[
            Step("intake"),
            Gate(name="route", awaits=RouteChoice, decide=ROUTER),
            Step("deterministic"),
            Step("cheap_model"),
            Step("frontier_agent"),
            Gate(name="review", awaits=Review),
            Step("handle_by_person"),
        ],
        edges=[
            Edge("intake", "route"),
            ConditionalEdge(
                source="route",
                condition=lambda answer: answer["route"],
                targets={
                    "deterministic": "deterministic",
                    "cheap_model": "cheap-model",
                    "frontier_agent": "frontier-agent",
                    "human_review": "review",
                },
            ),
            Edge("review", "handle-by-person"),
            Edge("deterministic", END),
            Edge("cheap-model", END),
            Edge("frontier-agent", END),
            Edge("handle-by-person", END),
        ],
    )
    def router() -> str:
        return "routed"

    app.register_dynamic_job("intake", intake)
    app.register_dynamic_job("deterministic", _stub("deterministic"))
    app.register_dynamic_job("cheap_model", _stub("cheap_model"))
    app.register_dynamic_job("frontier_agent", _stub("frontier_agent"))
    app.register_dynamic_job("handle_by_person", _stub("handle_by_person"))
    app.register_dynamic_job("router", router)
    return ran
