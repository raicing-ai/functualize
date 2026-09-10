"""Which package registers each agent step executor — the fixed answer to
"why is this name unregistered?".

The second provider table in core, copied from ``_gate/_strategy.py`` rather
than invented beside it: a workflow naming an executor nobody registered is the
*common* first-run failure, not an exotic one, and without this table the
refusal could only report the bare name, leaving the operator to guess which
package supplies it.

``cli-prompt`` is core's own: the executor that asks a human. It is in the
table from day one, before there are two implementations, because a table added
after the second implementation exists is a table that has already been worked
around. ``mcp-elicitation`` and ``ai`` name packages core must never import —
a string in a diagnostic is not a dependency, and both plugins depend on core,
so importing either from here would invert the graph.
``tests/gate/test_provider_tables.py`` pins that with a grep over ``src/``.

One divergence from the strategy table, recorded rather than papered over: this
one has **no validator to drift from**. ``AgentStep.executor`` is a free-form
name, checked against the registry that is actually populated rather than
against this dict, so the table is a source of hints and never the
accept/reject list. The strategy table's counterpart — a name the validator
accepts that the table omits — has no analogue here, and a later "reconcile the
two" task should not go looking for one.
"""

from __future__ import annotations

#: Which package registers each executor, so a refusal can say what to install.
EXECUTOR_PROVIDERS: dict[str, str] = {
    "cli-prompt": "functualize",
    "mcp-elicitation": "functualize-mcp",
    "ai": "functualize-ai",
}

#: The one core registers itself, at boot. Naming a package for it would be
#: actively misleading: if ``cli-prompt`` is unregistered the answer is not
#: "install something", it is that the registry was built by hand.
CORE_EXECUTORS: frozenset[str] = frozenset({"cli-prompt"})


def missing_executor_hint(name: str) -> str:
    """How to make ``name`` resolvable, as a phrase for an error message.

    Returns a short clause naming the package to install, or an empty string
    when there is nothing useful to say — an unknown name, or one core is
    supposed to have registered itself.
    """
    package = EXECUTOR_PROVIDERS.get(name)
    if package is None or name in CORE_EXECUTORS:
        return ""
    return f"install {package} to register it"
