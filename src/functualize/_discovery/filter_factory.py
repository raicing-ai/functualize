"""Factories for constructing discovery filter stacks from DiscoveryConfig.

Two levels, matching the two ``require_*`` setting families:

- :func:`build_pre_filter_from_config` — file level (``require_file_*``,
  ``exclude_patterns``). An AllOf combinator ordered cheapest-first to
  short-circuit expensive AST parsing when possible.
- :func:`build_job_filter_from_config` — job level (``require_job_*``), applied
  to extracted descriptors.

Only imports from ``_types/``, ``_primitives/``, and Python stdlib.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._primitives.cache_format import compute_discovery_hash
from functualize._primitives.job_filter import (
    AllJobFilters,
    JobDecoratorFilter,
    JobFilter,
    JobPostfixFilter,
    JobPrefixFilter,
)
from functualize._primitives.pre_filter import (
    AllOf,
    AnyOf,
    ASTModulePreFilter,
    DecoratorModulePreFilter,
    DefaultModulePreFilter,
    DisplayClassPreFilter,
    FilePostfixPreFilter,
    FilePrefixPreFilter,
    GlobExcludePreFilter,
    GroupOptionsPreFilter,
    ImportModulePreFilter,
    MarkerModulePreFilter,
    ModulePreFilter,
)

if TYPE_CHECKING:
    from functualize.app.config import DiscoveryConfig


def build_pre_filter_from_config(
    config: DiscoveryConfig,
    base_dir: Path,
    scan_roots: Sequence[Path] = (),
) -> ModulePreFilter:
    """Build a composable pre-filter stack from a DiscoveryConfig.

    Filter order within AllOf (cheapest-first):
    1. GlobExcludePreFilter (skip excluded files first — cheapest)
    2. DefaultModulePreFilter (skip _-prefixed — cheap string check)
    3. FilePrefixPreFilter (filename check — cheap)
    4. FilePostfixPreFilter (filename check — cheap)
    5. ASTModulePreFilter (requires file read + parse)
    6. ImportModulePreFilter (requires file read + parse)
    7. MarkerModulePreFilter (requires file read + parse)
    8. DecoratorModulePreFilter (requires file read + parse)

    Returns AllOf combinator with all applicable filters.

    Args:
        config: Resolved discovery configuration.
        base_dir: Primary scan root for glob pattern matching.
        scan_roots: The remaining scan roots. ``exclude_patterns`` is matched
            relative to whichever of these contains the candidate file, so an
            exclusion applies to every configured directory rather than only the
            first (ADR-011). Defaults to empty, which is single-root behaviour.

    Returns:
        A ModulePreFilter combining all applicable filters via AND semantics.

    Raises:
        ValueError: If ``require_job_decorators`` is an empty tuple (not None).
    """
    if (
        config.require_job_decorators is not None
        and len(config.require_job_decorators) == 0
    ):
        msg = (
            "require_job_decorators must contain at least one decorator name "
            "when explicitly set (use None to disable the filter)"
        )
        raise ValueError(msg)

    filters: list[ModulePreFilter] = []

    # 1. GlobExcludePreFilter — skip excluded files first (cheapest)
    if config.exclude_patterns:
        filters.append(
            GlobExcludePreFilter(config.exclude_patterns, base_dir, scan_roots)
        )

    # 2. DefaultModulePreFilter — always included (skip _-prefixed), except
    # for a module that declares a group's flags. `jobs/deploy/_group.py` is
    # the conventional home for a GroupOptions declaration, and the leading
    # underscore there means "defines no jobs", not "ignore me entirely".
    filters.append(AnyOf(DefaultModulePreFilter(), GroupOptionsPreFilter()))

    # 3. FilePrefixPreFilter — filename check (cheap)
    if config.require_file_prefix is not None:
        filters.append(FilePrefixPreFilter(config.require_file_prefix))

    # 4. FilePostfixPreFilter — filename check (cheap)
    if config.require_file_postfix is not None:
        filters.append(FilePostfixPreFilter(config.require_file_postfix))

    # 5. ASTModulePreFilter — always included (requires file read + parse).
    # A module qualifies with a public function (a job candidate), a
    # display-provider class, OR a GroupOptions declaration — display-only and
    # declaration-only modules must still be imported so the scan's detection
    # passes can cache them.
    filters.append(
        AnyOf(ASTModulePreFilter(), DisplayClassPreFilter(), GroupOptionsPreFilter())
    )

    # 6. ImportModulePreFilter — requires file read + parse
    if config.require_file_import is not None:
        filters.append(ImportModulePreFilter(config.require_file_import))

    # 7. MarkerModulePreFilter — requires file read + parse
    if config.require_file_marker is not None:
        filters.append(MarkerModulePreFilter(config.require_file_marker))

    # 8. DecoratorModulePreFilter — requires file read + parse.
    # An import-skip optimization for the job-level decorator filter, not the
    # filter itself: a file with zero decorated functions cannot contribute a
    # job, so skip importing it. Files that survive still have every public
    # function judged individually by JobDecoratorFilter below.
    if config.require_job_decorators is not None:
        filters.append(DecoratorModulePreFilter(config.require_job_decorators))

    # 9. The caller's own filter, if any — appended, never substituted, so a
    # host that adds one keeps every `require_*` setting it also configured.
    # Last because its cost is unknown: the built-ins above are ordered
    # cheapest-first precisely so an expensive check runs on the fewest files,
    # and an unknown cost is assumed expensive.
    caller_filter = getattr(config, "pre_filter", None)
    if caller_filter is not None:
        filters.append(caller_filter)

    return AllOf(*filters)


def build_job_filter_from_config(config: DiscoveryConfig) -> JobFilter | None:
    """Build a job-level (function-level) filter stack from a DiscoveryConfig.

    Covers the ``require_job_*`` family, which judges each extracted descriptor
    rather than each file:

    1. ``require_job_prefix`` — function name starts with the prefix
    2. ``require_job_postfix`` — function name ends with the postfix
    3. ``require_job_decorators`` — function carries one of the decorators

    Args:
        config: Resolved discovery configuration.

    Returns:
        A JobFilter combining all applicable filters via AND semantics, or None
        when no job-level setting is configured (so callers can skip the pass
        entirely).
    """
    filters: list[JobFilter] = []

    if config.require_job_prefix is not None:
        filters.append(JobPrefixFilter(config.require_job_prefix))

    if config.require_job_postfix is not None:
        filters.append(JobPostfixFilter(config.require_job_postfix))

    if config.require_job_decorators:
        filters.append(JobDecoratorFilter(config.require_job_decorators))

    if not filters:
        return None

    return AllJobFilters(*filters)


# The ten DiscoveryConfig settings that decide which modules and jobs are
# admitted, each paired with its DiscoveryConfig default. Kept beside the two
# builders above deliberately: the cache fingerprint must cover exactly the
# fields those builders consume, and one file is what keeps the two in agreement
# when an eleventh setting is added.
#
# `pre_filter` is the one entry whose *value* is not what gets hashed --
# see `_fingerprint_contribution` below.
#
# The defaults are repeated here because `_discovery` may not import the public
# `app.config` at runtime (see `.spec/CONSTITUTION.md` layer rules), so they
# cannot be read off the dataclass. `test_discovery_hash.py` pins this tuple to
# DiscoveryConfig's real field names *and* defaults, so drift fails a test rather
# than silently fingerprinting an unset config as something else.
_DISCOVERY_FINGERPRINT_FIELDS: tuple[tuple[str, object], ...] = (
    ("exclude_patterns", ()),
    ("extra_directories", ()),
    ("require_file_prefix", None),
    ("require_file_postfix", None),
    ("require_file_import", None),
    ("require_file_marker", None),
    ("require_job_decorators", None),
    ("require_job_prefix", None),
    ("require_job_postfix", None),
    ("pre_filter", None),
)


def discovery_hash_from_config(config: DiscoveryConfig | None) -> str:
    """Fingerprint a DiscoveryConfig for cache invalidation.

    The discovery cache stores the decisions these settings produced — both the
    admitted ``entries`` and the ``pre_filter_decisions`` that rejected a file.
    Neither is re-derived on a warm read, so a cache built under one filter set
    and replayed under another is silently wrong in both directions. Comparing
    this digest against the cached one is what makes the cache filter-aware.

    ``None`` fingerprints identically to an all-defaults ``DiscoveryConfig``,
    because the two build the same (empty) filter stack. They must agree: a boot
    that drops its config must invalidate a cache written under an active filter,
    which is the "user removed their `exclude_patterns`" direction of the bug.

    Args:
        config: Resolved discovery configuration, or None when none is set.

    Returns:
        A ``"sha256:<hex>"`` string from :func:`compute_discovery_hash`.
    """
    return compute_discovery_hash(
        [
            (
                name,
                _fingerprint_contribution(
                    name,
                    default if config is None else getattr(config, name, default),
                ),
            )
            for name, default in _DISCOVERY_FINGERPRINT_FIELDS
        ]
    )


def _fingerprint_contribution(name: str, value: object) -> object:
    """What a field contributes to the digest, which is not always its value.

    Nine of the ten settings are strings and tuples and hash as themselves. A
    caller-supplied ``pre_filter`` cannot: ``compute_discovery_hash`` renders an
    unrecognised value with ``str()``, and ``str()`` of an object carries its
    address, so the digest would differ on every boot -- invalidating the cache
    on every run while looking like it worked. Its ``fingerprint()`` is a
    stable, caller-declared string, and is the only thing hashed.

    A filter that predates the two-method Protocol has no ``fingerprint()``. It
    is not silently accepted: a filter whose identity cannot be established
    would replay decisions its own logic no longer makes, which is the X1-X4
    class ADR-010/ADR-011 exist to close.
    """
    if name != "pre_filter" or value is None:
        return value
    fingerprint = getattr(value, "fingerprint", None)
    if not callable(fingerprint):
        msg = (
            f"{type(value).__name__} was given as DiscoveryConfig.pre_filter but "
            f"has no fingerprint(). The discovery cache persists this filter's "
            f"negative decisions and replays them, so it needs a stable identity "
            f"that changes when the filter's behaviour changes. Add a "
            f"fingerprint() returning a string you bump when the logic changes."
        )
        raise TypeError(msg)
    return f"fingerprint:{fingerprint()}"
