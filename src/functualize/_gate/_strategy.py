"""Gate strategy enum definitions.

Defines the named strategies available for resolving gate inputs
when a workflow step pauses for input.
"""

from __future__ import annotations

from enum import StrEnum


class GateStrategy(StrEnum):
    """Named strategies for resolving gate inputs."""

    RESOLVE = "resolve"  # Resolve from config chain only
    PROMPT = "prompt"  # Collect via interactive InputProvider
    AI_INBOUND = "ai_inbound"  # Resolve via AI/LLM generation


#: Which package registers each strategy — the fixed answer to "why is this
#: name unregistered?".
#:
#: A gate naming a strategy nobody registered is the *common* first-run
#: failure, not an exotic one: `Gate(strategy="ai_inbound")` is valid to write
#: (`_types.workflow._VALID_GATE_STRATEGIES` accepts it) and resolves to
#: nothing until `functualize-ai` is installed. Without this table the walk
#: could only report the bare name, leaving the operator to guess which of
#: four packages supplies it.
#:
#: Core names the plugins; core must never import them. A string in a
#: diagnostic is not a dependency, and `functualize-ai` and `functualize-mcp`
#: both depend on core -- importing either from here would invert the graph.
#: `tests/gate/test_registry.py` pins that with a grep over `src/`.
#:
#: Note `"ai_outbound"` has no `GateStrategy` member. The enum carries three
#: names, `_types.workflow._VALID_GATE_STRATEGIES` accepts four, and this
#: table follows the validator because that is the set a `Gate` can actually
#: declare. Reconciling the two is deliberately out of scope here
#: (`spec.md`, "Redesigning gate strategy naming").
STRATEGY_PROVIDERS: dict[str, str] = {
    GateStrategy.RESOLVE.value: "functualize",
    GateStrategy.PROMPT.value: "functualize",
    GateStrategy.AI_INBOUND.value: "functualize-ai",
    "ai_outbound": "functualize-mcp",
}

#: The two the core registers itself, at boot. Naming a package for these
#: would be actively misleading: if `resolve` is unregistered the answer is
#: not "install something", it is that the registry was built by hand.
CORE_STRATEGIES: frozenset[str] = frozenset(
    {GateStrategy.RESOLVE.value, GateStrategy.PROMPT.value}
)


def missing_strategy_hint(name: str) -> str:
    """How to make ``name`` resolvable, as a phrase for an error message.

    Returns a short clause naming the package to install, or an empty string
    when there is nothing useful to say — an unknown name, or one core is
    supposed to have registered itself.
    """
    package = STRATEGY_PROVIDERS.get(name)
    if package is None or name in CORE_STRATEGIES:
        return ""
    return f"install {package} to register it"
