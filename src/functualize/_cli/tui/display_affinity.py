"""Display affinity matching for job-linked display behavior.

Determines whether a DisplayProvider is "related" to the current job
based on linked_jobs and linked_groups, and applies the display_auto_switch
setting behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app.utils import group_ancestors

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp
    from functualize.plugin.protocols import DisplayProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AffinityMatch:
    """Result of an affinity match check."""

    is_related: bool
    display_id: str
    match_type: str | None = None  # "job" | "group" | None


def is_display_related(
    provider: DisplayProvider,
    job_name: str | None,
) -> bool:
    """Check if a display provider is related to the given job.

    A display is "related" if:
    - The exact job name appears in provider.linked_jobs, OR
    - The job's group (or any ancestor group) appears in provider.linked_groups

    Args:
        provider: The DisplayProvider to check.
        job_name: The qualified job name (e.g., "infra.aws.deploy").

    Returns:
        True if the display is related to the job.
    """
    if job_name is None:
        return False

    # linked_jobs/linked_groups are optional: display discovery requires only
    # display_id/display_title/display_priority/should_show/compose_display, so
    # a minimal provider legitimately has neither attribute.
    linked_jobs = getattr(provider, "linked_jobs", None)
    linked_groups = getattr(provider, "linked_groups", None)

    # Check linked_jobs (exact match)
    if linked_jobs and job_name in linked_jobs:
        return True

    # Check linked_groups (group or ancestor group)
    if linked_groups:
        # Derive the job's group and check it plus every ancestor group.
        # "infra.aws.deploy" → group "infra.aws" → {"infra", "infra.aws"}.
        parts = job_name.rsplit(".", 1)
        if len(parts) == 2:
            group_path = parts[0]
            if any(
                a in linked_groups for a in group_ancestors(group_path, inclusive=True)
            ):
                return True

    return False


def find_related_displays(
    providers: list[DisplayProvider],
    job_name: str | None,
    cwd: Path,
    app: FunctualizeApp,
) -> list[DisplayProvider]:
    """Find all displays related to the current job that are also CWD-visible.

    A display must satisfy BOTH:
    1. is_display_related(provider, job_name) == True
    2. provider.should_show(cwd, app) == True

    Returns providers sorted by display_priority (ascending).
    """
    if job_name is None:
        return []

    related = []
    for provider in providers:
        try:
            if is_display_related(provider, job_name) and provider.should_show(
                cwd, app
            ):
                related.append(provider)
        except Exception as exc:
            # Per error handling spec: treat should_show errors as False
            logger.warning(
                f"find_related_displays: should_show() failed for {provider!r} "
                f"({type(exc).__name__}): {exc}"
            )
            continue

    # Sort by display_priority
    related.sort(key=lambda p: getattr(p, "display_priority", 100))
    return related


def get_auto_switch_target(
    providers: list[DisplayProvider],
    job_name: str | None,
    cwd: Path,
    app: FunctualizeApp,
    display_auto_switch: str,
) -> DisplayProvider | None:
    """Get the display to auto-switch to based on setting.

    - "auto": return the lowest-priority related display
    - "indicator": return None (caller shows indicator instead)
    - "off": return None

    Args:
        providers: All registered DisplayProviders.
        job_name: Current recognized job name.
        cwd: Current working directory.
        app: FunctualizeApp instance.
        display_auto_switch: Setting value ("auto", "indicator", "off").

    Returns:
        The DisplayProvider to switch to, or None.
    """
    if display_auto_switch != "auto":
        return None

    related = find_related_displays(providers, job_name, cwd, app)
    if related:
        return related[0]  # Lowest priority = first
    return None
