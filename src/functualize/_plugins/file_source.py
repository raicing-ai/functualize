"""Loading plugins that are files on disk rather than installed packages.

A file plugin is any `.py` file dropped into a plugin directory — no packaging,
no entry point. This module owns the on-disk format: which files are eligible,
what makes one a plugin, and how same-name collisions resolve.

Split out of `PluginLoader` by `declared-plugin-directories`/T4. That class had
grown to 595 lines against the constitution's ~500 bar
(`.spec/CONSTITUTION.md` → *Forbidden Patterns*, "if a class exceeds ~500 LOC,
decompose it"), and these methods are one cohesive responsibility with its own
reason to change.

It takes **paths, never an app**. `PluginLoader` used to resolve its own
directories by reaching into `app._resolution_chain` — an attribute that does
not exist yet when plugins load — and falling back to a hard-coded
`Path.cwd() / ".functualize" / "plugins"`. Both are gone; the composition root
decides and this scans.

Security note carried over from the loader: file plugins execute arbitrary
Python from the local filesystem at the same trust level as any local `.py`
file. They are NOT sandboxed or cryptographically verified.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from functualize._plugins.metadata import _validate_metadata

logger = logging.getLogger(__name__)

__all__ = ["FilePluginSource"]


class FilePluginSource:
    """Discovers and loads file-based plugins from a list of directories.

    Holds no state between calls; `PluginLoader` keeps one as a plain
    attribute. A concrete collaborator, not a Protocol — there is one
    implementation, and inventing a port for it would be speculative
    generality.
    """

    def discover(self, directories: Sequence[str]) -> list[Any]:
        """Load every file plugin found in `directories`, in the given order.

        Scans each directory for top-level `.py` files (non-recursive), skipping
        names starting with `_`, sorted case-insensitively so the order is
        deterministic. Same-name duplicates are resolved first-wins across the
        whole scan, not per directory — which is what lets a declared directory
        take precedence over the convention one.

        Takes paths, not an app. That is the point of the split: deciding
        *which* directories to scan is the composition root's job, and this
        class is then testable without a mock application.

        Args:
            directories: Absolute directory paths, in scan order.

        Returns:
            A list of valid plugin objects.
        """
        dirs = directories
        loaded: list[Any] = []
        loaded_names: set[str] = set()

        for plugin_dir in dirs:
            dir_path = Path(plugin_dir)
            if not dir_path.is_dir():
                logger.debug(f"Plugin directory does not exist: {plugin_dir}")
                continue

            # Sort files case-insensitively for deterministic ordering
            py_files = sorted(dir_path.glob("*.py"), key=lambda f: f.name.lower())

            for py_file in py_files:
                if py_file.name.startswith("_"):
                    continue

                plugin = self._load_file_plugin(py_file)
                if plugin is None:
                    continue

                # Handle same-name duplicates: first alphabetically wins
                plugin_name = plugin.name
                if plugin_name in loaded_names:
                    logger.warning(
                        f"Duplicate file plugin name '{plugin_name}' "
                        f"from '{py_file}'. Already loaded from an earlier "
                        f"file. Skipping."
                    )
                    continue

                loaded_names.add(plugin_name)
                loaded.append(plugin)

        return loaded

    def _load_file_plugin(self, py_file: Path) -> Any | None:
        """Load a single file plugin via importlib.

        Attempts to import the file as a module. Checks for a module-level
        `plugin` attribute first; if absent, inspects module members for any
        object satisfying the PluginMetadata protocol.

        Args:
            py_file: Path to the .py file to load.

        Returns:
            The plugin object if successfully loaded and validated, or None.
        """
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec is None or spec.loader is None:
                logger.warning(
                    f"Failed to load file plugin '{py_file}': "
                    f"could not create module spec"
                )
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning(f"Failed to load file plugin '{py_file}': {e}")
            return None

        # Check for module-level `plugin` attribute first
        plugin = getattr(module, "plugin", None)
        if plugin is None:
            # Inspect module for PluginMetadata protocol objects
            plugin = self._find_plugin_in_module(module)

        if plugin is None:
            return None

        # Validate metadata
        errors = _validate_metadata(plugin, str(py_file))
        if errors:
            logger.warning(f"File plugin '{py_file}' invalid: {'; '.join(errors)}")
            return None

        return plugin

    def _find_plugin_in_module(self, module: Any) -> Any | None:
        """Inspect a module for objects satisfying the PluginMetadata protocol.

        Looks for any object in the module that has `name`, `version`,
        `description` string attributes and is callable.

        Args:
            module: The imported module to inspect.

        Returns:
            The first matching plugin object, or None if no candidate found.
        """
        for _attr_name, obj in inspect.getmembers(module):
            if obj is module:
                continue
            if (
                hasattr(obj, "name")
                and hasattr(obj, "version")
                and hasattr(obj, "description")
                and isinstance(getattr(obj, "name", None), str)
                and isinstance(getattr(obj, "version", None), str)
                and isinstance(getattr(obj, "description", None), str)
                and callable(obj)
            ):
                return obj
        return None
