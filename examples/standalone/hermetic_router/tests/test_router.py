"""The hermetic router, driven end to end through the public surface.

Every case boots the example's own workflow through ``build_router``,
executes it with ``app.execute``, and reads the run back with
``decision_record`` — no resolver, provider or store is touched directly.
The provider is a fake implementing the public ``DecisionProvider``
protocol, so the whole example runs without a network, a key, or any
provider package installed.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from router import ROUTER, build_router

# Resetting process state between tests is the one internal touch these
# tests make; the example itself uses public API only.
from functualize._app.state import AppState
from functualize.app import FunctualizeApp
from functualize.app.utils import ScopeStore, answer_gate, decision_record, gate_draft
from functualize.job import RunStatus
from functualize.plugin import (
    DecisionFailure,
    DecisionGateResolver,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
    DecisionUnavailableError,
)
from functualize.types import RunRequest
from functualize.workflow import Gate, Step

_TEXT = "Refund my order 8831 — the box arrived empty."

_CLEAR_DISTRIBUTION: Mapping[str, float] = {
    "cheap_model": 0.82,
    "deterministic": 0.05,
    "frontier_agent": 0.03,
    "human_review": 0.10,
}

_WEAK_DISTRIBUTION: Mapping[str, float] = {
    "deterministic": 0.55,
    "cheap_model": 0.20,
    "frontier_agent": 0.15,
    "human_review": 0.10,
}

_EVIDENCE_KEYS = {
    "schema",
    "field",
    "state",
    "rule",
    "provider",
    "model",
    "requested_model",
    "proposal",
    "distribution",
    "confidence",
    "probability",
    "margin",
    "verdict",
    "failure",
    "latency_seconds",
    "input_tokens",
    "output_tokens",
}


@pytest.fixture(autouse=True)
def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield project
    AppState.reset()


@pytest.fixture(autouse=True)
def _never_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(seconds: float) -> None:
        raise AssertionError(f"the router slept for {seconds} s")

    monkeypatch.setattr(time, "sleep", refuse)


@dataclass
class FakeProvider:
    """A ``DecisionProvider`` answering every request with one canned result."""

    value: str = "cheap_model"
    distribution: Mapping[str, float] | None = None
    confidence: float | None = None
    error: DecisionUnavailableError | None = None
    calls: int = 0

    @property
    def name(self) -> str:
        return "fake"

    def choose(self, request: Any) -> DecisionResult[str]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return DecisionResult(
            value=self.value,
            provider="fake",
            model="fake-1",
            provenance=DecisionProvenance(
                requested_model="fake-1",
                latency_seconds=0.0,
                input_tokens=332,
                output_tokens=38,
            ),
            distribution=self.distribution,
            confidence=self.confidence,
        )


@dataclass
class Routed:
    """The booted app, the stubs that ran, and the provider it decides with."""

    app: FunctualizeApp
    ran: list[str]
    provider: FakeProvider
    scope: str

    def run(self) -> Any:
        return self.app.execute(
            RunRequest(
                job_name="router", surface="app.execute", workflow_scope_id=self.scope
            )
        )

    def store(self) -> ScopeStore:
        return ScopeStore(self.app.substrate)

    def record(self) -> dict[str, Any] | None:
        return decision_record(self.store(), self.scope, "route")


def _routed(provider: FakeProvider, scope: str = "req-1") -> Routed:
    app = FunctualizeApp(name="hermetic-router")
    ran = build_router(app, _TEXT)
    app.gates.register_gate_strategy("decision", DecisionGateResolver(provider))
    return Routed(app, ran, provider, scope)


def test_a_clear_proposal_routes_the_request() -> None:
    """AC-2: 0.82 with a 0.72 lead is taken; no person, no fallback."""
    routed = _routed(FakeProvider("cheap_model", _CLEAR_DISTRIBUTION))

    result = routed.run()

    assert result.status is RunStatus.SUCCESS
    assert routed.ran == ["cheap_model"]
    record = routed.record()
    assert record is not None
    assert record["route"] == "cheap_model"
    assert record["decided_by"] == "decision"
    assert record["fallback_used"] is False


def test_a_weak_proposal_falls_back_and_blocks_on_review() -> None:
    """AC-3: 0.55 with a 0.35 lead misses 0.70; the fallback routes to a person.

    The recorded ladder is asserted, not just the outcome: a gate walked
    with the wrong rungs (the no-fallback ladder) can end in this same
    blocked place, and only the candidates tell those apart.
    """
    routed = _routed(FakeProvider("deterministic", _WEAK_DISTRIBUTION))

    result = routed.run()

    assert result.status is RunStatus.BLOCKED
    assert result.metadata["blocked_on"] == "review"
    assert "deterministic" not in routed.ran
    record = routed.record()
    assert record is not None
    assert record["route"] == "human_review"
    assert record["fallback_used"] is True
    assert record["reason"] is not None
    assert "proposed 'deterministic' at 0.55" in record["reason"]
    candidates = gate_draft(routed.app, routed.store(), routed.scope, "route")[
        "resolution"
    ]["candidates"]
    assert [
        (candidate["source"], candidate["outcome"]) for candidate in candidates
    ] == [
        ("strategy:decision", "failed"),
        ("strategy:resolve", "accepted"),
    ]


def test_a_rate_limited_provider_falls_back_at_once() -> None:
    """AC-4: a 429 is routed around in under a second, not waited out."""
    routed = _routed(
        FakeProvider(
            error=DecisionUnavailableError(
                kind=DecisionFailure.RATE_LIMITED,
                provider="fake",
                status=429,
                retry_after=19014.0,
                detail="Rate limit exceeded",
            )
        )
    )
    started = time.monotonic()

    result = routed.run()

    assert time.monotonic() - started < 1.0
    assert result.status is RunStatus.BLOCKED
    assert result.metadata["blocked_on"] == "review"
    record = routed.record()
    assert record is not None
    assert record["route"] == "human_review"
    assert record["fallback_used"] is True
    assert record["evidence"] is not None
    assert record["evidence"]["failure"]["kind"] == "rate_limited"


def test_the_recorded_evidence_is_the_whole_story() -> None:
    """AC-6: the decision's evidence carries the contracted key set."""
    routed = _routed(FakeProvider("cheap_model", _CLEAR_DISTRIBUTION))
    routed.run()

    evidence = (routed.record() or {})["evidence"]
    assert set(evidence) == _EVIDENCE_KEYS
    assert evidence["state"]["sha256"] == hashlib.sha256(_TEXT.encode()).hexdigest()
    assert evidence["rule"]["digest"].startswith("sha256:")
    assert evidence["rule"]["fallback"] == "human_review"
    assert evidence["distribution"] == dict(_CLEAR_DISTRIBUTION)
    assert evidence["input_tokens"] == 332
    assert evidence["output_tokens"] == 38


@pytest.mark.parametrize(
    ("value", "distribution", "confidence", "expected_route"),
    [
        pytest.param(
            "deterministic",
            {"deterministic": 0.54, "cheap_model": 0.35},
            1.0,
            "human_review",
            id="sure-but-weak-falls-back",
        ),
        pytest.param(
            "cheap_model",
            {"cheap_model": 0.85, "deterministic": 0.10},
            0.0,
            "cheap_model",
            id="unsure-but-clear-is-taken",
        ),
    ],
)
def test_the_providers_own_assessment_never_decides(
    value: str,
    distribution: dict[str, float],
    confidence: float,
    expected_route: str,
) -> None:
    """AC-7: recorded, never read."""
    routed = _routed(FakeProvider(value, distribution, confidence=confidence))

    routed.run()

    record = routed.record()
    assert record is not None
    assert record["route"] == expected_route


def test_two_scopes_on_one_text_are_comparable() -> None:
    """AC-8: same state and rule, different distributions — both recorded."""
    first = _routed(FakeProvider("cheap_model", _CLEAR_DISTRIBUTION), scope="req-a")
    second = _routed(
        FakeProvider(
            "frontier_agent",
            {
                "frontier_agent": 0.80,
                "cheap_model": 0.10,
                "deterministic": 0.05,
                "human_review": 0.05,
            },
        ),
        scope="req-b",
    )
    first.run()
    second.run()

    a, b = first.record(), second.record()
    assert a is not None and b is not None
    assert a["evidence"]["state"]["sha256"] == b["evidence"]["state"]["sha256"]
    assert a["evidence"]["rule"]["digest"] == b["evidence"]["rule"]["digest"]
    assert a["evidence"]["distribution"] != b["evidence"]["distribution"]
    assert (a["route"], b["route"]) == ("cheap_model", "frontier_agent")


def test_resuming_a_routed_scope_does_not_ask_again() -> None:
    """AC-9: the accepted proposal is replayed from the record."""
    routed = _routed(FakeProvider("cheap_model", _CLEAR_DISTRIBUTION))
    assert routed.run().status is RunStatus.SUCCESS
    before = routed.record()

    resumed = routed.run()

    assert resumed.status is RunStatus.SUCCESS
    assert routed.provider.calls == 1
    assert routed.ran == ["cheap_model"]
    assert routed.record() == before


def test_a_person_answers_review_and_cannot_forge_evidence() -> None:
    """AC-10: the answered gate runs its branch; an answer records no evidence."""
    routed = _routed(FakeProvider("deterministic", _WEAK_DISTRIBUTION))
    assert routed.run().status is RunStatus.BLOCKED

    answer_gate(
        routed.app,
        routed.store(),
        routed.scope,
        "review",
        {"handled": True, "evidence": {"forged": 1}},
    )

    resumed = routed.run()

    assert resumed.status is RunStatus.SUCCESS
    assert routed.ran == ["handle_by_person"]
    candidates = gate_draft(routed.app, routed.store(), routed.scope, "review")[
        "resolution"
    ]["candidates"]
    assert len(candidates) == 1
    assert "evidence" not in candidates[0]


def test_every_step_past_the_router_is_not_effecting() -> None:
    """AC-14: routing decides, it never effects — every node reachable from the
    router without passing a gate is a plain, non-effecting step."""
    app = FunctualizeApp(name="hermetic-router")
    build_router(app, _TEXT)
    declaration = app.get_job("router").function.__functualize_workflow__

    by_name = {node.name: node for node in declaration.nodes}
    successors: dict[str, list[str]] = {}
    for edge in declaration.edges:
        targets = getattr(edge, "targets", None)
        reached = list(targets.values()) if targets else [edge.target]
        successors.setdefault(edge.source, []).extend(
            target for target in reached if isinstance(target, str)
        )

    seen: set[str] = set()
    frontier = list(successors.get("route", []))
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        node = by_name[name]
        if isinstance(node, Gate):
            continue  # beyond a gate is another question, not this one's
        assert isinstance(node, Step)
        assert node.effecting is False
        frontier.extend(successors.get(name, []))

    assert seen == {
        "deterministic",
        "cheap-model",
        "frontier-agent",
        "review",
    }


def test_with_no_provider_configured_the_fallback_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The router runs with nothing installed or configured: the fallback answers."""
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    app = FunctualizeApp(name="hermetic-router")
    ran = build_router(app, _TEXT)
    routed = Routed(app, ran, FakeProvider(), scope="req-1")

    result = routed.run()

    assert result.status is RunStatus.BLOCKED
    assert result.metadata["blocked_on"] == "review"
    record = routed.record()
    assert record is not None
    assert record["route"] == "human_review"
    assert record["fallback_used"] is True
    reason = record["reason"] or ""
    assert "not_configured" in reason or "install functualize-decision-jev" in reason


def test_the_declared_router_is_the_reference() -> None:
    """The example's numbers are the reference, and its fake is a provider."""
    assert isinstance(FakeProvider(), DecisionProvider)
    assert (ROUTER.accept_at, ROUTER.min_margin, ROUTER.fallback) == (
        0.70,
        0.10,
        "human_review",
    )
    assert set(ROUTER.options) == {
        "deterministic",
        "cheap_model",
        "frontier_agent",
        "human_review",
    }
