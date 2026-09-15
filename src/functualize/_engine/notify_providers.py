"""Which package registers each notifier — the fixed answer to "why is this
name unregistered?".

The **third** provider table in core, and deliberately a copy of
``_engine/agent_providers.py`` rather than something new beside it: a workflow
naming a notifier nobody registered is the ordinary first-run failure, and
without this table the refusal could only report the bare name.

Its own module rather than joining `agent_providers`, which the plan named. An
executor runs a step and a notifier delivers an effect; they share a *shape*,
not a subject, and a table about notifications inside a file whose docstring is
entirely about agent executors is a table nobody looking for it would find.
`tests/gate/test_provider_tables.py` discovers tables by scanning `src/` and
refuses any that does not join its list, so a third module costs nothing and
inherits every check.

``webhook`` and ``task`` name packages core must never import — a string in a
diagnostic is not a dependency, and both plugins depend on core. **Neither is
registered by anything yet**, exactly as ``mcp-elicitation`` and ``ai`` are not
in the executor table: this is a hint table and never the accept/reject list.
What a `Notify` is checked against is the registry that is actually populated
(`_engine/notify.NotifierRegistry`), so a name here that nobody supplies costs
an accurate install hint and nothing else.

``log`` is core's own, and core **does not register it by default** — the same
decision `_app.boot` makes for the `cli-prompt` executor, for the same reason: a
default registration makes the refusal unreachable, and a workflow whose "page
the on-call on failure" quietly became a debug line is worse than one that
refuses to start.
"""

from __future__ import annotations

#: Which package registers each notifier, so a refusal can say what to install.
NOTIFY_PROVIDERS: dict[str, str] = {
    "log": "functualize",
    "webhook": "functualize-http",
    "task": "functualize-tasks",
}

#: The one core **ships**. Naming a package for it would be actively
#: misleading: if ``log`` is unregistered the answer is not "install
#: something", it is that nobody registered it — a legitimate state, since core
#: registers no notifier by default.
CORE_NOTIFIERS: frozenset[str] = frozenset({"log"})


def missing_notifier_hint(name: str) -> str:
    """How to make ``name`` resolvable, as a phrase for an error message.

    Returns a short clause naming the package to install, or an empty string
    when there is nothing useful to say — an unknown name, or one core is
    supposed to have registered itself.
    """
    package = NOTIFY_PROVIDERS.get(name)
    if package is None or name in CORE_NOTIFIERS:
        return ""
    return f"install {package} to register it"
