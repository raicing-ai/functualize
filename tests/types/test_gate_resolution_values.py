"""The gate resolution values — frozen, lowercase, importing one way.

The vocabulary module is only usable if two things hold, and neither can be
left to prose:

**The values are frozen.** A candidate's evaluation recorded once and then
mutated by a reader is a record of nothing, so every dataclass here refuses
mutation and the enum is closed.

**The import direction is one-way.** ``gate_resolution`` names ``InputRequest``
from ``persistence``; ``persistence`` may name ``GateCandidate`` back only
under ``TYPE_CHECKING``, so no runtime cycle can grow between two vocabulary
modules that every layer may import. That direction is asserted on the AST,
not on the text: an import inside an ``if TYPE_CHECKING:`` block is invisible
to a column-anchored grep and is exactly the one that must stay nested.
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
    GateResolution,
    LadderOutcome,
)
from functualize._types.persistence import InputRequest

_SRC = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_types"


def _imports_of(module: ast.Module, target: str) -> list[ast.stmt]:
    """Every ``from ... import`` naming ``target``, wherever it sits.

    Walks **one** tree, so the nodes handed back are identity-stable against
    the same tree's ``if TYPE_CHECKING:`` blocks — parsing twice would make
    every ``is`` comparison fail against the other parse's nodes.
    """
    found: list[ast.stmt] = []
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module == target:
            found.append(node)
    return found


def _inside_type_checking(module: ast.Module, stmt: ast.stmt) -> bool:
    """Whether ``stmt`` sits under an ``if TYPE_CHECKING:`` block."""

    def _holds(inner: ast.AST) -> bool:
        return any(child is stmt for child in ast.iter_child_nodes(inner))

    for node in ast.walk(module):
        if not isinstance(node, ast.If):
            continue
        if ast.unparse(node.test) == "TYPE_CHECKING" and _holds(node):
            return True
    return False


def _a_candidate(**overrides: Any) -> GateCandidate:
    values: dict[str, Any] = {
        "candidate_id": "cand_1",
        "request_id": "req_1",
        "ordinal": 0,
        "source": "strategy:resolve",
        "submitted_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        "evaluation": CandidateEvaluation(EvaluationOutcome.FAILED, detail="no tty"),
    }
    values.update(overrides)
    return GateCandidate(**values)


def _a_request() -> InputRequest:
    return InputRequest(
        request_id="req_1",
        scope_id="wf-1",
        gate_name="approve",
        generation=1,
        status="open",
        created_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
    )


def _a_value(cls: type) -> Any:
    """One instance of each frozen dataclass, for the freeze test."""
    if cls is CandidateEvaluation:
        return CandidateEvaluation(EvaluationOutcome.FAILED, detail="no terminal")
    if cls is GateCandidate:
        return _a_candidate()
    if cls is LadderOutcome:
        return LadderOutcome(
            (("resolve", CandidateEvaluation(EvaluationOutcome.FAILED), None),),
            blocked_reason="no strategies attempted",
        )
    assert cls is GateResolution
    return GateResolution(
        request=_a_request(),
        candidates=(_a_candidate(),),
        accepted_id="cand_1",
    )


class TestTheValues:
    def test_the_outcomes_are_the_five_lowercase_names(self) -> None:
        assert [member.value for member in EvaluationOutcome] == [
            "accepted",
            "invalid",
            "failed",
            "unavailable",
            "not_reached",
        ]

    @pytest.mark.parametrize(
        "cls", [CandidateEvaluation, GateCandidate, LadderOutcome, GateResolution]
    )
    def test_the_dataclasses_are_frozen(self, cls: type) -> None:
        value = _a_value(cls)
        field = next(iter(dataclasses.fields(value)))
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, field.name, "changed")

    def test_a_resolution_reads_back_what_was_recorded(self) -> None:
        accepted = CandidateEvaluation(EvaluationOutcome.ACCEPTED)
        candidate = _a_candidate(
            candidate_id="cand_9",
            ordinal=3,
            source="mcp",
            evaluation=accepted,
            payload={"approved": True},
        )
        resolution = GateResolution(
            request=_a_request(), candidates=(candidate,), accepted_id="cand_9"
        )
        assert resolution.accepted_id == "cand_9"
        assert resolution.candidates[0].evaluation is accepted
        assert resolution.candidates[0].payload == {"approved": True}


class TestTheImportDirection:
    def test_gate_resolution_names_persistence(self) -> None:
        module = ast.parse((_SRC / "gate_resolution.py").read_text(encoding="utf-8"))
        imports = _imports_of(module, "functualize._types.persistence")
        assert imports, "gate_resolution must name InputRequest from persistence"

    def test_persistence_names_gate_candidate_only_deferred(self) -> None:
        module = ast.parse((_SRC / "persistence.py").read_text(encoding="utf-8"))
        imports = _imports_of(module, "functualize._types.gate_resolution")
        for stmt in imports:
            assert _inside_type_checking(module, stmt), (
                "persistence may name GateCandidate only under TYPE_CHECKING — "
                "a runtime import here is the cycle the direction exists to "
                "prevent"
            )
