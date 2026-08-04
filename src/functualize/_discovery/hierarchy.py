"""Child project composition for hierarchical functualize projects.

Discovers child functualize projects from configured paths and composes
their jobs into the parent application's job registry via namespace
prefixing. Absorbed from the top-level `hierarchy/` package.

Unlike the original hierarchy/loader.py, this module has NO CLI
dependency. It only discovers and composes child projects — the actual
CLI mounting is handled by the adapter layer.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChildProject:
    """Represents a discovered child functualize project.

    Attributes:
        name: The namespace under which this child's jobs are composed.
        path: Absolute path to the child project root directory.
        jobs_directories: Resolved absolute paths to the child's job directories.
        config_path: Path to the child's config directory (if found).
    """

    name: str
    path: str
    jobs_directories: list[str] = field(default_factory=list)
    config_path: str | None = None


# Re-exports from hierarchy_validator and version_resolver for backward compat
from functualize._discovery.hierarchy_validator import (  # noqa: E402, F401
    ErrorFormatter,
    HierarchyValidationError,
    HierarchyValidator,
    ValidationContext,
    ValidationFailure,
)
from functualize._discovery.version_resolver import (  # noqa: E402, F401
    ResolvedVersion,
    VersionResolver,
)
