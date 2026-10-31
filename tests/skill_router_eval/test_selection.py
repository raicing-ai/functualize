"""The gated selection: one request, one gate, and no silent fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from functualize.plugin import (
    DecisionFailure,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
    DecisionUnavailableError,
)
from functualize.types import RunStatus
from tests.skill_router_eval.catalog import OPTIONS, derive_catalog, option_meanings
from tests.skill_router_eval.selection import (
    ESCALATED,
    SELECT_INSTRUCTIONS,
    SkillChoice,
    _walk,
    select,
    select_decision,
)

ENTRIES = derive_catalog()
REQUEST = "func: command not found after composer global require"

class FakeProvider(DecisionProvider):
    """A provider that proposes one option at one probability, and records calls."""

    name = "fake"

    def __init__(self, value: str = "functualize-cli", probability: float = 0.90):
        self.value = value
        self.probability = probability
        self.calls: list[Any] = []

    def choose(self, request: Any) -> DecisionResult[str]:
        self.calls.append(request)
        options = list(request.options)
        rest = (1.0 - self.probability) / (len(options) - 1)
        distribution = {option: rest for option in options}
        distribution[self.value] = self.probability
        return DecisionResult(
            value=self.value,
            provider=self.name,
            model="fake-1",
            provenance=DecisionProvenance("fake-1", latency_seconds=0.0),
            distribution=distribution,
        )

    def identity(self) -> dict[str, object]:
        return {"comparator": self.name}

class UnavailableProvider(DecisionProvider):
    """A provider that cannot answer at all — the provider_failed path."""

    name = "unavailable"

    def choose(self, request: Any) -> DecisionResult[str]:
        raise DecisionUnavailableError(
            kind=DecisionFailure.MALFORMED,
            provider=self.name,
            detail="the provider refused the request",
        )

    def identity(self) -> dict[str, object]:
        return {"comparator": self.name}

@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project directory the app can resolve, never ``tmp_path`` itself."""
    root = tmp_path / "workspace"
    (root / ".functualize").mkdir(parents=True)
    return root

# --------------------------------------------------------------------------
# The declaration
# --------------------------------------------------------------------------


def test_the_decision_is_the_one_the_measurement_pins() -> None:
    decision = select_decision(ENTRIES)

    assert decision.field == "skill"
    assert decision.instructions == SELECT_INSTRUCTIONS
    assert dict(decision.options) == option_meanings(ENTRIES)
    assert list(decision.options) == list(OPTIONS)
    assert (decision.accept_at, decision.min_margin) == (0.70, 0.10)
    assert decision.fallback is None


def test_the_instruction_is_the_one_c4_names() -> None:
    assert SELECT_INSTRUCTIONS == (
        "Choose the one functualize skill whose instructions this request needs "
        "before work starts, or none if no functualize skill applies."
    )


def test_the_answer_shape_refuses_a_default_and_an_unknown_option() -> None:
    with pytest.raises(ValidationError):
        SkillChoice()
    with pytest.raises(ValidationError):
        SkillChoice(skill="functualize-both")
    assert SkillChoice(skill="none").skill == "none"


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------


def test_an_accepted_proposal_is_the_outcome(project: Path) -> None:
    provider = FakeProvider("functualize-cli", 0.90)

    selection = select(
        REQUEST, provider, entries=ENTRIES, project=project, scope="accept-1"
    )

    assert selection.decided_by == "decision"
    assert selection.outcome == "functualize-cli"
    assert selection.outcome != ESCALATED
    assert selection.rule_digest == selection.record["evidence"]["rule"]["digest"]
    assert selection.rule_digest.startswith("sha256:")
    assert selection.record["evidence"]["verdict"] == "accepted"
    assert selection.record["evidence"]["probability"] == pytest.approx(0.90)


def test_no_is_an_outcome_not_an_escalation(project: Path) -> None:
    selection = select(
        "what is the capital of France",
        FakeProvider("none", 0.95),
        entries=ENTRIES,
        project=project,
        scope="none-1",
    )

    assert selection.decided_by == "decision"
    assert selection.outcome == "none"


def test_a_proposal_below_the_threshold_blocks_for_a_person(project: Path) -> None:
    provider = FakeProvider("functualize-cli", 0.55)

    result, selection = _walk(
        REQUEST, provider, entries=ENTRIES, project=project, scope="below-1"
    )

    assert result.status is RunStatus.BLOCKED
    assert result.metadata["blocked_on"] == "select"
    assert selection.outcome == ESCALATED
    assert selection.decided_by is None
    assert selection.record["fallback_used"] is False
    assert selection.record["evidence"]["verdict"] == "below_threshold"
    assert selection.record["evidence"]["proposal"] == "functualize-cli"


def test_a_provider_that_cannot_answer_escalates(project: Path) -> None:
    result, selection = _walk(
        REQUEST,
        UnavailableProvider(),
        entries=ENTRIES,
        project=project,
        scope="failed-1",
    )

    assert result.status is RunStatus.BLOCKED
    assert selection.outcome == ESCALATED
    assert selection.decided_by is None
    assert selection.record["evidence"]["verdict"] == "provider_failed"


def test_the_gate_sees_the_request_and_the_five_meanings(project: Path) -> None:
    provider = FakeProvider("functualize", 0.90)

    select(REQUEST, provider, entries=ENTRIES, project=project, scope="seen-1")

    request = provider.calls[0]
    assert request.state == REQUEST
    assert request.instructions == SELECT_INSTRUCTIONS
    assert dict(request.options) == option_meanings(ENTRIES)
    assert list(request.options) == list(OPTIONS)


def test_the_walk_leaves_the_process_where_it_found_it(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    before = Path.cwd()

    select(
        REQUEST,
        FakeProvider("none", 0.90),
        entries=ENTRIES,
        project=project,
        scope="cwd-1",
    )

    assert Path.cwd() == before


def test_every_option_is_a_route_in_the_workflow(project: Path) -> None:
    for index, option in enumerate(OPTIONS):
        selection = select(
            REQUEST,
            FakeProvider(option, 0.90),
            entries=ENTRIES,
            project=project,
            scope=f"route-{index}",
        )

        assert selection.outcome == option
        assert selection.decided_by == "decision"
