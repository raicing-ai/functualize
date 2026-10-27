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

One name can also be a *settings section* — a job called ``shell`` answers to
the word a settings table is spelled with — and a job nobody can configure
without renaming a table is the same kind of silence, so the reserved-name
check runs here too, on the same pass over the same descriptors. Every
registration path that dedupes therefore gets it; a path that forgets to call
this function loses the report as well as the dedupe, which is one gap to
find, not two.

``_discovery`` peers may import each other; both provider modules import this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._types.discovery_report import (
    job_name_collision,
    record_discovery_finding,
    reserved_section_name,
)
from functualize._types.functualize_settings import FUNCTUALIZE_SETTINGS

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

    Each candidate is also checked against the declared settings sections: a
    job or group whose address is one of those is recorded as a reserved name,
    whether or not it collides with another claimant. The job still registers
    — the record says a ``[shell]`` table will not configure it, not that it
    is unavailable.

    Recording is a no-op outside a collection scope, so a caller that is not
    scanning loses nothing by calling this.

    Args:
        descriptors: Candidates, in any order.

    Returns:
        The surviving descriptors, in :func:`claim_order`.
    """
    kept: dict[str, JobDescriptor] = {}
    sections = FUNCTUALIZE_SETTINGS.sections()
    for descriptor in sorted(descriptors, key=claim_order):
        _record_reserved_section(descriptor, sections)
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
                    kept_path=descriptor.source_file,
                )
            )
        kept[descriptor.name] = descriptor
    return list(kept.values())


def _record_reserved_section(
    descriptor: JobDescriptor, sections: frozenset[str]
) -> None:
    """Record ``descriptor`` if its address is a declared settings section."""
    for segment in _address_segments(descriptor):
        if segment in sections:
            record_discovery_finding(
                reserved_section_name(
                    name=_address(descriptor),
                    section=segment,
                    module=descriptor.module_path or descriptor.source_file,
                    path=descriptor.source_file,
                )
            )
            return


def _address(descriptor: JobDescriptor) -> str:
    """The dotted name a user types for this descriptor."""
    if descriptor.group:
        return f"{descriptor.group}.{descriptor.name}"
    return descriptor.name


def _address_segments(descriptor: JobDescriptor) -> list[str]:
    """Every name this address passes through: leaf first, then its groups.

    A declared section is a single word, so a group formed by ``shell.deploy``
    is caught on ``shell`` and a job called ``shell`` on its own name. Leaf
    first, because the job's own name is the more specific finding.
    """
    segments = [descriptor.name]
    if descriptor.group:
        segments.extend(reversed(descriptor.group.split(".")))
    return segments
