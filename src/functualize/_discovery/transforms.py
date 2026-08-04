"""Job transform implementations for the discovery pipeline.

Concrete transforms that satisfy the JobTransform protocol from _types/:
- NamespaceTransform: Prefix all job names with a namespace string.
- GroupByModuleTransform: Set group field from a module-level variable.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._discovery.naming import normalize_name, qualified_name

if TYPE_CHECKING:
    from functualize._types import JobDescriptor

logger = logging.getLogger(__name__)


class NamespaceTransform:
    """Prefix all job names with a namespace.

    Satisfies the JobTransform Protocol via structural typing.

    Used to compose child project jobs under a parent namespace, replacing
    the older ChildProjectProvider pattern. Use DirectoryScanProvider +
    NamespaceTransform instead.

    Args:
        prefix: Non-empty namespace prefix string.
        separator: Separator between prefix and job name (default: ".").

    Raises:
        ValueError: If prefix is an empty string.
    """

    def __init__(self, prefix: str, separator: str = ".") -> None:
        if not prefix:
            raise ValueError("NamespaceTransform prefix must be non-empty")
        self._prefix = prefix
        self._separator = separator
        self._full_prefix = f"{prefix}{separator}"

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Prepend "{prefix}{separator}" to each descriptor's name."""
        return [self._add_prefix(job) for job in jobs]

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Strip prefix for lookup, return None if name doesn't match prefix.

        If the name does not start with "{prefix}{separator}", returns None.
        If the name matches but the underlying descriptor is None, returns None.
        Otherwise returns the descriptor with the prefixed name.
        """
        if not name.startswith(self._full_prefix):
            return None
        if descriptor is None:
            return None
        return self._add_prefix(descriptor)

    def _add_prefix(self, job: JobDescriptor) -> JobDescriptor:
        """Return a new JobDescriptor with the prefixed name.

        The prefix is normalized like any other address segment. A namespace
        *is* a group segment as far as the CLI is concerned, so leaving it raw
        would produce ``ns_a.job-x`` — half canonical, half not, and neither
        spelling typeable as a whole.
        """
        return dataclasses.replace(
            job, name=f"{normalize_name(self._prefix)}{self._separator}{job.name}"
        )


class GroupByModuleTransform:
    """Set the group field on job descriptors from a module-level variable.

    Reads a configurable module-level variable (default: ``JOB_GROUP``) from
    each job's source module and assigns its value as the ``group`` field.
    Also rewrites the descriptor's ``name`` to the qualified form using
    :func:`qualified_name`.

    If the module does NOT define the configured variable, the group field is
    left unchanged. This transform does NOT affect job eligibility — modules
    without the variable still have their functions discovered as jobs.

    Satisfies the JobTransform Protocol via structural typing.

    Args:
        attribute_name: Module-level variable name to read (default: "JOB_GROUP").
    """

    def __init__(self, attribute_name: str = "JOB_GROUP") -> None:
        self._attribute_name = attribute_name

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Set group field from module-level variable for each job."""
        return [self._apply_group(job) for job in jobs]

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Set group field from module-level variable for a single job."""
        if descriptor is None:
            return None
        return self._apply_group(descriptor)

    def _apply_group(self, job: JobDescriptor) -> JobDescriptor:
        """Read the module-level variable, set group, and rewrite name to qualified form."""
        group_value = self._read_module_attribute(job)
        if group_value is None:
            return job
        # The group is normalized alongside the name. Leaving it raw would give
        # one group two spellings — `descriptor.name` saying `shared-group.job-a`
        # while `descriptor.group` said `shared_group` — and the CLI mounts its
        # subcommand from the latter, so `func shared-group job-a` would not
        # reach a job whose own name claims exactly that address.
        return dataclasses.replace(
            job,
            group=normalize_name(group_value),
            name=qualified_name(group_value, job.func_name),
        )

    def _read_module_attribute(self, job: JobDescriptor) -> str | None:
        """Read the configured attribute from the job's source module.

        Attempts to find the module in sys.modules first by module_path, then
        by source_file. If not loaded, tries to load from the source file.
        Returns None if the attribute doesn't exist or the module can't be loaded.
        """
        # First try by module_path (most reliable for registered modules)
        if job.module_path:
            module = sys.modules.get(job.module_path)
            if module is not None:
                value = getattr(module, self._attribute_name, None)
                if value is not None and isinstance(value, str):
                    return value

        # Then try by source_file path
        source_path = Path(job.source_file) if job.source_file else Path(job.source)
        if not source_path.exists() or source_path.name == "<static>":
            return None

        # Try to find in sys.modules by checking loaded modules
        module = self._find_loaded_module(source_path)

        if module is None:
            # Try loading from the source file
            module = self._load_module(source_path)

        if module is None:
            return None

        value = getattr(module, self._attribute_name, None)
        if value is not None and isinstance(value, str):
            return value
        return None

    def _find_loaded_module(self, source_path: Path) -> Any | None:
        """Find a module in sys.modules that corresponds to the source file."""
        abs_source = str(source_path.resolve())
        for mod in sys.modules.values():
            mod_file = getattr(mod, "__file__", None)
            if mod_file is not None:
                try:
                    if Path(mod_file).resolve() == Path(abs_source).resolve():
                        return mod
                except (OSError, ValueError):
                    continue
        return None

    def _load_module(self, source_path: Path) -> Any | None:
        """Load a module from a source file for attribute extraction."""
        try:
            module_name = source_path.stem
            unique_name = f"_functualize_group_.{module_name}"
            spec = importlib.util.spec_from_file_location(unique_name, str(source_path))
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            logger.debug(
                "Failed to load module '%s' for group attribute",
                source_path,
            )
            return None


# Backward-compatible aliases
GroupByModuleAttributeTransform = GroupByModuleTransform


class IdentityTransform:
    """Identity transform (pass-through).

    Returns inputs unchanged. Useful as a default or no-op transform.
    Satisfies the JobTransform Protocol via structural typing.
    """

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Pass through the list unchanged."""
        return jobs

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Pass through the descriptor unchanged."""
        return descriptor


class GroupFilterTransform:
    """Filter jobs by group membership.

    Satisfies the JobTransform Protocol via structural typing.

    Args:
        include_groups: If set, only jobs whose group is in this set pass through.
        exclude_groups: If set, jobs whose group is in this set are removed.

    When both are provided: include first, then exclude from the result.
    Jobs with group=None are excluded by include_groups (None is not in any
    include set) and included when only exclude_groups is set (None is not in
    any exclusion set).
    """

    def __init__(
        self,
        include_groups: set[str] | None = None,
        exclude_groups: set[str] | None = None,
    ) -> None:
        self._include = include_groups
        self._exclude = exclude_groups

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Filter job list by group membership."""
        result = list(jobs)
        if self._include is not None:
            result = [j for j in result if j.group in self._include]
        if self._exclude is not None:
            result = [j for j in result if j.group not in self._exclude]
        return result

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Filter individual job lookup by group membership."""
        if descriptor is None:
            return None
        if self._include is not None and descriptor.group not in self._include:
            return None
        if self._exclude is not None and descriptor.group in self._exclude:
            return None
        return descriptor


class VisibilityTransform:
    """Hide jobs by name or tag.

    Satisfies the JobTransform Protocol via structural typing.

    Args:
        hidden_names: Set of job names to hide (case-sensitive exact match).
        hidden_tags: Set of tags; jobs with any matching tag are hidden.
    """

    def __init__(
        self,
        hidden_names: set[str] | None = None,
        hidden_tags: set[str] | None = None,
    ) -> None:
        self._hidden_names = hidden_names or set()
        self._hidden_tags = hidden_tags or set()

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Exclude jobs matching hidden_names or hidden_tags."""
        if not self._hidden_names and not self._hidden_tags:
            return jobs
        return [j for j in jobs if not self._is_hidden(j)]

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Return None if the job would be hidden, otherwise pass through."""
        if descriptor is None:
            return None
        if self._is_hidden(descriptor):
            return None
        return descriptor

    def _is_hidden(self, job: JobDescriptor) -> bool:
        """Check if a job should be hidden by name or tag intersection."""
        if job.name in self._hidden_names:
            return True
        return bool(
            (self._hidden_tags and job.declaration is not None and job.declaration.tags)
            and set(job.declaration.tags) & self._hidden_tags
        )


class RenameTransform:
    """Rename specific jobs by mapping old names to new names.

    Satisfies the JobTransform Protocol via structural typing.

    Args:
        renames: Dict mapping old_name → new_name.
    """

    def __init__(self, renames: dict[str, str]) -> None:
        self._renames = renames
        self._reverse: dict[str, str] = {v: k for k, v in renames.items()}

    def transform_list(self, jobs: Sequence[JobDescriptor]) -> Sequence[JobDescriptor]:
        """Replace names matching keys in renames dict with corresponding values."""
        result: list[JobDescriptor] = []
        for job in jobs:
            if job.name in self._renames:
                result.append(dataclasses.replace(job, name=self._renames[job.name]))
            else:
                result.append(job)
        return result

    def transform_get(
        self, name: str, descriptor: JobDescriptor | None
    ) -> JobDescriptor | None:
        """Handle renamed job lookups."""
        if name in self._reverse:
            if descriptor is None:
                return None
            return dataclasses.replace(descriptor, name=name)
        if name in self._renames:
            return None
        return descriptor
