"""A gate's declared decision rule is part of the graph a parked walk resumes.

A walk that blocked at a decision gate was started under one rule —
``accept_at``, ``min_margin``, the options, the instructions. If the module is
edited to loosen that rule while the walk is parked, resuming would apply a
rule the walk never ran under. So the rule is projected into the workflow shape,
the graph digest hashes that shape, and the walker's existing digest check
refuses the resume — the same refusal a moved edge already gets.

The other half matters as much: a gate that declares no decision must project,
and digest, byte-for-byte as it did before, or every walk parked before this
change would be refused on upgrade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel
from tests._support.engine_storage import port_for

from functualize._engine.workflow_validation import (
    WorkflowGraphChangedError,
    graph_digest,
)
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.decision import ChoiceDecision
from functualize._types.from_job import FromStep
from functualize._types.workflow import (
    END,
    Edge,
    Gate,
    Step,
    WorkflowDeclaration,
    WorkflowShape,
)

_OPTIONS = {
    "billing": "a question about an invoice or a charge",
    "returns": "the customer wants to send something back",
    "shipping": "where a parcel is, or when it arrives",
}


class Route(BaseModel):
    route: Literal["billing", "returns", "shipping"]


def _decision(**overrides: object) -> ChoiceDecision:
    arguments: dict[str, object] = {
        "field": "route",
        "instructions": "Route the ticket to the team that owns it.",
        "options": _OPTIONS,
        "state": FromStep("intake"),
        "accept_at": 0.70,
        "min_margin": 0.10,
    }
    arguments.update(overrides)
    return ChoiceDecision(**arguments)  # type: ignore[arg-type]


def _routed(decide: ChoiceDecision | None) -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("intake"), Gate(name="route", awaits=Route, decide=decide)),
        edges=(Edge(source="intake", target="route"), Edge(source="route", target=END)),
    )


class TestTheRuleIsInTheDigest:
    """AC-18."""

    @pytest.mark.parametrize(
        "changed",
        [
            pytest.param({"accept_at": 0.60}, id="accept_at"),
            pytest.param({"min_margin": 0.0}, id="min_margin"),
            pytest.param(
                {"options": {**_OPTIONS, "shipping": "parcels"}}, id="option-meaning"
            ),
            pytest.param({"instructions": "Pick a team."}, id="instructions"),
            pytest.param({"model": "jev-1.13"}, id="model"),
        ],
    )
    def test_changing_the_rule_changes_the_digest(
        self, changed: dict[str, object]
    ) -> None:
        """Case 1: any part of the declared rule moves the digest."""
        assert graph_digest(_routed(_decision())) != graph_digest(
            _routed(_decision(**changed))
        )

    def test_the_same_rule_digests_the_same(self) -> None:
        assert graph_digest(_routed(_decision())) == graph_digest(_routed(_decision()))

    def test_a_gate_without_a_decision_projects_as_before(self) -> None:
        """Case 2: no `decision` key at all, so pre-existing digests hold."""
        entry = _routed(None).shape().to_dict()["steps"][1]

        assert entry == {"gate": "route", "model": "Route"}
        assert "decision" not in entry

    def test_a_parked_walk_refuses_to_resume_under_a_changed_rule(
        self, tmp_path: Path
    ) -> None:
        """Case 3: the walker's existing check refuses, and says so."""
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        parked = _routed(_decision(accept_at=0.70))
        store.set_graph_digest("wf", graph_digest(parked))
        loosened = _routed(_decision(accept_at=0.50))

        walker = WorkflowWalker(
            loosened,
            store,
            "wf",
            run_step=lambda name: name,
            runtime_store=port_for(store),
        )
        with pytest.raises(WorkflowGraphChangedError) as raised:
            walker.run()

        assert raised.value.recorded == graph_digest(parked)
        assert raised.value.current == graph_digest(loosened)


class TestTheShapeRoundTrips:
    def test_the_projected_rule_is_json_safe_and_complete(self) -> None:
        entry = _routed(_decision(model="jev-1.13")).shape().to_dict()["steps"][1]

        assert entry == {
            "gate": "route",
            "model": "Route",
            "decision": {
                "field": "route",
                "instructions": "Route the ticket to the team that owns it.",
                "options": _OPTIONS,
                "state": "intake",
                "accept_at": 0.70,
                "min_margin": 0.10,
                "model": "jev-1.13",
            },
        }
        assert json.loads(json.dumps(entry)) == entry

    @pytest.mark.parametrize(
        "decide",
        [pytest.param(_decision(), id="with"), pytest.param(None, id="without")],
    )
    def test_to_dict_and_from_dict_round_trip(
        self, decide: ChoiceDecision | None
    ) -> None:
        shape = _routed(decide).shape()

        rebuilt = WorkflowShape.from_dict(json.loads(json.dumps(shape.to_dict())))

        assert rebuilt == shape
        assert rebuilt is not None and rebuilt.to_dict() == shape.to_dict()

    def test_a_malformed_decision_entry_rebuilds_nothing(self) -> None:
        data = _routed(_decision()).shape().to_dict()
        data["steps"][1]["decision"] = ["not", "an", "object"]

        assert WorkflowShape.from_dict(data) is None
