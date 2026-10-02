"""The rung evidence sink, and a declared fallback taken by the resolve rung.

Two behaviours of ``GateRegistry.evaluate`` that the recorded ladder needs:
each rung that runs gets a write-once ``RungEvidence`` and whatever it
recorded lands on that rung's ``CandidateEvaluation`` — accepted or failed
alike, because a rung that failed with evidence is exactly the rung an
operator wants the evidence for; and a ``ChoiceDecision`` that declares a
``fallback`` seeds the decided field and forces dispatch, so the ladder
reads ``decision → resolve`` with the fallback taken by the ordinary
``resolve`` rung rather than by a new primitive.

The resolvers are hand-rolled fakes registered straight into a bare
registry: the sink and the seeding are registry behaviour, and driving them
through the real decision resolver would test that resolver instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from functualize._gate._registry import GateRegistry
from functualize._gate._resolver import ResolveResolver
from functualize._types.decision import ChoiceDecision
from functualize._types.from_job import FromStep
from functualize._types.gate_resolution import EvaluationOutcome

if TYPE_CHECKING:
    from collections.abc import Mapping

    from functualize._gate._context import GateContext

_OPTIONS = {"a": "the first option", "b": "the second option"}


class Choice(BaseModel):
    choice: Literal["a", "b"]


def _decision(**overrides: object) -> ChoiceDecision:
    arguments: dict[str, object] = {
        "field": "choice",
        "instructions": "Pick one.",
        "options": _OPTIONS,
        "state": FromStep("intake"),
        "accept_at": 0.70,
    }
    arguments.update(overrides)
    return ChoiceDecision(**arguments)  # type: ignore[arg-type]


class _Rung:
    """A resolver that records fixed evidence, then returns or raises."""

    def __init__(
        self,
        evidence: list[Mapping[str, object]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.evidence = evidence or []
        self.error = error
        self.calls: list[GateContext] = []

    def resolve(self, ctx: GateContext) -> BaseModel:
        self.calls.append(ctx)
        for item in self.evidence:
            ctx.evidence.record(item)
        if self.error is not None:
            raise self.error
        return Choice(choice="a")


def _registry(*resolvers: tuple[str, object]) -> GateRegistry:
    registry = GateRegistry()
    for name, resolver in resolvers:
        registry.register_strategy(name, resolver)  # type: ignore[arg-type]
    return registry


class TestTheRungSink:
    def test_an_accepted_rung_carries_what_it_recorded(self) -> None:
        rung = _Rung(evidence=[{"k": 1}])
        outcome = _registry(("decision", rung)).evaluate(
            Choice, gate_strategy="decision", decision=_decision()
        )

        ((name, evaluation, _),) = outcome.rungs
        assert (name, evaluation.outcome) == ("decision", EvaluationOutcome.ACCEPTED)
        assert evaluation.evidence == {"k": 1}

    def test_a_failed_rung_carries_what_it_recorded(self) -> None:
        rung = _Rung(evidence=[{"k": 1}], error=RuntimeError("provider down"))
        outcome = _registry(("decision", rung)).evaluate(
            Choice, gate_strategy="decision", decision=_decision()
        )

        ((name, evaluation, _),) = outcome.rungs
        assert (name, evaluation.outcome) == ("decision", EvaluationOutcome.FAILED)
        assert evaluation.evidence == {"k": 1}
        assert "provider down" in evaluation.detail

    def test_recording_twice_fails_the_rung(self) -> None:
        rung = _Rung(evidence=[{"first": 1}, {"second": 2}])
        outcome = _registry(("decision", rung)).evaluate(
            Choice, gate_strategy="decision", decision=_decision()
        )

        ((_, evaluation, _),) = outcome.rungs
        assert evaluation.outcome is EvaluationOutcome.FAILED
        assert "records its evidence once" in evaluation.detail
        assert evaluation.evidence == {"first": 1}

    def test_a_rung_that_records_nothing_carries_none(self) -> None:
        outcome = _registry(("decision", _Rung())).evaluate(
            Choice, gate_strategy="decision", decision=_decision()
        )

        ((_, evaluation, _),) = outcome.rungs
        assert evaluation.outcome is EvaluationOutcome.ACCEPTED
        assert evaluation.evidence is None


class TestADeclaredFallback:
    def test_the_resolve_rung_takes_the_fallback(self) -> None:
        rung = _Rung(error=RuntimeError("provider down"))
        outcome = _registry(
            ("decision", rung), ("resolve", ResolveResolver())
        ).evaluate(
            Choice,
            gate_strategy=["decision", "resolve"],
            decision=_decision(fallback="b"),
        )

        assert [(name, e.outcome) for name, e, _ in outcome.rungs] == [
            ("decision", EvaluationOutcome.FAILED),
            ("resolve", EvaluationOutcome.ACCEPTED),
        ]
        assert outcome.model == Choice(choice="b")
        assert outcome.blocked_reason == ""

    def test_the_forced_rung_is_dispatched_exactly_once(self) -> None:
        """The fallback seeds and forces one dispatch, not one per rung."""
        rung = _Rung(error=RuntimeError("provider down"))

        _registry(("decision", rung), ("resolve", ResolveResolver())).evaluate(
            Choice,
            gate_strategy=["decision", "resolve"],
            decision=_decision(fallback="b"),
        )

        assert len(rung.calls) == 1

    def test_without_a_fallback_nothing_is_seeded_or_forced(self) -> None:
        rung = _Rung(error=RuntimeError("provider down"))
        outcome = _registry(
            ("decision", rung), ("resolve", ResolveResolver())
        ).evaluate(
            Choice,
            gate_strategy=["decision", "resolve"],
            decision=_decision(),
            resolved_fields={"choice": "a"},
        )

        assert [(name, e.outcome) for name, e, _ in outcome.rungs] == [
            ("resolve", EvaluationOutcome.ACCEPTED)
        ]
        assert outcome.model == Choice(choice="a")
        assert rung.calls == []
