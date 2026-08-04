"""FunctualizeApp internal method implementations (heavy lifting).

Contains utility functions delegated from the FunctualizeApp facade:
- build_resource_locator: Mode detection and ResourceLocator construction
- find_functualize_dir: Upward search for .functualize/ directory
- build_cached_provider: CachedDirectoryScanProvider with appropriate cache storage
- shutdown_plugins: Graceful plugin shutdown with timeout
- get_cache_stats: Gather CacheInfo from the resolution pipeline
- register_plugin_command: Plugin command validation and registration
- register_dynamic_job: Runtime job registration
- create_workflow_scope / get_workflow_scope: WorkflowScope management
- Decorator factories: Hook and middleware decorators
- resolve_model: Configuration model resolution
- on_job_submit_event: Interactivity event handler

This module is part of the composition root (`_app/`) and imports from all
peer layers as needed. It must NOT import from `_cli/` or any public folder.
"""

from __future__ import annotations

import concurrent.futures
import inspect
import logging
import re
from collections.abc import Callable, Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives import compute_project_id
from functualize._primitives.cache_format import find_functualize_dir
from functualize._primitives.locator import ResourceLocator

if TYPE_CHECKING:
    from functualize._types.descriptors import CacheInfo
    from functualize.app.config import ConfigSources, JobSources, PluginSources

logger = logging.getLogger(__name__)


def build_resource_locator(cwd: Path | None = None) -> ResourceLocator:
    """Build a ResourceLocator based on mode detection.

    - Standalone mode (no .functualize/ dir): write to XDG platform cache
    - Declared-project mode (.functualize/ exists): write to .functualize/

    Args:
        cwd: Current working directory. If None, uses Path.cwd().

    Returns:
        Configured ResourceLocator instance.
    """
    if cwd is None:
        cwd = Path.cwd().resolve()

    functualize_dir = find_functualize_dir(cwd)

    if functualize_dir is not None:
        # Declared-project mode: read/write to .functualize/
        return (
            ResourceLocator()
            .search_explicit(str(functualize_dir))
            .write_to_explicit(str(functualize_dir))
        )
    else:
        # Standalone mode: read from CWD + upward; write to XDG cache
        project_id = compute_project_id(str(cwd))
        return (
            ResourceLocator()
            .search_explicit(str(cwd))
            .search_upward(start=cwd)
            .search_platform_cache(project_id)
            .write_to_platform_cache(project_id)
        )


def build_cached_provider(
    directories: list[str],
    project_root: Path | None = None,
    pre_filter: Any = None,
    job_filter: Any = None,
) -> Any:
    """Build a CachedDirectoryScanProvider with appropriate cache storage.

    Determines cache location based on project mode (declared vs standalone)
    and returns a provider that persists scan results for warm boot. The
    location must stay in sync with cache_format.resolve_cache_path, which
    non-booting readers (CLI fast path, `func cache` commands) rely on.

    Args:
        directories: List of directory paths to scan for jobs.
        project_root: Starting point for mode detection. Defaults to cwd.
            In declared-project mode the effective project root becomes the
            parent of the discovered .functualize/ directory, so cache
            location and deps-hash keying don't depend on the invocation
            subdirectory. In standalone mode this path itself is the root.
        pre_filter: Optional ModulePreFilter to filter modules before import.
        job_filter: Optional JobFilter applied per descriptor on cache read
            (the ``require_job_*`` settings).

    Returns:
        CachedDirectoryScanProvider instance.
    """
    from functualize._discovery.cached_provider import CachedDirectoryScanProvider

    if project_root is None:
        project_root = Path.cwd().resolve()
    else:
        project_root = Path(project_root).resolve()

    functualize_dir = find_functualize_dir(project_root)

    if functualize_dir is not None:
        locator = (
            ResourceLocator()
            .search_explicit(str(functualize_dir))
            .write_to_explicit(str(functualize_dir))
        )
        project_root = functualize_dir.parent
    else:
        project_id = compute_project_id(str(project_root))
        locator = (
            ResourceLocator()
            .search_platform_cache(project_id)
            .write_to_platform_cache(project_id)
        )

    return CachedDirectoryScanProvider(
        directories=directories,
        locator=locator,
        pre_filter=pre_filter,
        job_filter=job_filter,
        project_root=project_root,
    )


def shutdown_plugins(plugin_loader: Any, app: Any) -> None:
    """Invoke on_shutdown(app) on all PluginWithShutdown plugins.

    Iterates plugins in reverse registration order, giving each
    a 5-second timeout for graceful shutdown.

    Args:
        plugin_loader: The PluginLoader instance containing loaded plugins.
        app: The FunctualizeApp instance passed to on_shutdown.
    """
    from functualize._types import PluginWithShutdown

    plugins_with_shutdown = [
        p for p in plugin_loader.loaded_instances if isinstance(p, PluginWithShutdown)
    ]

    for plugin in reversed(plugins_with_shutdown):
        plugin_name = getattr(plugin, "name", repr(plugin))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(plugin.on_shutdown, app)
                future.result(timeout=5.0)
        except concurrent.futures.TimeoutError:
            logger.error(
                f"Plugin '{plugin_name}' shutdown exceeded 5s timeout, abandoned"
            )
        except Exception as exc:
            logger.error(f"Plugin '{plugin_name}' on_shutdown raised: {exc}")


def get_cache_stats(app: Any) -> CacheInfo:
    """Gather cache statistics from the resolution pipeline.

    Inspects providers for CachedDirectoryScanProvider instances
    and aggregates their cache metrics.

    Args:
        app: The FunctualizeApp instance.

    Returns:
        CacheInfo with entry_count, stale_count, file_size_bytes, and cache_path.
    """
    from functualize._discovery.cached_provider import CachedDirectoryScanProvider
    from functualize._types.descriptors import CacheInfo

    # Search providers in the resolution pipeline for a cache-backed one
    for provider_entry in app._resolution_pipeline._providers:
        provider = provider_entry.provider
        if isinstance(provider, CachedDirectoryScanProvider):
            return provider.stats()

    return CacheInfo(
        entry_count=0,
        stale_count=0,
        file_size_bytes=0,
        cache_path=None,
    )


# ─── Static Wiring Detection ────────────────────────────────────────────


def is_fully_explicit(
    job_sources: JobSources,
    config_sources: ConfigSources,
    plugin_sources: PluginSources,
) -> bool:
    """Detect whether all sources are explicitly provided (static wiring).

    Args:
        job_sources: Job source configuration.
        config_sources: Config source configuration.
        plugin_sources: Plugin source configuration.

    Returns:
        True if all sources are fully explicit (no filesystem I/O needed).
    """
    has_explicit_jobs = job_sources.functions is not None
    no_directories = not (job_sources.directories or [])
    no_children = job_sources.children is None and job_sources.children_glob is None
    has_explicit_config = config_sources.config_resolution_chain is not None
    has_explicit_plugins = (
        plugin_sources.entry_point_group == ""
        and plugin_sources.explicit_plugins is not None
    )

    return (
        has_explicit_jobs
        and no_directories
        and no_children
        and has_explicit_config
        and has_explicit_plugins
    )


# ─── Plugin Command Registration ────────────────────────────────────────


def register_plugin_command(
    app: Any,
    name: str,
    callback: Callable[..., Any],
    help_text: str = "",
    namespace: str | None = None,
) -> None:
    """Validate and register a plugin command.

    Args:
        app: The FunctualizeApp instance.
        name: Command name (lowercase alphanumeric + hyphens).
        callback: Callable to invoke when the command is executed.
        help_text: Help text (max 256 chars).
        namespace: Optional flat CLI namespace to mount the command under.

    Raises:
        ValueError: If name, callback, or help_text is invalid, or if duplicate.
    """
    from functualize._app.models import PluginCommand
    from functualize._types.naming import BUILTIN_SEGMENT, RESERVED_SIGILS

    if namespace is not None and (
        namespace == BUILTIN_SEGMENT or namespace.startswith(BUILTIN_SEGMENT + ".")
    ):
        raise ValueError(
            f"Plugin namespace {namespace!r} claims the reserved top-level "
            f"name {BUILTIN_SEGMENT!r}. That subtree is first-party only — "
            f"rename the namespace."
        )

    # The command `name` below is already constrained to `^[a-z][a-z0-9-]{0,63}$`,
    # so a sigil can never reach it. The namespace had no such pattern — only
    # the `builtin` check above — so this is the one place a plugin could claim
    # an unreachable shell name.
    if namespace and namespace[0] in RESERVED_SIGILS:
        raise ValueError(
            f"Plugin namespace {namespace!r} starts with the reserved shell "
            f"sigil {namespace[0]!r}. The shell's input bar dispatches on the "
            f"first character, so this namespace could never be typed — "
            f"rename it."
        )

    if not isinstance(name, str) or not re.match(r"^[a-z][a-z0-9-]{0,63}$", name):
        raise ValueError(
            f"Invalid command name '{name}': must match pattern "
            "'^[a-z][a-z0-9-]{{0,63}}$' (1-64 chars, lowercase alphanumeric "
            "and hyphens, must start with a letter)"
        )
    if not callable(callback):
        raise ValueError(
            f"Invalid callback for command '{name}': callback must be callable"
        )
    if len(help_text) > 256:
        raise ValueError(
            f"Invalid help_text for command '{name}': "
            f"must be at most 256 characters (got {len(help_text)})"
        )

    if namespace not in app._plugin_command_names:
        app._plugin_command_names[namespace] = set()

    if name in app._plugin_command_names[namespace]:
        where = f"namespace '{namespace}'" if namespace is not None else "top level"
        raise ValueError(
            f"Duplicate command name '{name}' in {where}: "
            "a command with this name is already registered"
        )

    cmd = PluginCommand(
        name=name, callback=callback, help_text=help_text, namespace=namespace
    )
    app._plugin_commands_list.append(cmd)
    app._plugin_command_names[namespace].add(name)

    if namespace is not None and namespace not in app._plugin_sub_groups:
        app._plugin_sub_groups[namespace] = None


# ─── Decorator Factories ────────────────────────────────────────────────


def make_on_job_failure_decorator(app: Any) -> Callable[..., Any]:
    """Create AFTER_FAILURE hook decorator."""
    from functualize._app.decorators import _make_hook_decorator
    from functualize._events.hooks import HookEvent

    return _make_hook_decorator(
        register_global=lambda fn: app._hook_registry.register_global(
            HookEvent.AFTER_FAILURE, fn
        ),
        register_for_job=lambda name, fn: app._hook_registry.register_for_job(
            name, HookEvent.AFTER_FAILURE, fn
        ),
        event_name="on_job_failure",
    )


def make_on_job_success_decorator(app: Any) -> Callable[..., Any]:
    """Create AFTER_SUCCESS hook decorator."""
    from functualize._app.decorators import _make_hook_decorator
    from functualize._events.hooks import HookEvent

    return _make_hook_decorator(
        register_global=lambda fn: app._hook_registry.register_global(
            HookEvent.AFTER_SUCCESS, fn
        ),
        register_for_job=lambda name, fn: app._hook_registry.register_for_job(
            name, HookEvent.AFTER_SUCCESS, fn
        ),
        event_name="on_job_success",
    )


def make_on_job_teardown_decorator(app: Any) -> Callable[..., Any]:
    """Create ON_TEARDOWN hook decorator."""
    from functualize._app.decorators import _make_hook_decorator
    from functualize._events.hooks import HookEvent

    return _make_hook_decorator(
        register_global=lambda fn: app._hook_registry.register_global(
            HookEvent.ON_TEARDOWN, fn
        ),
        register_for_job=lambda name, fn: app._hook_registry.register_for_job(
            name, HookEvent.ON_TEARDOWN, fn
        ),
        event_name="on_job_teardown",
    )


def make_before_job_decorator(app: Any) -> Callable[..., Any]:
    """Create BEFORE_JOB hook decorator with parameter validation."""
    from functualize._app.decorators import _make_hook_decorator
    from functualize._events.hooks import HookEvent

    def _register_global_with_validation(fn: Callable[..., Any]) -> None:
        sig = inspect.signature(fn)
        if len(sig.parameters) < 1:
            raise TypeError(
                f"before_job hook {fn.__name__!r} must accept at least "
                f"one positional parameter (RunContext)"
            )
        app._hook_registry.register_global(HookEvent.BEFORE_JOB, fn)

    def _register_for_job_with_validation(name: str, fn: Callable[..., Any]) -> None:
        sig = inspect.signature(fn)
        if len(sig.parameters) < 1:
            raise TypeError(
                f"before_job hook {fn.__name__!r} must accept at least "
                f"one positional parameter (RunContext)"
            )
        app._hook_registry.register_for_job(name, HookEvent.BEFORE_JOB, fn)

    return _make_hook_decorator(
        register_global=_register_global_with_validation,
        register_for_job=_register_for_job_with_validation,
        event_name="before_job",
    )


def make_pre_execute_decorator(app: Any) -> Callable[..., Any]:
    """Create PRE_EXECUTE hook decorator."""
    from functualize._app.decorators import _make_hook_decorator
    from functualize._events.hooks import HookEvent

    return _make_hook_decorator(
        register_global=lambda fn: app._hook_registry.register_global(
            HookEvent.PRE_EXECUTE, fn
        ),
        register_for_job=lambda name, fn: app._hook_registry.register_for_job(
            name, HookEvent.PRE_EXECUTE, fn
        ),
        event_name="pre_execute",
    )


def make_on_phase_failure_decorator(app: Any) -> Callable[..., Any]:
    """Create ON_PHASE_FAILURE hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    return _make_global_only_decorator(
        lambda fn: app._hook_registry.register_global(HookEvent.ON_PHASE_FAILURE, fn)
    )


def make_on_phase_complete_decorator(app: Any) -> Callable[..., Any]:
    """Create ON_PHASE_COMPLETE hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    return _make_global_only_decorator(
        lambda fn: app._hook_registry.register_global(HookEvent.ON_PHASE_COMPLETE, fn)
    )


def make_on_phase_start_decorator(app: Any) -> Callable[..., Any]:
    """Create ON_PHASE_START hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    return _make_global_only_decorator(
        lambda fn: app._hook_registry.register_global(HookEvent.ON_PHASE_START, fn)
    )


def make_on_invoke_failure_decorator(app: Any) -> Callable[..., Any]:
    """Create INVOKE_FAILURE hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    return _make_global_only_decorator(
        lambda fn: app._hook_registry.register_global(HookEvent.INVOKE_FAILURE, fn)
    )


def make_on_invoke_start_decorator(app: Any) -> Callable[..., Any]:
    """Create INVOKE_START hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    return _make_global_only_decorator(
        lambda fn: app._hook_registry.register_global(HookEvent.INVOKE_START, fn)
    )


def make_on_invoke_end_decorator(app: Any) -> Callable[..., Any]:
    """Create INVOKE_END hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    return _make_global_only_decorator(
        lambda fn: app._hook_registry.register_global(HookEvent.INVOKE_END, fn)
    )


def make_on_ready_decorator(app: Any) -> Callable[..., Any]:
    """Create APP_READY hook decorator (global only)."""
    from functualize._app.decorators import _make_global_only_decorator
    from functualize._events.hooks import HookEvent

    def _register_with_validation(fn: Callable[..., Any]) -> None:
        if not callable(fn):
            raise TypeError(f"on_ready expects a callable, got {type(fn).__name__}")
        app._hook_registry.register_global(HookEvent.APP_READY, fn)

    return _make_global_only_decorator(_register_with_validation)


def make_on_event_decorator(app: Any, pattern: str) -> Callable[..., Any]:
    """Create event subscription decorator with pattern validation.

    Args:
        app: The FunctualizeApp instance.
        pattern: Event pattern (exact dotted name, prefix wildcard, or '*').

    Returns:
        Decorator function.

    Raises:
        ValueError: If pattern is invalid.
    """
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(
            f"Invalid event pattern: {pattern!r}. Not a valid regex: {exc}"
        ) from exc

    valid_exact = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    valid_prefix = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\.\*$")

    if (
        pattern != "*"
        and not valid_exact.match(pattern)
        and not valid_prefix.match(pattern)
    ):
        raise ValueError(
            f"Invalid event pattern: {pattern!r}. Must be an exact dotted name "
            f"(e.g., 'deploy.notify.start'), prefix wildcard (e.g., 'deploy.*'), "
            f"or global wildcard ('*')"
        )

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        app.event_bus.subscribe(pattern, fn)
        return fn

    return decorator


def make_run_middleware_decorator(app: Any) -> Callable[..., Any]:
    """Create RunContext middleware decorator."""
    from functualize._app.decorators import _make_middleware_decorator

    return _make_middleware_decorator(
        lambda fn, priority: app._middleware_registry.register(fn, priority)
    )


# ─── RunContext Middleware Registration ──────────────────────────────────


def register_run_middleware(
    app: Any,
    middleware: Callable[[Any], Generator[None]],
    priority: int = 0,
) -> None:
    """Register RunContext middleware for job execution wrapping.

    Args:
        app: The FunctualizeApp instance.
        middleware: Callable accepting RunContext, returning Generator.
        priority: Middleware priority (higher = runs first).

    Raises:
        TypeError: If middleware is not callable.
    """
    if not callable(middleware):
        raise TypeError(
            f"Expected a callable middleware, got {type(middleware).__name__}. "
            f"RunContextMiddleware must be a callable that accepts a RunContext "
            f"and returns a Generator."
        )
    app._middleware_registry.register(middleware, priority)
    # Also register in the execution middleware chain so the engine applies it
    app._execution_middleware_chain.register(middleware, priority)


# ─── Workflow Scope Management ───────────────────────────────────────────


def create_workflow_scope(
    app: Any,
    scope_id: str,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Create a new WorkflowScope with the given identifier.

    Args:
        app: The FunctualizeApp instance.
        scope_id: Unique scope identifier.
        metadata: Optional metadata for the scope.

    Returns:
        WorkflowScope instance.

    Raises:
        ValueError: If scope_id already exists.
    """
    from functualize._engine.capabilities.workflow_scope import WorkflowScope
    from functualize._events.hooks import HookEvent

    if scope_id in app._scope_registry:
        raise ValueError(f"Workflow scope '{scope_id}' already exists")
    scope = WorkflowScope(scope_id, metadata=metadata)
    app._scope_registry[scope_id] = scope

    hooks = app._hook_registry._global_hooks.get(HookEvent.ON_SCOPE_CREATED, [])
    for hook in hooks:
        try:
            hook(scope)
        except Exception as e:
            hook_name = getattr(hook, "__name__", repr(hook))
            logger.warning(
                f"ON_SCOPE_CREATED hook {hook_name!r} raised an error "
                f"for scope '{scope_id}': {e}"
            )

    return scope


def get_workflow_scope(app: Any, scope_id: str) -> Any:
    """Retrieve an existing WorkflowScope by identifier.

    Args:
        app: The FunctualizeApp instance.
        scope_id: Unique scope identifier.

    Returns:
        WorkflowScope instance.

    Raises:
        KeyError: If scope_id not found.
    """
    if scope_id not in app._scope_registry:
        raise KeyError(
            f"Workflow scope '{scope_id}' not found. "
            f"Available scopes: {list(app._scope_registry.keys())}"
        )
    return app._scope_registry[scope_id]


# ─── Plugin Lookup ───────────────────────────────────────────────────────


def get_plugin(app: Any, name: str) -> Any:
    """Look up a registered plugin instance by name.

    Args:
        app: The FunctualizeApp instance.
        name: Plugin name.

    Returns:
        Plugin instance.

    Raises:
        KeyError: If plugin not found.
    """
    if name in app._plugin_name_index:
        return app._plugin_name_index[name]
    registered_names = list(app._plugin_name_index.keys())
    raise KeyError(f"Plugin '{name}' not found. Registered plugins: {registered_names}")


# ─── Dynamic Job Registration ────────────────────────────────────────────


def register_dynamic_job(
    app: Any,
    name: str,
    function: Callable[..., Any],
    config_class: Any | None = None,
    group: str | None = None,
) -> None:
    """Register a callable as an executable job at runtime.

    Args:
        app: The FunctualizeApp instance.
        name: Job name.
        function: The callable job function.
        config_class: Optional config class for the job.
        group: Optional group name.

    Raises:
        ValueError: If a job with this name already exists.
    """
    from functualize._engine.result import RegisteredJob
    from functualize._types.descriptors import JobDescriptor

    # Dynamic registration is one of the three doors into the registry, so it
    # canonicalizes like the other two. Registering the raw spelling would put
    # `my_job` beside a discovered `my-job` — two entries for one address, the
    # duplicate check silently passing because it compared the wrong strings.
    from functualize._types.naming import normalize_name

    canonical = normalize_name(name) or name
    if group is not None:
        group = normalize_name(group)
    name = canonical

    if name in app.job_registry._registered_jobs:
        raise ValueError(
            f"Cannot register dynamic job '{name}': a job with this name already exists"
        )

    module_path = getattr(function, "__module__", "<dynamic>") or "<dynamic>"
    from functualize._types.from_job import declared_dependency_names

    entry = RegisteredJob(
        name=name,
        function=function,
        config_class=config_class,
        group=group,
        module_path=module_path,
        dependencies=declared_dependency_names(
            getattr(function, "__functualize_job__", None), function
        ),
    )
    app.job_registry._registered_jobs[name] = entry
    app._execution_engine.register_job(entry)

    from functualize._discovery.providers import (
        extract_capability_markers,
        extract_ext_metadata,
    )
    from functualize._types.from_job import from_job_names
    from functualize._types.workflow import workflow_shape_of

    descriptor = JobDescriptor(
        name=name,
        group=group,
        function=function,
        docstring=function.__doc__,
        parameters=[],
        source="<dynamic>",
        metadata=extract_ext_metadata(function),
        module_path=module_path,
        source_file="<dynamic>",
        source_mtime=0.0,
        content_hash="",
        declaration=getattr(function, "__functualize_job__", None),
        workflow=workflow_shape_of(function),
        from_job_deps=from_job_names(function),
        **extract_capability_markers(function),
    )
    app.job_registry._job_descriptors.append(descriptor)

    hook_metadata: dict[str, Any] = {
        "name": name,
        "group": group or "",
        "config_schema": config_class,
        "docstring": function.__doc__,
    }
    app._hook_registry.invoke_job_registered(hook_metadata)


# ─── Configuration Model Resolution ─────────────────────────────────────


def resolve_model(app: Any, section: str, model_class: type[object]) -> object:
    """Resolve a configuration model through the Resolution_Chain.

    Args:
        app: The FunctualizeApp instance.
        section: Configuration section name.
        model_class: The model class to instantiate.

    Returns:
        Instantiated model with resolved configuration values.
    """
    from functualize._events.hooks import ConfigHookEvent

    app.hook_registry.invoke_config_event(
        ConfigHookEvent.BEFORE_CONFIG_RESOLVE, section, model_class
    )
    resolved_data = app._resolution_chain.resolve_section(section)
    resolved_dict = {key: rv.value for key, rv in resolved_data.items()}
    model_instance = model_class(**resolved_dict)
    app.hook_registry.invoke_config_event(
        ConfigHookEvent.AFTER_CONFIG_RESOLVE, section, model_instance
    )
    return model_instance


# ─── Instrument Decorator ────────────────────────────────────────────────


def make_instrument_decorator(
    app: Any, operation_point: str, priority: int = 0
) -> Callable[..., Any]:
    """Create an operation-point middleware decorator.

    Args:
        app: The FunctualizeApp instance.
        operation_point: The operation point name.
        priority: Middleware priority.

    Returns:
        Decorator function.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        app.middleware.register(operation_point, fn, priority=priority)
        return fn

    return decorator


# ─── Interactivity Event Handler ─────────────────────────────────────────


def on_job_submit_event(app: Any, event: Any) -> None:
    """Handle interactivity.job.submit: execute a job by name.

    Args:
        app: The FunctualizeApp instance.
        event: The structured event with job_name and kwargs payload.
    """
    from functualize._engine.errors import JobNotFoundError

    job_name = event.payload.get("job_name", "")
    kwargs = event.payload.get("kwargs", {})
    try:
        registered_job = app.job_registry.get_job(job_name)
    except JobNotFoundError:
        logger.warning(f"interactivity.job.submit: job '{job_name}' not registered")
        return
    app.execution_engine.execute(
        job_name,
        registered_job.function,
        config_class=registered_job.config_class,
        kwargs=kwargs,
    )
