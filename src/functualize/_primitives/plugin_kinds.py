"""What *kind* of thing a ``functualize.*`` entry-point group holds.

The distinction is real and a user needs it before installing anything. An
adapter (``functualize-mcp``) adds commands anybody might want. A domain SDK
(``functualize-state``) publishes the protocol a capability is written
against. An *implementation* (``functualize-aws``, ``functualize-bitwarden``)
is a concrete backend you choose because of the infrastructure you already
run — installing two of them for the same domain is usually a mistake, not a
richer setup.

**Derived from the group name, never from a list of package names.** A
hard-coded set would be wrong the first time a domain declares a new provider
group, and domains do exactly that at runtime
(``_plugins/domain_registry.py`` reads the group out of domain metadata). The
same reasoning already governs ``_cli/plugin_cmd.py``, which scans whatever
``functualize.*`` groups are installed rather than enumerating them. So a
distribution publishing under ``functualize.vault_providers`` classifies as an
implementation here without anyone editing this file.

Lives in ``_primitives`` because it is pure string logic over a group name with
no dependencies. ``_cli`` reaches it through ``functualize.app.utils``, which is
the seam that layer is allowed to import through.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PLUGIN_GROUP_PREFIX", "PluginKind", "classify_group"]

#: Every group functualize itself extends through carries this prefix.
PLUGIN_GROUP_PREFIX = "functualize."

#: Suffix marking a group as holding concrete backends for some domain.
_PROVIDER_SUFFIX = "_providers"


class PluginKind(StrEnum):
    """What a plugin contributes, as opposed to what it is called.

    ``StrEnum`` so it serialises straight into the JSON that
    ``func builtin plugin`` emits, with no encoder and no ``.value`` at the
    call site.
    """

    #: Adds commands or a delivery surface — mcp, http, lambda, flow-viz.
    ADAPTER = "adapter"
    #: Publishes a capability protocol other plugins implement — ai, state, tasks.
    DOMAIN = "domain"
    #: A concrete backend, chosen per infrastructure — aws, bitwarden, sqlite.
    IMPLEMENTATION = "implementation"
    #: A `functualize.*` group this version has no opinion about.
    UNKNOWN = "unknown"


def classify_group(group: str) -> PluginKind:
    """Map a ``functualize.*`` entry-point group to what it holds.

    ``functualize.plugins`` → adapter, ``functualize.domains`` → domain, any
    ``functualize.<x>_providers`` → implementation, anything else → unknown.

    ``functualize.jobs`` is deliberately *not* special-cased here. It is a job
    source rather than an extension, and filtering it is the caller's job —
    ``_cli/plugin_cmd`` already excludes it by name and says why. Answering
    ``UNKNOWN`` for it keeps that decision in one place instead of two.
    """
    if not group.startswith(PLUGIN_GROUP_PREFIX):
        return PluginKind.UNKNOWN

    suffix = group[len(PLUGIN_GROUP_PREFIX) :]
    if not suffix or "." in suffix:
        return PluginKind.UNKNOWN
    if suffix == "plugins":
        return PluginKind.ADAPTER
    if suffix == "domains":
        return PluginKind.DOMAIN
    # `_providers` alone is a suffix with no domain in front of it, which names
    # nothing — require at least one character before it.
    if suffix.endswith(_PROVIDER_SUFFIX) and len(suffix) > len(_PROVIDER_SUFFIX):
        return PluginKind.IMPLEMENTATION
    return PluginKind.UNKNOWN
