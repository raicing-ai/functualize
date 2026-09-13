"""An unregistered strategy is a failed strategy, not a raise.

The defect this closes: `GateRegistry.resolve_gate` raised a bare `ValueError`
for a strategy name nobody had registered, from *outside* its per-strategy
`try`. Every other way a strategy can fail -- a resolver that raises, a
resolver that returns nothing usable -- fell through to the next rung of the
ladder and ended in a `GateResolutionError` the walker catches.

The practical asymmetry: a broken API key degraded gracefully, and a forgotten
`pip install functualize-ai` raised out of the walk.

Two cases keep raising, deliberately:

* a **single** explicitly-named strategy, because there is no ladder to fall
  down and a typo in `gate_strategy="ai_inbund"` must stay loud;
* a name referenced from a **preset**, because a preset is a registry entry
  and a dangling reference in one is a wiring mistake in the app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

from functualize._gate._registry import GateRegistry
from functualize._gate._resolver import ResolveResolver
from functualize._gate._strategy import GateStrategy
from functualize._types.errors import GateResolutionError

if TYPE_CHECKING:
    from functualize._gate._context import GateContext


class Answer(BaseModel):
    approved: bool


class _Boom:
    """A registered resolver that always fails -- the graceful case, which
    must keep behaving exactly as it did."""

    def resolve(self, ctx: GateContext) -> BaseModel:
        raise RuntimeError("resolver exploded")


def _registry(*, with_resolve: bool = True) -> GateRegistry:
    registry = GateRegistry()
    if with_resolve:
        registry.register_strategy(GateStrategy.RESOLVE.value, ResolveResolver())
    return registry


class TestTheLadderBehavesLikeALadder:
    def test_an_unregistered_rung_is_skipped(self) -> None:
        """The acceptance criterion. `resolve` sits behind `nope` and wins."""
        registry = _registry()
        result = registry.resolve_gate(
            Answer,
            gate_strategy=["nope", "resolve"],
            resolved_fields={"approved": True},
            force_gate=True,
            gate_name="triage",
        )
        assert isinstance(result, Answer)
        assert result.approved is True

    def test_the_real_shape_ai_inbound_then_prompt_then_resolve(self) -> None:
        """What `_gate_strategy_list` actually builds for
        `Gate(strategy="ai_inbound")`. Neither `ai_inbound` nor `prompt` is
        registered without their plugins; `resolve` must still answer."""
        registry = _registry()
        result = registry.resolve_gate(
            Answer,
            gate_strategy=["ai_inbound", "prompt", "resolve"],
            resolved_fields={"approved": False},
            force_gate=True,
            gate_name="triage",
        )
        assert isinstance(result, Answer)

    def test_every_rung_unregistered_gives_a_gate_resolution_error(self) -> None:
        """Not a `ValueError`. This is the type the walker catches, and
        catching it is what keeps the walk BLOCKED and resumable."""
        registry = _registry(with_resolve=False)
        with pytest.raises(GateResolutionError) as excinfo:
            registry.resolve_gate(
                Answer,
                gate_strategy=["ai_inbound", "prompt", "resolve"],
                gate_name="triage",
            )
        assert excinfo.value.gate_name == "triage"
        assert excinfo.value.strategies_attempted == 3

    def test_a_registered_resolver_that_raises_still_falls_through(self) -> None:
        """Regression guard for the case that was already correct."""
        registry = _registry()
        registry.register_strategy("boom", _Boom())
        result = registry.resolve_gate(
            Answer,
            gate_strategy=["boom", "resolve"],
            resolved_fields={"approved": True},
            force_gate=True,
            gate_name="triage",
        )
        assert isinstance(result, Answer)


class TestWhatStillRaises:
    def test_a_single_explicit_strategy_raises(self) -> None:
        """The acceptance criterion's other half. A typo must not be
        swallowed just because unregistered names are now tolerable in a
        ladder."""
        with pytest.raises(ValueError, match="Unregistered gate strategy 'nope'"):
            _registry().resolve_gate(Answer, gate_strategy="nope", gate_name="triage")

    def test_a_single_entry_list_raises_too(self) -> None:
        """`["nope"]` is the same statement as `"nope"`; the ladder has one
        rung, so there is nothing to fall to."""
        with pytest.raises(ValueError, match="Unregistered gate strategy 'nope'"):
            _registry().resolve_gate(Answer, gate_strategy=["nope"], gate_name="triage")

    def test_a_preset_keeps_its_distinct_message(self) -> None:
        registry = _registry()
        registry.register_preset("ai", ["ai_inbound", "resolve"])
        with pytest.raises(ValueError, match="referenced in preset 'ai'"):
            registry.resolve_gate(Answer, gate_strategy="ai", gate_name="triage")

    def test_the_preset_branch_wins_even_with_a_fallback_behind_it(self) -> None:
        """A preset expands to several entries, so `len(...) == 1` does not
        distinguish it -- `preset_source` does. Pinned, because collapsing
        the two checks would silently make a broken preset fall through."""
        registry = _registry()
        registry.register_preset("ai", ["ai_inbound", "prompt", "resolve"])
        with pytest.raises(ValueError, match="referenced in preset 'ai'"):
            registry.resolve_gate(
                Answer,
                gate_strategy="ai",
                resolved_fields={"approved": True},
                force_gate=True,
                gate_name="triage",
            )


class TestTheShippedAiPresetNeedsBothPlugins:
    """A documented consequence (`docs/guides/ai.md`, "Gate Strategies") that
    nothing else pins.

    `functualize-ai` registers the `"ai"` preset, but that preset's first rung
    is `ai_outbound`, which `functualize-mcp` registers. So installing only
    `functualize-ai` and writing `gate_strategy="ai"` is an error, not a
    degraded ladder -- the one place a missing plugin does not produce a
    graceful block.

    The preset definition is imported from the plugin rather than restated, so
    the doc claim cannot drift from the list the plugin actually registers.
    """

    @staticmethod
    def _with_functualize_ai() -> GateRegistry:
        """A registry in the state `functualize-ai` alone leaves it.

        The plugin registers its strategy *and* both presets in one call, so a
        test that registered only the presets would fail for the wrong reason.
        `functualize-mcp` is absent, which is the condition under test.
        """
        pytest.importorskip("functualize_ai")
        from functualize_ai._gate_strategy import (
            AI_INBOUND_PRESET_NAME,
            AI_INBOUND_PRESET_STRATEGIES,
            AI_INBOUND_STRATEGY_NAME,
            AI_PRESET_NAME,
            AI_PRESET_STRATEGIES,
        )

        registry = _registry()
        # `prompt` and `resolve` are the two core strategies a real boot
        # registers (verified: `FunctualizeApp("x")._gate_registry._strategies`
        # is exactly `['prompt', 'resolve']`). Both must be here, because the
        # preset branch raises on *any* unregistered rung, not only the first.
        registry.register_strategy(GateStrategy.PROMPT.value, _Boom())
        registry.register_strategy(AI_INBOUND_STRATEGY_NAME, _Boom())
        registry.register_preset(AI_INBOUND_PRESET_NAME, AI_INBOUND_PRESET_STRATEGIES)
        registry.register_preset(AI_PRESET_NAME, AI_PRESET_STRATEGIES)
        return registry

    def test_the_preset_raises_without_functualize_mcp(self) -> None:
        registry = self._with_functualize_ai()
        with pytest.raises(ValueError, match="'ai_outbound' referenced in preset 'ai'"):
            registry.resolve_gate(
                Answer,
                gate_strategy="ai",
                resolved_fields={"approved": True},
                force_gate=True,
                gate_name="triage",
            )

    def test_the_ai_inbound_preset_is_self_sufficient(self) -> None:
        """The alternative the docs point at. Its only non-core rung is
        `ai_inbound`, which the same plugin registers, so with `functualize-ai`
        alone it degrades down to `resolve` instead of raising -- even when
        `ai_inbound` itself fails.
        """
        registry = self._with_functualize_ai()
        result = registry.resolve_gate(
            Answer,
            gate_strategy="ai_inbound",
            resolved_fields={"approved": True},
            force_gate=True,
            gate_name="triage",
        )
        assert isinstance(result, Answer)


class TestLastErrorNamesTheStrategies:
    """`last_error` is what fills the walk's `blocked_reason`, so it is the
    string an operator actually reads."""

    def test_it_names_the_unregistered_strategy_and_its_package(self) -> None:
        registry = _registry(with_resolve=False)
        with pytest.raises(GateResolutionError) as excinfo:
            registry.resolve_gate(
                Answer, gate_strategy=["ai_inbound", "resolve"], gate_name="triage"
            )
        assert "ai_inbound" in excinfo.value.last_error
        assert "functualize-ai" in excinfo.value.last_error

    def test_it_names_several(self) -> None:
        registry = _registry(with_resolve=False)
        with pytest.raises(GateResolutionError) as excinfo:
            registry.resolve_gate(
                Answer,
                gate_strategy=["ai_inbound", "ai_outbound", "resolve"],
                gate_name="triage",
            )
        assert "ai_inbound" in excinfo.value.last_error
        assert "functualize-mcp" in excinfo.value.last_error

    def test_a_resolver_error_and_an_unregistered_name_are_both_reported(
        self,
    ) -> None:
        """Losing either half would leave the operator with only a symptom or
        only a cause."""
        registry = _registry(with_resolve=False)
        registry.register_strategy("boom", _Boom())
        with pytest.raises(GateResolutionError) as excinfo:
            registry.resolve_gate(
                Answer, gate_strategy=["ai_inbound", "boom"], gate_name="triage"
            )
        assert "functualize-ai" in excinfo.value.last_error
        assert "resolver exploded" in excinfo.value.last_error

    def test_no_strategies_attempted_is_still_reachable(self) -> None:
        """An empty ladder. Kept honest so the new branches cannot claim it."""
        registry = _registry()
        with pytest.raises(GateResolutionError) as excinfo:
            registry.resolve_gate(Answer, gate_strategy=[], gate_name="triage")
        assert excinfo.value.last_error == "no strategies attempted"
