"""The fallback changes routing without changing the Phase 1 gate vocabulary."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import time
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from functualize_decision_jev._provider import JevDecisionProvider, WireResponse
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._engine.workflow_validation import graph_digest
from functualize._engine.workflow_walker import WalkOutcome
from functualize._gate._strategy import CORE_STRATEGIES, STRATEGY_PROVIDERS
from functualize._types.gate_resolution import EvaluationOutcome
from functualize._types.workflow import _VALID_GATE_STRATEGIES
from functualize.app import FunctualizeApp
from functualize.app.utils import ScopeStore, decision_record, gate_draft
from functualize.job import RunStatus
from functualize.plugin import DecisionGateResolver
from functualize.types import RunRequest
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


class Route(BaseModel):
    route: Literal["returns", "shipping", "human_review"]


@dataclass
class FakeTransport:
    response: WireResponse

    def post(
        self, url: str, body: bytes, headers: Mapping[str, str], timeout: float
    ) -> WireResponse:
        return self.response


def _proposes(value: str, **probabilities: float) -> FakeTransport:
    body = json.dumps(
        {
            "answers": {
                "decision": {
                    "choice": value,
                    "confidence": 0.99,
                    "probabilities": probabilities,
                    "type": "choice",
                }
            },
            "model": "jev-1.13-free",
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }
    )
    return FakeTransport(WireResponse(200, body, {}))


@pytest.fixture(autouse=True)
def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    AppState.reset()
    monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("a decision slept"))
    yield
    AppState.reset()


def _app(*, fallback: str | None) -> FunctualizeApp:
    app = FunctualizeApp(name="routing-guard")
    decision = ChoiceDecision(
        field="route",
        instructions="Route this request.",
        options={
            "returns": "a return",
            "shipping": "a shipment",
            "human_review": "a person must decide",
        },
        state=FromStep("intake"),
        accept_at=0.70,
        min_margin=0.10,
        fallback=fallback,
    )

    @workflow(
        steps=[
            Step("intake"),
            Gate(name="route", awaits=Route, decide=decision),
            Step("returns"),
            Step("shipping"),
            Step("human_review"),
        ],
        edges=[
            Edge("intake", "route"),
            ConditionalEdge(
                source="route",
                condition=lambda answer: answer["route"],
                targets={
                    "returns": "returns",
                    "shipping": "shipping",
                    "human_review": "human_review",
                },
            ),
            Edge("returns", END),
            Edge("shipping", END),
            Edge("human_review", END),
        ],
    )
    def router() -> str:
        return "routed"

    app.register_dynamic_job("intake", lambda: "Where is my parcel?")
    for name in ("returns", "shipping", "human_review"):
        app.register_dynamic_job(name, lambda route=name: route)
    app.register_dynamic_job("router", router)
    return app


def _run(app: FunctualizeApp) -> Any:
    return app.execute(
        RunRequest(job_name="router", surface="app.execute", workflow_scope_id="req-1")
    )


def _store(app: FunctualizeApp) -> ScopeStore:
    return ScopeStore(app.substrate)


def test_missing_provider_takes_the_declared_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: hiding the plugin still leaves a complete fallback route."""
    ep_module = importlib.import_module("functualize._primitives.entry_points")
    loader = importlib.import_module("functualize._plugins.loader")
    visible = ep_module.entry_points

    def without_jev(*, group: str) -> tuple[Any, ...]:
        return tuple(
            ep
            for ep in visible(group=group)
            if getattr(getattr(ep, "dist", None), "name", None)
            != "functualize-decision-jev"
        )

    monkeypatch.setattr(ep_module, "entry_points", without_jev)
    monkeypatch.setattr(loader, "entry_points", without_jev, raising=False)
    app = _app(fallback="human_review")

    assert _run(app).status is RunStatus.SUCCESS
    record = decision_record(_store(app), "req-1", "route")
    assert record is not None
    assert record["route"] == "human_review"
    assert record["decided_by"] == "fallback"
    assert "install functualize-decision-jev" in record["reason"]
    candidates = gate_draft(app, _store(app), "req-1", "route")["resolution"][
        "candidates"
    ]
    assert [(c["source"], c["outcome"]) for c in candidates] == [
        ("strategy:decision", "unavailable"),
        ("strategy:resolve", "accepted"),
    ]


def test_phase_one_weak_proposal_still_blocks_for_a_person() -> None:
    """AC-11: no fallback keeps the original blocking reason and ladder."""
    app = _app(fallback=None)
    provider = JevDecisionProvider(
        transport=_proposes("returns", returns=0.54, shipping=0.46),
        credential=lambda: "test-key",
    )
    app.gates.register_gate_strategy("decision", DecisionGateResolver(provider))

    result = _run(app)

    assert result.status is RunStatus.BLOCKED
    assert (
        "decision: jev/jev-1.13-free proposed 'returns' at 0.54 (margin 0.08); "
        "workflow requires >= 0.70, margin >= 0.10"
    ) in result.metadata["blocked_reason"]
    candidates = gate_draft(app, _store(app), "req-1", "route")["resolution"][
        "candidates"
    ]
    assert candidates[0]["source"] == "strategy:decision"
    assert candidates[0]["outcome"] == "failed"
    assert candidates[0]["evidence"]["verdict"] == "below_threshold"


def test_declaring_a_fallback_changes_the_graph_digest() -> None:
    """AC-12: a parked run can detect that its policy changed."""
    without = _app(fallback=None).get_job("router").function.__functualize_workflow__
    with_fallback = (
        _app(fallback="human_review")
        .get_job("router")
        .function.__functualize_workflow__
    )
    assert graph_digest(without) != graph_digest(with_fallback)


def test_no_new_gate_or_walk_primitive_was_added() -> None:
    """AC-13: pin the five outcomes, five strategies, and five walk results."""
    assert {item.value for item in EvaluationOutcome} == {
        "accepted",
        "invalid",
        "failed",
        "unavailable",
        "not_reached",
    }
    assert {
        "resolve",
        "prompt",
        "ai_inbound",
        "ai_outbound",
        "decision",
    } == _VALID_GATE_STRATEGIES
    assert set(STRATEGY_PROVIDERS) == _VALID_GATE_STRATEGIES
    assert {"resolve", "prompt"} == CORE_STRATEGIES
    assert {item.value for item in WalkOutcome} == {
        "completed",
        "blocked",
        "failed",
        "superseded",
        "held",
    }


def test_provider_source_is_unchanged() -> None:
    """AC-16: this branch did not rewrite the experimental provider."""
    if shutil.which("git") is None:
        pytest.skip("git is unavailable")
    result = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "ef1939d",
            "--",
            "plugins/domains/functualize-decision-jev/src",
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
