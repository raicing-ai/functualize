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
    return (descriptor.source_file or "", descriptor.python_name or descriptor.name)


def resolve_name_collisions(
    descriptors: Iterable[JobDescriptor],
) -> list[JobDescriptor]:
    """Keep one descriptor per job name, reporting every displaced claimant.

    The **last** claimant in :func:`claim_order` wins, and each loser is
    recorded through the discovery-failure collector — so it reaches
    ``builtin info`` and ``builtin self doctor`` alongside a module that failed
    to parse or import, which is the same user-visible fact: a job the user
    wrote is not in the CLI.

    Recording is a no-op outside a collection scope, so a caller that is not
    scanning loses nothing by calling this.

    Args:
        descriptors: Candidates, in any order.

    Returns:
        The surviving descriptors, in :func:`claim_order`.
    """
    kept: dict[str, JobDescriptor] = {}
    for descriptor in sorted(descriptors, key=claim_order):
        previous = kept.get(descriptor.name)
        if previous is not None and previous is not descriptor:
            record_discovery_finding(
                job_name_collision(
                    canonical_name=descriptor.name,
                    kept_module=descriptor.module_path or descriptor.source_file,
                    kept_python_name=descriptor.python_name or descriptor.name,
                    dropped_module=previous.module_path or previous.source_file,
                    dropped_python_name=previous.python_name or previous.name,
                    dropped_path=previous.source_file,
                )
            )
        kept[descriptor.name] = descriptor
    return list(kept.values())
