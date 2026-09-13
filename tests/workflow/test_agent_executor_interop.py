"""A plugin's executor is duck-typed, and the port must mean it.

`AgentStepRegistry.register` takes `object` on purpose — the door is reached by
a plugin entry point, a hand-built registry, a test double — so the runtime
check *is* the contract. A review found two places where the contract was
narrower than it claimed (asp M-2, M-4):

* `isinstance` against a runtime Protocol checks that `capabilities` is
  **present**, not what it holds, so an executor declaring a tuple passed the
  door and raised `TypeError: unsupported operand type(s) for -: 'frozenset'
  and 'tuple'` from the middle of a walk — the exact surprise the door's
  docstring says it prevents.
* Capability matching was `node.requires - executor.capabilities`, set
  arithmetic between enum members. It works today only because
  `AgentCapability` is a `StrEnum` and the `str` mixin's `__eq__`/`__hash__`
  win the MRO. Under a plain `Enum` — the spelling the contracts use, one
  `UP042` away — the same expression reports a capability the executor **did**
  declare as missing. Every test double in the suite used the enum, so nothing
  pinned it.

So this file uses the spellings a plugin author would actually reach for,
taken from what the docs publish.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import pytest

from functualize._engine.agent_step import AgentStepRegistry
from functualize._types.errors import AgentCapabilityRefusedError
from functualize._types.protocols import AgentCapability, capability_value
from functualize._types.workflow import AgentStep, WorkflowDeclaration

_ALLOWLIST = AgentCapability.ENFORCES_TOOL_ALLOWLIST


class _Executor:
    """The shape a plugin ships: a name, some capabilities, an `execute`."""

    def __init__(self, name: str, capabilities: Any) -> None:
        self.name = name
        self.capabilities = capabilities

    def execute(self, ctx: Any) -> Any:  # pragma: no cover - never reached here
        raise AssertionError("these tests refuse before any step runs")


def _needs_allowlist() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(
            AgentStep(
                name="draft",
                instructions="write it",
                tools=("deploy",),
                requires=frozenset({_ALLOWLIST}),
            ),
        ),
        edges=(),
    )


class TestBareStringsAreALegitimateSpelling:
    """The docs publish `"enforces_tool_allowlist"`. A plugin may declare it."""

    def test_a_string_capability_satisfies_an_enum_requirement(self) -> None:
        registry = AgentStepRegistry()
        registry.register(_Executor("plug", frozenset({"enforces_tool_allowlist"})))

        registry.check(_needs_allowlist())  # no refusal

    def test_a_string_capability_that_does_not_match_still_refuses(self) -> None:
        """The falsifier. Comparing by value must not mean accepting everything."""
        registry = AgentStepRegistry()
        registry.register(_Executor("plug", frozenset({"supports_visible_output"})))

        with pytest.raises(AgentCapabilityRefusedError) as caught:
            registry.check(_needs_allowlist())

        assert caught.value.capability == _ALLOWLIST

    def test_the_comparison_does_not_depend_on_the_enum_base(self) -> None:
        """Spelled out, because this is the property that was accidental.

        Under a plain `Enum`, `frozenset({member}) - frozenset({member.value})`
        is non-empty — a false refusal. `capability_value` is what makes the
        two sides comparable regardless of the base.
        """

        class Plain(Enum):
            ALLOWLIST = "enforces_tool_allowlist"

        assert frozenset({Plain.ALLOWLIST}) - frozenset({Plain.ALLOWLIST.value})
        assert capability_value(Plain.ALLOWLIST) == capability_value(
            Plain.ALLOWLIST.value
        )
        assert capability_value(_ALLOWLIST) == "enforces_tool_allowlist"


class TestTheDoorChecksWhatItPromises:
    """`register`'s docstring says a malformed executor is refused *here*."""

    def test_a_tuple_of_capabilities_is_accepted_and_matched(self) -> None:
        """Not every non-frozenset is malformed — a tuple is a collection of
        capability names and reads the same to every consumer now."""
        registry = AgentStepRegistry()
        registry.register(_Executor("tup", ("enforces_tool_allowlist",)))

        registry.check(_needs_allowlist())

    @pytest.mark.parametrize("capabilities", [None, 7, object()])
    def test_something_that_is_not_a_collection_is_refused_at_the_door(
        self, capabilities: Any
    ) -> None:
        registry = AgentStepRegistry()

        with pytest.raises(TypeError, match="must be a collection"):
            registry.register(_Executor("bad", capabilities))

    def test_a_bare_string_is_refused_rather_than_iterated(self) -> None:
        """`"enforces_tool_allowlist"` is iterable — into characters.

        Accepting it would declare twenty-three one-letter capabilities and
        match nothing, which is the silent version of the same typo.
        """
        registry = AgentStepRegistry()

        with pytest.raises(TypeError, match="must be a collection"):
            registry.register(_Executor("str", "enforces_tool_allowlist"))

    def test_an_unknown_capability_name_is_refused_at_the_door(self) -> None:
        """A capability nothing requires can never be matched, so it is a typo."""
        registry = AgentStepRegistry()

        with pytest.raises(ValueError, match="enforces_tool_allowlst"):
            registry.register(_Executor("typo", frozenset({"enforces_tool_allowlst"})))

    def test_declaring_nothing_is_still_fine(self) -> None:
        """`CliPromptExecutor` declares no capabilities, deliberately."""
        registry = AgentStepRegistry()

        registry.register(_Executor("none", frozenset()))

        assert registry.names() == ("none",)
