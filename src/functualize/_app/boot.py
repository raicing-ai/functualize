"""Boot orchestration for FunctualizeApp.

Contains the composition root logic that wires together all peer layers:
- boot_static: Fast path for fully-explicit configuration (zero I/O)
- boot_standard: Full boot with filesystem discovery, plugin loading, config resolution
- build_resolution_chain: Classic config chain construction [CLI → Env → Files → Defaults]
- discover_config_path: Upward search for config files matching pattern
- init_observability: EventBus + MiddlewareStack initialization
- wire_children_to_pipeline: Discover, validate, and wire child projects into
  the resolution pipeline (single source of truth for child projects)
- resolve_and_register_jobs: Use resolution pipeline to discover and register jobs
- register_descriptors: Register job descriptors from providers

This module is the composition root — the only internal module allowed to
import from ALL peer layers (`_discovery`, `_config`, `_engine`, `_plugins`,
`_events`, `_primitives`, `_types`).

It must NOT import from `_cli/` or any public folder.
"""

from __future__ import annotations

import contextlib
import glob as glob_module
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection

from functualize._app.environment import detect_environment
from functualize._app.impl import build_resource_locator
from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._config.sources import CliSource, DefaultSource, EnvSource, FileSource
from functualize._discovery.pipeline import ResolutionPipeline
from functualize._discovery.providers import DirectoryScanProvider, StaticProvider
from functualize._events import HookEvent
from functualize._primitives.locator import ResourceLocator
from functualize._types.from_job import declared_dependency_names

logger = logging.getLogger(__name__)


def load_boot_dotenv(app: Any) -> str | None:
    """Load a .env file according to ``ConfigSources.dotenv``/``dotenv_path``.

    Runs at the very start of boot so the variables are visible to
    ``EnvSource`` when the resolution chain is built. Uses ``override=False``
    so values already present in the environment (including a .env loaded
    earlier by the CLI) win.

    Returns the loaded file's path, or None when nothing was loaded.
    """
    config_sources = app._config_sources
    if not config_sources.dotenv and config_sources.dotenv_path is None:
        return None

    from dotenv import load_dotenv

    if config_sources.dotenv_path is not None:
        explicit = Path(config_sources.dotenv_path)
        if explicit.is_file():
            load_dotenv(str(explicit), override=False)
            AppState.set("dotenv_path", str(explicit))
            return str(explicit)
        logger.warning("dotenv_path '%s' not found, skipping", explicit)
        return None

    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        load_dotenv(str(cwd_env), override=False)
        AppState.set("dotenv_path", str(cwd_env))
        return str(cwd_env)
    return None


def init_observability(app: Any) -> None:
    """Initialize observability subsystem (idempotent).

    Sets up EventBus, MiddlewareStack, and registers framework event catalog.

    Args:
        app: The FunctualizeApp instance being booted.
    """
    if app._observability_initialized:
        return

    from functualize._events.adapter import install_adapter
    from functualize._events.bus import EventBus as _EventBus
    from functualize._events.middleware_stack import (
        MiddlewareStack as _MiddlewareStack,
    )

    app._event_bus = _EventBus()
    app._middleware_stack = _MiddlewareStack()
    install_adapter(app._event_bus)

    from functualize._events._catalog_entries import (
        get_framework_event_catalog,
    )

    for metadata in get_framework_event_catalog():
        app._event_bus.register_event_metadata(metadata)

    app._observability_initialized = True


def boot_static(app: Any, perf_timeline: Any) -> None:
    """Static wiring fast path — zero filesystem I/O.

    Used when all configuration is explicitly provided. Skips:
    - Directory scanning / module importing
    - Config file discovery
    - Entry-point plugin discovery
    - Filesystem walks for resource location

    Dotenv loading is honored when ``ConfigSources.dotenv`` requests it
    (the only filesystem I/O on this path).

    Target: <5ms cold-start.

    Args:
        app: The FunctualizeApp instance being booted.
        perf_timeline: PerfTimeline for marking boot phases.
    """
    from functualize._config.registry import ProviderRegistry
    from functualize._discovery.registry import JobRegistry
    from functualize._engine.executor import JobExecutionEngine
    from functualize._engine.job_middleware import MiddlewareRegistry
    from functualize._events import HookRegistry
    from functualize._plugins.loader import PluginLoader
    from functualize._primitives.di import DIRegistry

    # Dotenv is the one I/O exception on this path: an explicit
    # ConfigSources(dotenv=True) (e.g. env_only()) is a direct request to
    # load .env before EnvSource resolves.
    load_boot_dotenv(app)

    # Core infrastructure (no filesystem)
    perf_timeline.mark("boot.core_infra.start")
    app._hook_registry = HookRegistry()
    app._di_registry = DIRegistry()

    from functualize._config.job_config import validate_job_config_types

    app.job_registry = JobRegistry(
        hook_registry=app._hook_registry,
        app=app,
        config_validator=validate_job_config_types,
    )
    # Empty PluginLoader (no entry-point group to scan)
    app.plugin_loader = PluginLoader("")

    # Gate resolution registry
    from functualize._gate._registry import GateRegistry as _GateRegistry
    from functualize._gate._resolver import ResolveResolver as _ResolveResolver
    from functualize._gate._strategy import GateStrategy as _GateStrategy
    from functualize._gate.prompt_strategy import (
        register_prompt_gate_strategy as _register_prompt_gate_strategy,
    )

    app._gate_registry = _GateRegistry()
    app._gate_registry.register_strategy(
        _GateStrategy.RESOLVE.value, _ResolveResolver()
    )

    # Observability subsystem (lazy-initialized)
    app._observability_initialized = False
    app._event_bus = None
    app._middleware_stack = None

    # Plugin system registries
    from functualize._engine.middleware import ExecutionMiddlewareChain
    from functualize._plugins.config import PluginConfigRegistry

    app.plugin_config_registry = PluginConfigRegistry()
    app._middleware_registry = MiddlewareRegistry()
    app._execution_middleware_chain = ExecutionMiddlewareChain()
    app._scope_registry = {}
    app._plugin_commands_list = []
    app._plugin_command_names = {}
    app._plugin_commands = app._plugin_command_names
    app._plugin_sub_groups = {}
    app._cli_command_cache = None
    app._surfaces = []
    app._surface_stack = []
    app._plugin_name_index = {}

    # The collector resolver is injected here rather than imported inside
    # `_gate`: `_gate` and `_engine` are peers, and this module is the one
    # place allowed to know both.
    from functualize._engine.surface_routing import active_collector

    _register_prompt_gate_strategy(app, collector_factory=active_collector)

    # Initialize observability early so EventBus is available for the engine
    init_observability(app)

    # Execution engine
    from functualize._config.chain import ResolutionChain as _ResolutionChain
    from functualize._config.job_config import (
        JobConfigView as _JobConfigView,
    )
    from functualize._config.job_config import (
        resolve_job_config as _resolve_job_config,
    )

    def _config_view_factory(*, section_prefix: str) -> Any:
        chain = getattr(app, "_resolution_chain", None) or _ResolutionChain([])
        return _JobConfigView(
            resolution_chain=chain,
            default_section_prefix=section_prefix,
        )

    app._execution_engine = JobExecutionEngine(
        di_registry=app._di_registry,
        hook_registry=app._hook_registry,
        middleware_chain=app._execution_middleware_chain,
        event_bus=app._event_bus,
        max_invoke_depth=app._execution_config.max_invoke_depth,
        plugin_config_registry=app.plugin_config_registry,
        gate_registry=app._gate_registry,
        config_view_factory=_config_view_factory,
        config_resolver=_resolve_job_config,
    )
    # Back-reference to the owning app so the engine can resolve the active
    # surface stack (Live binding via active_live_zone), the active prompt
    # collector, and job descriptors at execution time. Without this, `Live`
    # capabilities no-op even when a StdoutSurface is pushed (see
    # _engine/surface_routing.active_live_zone and runcontext `_app` reads).
    app._execution_engine._app = app
    # Keep the JobRegistry consistent when the engine materializes lazy entries
    app._execution_engine.add_registry_mirror(app.job_registry._registered_jobs)

    # Resolution pipeline with StaticProvider (zero I/O)
    app._resolution_pipeline = ResolutionPipeline()
    app._jobs_memo = None
    if app._job_sources.functions:
        static_provider = StaticProvider(app._job_sources.functions)
        app._resolution_pipeline.add_provider(static_provider)

    perf_timeline.mark("boot.core_infra.end")

    # Use explicit config resolution chain directly (no file discovery)
    app._resolution_chain = app._config_sources.config_resolution_chain
    app._config_path = ""
    # No file discovery here, so nothing consumes the environment — but
    # active_environment() must still answer on this path.
    app._environment, app._environment_source = detect_environment()
    # ResourceLocator not needed — no filesystem operations
    app._resource_locator = ResourceLocator()

    # Minimal ProviderRegistry (no discovery)
    app.config_registry = ProviderRegistry()

    # Observability already initialized during engine setup (idempotent)

    # Load explicit plugins (no entry-point discovery, no file discovery)
    explicit_plugins = app._plugin_sources.explicit_plugins or []
    disabled = set(app._plugin_sources.disabled or [])
    for plugin in explicit_plugins:
        plugin_name = getattr(plugin, "name", None)
        if plugin_name and plugin_name in disabled:
            continue
        try:
            plugin(app)
        except Exception as exc:
            plugin_name = plugin_name or repr(plugin)
            logger.warning(
                f"Explicit plugin '{plugin_name}' raised during registration: {exc}"
            )
            continue
        if plugin_name:
            app._plugin_name_index[plugin_name] = plugin
            app.plugin_loader._loaded_instances.append(plugin)

    # Child projects are not wired in static mode; keep the attribute present
    # so diagnostics/provenance can read an empty list uniformly.
    app.child_projects = []

    # Domain registry (empty in static mode — no entry-point scanning)
    from functualize._plugins.domain_registry import DomainRegistry

    app._domain_registry = DomainRegistry()

    # Register jobs from static provider
    all_descriptors = app._resolution_pipeline.resolve_all()
    if all_descriptors:
        register_descriptors(app, all_descriptors)

    # Validate plugin extension metadata against loaded plugins (§A.6)
    validate_plugin_ext_metadata(app)

    # Resolve @job(deps=...) refs and reject unknown refs / cycles (§A.4)
    validate_job_deps(app)

    # Resolve @workflow Step refs and reject nesting cycles (§A.7)
    validate_workflow_declarations(app)

    # Fire APP_READY hooks
    for hook in app._hook_registry._global_hooks.get(HookEvent.APP_READY, []):
        try:
            hook(app)
        except Exception as exc:
            hook_name = getattr(hook, "__name__", repr(hook))
            logger.warning(f"APP_READY hook {hook_name!r} raised: {exc}")

    # Validate DI bindings
    app._execution_engine.validate_di_bindings()

    # Freeze DI registry
    app._di_registry.freeze()
    with contextlib.suppress(Exception):
        app.event_bus.emit(
            "lifecycle.registry.frozen",
            resource="di_registry",
            app=app,
        )

    perf_timeline.mark("boot.total.end")


def boot_standard(app: Any, perf_timeline: Any) -> None:
    """Standard boot path — full filesystem discovery.

    Args:
        app: The FunctualizeApp instance being booted.
        perf_timeline: PerfTimeline for marking boot phases.
    """
    # 0. Dotenv first — variables must be in os.environ before EnvSource
    # joins the resolution chain.
    load_boot_dotenv(app)

    # Imports + resource locator (measures lazy import cost)
    perf_timeline.mark("boot.imports.start")

    from functualize._app.impl import build_cached_provider as _build_cached_provider
    from functualize._config.providers.ini import IniFormatProvider
    from functualize._config.providers.toml import TomlFormatProvider
    from functualize._config.registry import ProviderRegistry
    from functualize._discovery.registry import JobRegistry
    from functualize._engine.executor import JobExecutionEngine
    from functualize._engine.job_middleware import MiddlewareRegistry
    from functualize._events import HookRegistry
    from functualize._events.hooks import ConfigHookEvent
    from functualize._plugins.config import PluginConfigRegistry
    from functualize._plugins.loader import PluginLoader
    from functualize._primitives.di import DIRegistry

    # Wire ResourceLocator based on mode detection (standalone vs declared)
    app._resource_locator = build_resource_locator()

    perf_timeline.mark("boot.imports.end")

    # 1. Core infrastructure
    perf_timeline.mark("boot.core_infra.start")
    app._hook_registry = HookRegistry()
    app._di_registry = DIRegistry()

    from functualize._config.job_config import validate_job_config_types

    app.job_registry = JobRegistry(
        hook_registry=app._hook_registry,
        app=app,
        config_validator=validate_job_config_types,
    )
    app.plugin_loader = PluginLoader(app._plugin_sources.entry_point_group)

    # Gate resolution registry
    from functualize._gate._registry import GateRegistry as _GateRegistry
    from functualize._gate._resolver import ResolveResolver as _ResolveResolver
    from functualize._gate._strategy import GateStrategy as _GateStrategy
    from functualize._gate.prompt_strategy import (
        register_prompt_gate_strategy as _register_prompt_gate_strategy,
    )

    app._gate_registry = _GateRegistry()
    app._gate_registry.register_strategy(
        _GateStrategy.RESOLVE.value, _ResolveResolver()
    )

    # Observability subsystem (lazy-initialized)
    app._observability_initialized = False
    app._event_bus = None
    app._middleware_stack = None

    # Plugin system registries
    from functualize._engine.middleware import ExecutionMiddlewareChain

    app.plugin_config_registry = PluginConfigRegistry()
    app._middleware_registry = MiddlewareRegistry()
    app._execution_middleware_chain = ExecutionMiddlewareChain()
    app._scope_registry = {}
    app._plugin_commands_list = []
    app._plugin_command_names = {}
    app._plugin_commands = app._plugin_command_names
    app._plugin_sub_groups = {}
    app._cli_command_cache = None
    app._surfaces = []
    app._surface_stack = []
    app._plugin_name_index = {}

    # The collector resolver is injected here rather than imported inside
    # `_gate`: `_gate` and `_engine` are peers, and this module is the one
    # place allowed to know both.
    from functualize._engine.surface_routing import active_collector

    _register_prompt_gate_strategy(app, collector_factory=active_collector)

    # Initialize observability early so EventBus is available for the engine
    init_observability(app)
    app.event_bus.subscribe("interactivity.job.submit", app._on_job_submit_event)

    # Execution engine (single path for all adapters)
    from functualize._config.chain import ResolutionChain as _ResolutionChain2
    from functualize._config.job_config import (
        JobConfigView as _JobConfigView2,
    )
    from functualize._config.job_config import (
        resolve_job_config as _resolve_job_config2,
    )

    def _config_view_factory2(*, section_prefix: str) -> Any:
        chain = getattr(app, "_resolution_chain", None) or _ResolutionChain2([])
        return _JobConfigView2(
            resolution_chain=chain,
            default_section_prefix=section_prefix,
        )

    app._execution_engine = JobExecutionEngine(
        di_registry=app._di_registry,
        hook_registry=app._hook_registry,
        middleware_chain=app._execution_middleware_chain,
        event_bus=app._event_bus,
        max_invoke_depth=app._execution_config.max_invoke_depth,
        plugin_config_registry=app.plugin_config_registry,
        gate_registry=app._gate_registry,
        config_view_factory=_config_view_factory2,
        config_resolver=_resolve_job_config2,
    )
    # Back-reference to the owning app so the engine can resolve the active
    # surface stack (Live binding via active_live_zone), the active prompt
    # collector, and job descriptors at execution time. Without this, `Live`
    # capabilities no-op even when a StdoutSurface is pushed (see
    # _engine/surface_routing.active_live_zone and runcontext `_app` reads).
    app._execution_engine._app = app
    # Keep the JobRegistry consistent when the engine materializes lazy entries
    app._execution_engine.add_registry_mirror(app.job_registry._registered_jobs)

    # Resolution pipeline for Provider/Transform architecture
    app._resolution_pipeline = ResolutionPipeline()
    app._jobs_memo = None

    # Wire jobs_directories to pipeline as the appropriate provider.
    if app._jobs_directories:
        # Build the file-level and job-level filters from discovery_config
        pre_filter = None
        job_filter = None
        if getattr(app, "_discovery_config", None) is not None:
            from functualize._discovery.filter_factory import (
                build_job_filter_from_config,
                build_pre_filter_from_config,
            )

            # Use first jobs directory as base_dir for glob patterns
            base_dir = Path(app._jobs_directories[0])
            pre_filter = build_pre_filter_from_config(app._discovery_config, base_dir)
            job_filter = build_job_filter_from_config(app._discovery_config)

        if app._lazy_boot:
            app._cached_provider = _build_cached_provider(
                app._jobs_directories, pre_filter=pre_filter, job_filter=job_filter
            )
            app._resolution_pipeline.add_provider(app._cached_provider)
        else:
            app._resolution_pipeline.add_provider(
                DirectoryScanProvider(
                    app._jobs_directories,
                    pre_filter=pre_filter,
                    job_filter=job_filter,
                )
            )

    perf_timeline.mark("boot.core_infra.end")

    # 2. Initialize ProviderRegistry with built-in providers
    perf_timeline.mark("boot.provider_registry.start")
    app.config_registry = ProviderRegistry()
    app.config_registry.register_format_provider(TomlFormatProvider())
    app.config_registry.register_format_provider(IniFormatProvider())
    perf_timeline.mark("boot.provider_registry.end")

    # 3. Initialize observability BEFORE plugin loading
    perf_timeline.mark("boot.observability.start")
    # init_observability already called during engine setup (idempotent)
    perf_timeline.mark("boot.observability.end")

    # 4. Load plugins EARLY (so they can register providers)
    perf_timeline.mark("boot.plugins.start")
    disabled_plugins = set(
        name.lower() for name in (app._plugin_sources.disabled or [])
    )
    app.plugin_loader.load_all(
        app,
        event_bus=app._event_bus,
        perf_timeline=perf_timeline,
        disabled=disabled_plugins or None,
        # `boot_static` has always honoured these; this path used to drop them
        # silently, so `PluginSources(explicit_plugins=[p])` did nothing at all
        # unless jobs, config and plugins were *all* explicit (the condition
        # `is_fully_explicit` tests). Handing an object in is an instruction,
        # not a hint.
        explicit=app._plugin_sources.explicit_plugins or None,
    )
    perf_timeline.mark("boot.plugins.end")

    # 4b. Discover domain SDKs via functualize.domains entry points
    perf_timeline.mark("boot.domains.start")
    from functualize._plugins.domain_registry import boot_domain_registry

    app._domain_registry = boot_domain_registry(app)
    perf_timeline.mark("boot.domains.end")

    # 5. Discover dedicated config entry points
    perf_timeline.mark("boot.config_entry_points.start")
    app.config_registry.discover_entry_points()
    perf_timeline.mark("boot.config_entry_points.end")

    # 5b. Child projects are wired into the resolution pipeline later
    # (wire_children_to_pipeline), which also records app.child_projects.
    app.child_projects = []

    # 6. Build ResourceLocator + ResolutionChain
    perf_timeline.mark("boot.config_resolution.start")
    # Resolved on every path: the active environment is a property of the
    # process, not of whether this app happens to resolve config from files.
    app._environment, app._environment_source = detect_environment()
    if app._config_sources.config_resolution_chain is not None:
        # Explicit chain provided (e.g., from twelve_factor() or env_only())
        app._config_path = ""
        app._resolution_chain = app._config_sources.config_resolution_chain
    else:
        # Default path: discover config files and build the classic chain
        app._config_path = discover_config_path(
            app._config_file_regex,
            app.name,
            extensions=app.config_registry.list_format_providers().keys(),
        )
        AppState.set("config_directory", app._config_path)
        # A non-default file_pattern must reach FileSource, not just anchor
        # discovery; the dataclass class attribute holds the field default.
        default_file_regex = type(app._config_sources).file_pattern
        custom_regex = (
            app._config_file_regex
            if app._config_file_regex != default_file_regex
            else None
        )
        app._resolution_chain = build_resolution_chain(
            app._config_path,
            app.name,
            app.config_registry,
            file_regex=custom_regex,
            environment=app._environment,
            event_bus=app.event_bus,
        )
    perf_timeline.mark("boot.config_resolution.end")

    # 7. Fire AFTER_CONFIG_INIT hook
    app.hook_registry.invoke_config_event(
        ConfigHookEvent.AFTER_CONFIG_INIT, app._resolution_chain
    )

    # 7a. Wire resolution chain to execution engine
    app._execution_engine._resolution_chain = app._resolution_chain

    # 7b. Resolve max_invoke_depth from config
    _resolve_max_invoke_depth(app)

    # 7c. Discover, validate, and wire children into the resolution pipeline
    perf_timeline.mark("boot.children.start")
    wire_children_to_pipeline(app)
    perf_timeline.mark("boot.children.end")

    # 8. Discover and register jobs via resolution pipeline
    perf_timeline.mark("boot.job_registration.start")
    resolve_and_register_jobs(app)
    perf_timeline.mark("boot.job_registration.end")

    # 8b. Validate plugin extension metadata against loaded plugins (§A.6)
    validate_plugin_ext_metadata(app)

    # 8c. Resolve @job(deps=...) refs and reject unknown refs / cycles (§A.4)
    validate_job_deps(app)

    # 8d. Resolve @workflow Step refs and reject nesting cycles (§A.7)
    validate_workflow_declarations(app)

    # 8e. Validate no user name claims the reserved ``builtin`` subtree (§A.4)
    _validate_builtin_reservation(app)

    # 9. Fire APP_READY hook — all boot steps complete
    perf_timeline.mark("boot.app_ready_hooks.start")
    for hook in app._hook_registry._global_hooks.get(HookEvent.APP_READY, []):
        hook_name = getattr(hook, "__name__", None) or repr(hook)
        # Use the bound method's class name for perf marks
        if hasattr(hook, "__self__"):
            cls_name = type(hook.__self__).__name__
            phase_label = f"boot.app_ready.{cls_name}"
        else:
            phase_label = f"boot.app_ready.{hook_name}"
        perf_timeline.mark(f"{phase_label}.start")
        try:
            hook(app)
        except Exception as exc:
            logger.warning(f"APP_READY hook {hook_name!r} raised: {exc}")
        perf_timeline.mark(f"{phase_label}.end")
    perf_timeline.mark("boot.app_ready_hooks.end")

    # 9b. Validate DI bindings
    perf_timeline.mark("boot.di_validation.start")
    app._execution_engine.validate_di_bindings()
    perf_timeline.mark("boot.di_validation.end")

    # 10. Freeze DI registry and emit REGISTRY_FROZEN event
    perf_timeline.mark("boot.freeze.start")
    app._di_registry.freeze()
    with contextlib.suppress(Exception):
        app.event_bus.emit(
            "lifecycle.registry.frozen",
            resource="di_registry",
            app=app,
        )
    perf_timeline.mark("boot.freeze.end")

    perf_timeline.mark("boot.total.end")


def discover_config_path(
    config_file_regex: str,
    app_name: str,
    extensions: Collection[str] | None = None,
) -> str:
    """Discover config directory by searching upward from CWD.

    Searches parent directories for files matching the given regex pattern.
    Falls back to ~/.config/<app_name> if no config file is found.

    Args:
        config_file_regex: Regex pattern for config file name matching.
        app_name: Application name (for fallback path).
        extensions: File extensions (with leading dot) that a registered
            format provider can parse. When given, a candidate must also
            carry one of them. This is what keeps the anchor and the file
            reader describing the same set of files: the reader parses a
            discovered file only if a provider handles its extension, so an
            anchor that accepted extensions nobody can parse would anchor a
            directory on a file that then contributes nothing. Passing None
            skips the check, for callers with no registry to consult.

    Returns:
        Path to the directory containing config files.
    """
    regex = re.compile(config_file_regex)
    known = {ext.lower() for ext in extensions} if extensions is not None else None
    current = Path.cwd().resolve()

    while True:
        if current.is_dir():
            try:
                for entry in current.iterdir():
                    if not (entry.is_file() and regex.match(entry.name)):
                        continue
                    if known is not None and entry.suffix.lower() not in known:
                        continue
                    return str(current)
            except (PermissionError, OSError):
                pass
        if current == Path.home():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return str(Path.home() / ".config" / app_name)


def build_resolution_chain(
    config_path: str,
    app_name: str,
    config_registry: Any,
    *,
    file_regex: str | None = None,
    environment: str | None = None,
    event_bus: Any = None,
) -> ResolutionChain:
    """Build a ResolutionChain with source precedence: CLI → Env → Files → Defaults.

    This is the "classic" resolution order — identical to what the
    `classic()` preset produces when the boot path discovers files.

    Args:
        config_path: Path to the directory containing config files.
        app_name: Application name (for platform user config search).
        config_registry: ProviderRegistry for FileSource format resolution.
        file_regex: A custom ``ConfigSources.file_pattern`` regex, or None
            for the default. When set, FileSource switches to regex-filtered
            discovery so custom patterns actually match files; None keeps
            the fast ``config.*`` glob path. Callers pass None when the
            app's pattern equals the ConfigSources default.
        environment: The active environment name, selecting which
            ``config.<slot>.*`` overlay wins. None disables environment
            banding (every discovered file merges in discovery order).
        event_bus: Optional EventBus, so FileSource can report which
            overlay slots matched and which were inert.

    Returns:
        Configured ResolutionChain instance.
    """
    resolver = (
        ResourceLocator()
        .search_explicit(config_path)
        .search_upward(start=Path(config_path), stop=Path.home())
        .search_platform_user(app_name=app_name)
    )
    filename_regex = file_regex
    sources: list[CliSource | EnvSource | FileSource | DefaultSource] = [
        CliSource({}),
        EnvSource(),
        FileSource(
            resolver,
            config_registry.list_format_providers(),
            pattern="config.*",
            filename_regex=filename_regex,
            environment=environment,
            event_bus=event_bus,
            # Read exactly what discovery anchors on. `discover_config_path`
            # requires a `<slot>` segment, so accepting an unslotted
            # `config.toml` here would make that file count only when a
            # slotted sibling happened to anchor its directory.
            require_slot=True,
        ),
        DefaultSource({}),
    ]
    return ResolutionChain(sources)  # type: ignore[arg-type]


def wire_children_to_pipeline(app: Any) -> None:
    """Wire child projects into the resolution pipeline (single source of truth).

    For every child (from the ``children`` dict and the ``children_glob``
    pattern) this:

    1. Validates the child against the parent via ``HierarchyValidator`` —
       depth, cycles, version compatibility — collecting failures. In strict
       mode (``strict_hierarchy_validation`` = true) a failure aborts boot;
       otherwise a failed child is skipped with a warning.
    2. Adds a job provider under a ``NamespaceTransform(namespace)``. Under lazy
       boot the provider is the cache-first ``CachedDirectoryScanProvider`` (keyed
       to the child project root), so child jobs get the same zero-import warm
       boot as parent jobs; otherwise an eager ``DirectoryScanProvider``.
    3. Records a ``ChildProject`` on ``app.child_projects`` — the single source
       diagnostics (``show-info``) and completion provenance read from.

    This is the single source of truth for child projects — it replaced the
    former second discovery pass.

    Args:
        app: The FunctualizeApp instance.
    """
    from functualize._app.impl import build_cached_provider
    from functualize._discovery.hierarchy import ChildProject
    from functualize._discovery.hierarchy_validator import HierarchyValidator
    from functualize._discovery.transforms import NamespaceTransform
    from functualize._discovery.version_resolver import VersionResolver

    app.child_projects = []

    try:
        resolved = app._resolution_chain.resolve(
            "strict_hierarchy_validation", "general"
        )
        strict = str(resolved.value).lower() == "true"
    except Exception:
        strict = False

    parent_version = VersionResolver.resolve_running_version()
    context = HierarchyValidator.create_root_context(
        root_path=Path(app._config_path),
        parent_version=parent_version,
        strict=strict,
    )
    failures: list[Any] = []

    def _wire_one(namespace: str, child_path: Path) -> None:
        if not child_path.exists() or not child_path.is_dir():
            logger.warning(
                "Child project path does not exist for namespace '%s': %s",
                namespace,
                child_path,
            )
            return

        # Validate before wiring (version/depth/cycle checks).
        try:
            child_version = VersionResolver.resolve(child_path).minimum
            failure = HierarchyValidator.validate_child(
                child_namespace=namespace,
                child_path=child_path,
                context=context,
                child_version=child_version,
            )
        except Exception as exc:
            logger.warning(
                "Child project validation error for namespace '%s': %s",
                namespace,
                exc,
            )
            failure = None

        if failure is not None:
            failures.append(failure)
            logger.warning(
                "Skipping child project '%s': %s",
                namespace,
                getattr(failure, "reason", failure),
            )
            return

        jobs_dir = child_path / "jobs"
        scan_dir = str(jobs_dir) if jobs_dir.is_dir() else str(child_path)
        try:
            if app._lazy_boot:
                provider: Any = build_cached_provider(
                    [scan_dir], project_root=child_path
                )
            else:
                provider = DirectoryScanProvider(directories=[scan_dir])
            app._resolution_pipeline.add_provider(
                provider,
                transforms=[NamespaceTransform(namespace)],
            )
        except Exception as e:
            logger.warning(
                "Failed to create provider for child namespace '%s': %s",
                namespace,
                e,
            )
            return

        app.child_projects.append(
            ChildProject(
                name=namespace,
                path=str(child_path),
                jobs_directories=[scan_dir],
                config_path=str(child_path)
                if (child_path / "config").is_dir()
                else None,
            )
        )

    if app._children:
        for namespace, path in app._children.items():
            _wire_one(namespace, Path(path))

    if app._children_glob:
        base = Path(app._config_path)
        pattern = app._children_glob
        if not os.path.isabs(pattern):
            pattern = str(base / pattern)
        for match in sorted(glob_module.glob(pattern, recursive=True)):
            dir_path = Path(match)
            if dir_path.is_dir():
                _wire_one(dir_path.name, dir_path)

    if strict and failures:
        from functualize._discovery.hierarchy_validator import (
            HierarchyValidationError,
        )

        raise HierarchyValidationError(
            f"Hierarchy validation failed for {len(failures)} child "
            f"project(s) (strict mode enabled)",
            failures=failures,
        )


def resolve_and_register_jobs(app: Any) -> None:
    """Use the resolution pipeline to discover jobs and register them.

    Args:
        app: The FunctualizeApp instance.
    """
    if app._jobs_directories:
        if app._lazy_boot:
            _register_jobs_lazy(app)
        else:
            app.job_registry.scan_and_register_headless(app._jobs_directories)
            # Sync registered jobs from JobRegistry to execution engine
            _sync_registry_to_engine(app)

    # Pipeline-based registration for non-directory providers
    if app._resolution_pipeline.provider_count > (1 if app._jobs_directories else 0):
        try:
            all_descriptors = app._resolution_pipeline.resolve_all()
        except ValueError as e:
            logger.warning("Resolution pipeline error: %s", e)
            return

        already_registered = set(app.job_registry._registered_jobs.keys())
        new_descriptors = [
            d for d in all_descriptors if d.name not in already_registered
        ]

        if new_descriptors:
            register_descriptors(app, new_descriptors)


def _sync_registry_to_engine(app: Any) -> None:
    """Sync jobs registered in JobRegistry to the execution engine.

    After scan_and_register_headless populates the JobRegistry, this
    ensures those jobs are also available in the execution engine for
    rc.invoke() lookups.
    """
    for name, entry in app.job_registry._registered_jobs.items():
        if name not in app._execution_engine._registered_jobs:
            app._execution_engine.register_job(entry)


def adopt_descriptor_declaration(descriptor: Any, live_fn: Any) -> None:
    """Make ``descriptor.declaration`` reach the executor, not just the graph.

    Registration reads ``deps`` off the *descriptor* (see ``dependencies``
    below), but the executor reads ``cache``/``guards``/``exec`` off the
    *function* (``function.__functualize_job__``, five sites in
    ``_engine/executor.py``). For a scanned job the two cannot disagree — the
    provider derives the declaration from the decorated function — so the split
    is invisible until a descriptor is built by hand, which in practice means a
    ``JobProvider``. There, ``declaration=JobDeclaration(deps=...)`` worked
    while ``declaration=JobDeclaration(cache=...)`` silently did nothing.

    Partial honouring is the worst of the three options: the field visibly
    works, so the ignored half reads as a runtime bug rather than an
    unsupported input. This closes it by giving the function the declaration
    the decorator would have set, so the descriptor is uniformly authoritative
    and all five executor sites are reached without a lookup on the hot path.

    Fills in only — a function that already carries a declaration keeps it, so
    every scanned job is untouched.
    """
    declaration = getattr(descriptor, "declaration", None)
    if declaration is None:
        return
    if getattr(live_fn, "__functualize_job__", None) is not None:
        return
    try:
        live_fn.__functualize_job__ = declaration
    except (AttributeError, TypeError) as exc:
        # A C function or a slotted callable takes no attributes. Say so:
        # falling back to silence is the bug this function exists to remove.
        logger.warning(
            "Job %r declares cache/guards/exec on its descriptor, but the "
            "declaration could not be attached to %r (%s). Those settings will "
            "not take effect — decorate the function with @job(...) instead.",
            getattr(descriptor, "name", "<unknown>"),
            live_fn,
            exc,
        )


def register_descriptors(app: Any, descriptors: list[Any]) -> None:
    """Register job descriptors in the registry for programmatic access.

    Registers in both the job registry (for discovery/listing) and the
    execution engine (for rc.invoke() lookups).

    Descriptors that carry a live function (cold-boot scan, static
    providers) register it directly with a detected config_class —
    identical behavior and boot-time DI validation to the eager path.
    Cache-only descriptors (warm boot, function=None) register a
    LazyJobFunction proxy: NO module import happens here; the engine
    materializes the entry on first use.

    Args:
        app: The FunctualizeApp instance.
        descriptors: List of JobDescriptor instances to register.
    """
    from functualize._discovery.lazy_wrapper import (
        LazyJobFunction,
        _detect_config_class,
    )
    from functualize._engine.result import RegisteredJob

    for descriptor in descriptors:
        live_fn = getattr(descriptor, "function", None)
        if live_fn is not None and callable(live_fn):
            fn: Any = live_fn
            adopt_descriptor_declaration(descriptor, live_fn)
            config_class = _detect_config_class(live_fn)
        else:
            fn = LazyJobFunction(descriptor)
            config_class = None
        entry = RegisteredJob(
            name=descriptor.name,
            function=fn,
            config_class=config_class,
            group=descriptor.group,
            module_path=descriptor.module_path,
            # From the descriptor, which survives a warm boot; `live_fn` is
            # None there, so reading deps off the function would lose them.
            dependencies=declared_dependency_names(
                getattr(descriptor, "declaration", None),
                live_fn,
                getattr(descriptor, "from_job_deps", ()),
            ),
        )
        app.job_registry._registered_jobs[descriptor.name] = entry
        app.job_registry._job_descriptors.append(descriptor)

        # Also register in execution engine for rc.invoke() lookups
        app._execution_engine.register_job(entry)

        group_key = descriptor.group if descriptor.group else "__top__"
        registry_key = f"{group_key}::{descriptor.name}"
        app.job_registry._registered_commands[registry_key] = (
            descriptor.module_path or ""
        )


def validate_job_deps(app: Any) -> None:
    """Resolve every job's dependency refs and reject unknown refs and cycles.

    Delegates to :class:`~functualize._engine.job_graph.JobGraph`, which is the
    same object the executor consults, so a graph that validates here cannot
    fail differently at run time. It used to be a second implementation with a
    second resolver, and the two disagreed: a callable reference to a *grouped*
    job validated as ``build.compile_it`` and executed as bare ``compile_it``.

    This is now a convenience entry point rather than the only guard. Building
    the graph validates it, and nothing can run a dependency without building
    it — so jobs registered through `register_dynamic_job` or `register_module`,
    which never reach this function, are checked all the same.
    """
    app._execution_engine.job_graph.validate()


def _resolve_plugins_strict(app: Any) -> bool:
    """Resolve the ``plugins.strict`` boolean from config (default False)."""
    try:
        resolved = app._resolution_chain.resolve("strict", "plugins")
    except Exception:
        return False
    value = resolved.value
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def validate_plugin_ext_metadata(app: Any) -> None:
    """Flag ``__functualize_ext_*`` job metadata with no loaded owning plugin (§A.6).

    A loaded plugin "owns" namespace ``N`` if its ``name`` equals ``N`` or ``N``
    appears in its optional ``functualize_ext_namespaces`` attribute. Orphaned
    metadata warns by default and raises ``OrphanedPluginMetadataError`` when
    ``plugins.strict`` is enabled.
    """
    from functualize._types.errors import OrphanedPluginMetadataError

    owned: set[str] = set()
    for plugin in app.plugin_loader.loaded_instances:
        name = getattr(plugin, "name", None)
        if isinstance(name, str) and name:
            owned.add(name)
        for ns in getattr(plugin, "functualize_ext_namespaces", ()) or ():
            if isinstance(ns, str) and ns:
                owned.add(ns)

    orphans: list[tuple[str, str]] = []
    for descriptor in app.job_registry._job_descriptors:
        metadata = getattr(descriptor, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        plugins_meta = metadata.get("plugins")
        if not isinstance(plugins_meta, dict):
            continue
        for namespace in plugins_meta:
            if namespace not in owned:
                orphans.append((descriptor.name, namespace))

    if not orphans:
        return

    if _resolve_plugins_strict(app):
        raise OrphanedPluginMetadataError(orphans)
    for job_name, namespace in orphans:
        logger.warning(
            "Job '%s' carries plugin metadata '__functualize_ext_%s__' but no "
            "loaded plugin owns namespace '%s'. Enable the plugin or remove the "
            "decorator; set plugins.strict = true to make this an error.",
            job_name,
            namespace,
            namespace,
        )


def _resolve_max_invoke_depth(app: Any) -> None:
    """Resolve max_invoke_depth from config and update the engine.

    Args:
        app: The FunctualizeApp instance.
    """
    try:
        resolved = app._resolution_chain.resolve("max_invoke_depth", "general")
        depth = int(resolved.value)
        if depth > 0:
            app._execution_engine._max_invoke_depth = depth
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    except Exception as exc:
        # Resolution chain may raise MissingKeyError from functualize._config.errors
        if "MissingKeyError" in type(exc).__name__ or "not found" in str(exc).lower():
            pass
        else:
            raise


def _validate_builtin_reservation(app: Any) -> None:
    """Reject user names claiming a reserved part of the command tree.

    Two reservations, one pass, because both fail the same way — the name is
    unreachable, and the run should not get as far as dispatch before that is
    discovered:

    - **The ``builtin`` subtree** is first-party only.
    - **Names starting with a shell sigil** (``!``, ``?``) can never be typed
      into the shell's input bar as themselves: the bar dispatches on the first
      character, so ``!deploy`` selects the shell mode and runs ``deploy`` as an
      external program. Reserving them at boot beats a job that exists on the
      CLI and is invisible in the shell.

    Covers job names, job groups, **and plugin commands/namespaces** — the last
    of these was previously only claimed by this docstring, not checked.

    Raises:
        ValueError: a registered job name, job group, plugin command or plugin
            namespace claims a reserved name.
    """
    from functualize._types.naming import BUILTIN_SEGMENT, RESERVED_SIGILS

    violations: list[str] = []

    def _check(label: str, value: str | None) -> None:
        if not value:
            return
        if value == BUILTIN_SEGMENT or value.startswith(BUILTIN_SEGMENT + "."):
            violations.append(f"  {label} claims the reserved name {BUILTIN_SEGMENT!r}")
        # Any segment of a dotted name, not just the first: `ops.!x` is as
        # untypeable as `!x` once the shell drills into `ops`.
        for segment in value.split("."):
            if segment and segment[0] in RESERVED_SIGILS:
                violations.append(
                    f"  {label} starts with the reserved shell sigil {segment[0]!r}"
                )

    for name, entry in getattr(app.job_registry, "_registered_jobs", {}).items():
        _check(f"job name {name!r}", name)
        group = getattr(entry, "group", None)
        if group:
            _check(f"group {group!r} of job {name!r}", group)

    for cmd in getattr(app, "_plugin_commands_list", []):
        cmd_name = getattr(cmd, "name", None)
        namespace = getattr(cmd, "namespace", None)
        _check(f"plugin command {cmd_name!r}", cmd_name)
        if namespace:
            _check(f"namespace {namespace!r} of plugin command {cmd_name!r}", namespace)

    if violations:
        raise ValueError(
            f"Reserved name(s) claimed by {len(violations)} registered name(s):\n"
            + "\n".join(violations)
            + "\n\nThe 'builtin' subtree is first-party only, and names starting "
            f"with {', '.join(repr(s) for s in sorted(RESERVED_SIGILS))} are "
            "reserved for the shell's input modes — rename the job, group, "
            "command, or namespace."
        )


def _register_jobs_lazy(app: Any) -> None:
    """Register jobs from the cached provider (cold and warm boot path).

    The CachedDirectoryScanProvider built during boot_standard handles both
    cases: cold boot imports every module and persists the cache; warm boot
    serves validated descriptors without imports, re-importing only stale
    modules.

    Args:
        app: The FunctualizeApp instance.
    """
    provider = getattr(app, "_cached_provider", None)
    if provider is None:
        # No cached provider was wired (defensive) — fall back to eager scan
        app.job_registry.scan_and_register_headless(app._jobs_directories)
        _sync_registry_to_engine(app)
        return

    descriptors = list(provider.list_jobs())
    register_descriptors(app, descriptors)


# Re-exported: the implementation moved to `_engine` so the executor can run
# it before a walk without `_engine` importing `_app`. Boot still validates
# eagerly, which is what turns a bad declaration into a startup error rather
# than a first-run one.
from functualize._engine.workflow_validation import (  # noqa: E402
    validate_workflow_declarations,
)

__all__ = [*globals().get("__all__", []), "validate_workflow_declarations"]
