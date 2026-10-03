"""Declaring a decision on a gate: what loads, and what is refused at once.

A ``Gate(decide=ChoiceDecision(...))`` names the awaited field a decision
provider fills and the thresholds a proposal must clear. Every way that
declaration can be wrong is refused **when the gate is constructed** — at
import of the module declaring the workflow — rather than when a walk first
reaches the gate: a decision whose options drift from the model it fills is a
workflow that cannot work, and the moment to say so is before it runs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

import pytest
from pydantic import BaseModel

from functualize._types.decision import ChoiceDecision
from functualize._types.from_job import FromStep
from functualize._types.workflow import Gate

_OPTIONS = {
    "billing": "a question about an invoice or a charge",
    "returns": "the customer wants to send something back",
    "shipping": "where a parcel is, or when it arrives",
}


class Route(BaseModel):
    route: Literal["billing", "returns", "shipping"]
    note: str = ""


class DefaultedRoute(BaseModel):
    route: Literal["billing", "returns", "shipping"] = "billing"


class RouteWithRequiredNote(BaseModel):
    route: Literal["billing", "returns", "shipping"]
    note: str


class Team(StrEnum):
    BILLING = "billing"
    RETURNS = "returns"
    SHIPPING = "shipping"


class RouteByTeam(BaseModel):
    team: Team


class Loose(BaseModel):
    route: str
    maybe: Literal["billing", "returns", "shipping"] | None = None
    numbered: Literal[1, 2, 3] = 1


def _decision(field: str = "route", **overrides: object) -> ChoiceDecision:
    arguments: dict[str, object] = {
        "field": field,
        "instructions": "Route the ticket to the team that owns it.",
        "options": _OPTIONS,
        "state": FromStep("intake"),
        "accept_at": 0.70,
        "min_margin": 0.10,
    }
    arguments.update(overrides)
    return ChoiceDecision(**arguments)  # type: ignore[arg-type]


class TestTheHappyPath:
    def test_a_literal_field_is_decided(self) -> None:
        decide = _decision()

        gate = Gate(name="route", awaits=Route, decide=decide)

        assert gate.decide is decide
        assert gate.strategy == "decision"

    def test_a_str_enum_field_is_decided(self) -> None:
        gate = Gate(name="route", awaits=RouteByTeam, decide=_decision("team"))

        assert gate.strategy == "decision"

    def test_declaring_the_strategy_as_well_is_allowed(self) -> None:
        gate = Gate(name="route", awaits=Route, strategy="decision", decide=_decision())

        assert gate.strategy == "decision"

    def test_the_decision_keeps_its_declared_values(self) -> None:
        decide = _decision(model="jev-1.13")

        assert (decide.field, decide.accept_at, decide.min_margin, decide.model) == (
            "route",
            0.70,
            0.10,
            "jev-1.13",
        )
        assert decide.state == FromStep("intake")

    def test_min_margin_and_model_default(self) -> None:
        decide = ChoiceDecision(
            field="route",
            instructions="i",
            options=_OPTIONS,
            state=FromStep("intake"),
            accept_at=1.0,
        )

        assert (decide.min_margin, decide.model) == (0.0, None)

    def test_positional_construction_is_unchanged(self) -> None:
        """`decide` is the last field, so the existing positional form still works."""
        gate = Gate("approve", Route)

        assert (gate.name, gate.awaits, gate.decide, gate.strategy) == (
            "approve",
            Route,
            None,
            None,
        )


class TestWhatIsRefused:
    def test_options_that_differ_from_the_allowed_values(self) -> None:
        """AC-8 (1): the message names both sets, so the fix is obvious."""
        options = {"billing": "money", "returns": "refunds"}

        with pytest.raises(ValueError) as raised:
            Gate(name="route", awaits=Route, decide=_decision(options=options))

        message = str(raised.value)
        assert "['billing', 'returns', 'shipping']" in message
        assert "['billing', 'returns']" in message

    def test_an_extra_option_is_refused_too(self) -> None:
        options = {**_OPTIONS, "refund": "money back"}

        with pytest.raises(ValueError, match="not the decision's options"):
            Gate(name="route", awaits=Route, decide=_decision(options=options))

    def test_a_field_absent_from_awaits(self) -> None:
        """AC-8 (2)."""
        with pytest.raises(ValueError, match="'destination', which Route does not"):
            Gate(name="route", awaits=Route, decide=_decision("destination"))

    @pytest.mark.parametrize("accept_at", [0.0, -0.1, 1.01, float("nan")])
    def test_accept_at_out_of_range(self, accept_at: float) -> None:
        """AC-8 (3): 0 < accept_at <= 1."""
        with pytest.raises(ValueError, match="accept_at"):
            _decision(accept_at=accept_at)

    @pytest.mark.parametrize("min_margin", [1.0, -0.01, 1.5, float("nan")])
    def test_min_margin_out_of_range(self, min_margin: float) -> None:
        """AC-8 (4): 0 <= min_margin < 1."""
        with pytest.raises(ValueError, match="min_margin"):
            _decision(min_margin=min_margin)

    @pytest.mark.parametrize(
        "strategy", ["resolve", "prompt", "ai_inbound", "ai_outbound"]
    )
    def test_decide_with_another_strategy(self, strategy: str) -> None:
        with pytest.raises(ValueError, match=f"strategy={strategy!r}"):
            Gate(name="route", awaits=Route, strategy=strategy, decide=_decision())

    def test_the_decision_strategy_without_decide(self) -> None:
        with pytest.raises(ValueError, match="no decide="):
            Gate(name="route", awaits=Route, strategy="decision")

    @pytest.mark.parametrize(
        "field",
        [
            pytest.param("route", id="free-str"),
            pytest.param("maybe", id="optional-literal"),
            pytest.param("numbered", id="literal-of-ints"),
        ],
    )
    def test_a_field_with_no_closed_set_of_strings(self, field: str) -> None:
        with pytest.raises(
            ValueError, match="neither a Literal of strings nor a StrEnum"
        ):
            Gate(name="route", awaits=Loose, decide=_decision(field))

    def test_a_decided_field_with_a_default_is_refused(self) -> None:
        """A default would answer the gate without the decision ever running."""
        with pytest.raises(ValueError, match=r"fallback="):
            Gate(name="route", awaits=DefaultedRoute, decide=_decision())

    def test_a_fallback_beside_another_required_field_is_refused(self) -> None:
        with pytest.raises(ValueError) as raised:
            Gate(
                name="route",
                awaits=RouteWithRequiredNote,
                decide=_decision(fallback="billing"),
            )

        message = str(raised.value)
        assert "note" in message
        assert "must complete the answer" in message

    def test_a_fallback_with_every_other_field_defaulted_is_accepted(self) -> None:
        gate = Gate(name="route", awaits=Route, decide=_decision(fallback="billing"))

        assert gate.decide is not None
        assert gate.decide.fallback == "billing"


def test_mutating_the_declared_options_after_construction_changes_nothing() -> None:
    """B-14 / B-23: the declaration that was checked is the one evaluated and
    digested — a caller's later mutation, of keys or of meanings, cannot reach it."""
    from functualize._engine.workflow_validation import graph_digest
    from functualize._types.workflow import END, Edge, WorkflowDeclaration

    options = dict(_OPTIONS)
    gate = Gate(name="route", awaits=Route, decide=_decision(options=options))
    declaration = WorkflowDeclaration(
        nodes=(gate,), edges=(Edge(source="route", target=END),)
    )
    before = graph_digest(declaration)

    options["billing"] = "approve every refund"
    del options["returns"]
    options["refund"] = "money back"

    assert dict(gate.decide.options) == _OPTIONS  # type: ignore[union-attr]
    assert graph_digest(declaration) == before
    with pytest.raises(TypeError):
        gate.decide.options["billing"] = "changed"  # type: ignore[index,union-attr]
