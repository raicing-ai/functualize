"""One job name addresses one function — the rule, in one place.

Job names are canonicalized to lowercase-hyphenated form, so two distinct
functions can resolve to one address: ``build_wheel`` and ``buildWheel`` both
become ``build-wheel``, and so does ``build_wheel`` declared in two files.

Before this module the codebase gave **four** different answers to that one
situation, one per registration path:

| path | answer |
|---|---|
| cached directory scan (every ``func`` invocation) | one job, no message, and *which* one was random per boot |
| uncached directory scan (``lazy=False``) | two entries under one name, ambiguous |
| eager registry scan | ``ValueError``, fatal to app construction |
| resolution pipeline (a provider built by hand) | ``ValueError`` the caller swallowed — **every** job vanished |

The rule lives here so a fifth path cannot invent a fifth answer, which is how
the first four happened.

``_discovery`` peers may import each other; both provider modules import this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._types.discovery_report import (
    class_job_name_collision,
    job_name_collision,
    record_discovery_finding,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from functualize._types.descriptors import JobDescriptor

__all__ = ["claim_order", "resolve_name_collisions"]


def claim_order(descriptor: JobDescriptor) -> tuple[str, str]:
    """The sort key deciding which claimant a name resolves to.

    Source file, then Python name. Two properties matter and neither is
    cosmetic:

    * **It is total and stable**, so the surviving job does not change between
      invocations. It used to: the cached scan imports new files while
      iterating a *set* difference, and string-hash randomization reorders
      that per process — two files each declaring ``build_wheel`` produced
      winners ``b b a b b a a a`` over eight cold boots of 0.2.3. The
      behaviour of the job that survived changed with nothing changing on disk.
    * **It reproduces the one case that was already deterministic.** Two
      spellings in a single file arrive from one import in ``dir()`` order,
      alphabetically, and this key sorts them the same way — so preserving
      "last claimant wins" preserves the function a project already runs.
    """
    identity = descriptor.python_name or descriptor.name
    if descriptor.owner_class:
        identity = f"{descriptor.owner_class}.{identity}"
    return (descriptor.source_file or "", identity)


def resolve_name_collisions(
    descriptors: Iterable[JobDescriptor],
) -> list[JobDescriptor]:
    """Keep one descriptor per job name, reporting every displaced claimant.

    Two rules, split on whether a class job is a claimant.

    With plain functions the **last** claimant in :func:`claim_order` wins and
    each loser is recorded — "the same job under two spellings, one of them
    runs". A class job makes the collision strict: *nobody* is registered,
    because a class job's name comes from a class the user wrote and ran
    together with its siblings, so silently running somebody else's function
    under that name, or one arbitrary method of the class, hides the problem
    rather than resolving it.

    Either way the record goes through the discovery-failure collector, so it
    reaches ``builtin info`` and ``builtin self doctor`` alongside a module
    that failed to parse or import — the same user-visible fact: a job the user
    wrote is not in the CLI.

    Recording is a no-op outside a collection scope, so a caller that is not
    scanning loses nothing by calling this.

    Args:
        descriptors: Candidates, in any order.

    Returns:
        The surviving descriptors, in :func:`claim_order`.
    """
    grouped: dict[str, list[JobDescriptor]] = {}
    for descriptor in sorted(descriptors, key=claim_order):
        claimants = grouped.setdefault(descriptor.name, [])
        if not claimants or claimants[-1] is not descriptor:
            claimants.append(descriptor)

    kept: list[JobDescriptor] = []
    for name, claimants in grouped.items():
        if len(claimants) == 1:
            kept.append(claimants[0])
        elif all(claimant.owner_class is None for claimant in claimants):
            kept.append(_last_claimant_wins(name, claimants))
        else:
            record_discovery_finding(
                class_job_name_collision(
                    canonical_name=name,
                    claimants=tuple(
                        (_qualified_name(claimant), claimant.source_file or "")
                        for claimant in claimants
                    ),
                    # The record names a file an operator can open. Every
                    # claimant has one, and the first in claim order is the one
                    # that does not move between boots.
                    module=claimants[0].module_path or claimants[0].source_file,
                    path=claimants[0].source_file or "",
                )
            )
            # Nothing is kept: the name is registered to nobody rather than to
            # a claimant the user did not choose.
    return kept


def _last_claimant_wins(name: str, claimants: list[JobDescriptor]) -> JobDescriptor:
    """Resolve a collision between plain functions exactly as before.

    Two spellings of one name have always meant "the last one in claim order
    runs, the others are reported". A class job is not in that set: the rule
    for it lives in :func:`resolve_name_collisions`, because it is not a choice
    between two spellings but a name that cannot be honoured at all.
    """
    winner = claimants[0]
    for descriptor in claimants[1:]:
        if descriptor is winner:
            continue
        record_discovery_finding(
            job_name_collision(
                canonical_name=name,
                kept_module=descriptor.module_path or descriptor.source_file,
                kept_python_name=descriptor.python_name or descriptor.name,
                dropped_module=winner.module_path or winner.source_file,
                dropped_python_name=winner.python_name or winner.name,
                dropped_path=winner.source_file,
                kept_path=descriptor.source_file,
            )
        )
        winner = descriptor
    return winner


def _qualified_name(descriptor: JobDescriptor) -> str:
    """``Class.method`` for a class job, the function's own name otherwise."""
    leaf = descriptor.python_name or descriptor.name
    if descriptor.owner_class is None:
        return leaf
    return f"{descriptor.owner_class}.{leaf}"
