"""Job origin classification for TUI provenance badges.

Classifies jobs by their origin (local, plugin, child, builtin) and provides
display metadata for rendering provenance badges in the TUI smart bar.

This module is in the ``_cli/`` layer — it imports only from public API
(``functualize.app``, ``functualize.types``) and from sibling ``_cli/`` modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._cli.builtins import BUILTIN_NAMES

if TYPE_CHECKING:
    from functualize._cli.data.argument_history import ArgumentHistory
    from functualize.app.core import FunctualizeApp
    from functualize.types import JobDescriptor


@dataclass(frozen=True)
class ProvenanceInfo:
    """Classification result for a job's origin.

    Attributes:
        source_type: One of "local", "plugin", "child", "builtin".
        display_label: Human-readable label for TUI badges.
        badge_style: Rich markup style string for rendering.
    """

    source_type: str
    display_label: str
    badge_style: str


class CompletionProvenanceClassifier:
    """Classifies jobs by their origin for TUI provenance badges.

    Classification priority (highest to lowest):
        1. builtin — name matches a known built-in command
        2. plugin — registered by a loaded plugin
        3. child — originates from a mounted child app
        4. local — default for project-discovered jobs
    """

    def __init__(
        self,
        app: FunctualizeApp,
        history: ArgumentHistory | None = None,
    ) -> None:
        self._app = app
        self._history = history
        self._builtin_names: frozenset[str] = BUILTIN_NAMES

    def get_provenance(self, job: JobDescriptor) -> ProvenanceInfo:
        """Classify a job into its provenance category.

        Uses priority-ordered classification:
        builtin → plugin → child → local (default).

        Args:
            job: The job descriptor to classify.

        Returns:
            A ProvenanceInfo with source_type, display_label, and badge_style.
        """
        if job.name in self._builtin_names:
            return ProvenanceInfo(
                source_type="builtin",
                display_label="built-in",
                badge_style="dim cyan",
            )

        if self._is_plugin(job):
            return ProvenanceInfo(
                source_type="plugin",
                display_label=self._get_plugin_display_name(job),
                badge_style="bold magenta",
            )

        if self._is_child(job):
            return ProvenanceInfo(
                source_type="child",
                display_label=self._get_child_display_name(job),
                badge_style="bold blue",
            )

        return ProvenanceInfo(
            source_type="local",
            display_label="local",
            badge_style="bold",
        )

    def is_recent(self, job_name: str) -> bool:
        """Check if a job has history entries (qualifies as 'recent').

        The "recent" category is orthogonal to the primary classification —
        a job can be both "local" and "recent".

        Args:
            job_name: The job name to check.

        Returns:
            True if the ArgumentHistory contains at least one entry for this job.
        """
        if self._history is None:
            return False
        return self._history.has_history(job_name)

    def _is_local(self, job: JobDescriptor) -> bool:
        """Check if source_file is within configured job directories.

        Args:
            job: The job descriptor to check.

        Returns:
            True if the job's source_file is under one of the app's
            configured job directories.
        """
        if not job.source_file:
            return False

        job_path = Path(job.source_file).resolve()
        job_dirs: list[str] = getattr(self._app, "_jobs_directories", [])

        for directory in job_dirs:
            dir_path = Path(directory).resolve()
            try:
                job_path.relative_to(dir_path)
                return True
            except ValueError:
                continue

        return False

    def _is_plugin(self, job: JobDescriptor) -> bool:
        """Check if job was registered by a plugin.

        Checks whether the job name appears in the PluginLoader's
        loaded_plugins registry (plugin name → entry point name mapping).

        Args:
            job: The job descriptor to check.

        Returns:
            True if the job is associated with a loaded plugin.
        """
        if not hasattr(self._app, "plugin_loader"):
            return False

        loaded_plugins: dict[str, str] = self._app.plugin_loader.loaded_plugins

        # Check if job name matches a plugin name directly
        if job.name in loaded_plugins:
            return True

        # Check if job's group prefix matches a plugin name
        if job.group and job.group in loaded_plugins:
            return True

        # Check job metadata for plugin_name marker
        if job.metadata and isinstance(job.metadata, dict):
            plugin_name = job.metadata.get("plugin_name")
            if plugin_name and plugin_name in loaded_plugins:
                return True

        return False

    def _is_child(self, job: JobDescriptor) -> bool:
        """Check if job originates from a child app.

        Detection heuristics:
        1. Job's group prefix matches a known child app namespace.
        2. Job metadata contains a "child_app" key.

        Args:
            job: The job descriptor to check.

        Returns:
            True if the job originates from a mounted child app.
        """
        # Check metadata for explicit child_app marker
        if (
            job.metadata
            and isinstance(job.metadata, dict)
            and "child_app" in job.metadata
        ):
            return True

        # Check if job group prefix matches a child app namespace
        child_names = self._get_child_app_names()
        if not child_names:
            return False

        if job.group and job.group in child_names:
            return True

        # Check if the job name itself has a child namespace prefix
        name_prefix = job.name.split(".")[0] if "." in job.name else None
        return bool(name_prefix and name_prefix in child_names)

    def _get_child_app_names(self) -> frozenset[str]:
        """Get the set of mounted child app namespace names."""
        children = getattr(self._app, "child_projects", [])
        return frozenset(child.name for child in children)

    def _get_plugin_display_name(self, job: JobDescriptor) -> str:
        """Get the plugin's display name for a plugin-sourced job."""
        if job.metadata and isinstance(job.metadata, dict):
            plugin_name = job.metadata.get("plugin_name")
            if plugin_name:
                return str(plugin_name)

        if job.group and hasattr(self._app, "plugin_loader"):
            loaded = self._app.plugin_loader.loaded_plugins
            if job.group in loaded:
                return job.group

        return "plugin"

    def _get_child_display_name(self, job: JobDescriptor) -> str:
        """Get the child app's display name for a child-sourced job."""
        if job.metadata and isinstance(job.metadata, dict):
            child_name = job.metadata.get("child_app")
            if child_name:
                return str(child_name)

        child_names = self._get_child_app_names()

        if job.group and job.group in child_names:
            return job.group

        name_prefix = job.name.split(".")[0] if "." in job.name else None
        if name_prefix and name_prefix in child_names:
            return name_prefix

        return "child"
