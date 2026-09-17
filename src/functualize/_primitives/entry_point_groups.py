"""The ``functualize.*`` entry-point groups core reads, named in one place.

`plugin-taxonomy`/T4. This module exists because the set was **implicit**, and
an implicit set cannot be compared against anything.

Nine call sites read entry points; their group names arrived three different
ways — three bare string literals, three module-level constants in three
different layers, and two supplied by a caller. Meanwhile thirteen shipped
``pyproject.toml`` files *declare* groups. Nothing compared the two lists, so
three declared groups had no reader at all and the only symptom was that
installing a plugin did nothing:

- ``functualize.state_providers`` — ``functualize-state-sqlite`` and the
  documented substrate tutorial;
- ``functualize.interactivity_providers`` — ``functualize-inline``;
- ``functualize.vault_key_providers`` — declared by core's own
  ``pyproject.toml``.

**Why those three could not simply be "given a reader."** A group named
``functualize.<x>_providers`` is not a naming convention; it is a *mechanism*.
``_plugins/domain_registry.scan_domain_providers`` reads it out of the
``entry_point_group`` field of a live :class:`DomainMetadata`, published by a
domain SDK under ``functualize.domains``. Exactly two domain SDKs exist —
``ai`` and ``tasks`` — so ``ai_providers`` and ``tasks_providers`` are read and
a ``_providers`` group with no domain behind it has no reader by construction.
ADR-022 removed the ``state`` domain; there was never an ``interactivity`` or
``vault_key`` one.

So the readable set has two halves, and both are needed to judge a declaration:

1. :data:`READ_GROUPS` — the closed set below, read by a fixed call site in
   ``src/``.
2. every installed ``DomainMetadata.entry_point_group`` — open, because a
   third-party domain SDK may add one at any time.

``tests/spec/test_every_declared_group_has_a_reader.py`` is what makes that
judgement mechanically, over every shipped manifest.

**Not a classifier.** ``_primitives/plugin_kinds.classify_group`` answers a
different question — *what kind of thing does this group hold* — and derives it
from the group's shape precisely so a new third-party provider group needs no
edit here. That file's docstring argues against enumerating group names, and it
is right about classification. This module enumerates the groups **core itself
reads**, which is closed by definition: it is the set of ``entry_points(group=)``
call sites in ``src/``. Classifying a group and loading it are not the same
question, and conflating them is what made ``functualize.state_providers`` look
healthy in ``func builtin plugin available`` while doing nothing.

**``_cli`` is absent from the importers, deliberately.** ``functualize.skills``
and ``functualize.displays`` are read from ``_cli/skills.py`` and
``_cli/tui/display_provider_discovery.py``, and the ``_cli uses public API
only`` import contract forbids that layer from importing ``_primitives``.
Exporting these through ``functualize.app.utils`` would widen the public API —
and every public symbol owes a caller in ``examples/``
(``contributor/reference/public-api-example-coverage.md``) — to buy nothing at
runtime. Those two constants therefore stay where they are and are tied to this
module **by test** rather than by import.

Lives in ``_primitives/`` beside ``entry_points.py`` for the same reason that
module does: ``_config``, ``_discovery`` and ``_plugins`` are peer-independent,
so a constant any of them needs cannot live in one of the others.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "DISPLAYS",
    "DOMAINS",
    "FORMAT_PROVIDERS",
    "JOBS",
    "PLUGINS",
    "READ_GROUPS",
    "REMOTE_PROVIDERS",
    "SKILLS",
]

#: Job *sources*. A distribution publishing here supplies work to run rather
#: than changing what functualize can do — which is why `plugin list` excludes
#: it by name. Read by `_app/boot.py`.
JOBS: Final = "functualize.jobs"

#: The general extension point: anything that registers itself against the app
#: at boot. Read by `_plugins/loader.py`, and the default for
#: `app.config.PluginSources.entry_point_group`.
PLUGINS: Final = "functualize.plugins"

#: Domain SDKs. Each publishes a `DomainMetadata` naming its own provider
#: group, which is the only way a `functualize.<x>_providers` group acquires a
#: reader. Read by `_plugins/domain_registry.py`.
DOMAINS: Final = "functualize.domains"

#: Agent skills shipped by a distribution. Read by `_cli/skills.py` — see the
#: module docstring for why that one is not an importer.
SKILLS: Final = "functualize.skills"

#: TUI display providers. Read by `_cli/tui/display_provider_discovery.py`.
DISPLAYS: Final = "functualize.displays"

#: Config file format parsers. Core registers TOML here; `IniFormatProvider` is
#: in-tree and deliberately unregistered (ADR-007). Read by `_config/registry.py`.
FORMAT_PROVIDERS: Final = "functualize.format_providers"

#: Remote config source providers — in practice, secrets backends. Read by
#: `_config/registry.py`.
REMOTE_PROVIDERS: Final = "functualize.remote_providers"

#: Every group core reads from a fixed call site. Closed by definition: adding
#: a member here without adding the `entry_points(group=)` call that reads it
#: re-creates the exact defect this module exists to prevent.
#:
#: A group **absent** from this set is readable only if some installed
#: `DomainMetadata` names it as its `entry_point_group`. Nothing else loads.
READ_GROUPS: Final[frozenset[str]] = frozenset(
    {
        JOBS,
        PLUGINS,
        DOMAINS,
        SKILLS,
        DISPLAYS,
        FORMAT_PROVIDERS,
        REMOTE_PROVIDERS,
    }
)
