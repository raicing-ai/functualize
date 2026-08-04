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

from pathlib import Path
from typing import TYPE_CHECKING

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
        base_dir: Base directory for glob pattern matching.

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
        filters.append(GlobExcludePreFilter(config.exclude_patterns, base_dir))

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
