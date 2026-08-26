"""Plugin loader for discovering and loading plugins via entry points and files.

Contains plugin discovery, dependency sorting (topological sort), validation,
and registration logic.

Security Note:
    File plugins (loaded from local .functualize/plugins/ directories) execute
    arbitrary Python code from the local filesystem at the same trust level as
    any local .py file. They are NOT sandboxed or cryptographically verified.

Only imports from _types/, _primitives/, _events/, and Python stdlib.
"""

from __future__ import annotations

import contextlib
import importlib.util
import inspect
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from functualize._plugins.config import PluginConfigRegistry
from functualize._primitives.entry_points import entry_points

if TYPE_CHECKING:
    from functualize._events import EventBus

logger = logging.getLogger(__name__)

__all__ = [
    "CircularDependencyError",
    "MissingDependencyError",
    "PluginLoader",
    "topological_sort",
]

# PEP 440 version pattern
_PEP440_PATTERN = re.compile(
    r"^([1-9][0-9]*!)?"  # epoch
    r"(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*"  # release
    r"((a|b|rc)(0|[1-9][0-9]*))?"  # pre-release
    r"(\.post(0|[1-9][0-9]*))?"  # post-release
    r"(\.dev(0|[1-9][0-9]*))?$"  # dev release
)


# --- Dependency Resolution Errors ---


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected among plugins."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle)}")


class MissingDependencyError(Exception):
    """Raised when a plugin depends on a plugin that is not available."""

    def __init__(self, plugin_name: str, missing: str) -> None:
        self.plugin_name = plugin_name
        self.missing = missing
        super().__init__(
            f"Plugin '{plugin_name}' depends on '{missing}' which is not available"
        )


# --- Plugin Metadata Protocol ---


@runtime_checkable
class PluginMetadata(Protocol):
    """Protocol that plugins must satisfy to be loaded.

    Attributes:
        name: Plugin name, maximum 64 characters.
        version: Plugin version conforming to PEP 440.
        description: Plugin description, maximum 256 characters.
    """

    name: str
    version: str
    description: str


@runtime_checkable
class PluginWithConfigResolved(Protocol):
    """Protocol for plugins that want post-resolution notification."""

    def on_config_resolved(self, config: Any) -> None:
        """Called after config resolution with the validated config instance."""
        ...


# --- Validation Helpers ---


def _validate_pep440(version: str) -> bool:
    """Check if a version string conforms to PEP 440."""
    return _PEP440_PATTERN.match(version) is not None


def _validate_metadata(plugin: Any, entry_point_name: str) -> list[str]:
    """Validate plugin metadata attributes.

    Returns a list of validation error messages. Empty list means valid.
    """
    errors: list[str] = []

    # Check name attribute
    if not hasattr(plugin, "name"):
        errors.append("missing 'name' attribute")
    else:
        name = plugin.name
        if not isinstance(name, str):
            errors.append(f"'name' must be a string, got {type(name).__name__}")
        elif len(name) > 64:
            errors.append(f"'name' exceeds 64 characters (got {len(name)})")

    # Check version attribute
    if not hasattr(plugin, "version"):
        errors.append("missing 'version' attribute")
    else:
        version = plugin.version
        if not isinstance(version, str):
            errors.append(f"'version' must be a string, got {type(version).__name__}")
        elif not _validate_pep440(version):
            errors.append(f"'version' does not conform to PEP 440: {version!r}")

    # Check description attribute
    if not hasattr(plugin, "description"):
        errors.append("missing 'description' attribute")
    else:
        description = plugin.description
        if not isinstance(description, str):
            errors.append(
                f"'description' must be a string, got {type(description).__name__}"
            )
        elif len(description) > 256:
            errors.append(
                f"'description' exceeds 256 characters (got {len(description)})"
            )

    return errors


def _has_config_declaration(plugin: Any) -> bool:
    """Check if a plugin declares config requirements.

    A plugin is config-declaring if it has both `config_model` and
    `config_section` attributes, where `config_model` is a type (class)
    and `config_section` is a string.
    """
    if not hasattr(plugin, "config_model") or not hasattr(plugin, "config_section"):
        return False
    return isinstance(plugin.config_section, str) and isinstance(
        plugin.config_model, type
    )


def _resolve_plugin_config(plugin: Any, app: Any) -> Any:
    """Resolve a plugin's config model through the app's Resolution_Chain.

    Uses the same `app.resolve_model()` mechanism used by the framework
    for job configs, ensuring identical resolution semantics.

    Args:
        plugin: Plugin object with `config_model` and `config_section` attributes.
        app: The application instance with `resolve_model()` method.

    Returns:
        A validated instance of the plugin's config model.
    """
    section: str = plugin.config_section
    model_cls: type[Any] = plugin.config_model
    return app.resolve_model(section, model_cls)


# --- Topological Sort ---


def topological_sort(plugins: list[Any]) -> list[Any]:
    """Sort plugins by dependency order using Kahn's algorithm.

    Each plugin must have a `name` attribute. Plugins with a `depends_on`
    attribute (list[str]) declare dependencies on other plugin names.

    Uses stable alphabetical ordering when multiple plugins have zero
    in-degree simultaneously, ensuring deterministic output.

    Args:
        plugins: List of loaded plugin objects (unsorted).

    Returns:
        Plugins sorted so dependencies come before dependents.

    Raises:
        MissingDependencyError: If a declared dependency is not in the list.
        CircularDependencyError: If a cycle exists.
    """
    from functualize._primitives.graph import (
        GraphCycleError,
        MissingNodeError,
        topological_order,
    )

    name_to_plugin: dict[str, Any] = {p.name: p for p in plugins}
    dependencies: dict[str, list[str]] = {
        p.name: list(getattr(p, "depends_on", []) or []) for p in plugins
    }

    # The algorithm (Kahn's, alphabetically stable) lives in _primitives so
    # plugin loading and job scheduling share one ordering guarantee; the
    # plugin-domain error vocabulary is restored here.
    try:
        sorted_names = topological_order(dependencies)
    except MissingNodeError as exc:
        raise MissingDependencyError(exc.node, exc.dependency) from None
    except GraphCycleError as exc:
        raise CircularDependencyError(exc.cycle) from None

    return [name_to_plugin[name] for name in sorted_names]


# --- Plugin Loader ---


class PluginLoader:
    """Discovers and loads plugins via Python entry points and file-based plugins.

    Plugins are discovered under a configurable entry point group name
    (default: "functualize.plugins"). Each plugin must satisfy the
    PluginMetadata protocol and provide a registration callable that
    receives the application instance.

    The loader supports:
    - Dependency ordering via topological sort (plugins with `depends_on`)
    - Automatic config resolution for plugins declaring `config_model`/`config_section`
    - Post-resolution notification via `on_config_resolved(config)` callback
    - Config section conflict detection
    - File-based plugin discovery from local directories
    - Plugins without config attributes are loaded without config resolution
    """

    def __init__(self, group: str = "functualize.plugins"):
        self._group = group
        self._loaded: dict[str, str] = {}  # plugin name -> entry point name
        self._loaded_instances: list[Any] = []  # plugin instances in loading order

    @property
    def loaded_plugins(self) -> dict[str, str]:
        """Return a mapping of loaded plugin names to their entry point names."""
        return dict(self._loaded)

    @property
    def loaded_instances(self) -> list[Any]:
        """Return plugin instances in loading order."""
        return list(self._loaded_instances)

    def load_all(
        self,
        app: Any,
        event_bus: EventBus | None = None,
        perf_timeline: Any | None = None,
        disabled: set[str] | None = None,
        explicit: list[Any] | None = None,
    ) -> None:
        """Load all discovered plugins with dependency ordering and config resolution.

        The loading process follows these phases:

        Phase 1a: Discover entry points and load plugin objects, validating
                  metadata for each. Invalid plugins are skipped with warnings.

        Phase 1b: Discover file-based plugins from local plugin directories.

        Phase 1c: Add `explicit` plugins handed in by the caller.

        Merge: Entry-point plugins take precedence over file plugins; an
        explicit plugin takes precedence over both, because the caller
        constructed that object and passed it in by hand — discovery finding
        something of the same name is the weaker claim.

        Phase 2: Topological sort by `depends_on` attributes using Kahn's algorithm.

        Phase 3: Invoke `__call__(app)` in sorted order. For plugins declaring
                 `config_model` and `config_section`, resolve the config through
                 the Resolution_Chain, register it in the PluginConfigRegistry,
                 and invoke `on_config_resolved(config)` if implemented.

        Args:
            app: The application instance passed to each plugin's
                 registration callable.
            event_bus: Optional EventBus for emitting plugin lifecycle events.
            perf_timeline: Optional PerfTimeline for timing marks.
            disabled: Optional set of lowercased plugin names to skip during
                discovery. Matching is case-insensitive against entry-point names.
            explicit: Optional list of pre-instantiated plugin objects
                (``PluginSources.explicit_plugins``). Passed through the same
                metadata validation, `disabled` filter, topological sort and
                config resolution as a discovered plugin — the only difference
                is that it skips discovery.

        Raises:
            CircularDependencyError: If a circular dependency is detected.
            MissingDependencyError: If a declared dependency is not available.
            ValueError: If two plugins declare the same config_section.
        """
        # --- Discovery phase instrumentation ---
        if event_bus:
            with contextlib.suppress(Exception):
                event_bus.emit(
                    "plugin.discovery.start",
                    resource=self._group,
                    group=self._group,
                )

        if perf_timeline:
            perf_timeline.mark("boot.plugins.discovery.start")
        discovery_start = time.perf_counter()

        discovered = entry_points(group=self._group)

        # --- Phase 1a: Load all plugin objects from entry points ---
        loaded_objects: list[Any] = []
        plugin_entry_point_names: dict[str, str] = {}  # plugin name -> ep name

        for ep in discovered:
            # Skip disabled plugins before importing them
            if disabled and ep.name.lower() in disabled:
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.skip.{ep.name}")
                continue

            if event_bus:
                with contextlib.suppress(Exception):
                    event_bus.emit(
                        "plugin.load.start",
                        resource=ep.name,
                        plugin_name=ep.name,
                        entry_point=ep.name,
                    )

            if perf_timeline:
                perf_timeline.mark(f"boot.plugins.load.{ep.name}.start")
            load_start = time.perf_counter()

            try:
                plugin = ep.load()
                # If entry point resolves to a class, instantiate it.
                # Plugin classes define metadata as class attributes and
                # implement __call__(self, app) for registration.
                if isinstance(plugin, type):
                    plugin = plugin()
            except (ImportError, ModuleNotFoundError) as e:
                load_duration_ms = (time.perf_counter() - load_start) * 1000
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.load.{ep.name}.end")
                if event_bus:
                    with contextlib.suppress(Exception):
                        event_bus.emit(
                            "plugin.load.end",
                            resource=ep.name,
                            plugin_name=ep.name,
                            duration_ms=load_duration_ms,
                        )
                logger.warning(
                    f"Plugin '{ep.name}' could not be loaded due to a "
                    f"missing dependency: {e.name if e.name else e}. "
                    f"Install the plugin's dependencies to enable it."
                )
                continue
            except Exception as e:
                load_duration_ms = (time.perf_counter() - load_start) * 1000
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.load.{ep.name}.end")
                if event_bus:
                    with contextlib.suppress(Exception):
                        event_bus.emit(
                            "plugin.load.end",
                            resource=ep.name,
                            plugin_name=ep.name,
                            duration_ms=load_duration_ms,
                        )
                logger.warning(f"Plugin '{ep.name}' failed to load: {e}")
                continue

            # Validate metadata
            validation_errors = _validate_metadata(plugin, ep.name)
            if validation_errors:
                load_duration_ms = (time.perf_counter() - load_start) * 1000
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.load.{ep.name}.end")
                if event_bus:
                    with contextlib.suppress(Exception):
                        event_bus.emit(
                            "plugin.load.end",
                            resource=ep.name,
                            plugin_name=ep.name,
                            duration_ms=load_duration_ms,
                        )
                logger.warning(
                    f"Plugin entry point '{ep.name}' does not satisfy "
                    f"metadata protocol: {'; '.join(validation_errors)}"
                )
                continue

            plugin_name: str = plugin.name

            # Check for duplicate names
            if plugin_name in plugin_entry_point_names:
                load_duration_ms = (time.perf_counter() - load_start) * 1000
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.load.{ep.name}.end")
                if event_bus:
                    with contextlib.suppress(Exception):
                        event_bus.emit(
                            "plugin.load.end",
                            resource=plugin_name,
                            plugin_name=plugin_name,
                            duration_ms=load_duration_ms,
                        )
                logger.warning(
                    f"Duplicate plugin name '{plugin_name}' from entry "
                    f"point '{ep.name}' (already loaded from "
                    f"'{plugin_entry_point_names[plugin_name]}'). Skipping."
                )
                continue

            load_duration_ms = (time.perf_counter() - load_start) * 1000
            if perf_timeline:
                perf_timeline.mark(f"boot.plugins.load.{ep.name}.end")
            if event_bus:
                with contextlib.suppress(Exception):
                    event_bus.emit(
                        "plugin.load.end",
                        resource=plugin_name,
                        plugin_name=plugin_name,
                        version=plugin.version,
                        duration_ms=load_duration_ms,
                    )

            # Warn on slow plugin imports (>50ms is a code smell)
            plugin_load_budget_ms = 50.0
            if load_duration_ms > plugin_load_budget_ms:
                logger.warning(
                    f"Plugin '{plugin_name}' took {load_duration_ms:.0f}ms to load "
                    f"(budget: {plugin_load_budget_ms:.0f}ms). "
                    f"Consider deferring heavy imports to __call__() or first use."
                )

            loaded_objects.append(plugin)
            plugin_entry_point_names[plugin_name] = ep.name

        discovery_duration_ms = (time.perf_counter() - discovery_start) * 1000
        if perf_timeline:
            perf_timeline.mark("boot.plugins.discovery.end")
        if event_bus:
            with contextlib.suppress(Exception):
                event_bus.emit(
                    "plugin.discovery.end",
                    resource=self._group,
                    group=self._group,
                    count=len(loaded_objects),
                    duration_ms=discovery_duration_ms,
                )

        # --- Phase 1b: File-based discovery ---
        file_plugins = self._discover_from_files(app)

        # Merge: entry-point plugins take precedence on name collision
        loaded_names = {p.name for p in loaded_objects}
        for fp in file_plugins:
            if fp.name in loaded_names:
                logger.warning(
                    f"File plugin '{fp.name}' collides with entry-point "
                    f"plugin. Skipping."
                )
                continue
            # Skip disabled file-based plugins
            if disabled and fp.name.lower() in disabled:
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.skip.{fp.name}")
                continue
            loaded_objects.append(fp)
            plugin_entry_point_names[fp.name] = f"file:{fp.name}"

        # --- Phase 1c: Explicit plugins handed in by the caller ---
        for plugin in explicit or []:
            errors = _validate_metadata(plugin, repr(plugin))
            if errors:
                logger.warning(
                    f"Explicit plugin {plugin!r} does not satisfy the metadata "
                    f"protocol and was not loaded: {'; '.join(errors)}"
                )
                continue

            name: str = plugin.name
            if disabled and name.lower() in disabled:
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.skip.{name}")
                continue

            # An explicit object outranks anything discovery found under the
            # same name: replace in place so `depends_on` ordering still sees
            # exactly one plugin per name.
            existing = next(
                (i for i, p in enumerate(loaded_objects) if p.name == name), None
            )
            if existing is not None:
                logger.debug(
                    f"Explicit plugin '{name}' overrides the discovered plugin "
                    f"of the same name."
                )
                loaded_objects[existing] = plugin
            else:
                loaded_objects.append(plugin)
            plugin_entry_point_names[name] = f"explicit:{name}"

        if not loaded_objects:
            return

        # --- Phase 2: Topological sort by depends_on ---
        if perf_timeline:
            perf_timeline.mark("boot.plugins.sort.start")
        sorted_plugins = topological_sort(loaded_objects)
        if perf_timeline:
            perf_timeline.mark("boot.plugins.sort.end")

        # --- Phase 3: Invoke __call__ and resolve configs in order ---
        plugin_config_registry = self._get_config_registry(app)

        for plugin in sorted_plugins:
            plugin_name = plugin.name
            ep_name = plugin_entry_point_names[plugin_name]

            if plugin_name in self._loaded:
                continue  # Duplicate check

            # --- Plugin registration instrumentation ---
            if event_bus:
                with contextlib.suppress(Exception):
                    event_bus.emit(
                        "plugin.registration.start",
                        resource=plugin_name,
                        plugin_name=plugin_name,
                    )

            if perf_timeline:
                perf_timeline.mark(f"boot.plugins.register.{plugin_name}.start")
            registration_start = time.perf_counter()

            # Invoke the registration callable
            try:
                plugin(app)
            except Exception as e:
                registration_duration_ms = (
                    time.perf_counter() - registration_start
                ) * 1000
                if perf_timeline:
                    perf_timeline.mark(f"boot.plugins.register.{plugin_name}.end")
                if event_bus:
                    with contextlib.suppress(Exception):
                        event_bus.emit(
                            "plugin.registration.end",
                            resource=plugin_name,
                            plugin_name=plugin_name,
                            duration_ms=registration_duration_ms,
                        )
                logger.warning(
                    f"Plugin '{plugin_name}' (entry point '{ep_name}') "
                    f"raised an error during registration: {e}"
                )
                continue

            registration_duration_ms = (time.perf_counter() - registration_start) * 1000
            if perf_timeline:
                perf_timeline.mark(f"boot.plugins.register.{plugin_name}.end")
            if event_bus:
                with contextlib.suppress(Exception):
                    event_bus.emit(
                        "plugin.registration.end",
                        resource=plugin_name,
                        plugin_name=plugin_name,
                        duration_ms=registration_duration_ms,
                    )

            self._loaded[plugin_name] = ep_name
            self._loaded_instances.append(plugin)
            logger.debug(
                f"Successfully loaded plugin '{plugin_name}' (version {plugin.version})"
            )

            # Index plugin by name for get_plugin() lookups
            if hasattr(app, "_plugin_name_index"):
                app._plugin_name_index[plugin_name] = plugin

            # Config resolution (if plugin declares config requirements)
            if _has_config_declaration(plugin):
                self._resolve_and_register_config(plugin, app, plugin_config_registry)

    def _get_config_registry(self, app: Any) -> PluginConfigRegistry:
        """Get the PluginConfigRegistry from the app, or create a fallback.

        Args:
            app: The application instance.

        Returns:
            The PluginConfigRegistry instance.
        """
        if hasattr(app, "plugin_config_registry"):
            registry: PluginConfigRegistry = app.plugin_config_registry
            return registry
        # Fallback: create and attach a registry if the app doesn't have one yet
        registry = PluginConfigRegistry()
        app.plugin_config_registry = registry
        return registry

    def _resolve_and_register_config(
        self,
        plugin: Any,
        app: Any,
        registry: PluginConfigRegistry,
    ) -> None:
        """Resolve plugin config and register it, then notify the plugin.

        Args:
            plugin: Plugin with config_model and config_section attributes.
            app: The application instance with resolve_model method.
            registry: The PluginConfigRegistry to store resolved configs.

        Raises:
            ValueError: If config_section conflicts with another plugin.
        """
        section: str = plugin.config_section
        plugin_name: str = plugin.name

        # Check for config_section conflicts
        if registry.has(section):
            raise ValueError(
                f"Plugin config section '{section}' is already registered "
                f"by another plugin. Conflicting plugin: '{plugin_name}'"
            )

        # Resolve config through the Resolution_Chain
        config_instance = _resolve_plugin_config(plugin, app)

        # Register in the config registry
        registry.register(section, config_instance, plugin_name)

        logger.debug(
            f"Resolved config for plugin '{plugin_name}' (section '{section}')"
        )

        # Post-resolution callback
        if isinstance(plugin, PluginWithConfigResolved):
            plugin.on_config_resolved(config_instance)
            logger.debug(f"Invoked on_config_resolved for plugin '{plugin_name}'")

    def _resolve_plugin_directories(self, app: Any) -> list[str]:
        """Resolve plugin directories from config or convention.

        Resolution order:
        1. Try [tool.functualize] plugins_directories from app._resolution_chain
        2. Fall back to convention directory: .functualize/plugins/ in CWD
        3. Return empty list if neither is available

        Args:
            app: The application instance, potentially with a _resolution_chain.

        Returns:
            A list of absolute directory path strings for file plugin sources.
        """
        # Try config: [tool.functualize] plugins_directories
        if hasattr(app, "_resolution_chain"):
            try:
                resolved = app._resolution_chain.resolve(
                    "plugins_directories", "tool.functualize"
                )
                if resolved:
                    value = resolved.value
                    paths = value if isinstance(value, list) else [value]
                    return [str(Path(p).resolve()) for p in paths]
            except Exception:
                logger.debug("Could not resolve plugins_directories from config")

        # Convention fallback: .functualize/plugins/ in CWD
        convention = Path.cwd() / ".functualize" / "plugins"
        if convention.is_dir():
            return [str(convention)]

        return []

    def _discover_from_files(self, app: Any) -> list[Any]:
        """Scan plugin directories for *.py files and load as plugins.

        Scans each resolved plugin directory for top-level .py files (non-recursive),
        skipping files whose name starts with '_'. Files are sorted case-insensitively
        for deterministic ordering. Same-name duplicates within the scan are detected
        and only the first (alphabetically) is loaded.

        Args:
            app: The application instance.

        Returns:
            A list of valid plugin objects discovered from file-based plugins.
        """
        dirs = self._resolve_plugin_directories(app)
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
