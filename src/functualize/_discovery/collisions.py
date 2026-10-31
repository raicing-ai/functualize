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

import inspect
from typing import TYPE_CHECKING

from functualize._types.discovery_report import (
    class_job_name_collision,
    job_name_collision,
    record_discovery_finding,
    reserved_section_name,
)
from functualize._types.functualize_settings import FUNCTUALIZE_SETTINGS

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from functualize._types.descriptors import JobDescriptor
    from functualize._types.discovery_report import DiscoveryFailure

__all__ = [
    "claim_order",
    "involves_class_job",
    "resolve_name_collisions",
    "strict_collision",
]


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
    grouped: dict[str, list[JobDescriptor]] = {}
    sections = FUNCTUALIZE_SETTINGS.sections()
    for descriptor in sorted(descriptors, key=claim_order):
        _record_reserved_section(descriptor, sections)
        claimants = grouped.setdefault(descriptor.name, [])
        if not claimants or claimants[-1] is not descriptor:
            claimants.append(descriptor)

    kept: list[JobDescriptor] = []
    for name, claimants in grouped.items():
        if len(claimants) == 1:
            kept.append(claimants[0])
        elif not involves_class_job(claimants):
            kept.append(_last_claimant_wins(name, claimants))
        else:
            record_discovery_finding(strict_collision(name, claimants))
            # Nothing is kept: the name is registered to nobody rather than to
            # a claimant the user did not choose.
    return kept


def involves_class_job(claimants: Sequence[JobDescriptor]) -> bool:
    """Whether a name claimed by ``claimants`` falls under the strict rule.

    Two or more claimants, at least one of them a method of a job class. The
    test both resolution sites apply — the scan inside one provider, and the
    pipeline across providers — so the two cannot disagree on which rule a
    collision gets.
    """
    return len(claimants) > 1 and any(
        claimant.owner_class is not None for claimant in claimants
    )


def strict_collision(name: str, claimants: Sequence[JobDescriptor]) -> DiscoveryFailure:
    """The record for a name no claimant is registered under.

    Names every claimant, ``Class.method`` for a class job, with its file. Built
    here for both resolution sites, so a collision found across providers reads
    exactly like one found inside a scan.
    """
    return class_job_name_collision(
        canonical_name=name,
        claimants=tuple(
            (_qualified_name(claimant), _source_of(claimant)) for claimant in claimants
        ),
        # The record names a file an operator can open. Every claimant has
        # one, and the first in claim order is the one that does not move
        # between boots.
        module=claimants[0].module_path or claimants[0].source_file,
        path=claimants[0].source_file or "",
    )


def _source_of(claimant: JobDescriptor) -> str:
    """The file a claimant was defined in, for the record that names it.

    A scanned descriptor carries it. A plain function handed to a
    ``StaticProvider`` does not — that provider never needed one — so it is
    read off the live function instead. Only this record asks, so no other
    descriptor changes.

    ``<entry_point>`` and ``<dynamic>`` are provenance markers, not files — the
    line ``lazy_wrapper._import_real_function`` draws too. Taking a marker for a
    file made the record print ``(<entry_point>)`` for a job class whose module
    is a readable file on ``sys.path``, the one name an operator needs. So a
    marker counts as absent until the live callable has been asked; a job
    class's proxy is read through ``__wrapped__`` to the method it stands for.
    The marker is the answer only when nothing names a file — an entry point
    whose source cannot be read, the limitation D10 accepts — and a claimant
    with neither stays blank rather than guessed.
    """
    recorded = claimant.source_file or ""
    if recorded and recorded not in _PROVENANCE_MARKERS:
        return recorded
    if claimant.function is not None:
        try:
            located = inspect.getsourcefile(inspect.unwrap(claimant.function))
        except (TypeError, ValueError):
            located = None
        if located:
            return located
    return recorded


#: ``source_file`` values that say where a descriptor came from, not which file
#: defines it. Spelled as ``lazy_wrapper._import_real_function`` spells them.
_PROVENANCE_MARKERS = frozenset({"<entry_point>", "<dynamic>"})


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
