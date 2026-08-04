"""Job and group identity: construction, normalization, and resolution.

The one place that answers "what name does this denote". The coming kernel
group trie (CLI/shell convergence plan, phase A3) resolves over these names for
dispatch and completion; the dependency graph resolves over them for edges.
Both ask here rather than each carrying a policy — which is how this codebase
previously ended up with three dependency resolvers that disagreed in
production.
"""

from __future__ import annotations

__all__ = ["normalize_name", "normalize_segment", "qualified_name", "resolve_name"]

# Re-exported: the policy lives in `_types.naming` because `_engine` may
# not import `_discovery` (peer layers are independent), and the coming
# group trie is consumed by the engine and the CLI alike.
from functualize._types.naming import (  # noqa: E402
    normalize_name,
    normalize_segment,
    resolve_name,
)


def qualified_name(group: str | None, func_name: str) -> str:
    """Build a qualified job name, normalized to canonical hyphenated form.

    Every registration path funnels through here — cold discovery
    (`_discovery/sync.py`), module registration (`_discovery/registry.py`), and
    the group transform (`_discovery/transforms.py`) — so normalizing here is
    what makes a job have exactly one name. Normalizing at the call sites
    instead would be three places to keep in sync, which is how this codebase
    previously acquired three disagreeing dependency resolvers.

    ``build_wheel`` registers and is addressed as ``build-wheel``;
    ``infra.provision_db`` as ``infra.provision-db``. Python identifiers cannot
    contain hyphens and command names conventionally do, so without a canonical
    form the same job has two spellings and each consumer picks one.

    Group segments are validated as Python identifiers *before* normalization,
    because the group comes from a ``JOB_GROUP`` module variable and a
    non-identifier there is an authoring mistake worth reporting, not a
    spelling to silently repair.

    Args:
        group: The JOB_GROUP value (None for ungrouped jobs).
               May contain dots for nested groups: "infra.aws".
        func_name: The function's __name__.

    Returns:
        "group.func-name" if grouped (e.g., "infra.aws.provision-db"),
        "func-name" if ungrouped.

    Raises:
        ValueError: If func_name contains a dot, is empty, or if group
            segments are not valid Python identifiers.
    """
    if not func_name:
        msg = "func_name must be a non-empty string"
        raise ValueError(msg)

    if "." in func_name:
        msg = f"func_name must not contain '.': got {func_name!r}"
        raise ValueError(msg)

    leaf = normalize_segment(func_name)

    if group is not None:
        if not group:
            msg = "group must be a non-empty string when provided"
            raise ValueError(msg)

        segments = group.split(".")
        for segment in segments:
            if not segment.isidentifier():
                msg = (
                    f"each segment of group must be a valid identifier: "
                    f"got {segment!r} in {group!r}"
                )
                raise ValueError(msg)

        prefix = ".".join(normalize_segment(segment) for segment in segments)
        return f"{prefix}.{leaf}"

    return leaf
