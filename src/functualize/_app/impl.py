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
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives import compute_project_id
from functualize._primitives.cache_format import find_functualize_dir
from functualize._primitives.locator import ResourceLocator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._config.chain import ResolutionChain
    from functualize._engine.result import JobResult
    from functualize._types.descriptors import (
        CacheInfo,
        ConfigFileInfo,
        JobDescriptor,
    )
    from functualize.app.config import ConfigSources, JobSources, PluginSources

logger = logging.getLogger(__name__)


#: The `source_file` a job registered from code carries. Re-reading the disk can
#: never rediscover such a job, which is why `refresh` retains them.
_DYNAMIC_SOURCE = "<dynamic>"


def _is_dynamic(descriptor: Any) -> bool:
    """True if the descriptor was registered from code rather than discovered.

    Lives here rather than in `app/core.py` because `refresh` — the one caller
    that matters — moved here in T9, and `_app` may not import a public folder
    to reach back for it. `core.py` re-exports it for its own use.
    """
    return bool(descriptor.source_file == _DYNAMIC_SOURCE)


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
    discovery_hash: str | None = None,
    ancestor_search: bool = True,
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
        discovery_hash: Fingerprint of the discovery config the filters were
            built from. ``None`` means "does not know the config" and skips the
            check -- correct for a reader, wrong for anything that persists.
        ancestor_search: When True (default) the ``.functualize/`` lookup walks
            *upward* from ``project_root``. Child projects pass False so they
            resolve their own cache instead of landing on the parent's and
            sharing one ``cache.json`` with it (ADR-011).

    Returns:
        CachedDirectoryScanProvider instance.
    """
    from functualize._discovery.cached_provider import CachedDirectoryScanProvider

    if project_root is None:
        project_root = Path.cwd().resolve()
    else:
        project_root = Path(project_root).resolve()

    if ancestor_search:
        functualize_dir = find_functualize_dir(project_root)
    else:
        candidate = project_root / ".functualize"
        functualize_dir = candidate if candidate.is_dir() else None

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
        discovery_hash=discovery_hash,
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
    needs_terminal: bool = False,
) -> None:
    """Validate and register a plugin command.

    Args:
        app: The FunctualizeApp instance.
        name: Command name (lowercase alphanumeric + hyphens).
        callback: Callable to invoke when the command is executed.
        help_text: Help text (max 256 chars).
        namespace: Optional flat CLI namespace to mount the command under.
        needs_terminal: True when the command takes over the controlling
            terminal (a server on stdio, an editor), so a TUI front-end steps
            aside instead of capturing its output.

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
        name=name,
        callback=callback,
        help_text=help_text,
        namespace=namespace,
        needs_terminal=needs_terminal,
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
    from functualize._engine.capabilities.state import ScopeBackedStateStore
    from functualize._engine.capabilities.workflow_scope import WorkflowScope
    from functualize._events.hooks import HookEvent

    if scope_id in app._scope_registry:
        raise ValueError(f"Workflow scope '{scope_id}' already exists")
    # The durable default. The scope's own records already live in
    # `scopes.json`; its state joins them there rather than in a dict that
    # `_scope_registry = {}` at boot would drop — which is what made a resumed
    # run come back with its step records intact and its state silently empty.
    #
    # The engine's own substrate, so a reader and a writer cannot disagree
    # about which project's documents these are — no second walk to keep in
    # agreement, and no way to give records one backend and state another.
    scopes = app.execution_engine._scope_store()
    scope = WorkflowScope(
        scope_id,
        metadata=metadata,
        state_store=ScopeBackedStateStore(scopes, scope_id),
    )
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

    import contextlib

    from functualize._discovery.providers import (
        extract_capability_markers,
        extract_ext_metadata,
        extract_parameters_from_signature,
    )
    from functualize._discovery.schema_extractor import extract_field_descriptors
    from functualize._primitives.config_class_detection import detect_config_class
    from functualize._types.from_job import from_job_names
    from functualize._types.workflow import workflow_shape_of

    # The same extraction directory discovery uses. `parameters` was `[]` here,
    # so the *same function* registered dynamically took different arguments
    # from one discovered from a file.
    parameters = extract_parameters_from_signature(function)

    # `config_fields` is the other half, and populating only `parameters` makes
    # the mismatch worse rather than better for a job with a config class:
    # `job_detail` reads `config_fields or parameters`, so such a job would
    # publish its bare `config: NeedsCity` parameter -- which no caller can
    # supply -- in place of the model's actual fields.
    #
    # The rule is discovery's, unchanged: fields from the config class if there
    # is one, else the signature. An explicitly passed `config_class` wins over
    # the one detected on the signature, because it is the caller stating the
    # answer this function already trusts for `RegisteredJob`.
    config_fields: list[Any] = []
    effective_config_class = config_class or detect_config_class(function)
    if effective_config_class is not None:
        with contextlib.suppress(Exception):
            config_fields = extract_field_descriptors(effective_config_class)

    descriptor = JobDescriptor(
        name=name,
        group=group,
        function=function,
        docstring=function.__doc__,
        parameters=parameters,
        config_fields=config_fields if config_fields else parameters,
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


# ─── Agent Step Executors ────────────────────────────────────────────────


def register_agent_step_executor(app: Any, executor: Any) -> None:
    """Register an agent step executor on ``app``.

    Registered, never auto-discovered (the agent-step port's §3.1):
    auto-discovery is how a surface acquires behaviour nobody declared, and
    this is the one node kind whose behaviour runs outside the process.

    Args:
        app: The FunctualizeApp instance.
        executor: An `AgentStepExecutor`. It is refused unless it declares a
            `name`, a `capabilities` set and `execute(ctx)` — a missing
            declaration must fail where it is declared, not mid-walk.

    Raises:
        TypeError: ``executor`` does not satisfy `AgentStepExecutor`.
        ValueError: Its name is already registered, or empty.
    """
    app._agent_step_registry.register(executor)


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
    from functualize._types.run_request import RunRequest

    job_name = event.payload.get("job_name", "")
    kwargs = event.payload.get("kwargs", {})
    try:
        app.job_registry.get_job(job_name)
    except JobNotFoundError:
        logger.warning(f"interactivity.job.submit: job '{job_name}' not registered")
        return

    # D-13. This door used to reach past the facade straight into the engine,
    # resolving the function itself. The engine still minted a *persisted* scope
    # for a `@workflow` (`_engine/workflow_runner.py:97`), so the run was not
    # scope-less -- it was **unaddressable**: nothing here ever learned the id,
    # so a blocked workflow submitted this way could never be answered or
    # resumed. Going through the facade is what makes the scope reachable,
    # because the facade creates it and the result carries it.
    request = RunRequest(job_name=job_name, surface="event.job-submit", kwargs=kwargs)
    result = app.execute(request)
    scope_id = (result.metadata or {}).get("workflow_scope")
    if scope_id:
        logger.info(
            "interactivity.job.submit: job '%s' ran in scope '%s'", job_name, scope_id
        )


# ─── `func builtin why` — the verdict surface ─────────────────────────────
#
# Moved out of `app/core.py` by `engine-sealed-construction`/T9. It is ~115
# executable lines of *evaluation* on a class whose job is composition, and it
# was the largest single block there. `RunContext`'s diet (T8) used facades
# because a job author reaches those members by name; this one uses `_app/impl`
# because nothing outside `core.py` calls them — `explain`, `explain_data` and
# `explain_verdicts` are what `func builtin why` and the TUI ask the app for,
# and they stay on the app, three lines each.


def explain(app: Any, job_name: str) -> str:
    """Render why ``job_name`` would or would not run (§D.6).

    The prose half of :meth:`explain_verdicts`, which is where the
    evaluation lives. Two forms of one answer, derived from one set of
    verdicts, so `func builtin why` and `func builtin why --json` cannot
    disagree — a `--json` that re-derived the verdicts would be a second
    reader of the same question, which is the shape of every defect this
    module's history records.
    """
    from functualize._engine.explain import render_dep_line, render_verdict

    target, deps, note, error = explain_verdicts(app, job_name)
    if error is not None:
        return error

    assert target is not None
    rendered = render_verdict(
        job_name,
        target,
        deps=[render_dep_line(name, verdict) for name, verdict in deps],
    )
    return f"{rendered}\n  {note}" if note else rendered


def explain_verdicts(app: Any, job_name: str) -> tuple[Any, list[Any], str, str | None]:
    """The raw material behind `func builtin why`.

    Returns ``(target_verdict, [(dep_name, dep_verdict), …], note, error)``.
    ``error`` is a rendered string for the two cases that have no verdict at
    all — an unresolvable job, and one with no `@job` declaration — and is
    None otherwise.

    Evaluates the same pre-flight pipeline the executor consults, so this
    can never describe a decision the run would not make. Evaluated fresh
    rather than read from a cache: a verdict is a function of the world
    *now* — files on disk, a precondition's exit code — and a stored
    explanation goes stale exactly when someone asks.

    Lives on the app because `func why`, the JSON form and the TUI all need
    it, and none of them may import the engine directly.
    """

    from functualize._engine.guards import GuardState, GuardVerdict
    from functualize._engine.preflight import Preflight
    from functualize._primitives.fresh_store import FreshStore

    try:
        entry = app.execution_engine.materialize_job(job_name)
    except Exception as exc:
        # `KeyError: "Job 'x' not found in engine registry"` is what this
        # said, which is the exception's repr rather than an answer.
        # `func builtin why` exists to answer "why is my job missing?", and
        # when discovery already knows — a module that failed to load, two
        # files contesting one group's flags — that is the answer, in the
        # same words the unknown-command reporters use. One implementation,
        # so the two doors cannot say different things about one project
        # (adj M4, decision D-4).
        import contextlib

        from functualize._cli.info import explain_missing_job

        reason = None
        with contextlib.suppress(Exception):
            reason = explain_missing_job(job_name, app)
        detail = reason or f"{type(exc).__name__}: {exc}"
        return None, [], "", f"{job_name} → UNKNOWN\n  {detail}"

    declaration = getattr(entry.function, "__functualize_job__", None)
    if declaration is None:
        return (
            None,
            [],
            "",
            f"{job_name} → WOULD RUN\n"
            "  no @job declaration — nothing guards or caches this job",
        )

    store = FreshStore(app.execution_engine.substrate)
    preflight = Preflight(store, root=app.fresh_root)

    def config_for(name: str) -> Any:
        """The config a run of ``name`` would resolve, or None.

        The fingerprint key is a function of the resolved config, so
        omitting it here addressed a *different* key than the run wrote
        under and this method reported "no previous run recorded" for a
        job that had just succeeded — the contradiction §D.6 exists to
        make impossible.

        `resolve_config_model` deliberately propagates ValidationError; on
        a read path that must degrade rather than turn `why` into a crash,
        so an unresolvable config becomes None *and says so* in the log.
        """
        import logging

        try:
            return app.execution_engine.resolve_config_model(name)
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "config for %r could not be resolved while explaining it "
                "(%s); the verdict is computed without it",
                name,
                exc,
            )
            return None

    def verdict_for(name: str) -> Any:
        try:
            dep_entry = app.execution_engine.materialize_job(name)
        except Exception:
            return GuardVerdict(GuardState.RUN, "not registered")
        dep_declaration = getattr(dep_entry.function, "__functualize_job__", None)
        if dep_declaration is None:
            return GuardVerdict(GuardState.RUN, "no @job declaration")
        return preflight.check(name, dep_declaration, config=config_for(name)).verdict

    # A dependency's own verdict matters: a fresh target with a stale dep
    # still runs, and a user staring at the target alone cannot see why.
    deps = [
        (name, verdict_for(name))
        for name in app.execution_engine._declared_dep_names(job_name)
    ]
    # The *target's* verdict needs the same config as the dependencies'.
    # It produces the headline, so getting this one wrong is the visible
    # half of the contradiction.
    target = preflight.check(job_name, declaration, config=config_for(job_name)).verdict

    # Resolved Q19: a recorded value that cannot be handed to a `FromJob`
    # dependent is a reason the upstream keeps re-running, and it is
    # invisible in the freshness verdict — the job *is* fresh; only its
    # value cannot travel. `func why` is where someone already asks "why
    # did this run again", so the answer belongs here.
    note = _return_value_note(app, job_name, declaration, store)
    return target, deps, note, None


def explain_data(app: Any, job_name: str) -> dict[str, Any]:
    """`func builtin why --json` — the same verdicts, as data.

    `ExitCode.STALE` (4) has been pinned in `_types/exit_codes.py` since the
    table was written, documented as "stale-check failure", and produced
    **nowhere**: an inert surface of the same class as the `@job(matrix=…)`
    kwarg this branch removed. `why` answers exactly the question that
    number was reserved for, and answered it in prose with exit 0, so no
    script could act on it. This gives the code its first producer.

    `exit_code` is in the payload as well as being the process's exit code,
    so a caller that captured stdout does not also have to capture ``$?``.
    """
    from functualize._engine.explain import explain_exit_code, model_name
    from functualize._types.exit_codes import ExitCode

    target, deps, note, error = explain_verdicts(app, job_name)
    if error is not None:
        return {
            "job": job_name,
            "state": "unknown",
            "will_run": True,
            "reason": error.split("\n", 1)[-1].strip(),
            "checks": [],
            "awaiting": None,
            "note": None,
            "deps": [],
            "exit_code": int(ExitCode.USAGE),
        }

    assert target is not None
    return {
        "job": job_name,
        # The enum's *wire* values, so a new member is a new string rather
        # than a renamed one.
        "state": target.state.value,
        "will_run": bool(target.will_run),
        "reason": target.reason,
        # No `changed` key: a `GuardVerdict` does not carry the
        # fingerprint's changed-path list — it carries the rendered
        # explanation of it, in `reason` and `checks`. Emitting an
        # always-empty array would be worse than omitting it.
        "checks": list(target.checks),
        "awaiting": model_name(target.awaiting),
        "note": note or None,
        "deps": [
            {
                "job": name,
                "state": verdict.state.value,
                "will_run": bool(verdict.will_run),
            }
            for name, verdict in deps
        ],
        "exit_code": int(explain_exit_code(target)),
    }


def _return_value_note(app: Any, job_name: str, declaration: Any, store: Any) -> str:
    """One line about an unusable recorded return value, or ""."""
    from functualize._primitives.fingerprint import why_return_value_unreusable

    if getattr(declaration, "cache", None) is None:
        return ""
    for method in ("checksum", "timestamp", "none"):
        # Through the engine's own key derivation. Reading under
        # `compute_args_hash(None, {})` found no record for any job with a
        # config class, so the note this method exists to print was
        # unprintable exactly where it mattered most.
        record = store.get_fingerprint(
            app.execution_engine.fingerprint_key_for(job_name, method)
        )
        if record is not None:
            return why_return_value_unreusable(record)
    return ""


# ─── Bodies moved out of the app facade (T9) ──────────────────────────────
#
# `FunctualizeApp` is the composition root's public face. Everything here was a
# method on it and is *work* rather than composition — resolving a chain,
# rendering a config-file list, validating a surface registration, fanning out a
# parallel batch. `core.py` keeps a delegate with the public docstring; the
# reasoning that belongs with the code came here with it.


def config_files(app: Any, job_name: str | None = None) -> list[ConfigFileInfo]:
    """Return every config file the kernel discovered, and its role.

    The single answer to "what happened with the config files": where
    they are, which environment slot each names, whether it is actually
    contributing under the active environment, how strongly it wins, and
    what it said. Delivery layers need all of that together — knowing a
    file merely exists cannot explain why its values aren't taking
    effect.

    Inactive (INERT) and unparsed files are included, precisely so a
    caller can show "present, but belongs to another environment"
    instead of silently omitting the file the user is asking about.

    Args:
        job_name: When given, each file's ``values`` are narrowed to that
            job's config section. When None, ``values`` are the file's
            full contents.

    Returns:
        Files in kernel discovery order. Empty if the active preset has
        no file source (e.g. ``env_only()``) or nothing was discovered.
    """
    infos = _file_source_infos(app)
    if job_name is None:
        return infos

    section = app.configuration.get_job_config_section(job_name)
    narrowed: list[ConfigFileInfo] = []
    for info in infos:
        section_data = info.values.get(section)
        values = dict(section_data) if isinstance(section_data, dict) else {}
        narrowed.append(replace(info, values=values))
    return narrowed


def refresh(app: Any) -> None:
    """Re-read the project from disk: discovery and config resolution.

    For persistent consumers (TUI, MCP server) whose process outlives the
    project state it booted from. After a job file is added, edited, or
    deleted — or a config file changes — ``refresh()`` makes the next
    :meth:`get_jobs` / :meth:`execute` observe the new state.

    Rebuilds:
    - Job discovery — re-runs the same registration the boot path uses,
      so added/removed/edited job modules are picked up.
    - The config resolution chain — unless an explicit chain was supplied
      via ``ConfigSources(config_resolution_chain=...)``, in which case
      the caller owns the chain and it is left untouched.
    - Live RunContext config views, so in-flight contexts see new values.

    Scope: refresh owns only what *discovery* produced. Jobs registered
    programmatically (decorators, ``register_job``) are left in place —
    their source is code that already ran, not a file being re-read. It
    does not re-run plugin boot.

    Not safe to call while a job is executing: it re-registers the very
    entries an in-flight execution resolves against. Call it on a
    boundary, e.g. between TUI shell cycles.
    """
    from functualize._app.boot import resolve_and_register_jobs

    registry = app.job_registry

    # Retire the previous discovery generation. Jobs registered from code
    # (register_dynamic_job) also live in _job_descriptors but carry the
    # "<dynamic>" sentinel — re-reading the disk can never rediscover
    # them, so purging them would destroy them permanently.
    retained = [d for d in registry._job_descriptors if _is_dynamic(d)]
    discovered_names = {d.name for d in registry._job_descriptors if not _is_dynamic(d)}
    registry._job_descriptors[:] = retained
    for name in discovered_names:
        registry._registered_jobs.pop(name, None)
        app._execution_engine._registered_jobs.pop(name, None)
    registry._registered_commands = {
        key: module_path
        for key, module_path in registry._registered_commands.items()
        # Keys are "<group_or___top__>::<job name>".
        if key.split("::", 1)[-1] not in discovered_names
    }

    # Drop the listing memo so get_jobs() re-reads the rebuilt registry.
    app._jobs_memo = None

    resolve_and_register_jobs(app)

    # Config: an explicitly-supplied chain is the caller's to manage;
    # rebuilding it would discard what they passed in.
    if app._config_sources.config_resolution_chain is None:
        # Through the app, not directly: the regex default it compares
        # against is public, and only the app may read it (see the delegate).
        app._resolution_chain = app._build_resolution_chain()
        # Nothing is pushed into the engine: it reads the chain through
        # this object (``resolution_chain()``), so a rebuild is visible to
        # it the moment it asks. This used to be a write into the engine's
        # private field, at runtime, from a *refresh* — which is how the
        # engine's config dependency became something that could change
        # under a run.

    # Push the (possibly new) chain into live RunContext config views.
    app.job_registry.update_config_paths()


def _file_source_infos(app: Any) -> list[ConfigFileInfo]:
    """Return the FileSource's per-file info, or [] if there is none."""
    try:
        for source in app._resolution_chain.sources:
            if getattr(source, "source_type", "") != "file":
                continue
            infos = getattr(source, "file_infos", None)
            return list(infos) if infos else []
    except (AttributeError, TypeError):
        pass
    return []


def _build_resolution_chain(app: Any, custom_regex: str | None) -> ResolutionChain:
    """Build a ResolutionChain [CLI → Env → Files → Defaults].

    Must stay argument-for-argument equivalent to the boot path's own
    call (``_app/boot.py`` step 6) — a rebuild that omits ``environment``
    silently disables overlay banding, so every ``config.<slot>.*`` file
    would merge in discovery order instead of only the active one.
    """
    from functualize._app.boot import build_resolution_chain

    return build_resolution_chain(
        app._config_path,
        app.name,
        app.config_registry,
        file_regex=custom_regex,
        environment=app._environment,
        event_bus=app.event_bus,
    )


def execute_parallel(
    app: Any,
    job_names: Sequence[str],
    *,
    timeout: float | None = None,
    observer: Any | None = None,
) -> list[JobResult]:
    """Execute jobs concurrently, returning results in input order (T40).

    The public seam over ``Invoke.parallel`` for callers that are not
    themselves jobs — ``func builtin parallel``, primarily. It lives on the
    app because ``_cli`` may not import the engine, and because "run these
    N jobs at once" is the same operation whether a job asks for it or a
    command line does; two implementations would drift on the parts that
    matter (ordering, the timeout, how a failure is reported).

    Args:
        job_names: 1-32 registered job names.
        timeout: Seconds the batch may run before unfinished jobs come back
            as :attr:`RunStatus.TIMEOUT`. ``None`` uses the engine default
            (300s); ``<= 0`` waits indefinitely.
        observer: Notified on each worker thread around its job — what
            per-job output attribution is built on. See
            ``_engine.capabilities.invoke.ParallelObserver``.

    Returns:
        One :class:`JobResult` per name, in input order. Failures are
        *returned*, not raised — a batch reports on every job, including
        the ones that ran fine beside a broken one.
    """
    from pathlib import Path

    from functualize._engine.capabilities.invoke import WiredInvoke

    # Under lazy boot nothing is in the engine registry until something
    # asks, and `parallel` resolves names on a worker thread where a miss
    # surfaces as a bare KeyError per job rather than a usable error. The
    # normal CLI path materializes while building the command tree; this
    # command never builds one, so it has to ask here.
    app.get_jobs()

    invoke = WiredInvoke(
        execution_engine=app.execution_engine,
        gate_registry=getattr(app, "_gate_registry", None),
        invoke_depth=0,
        # This door is a caller who is *not* a job — `func builtin
        # parallel`, or an embedder. Its items are top-level work the user
        # asked for, so they say `app.parallel` and reach history; a job's
        # own `rc.invoke_parallel` says `invoke.parallel` and does not
        # (run-request/T16).
        parallel_item_surface="app.parallel",
        cwd=Path.cwd(),
    )
    return invoke.parallel(
        [(name, {}) for name in job_names],
        timeout=timeout,
        observer=observer,
    )


def resolve_gate(
    app: Any,
    model_class: type,
    *,
    force_gate: bool = False,
    gate_strategy: Any = None,
    resolved_fields: dict[str, Any] | None = None,
    workflow_context: dict[str, Any] | None = None,
    gate_name: str = "unnamed",
) -> Any:
    """Resolve a gate by applying the resolution algorithm.

    Delegates to the underlying GateRegistry.resolve_gate() method.

    Args:
        model_class: The Pydantic BaseModel subclass to resolve.
        force_gate: If True, dispatch to strategy even when fully resolved.
        gate_strategy: Override strategy — a single strategy name/enum,
            or list of strategies, or a preset name.
        resolved_fields: Dict of field names to already-resolved values.
        workflow_context: Arbitrary context from the current workflow state.
        gate_name: Identifier for the gate (used in error messages).

    Returns:
        A fully populated BaseModel instance.

    Raises:
        GateResolutionError: If all strategies fail to resolve.
        ValueError: If a preset references an unregistered strategy.
    """
    return app._gate_registry.resolve_gate(
        model_class,
        force_gate=force_gate,
        gate_strategy=gate_strategy,
        resolved_fields=resolved_fields,
        workflow_context=workflow_context,
        gate_name=gate_name,
    )


def register_surface(app: Any, surface: Any) -> None:
    """Register something that renders a job's events, answers its
    prompts, or both.

    The two capabilities are independent — a renderer need not be able to
    collect, and a collector need not render — so satisfying either is
    enough:

    - :class:`Surface` — has ``handle_event(event)``; receives the event
      fan-out.
    - :class:`PromptCollector` — has ``collect(request)``; eligible to
      answer ``rc.prompt_*()``.

    Raises:
        TypeError: If the object satisfies neither protocol.
    """
    from functualize._types.interactivity import PromptCollector, Surface

    renders = isinstance(surface, Surface)
    collects = isinstance(surface, PromptCollector)

    if not renders and not collects:
        raise TypeError(
            "Surface protocol not satisfied. An object registered here "
            "must implement handle_event(event) to receive events, "
            "collect(request) to answer prompts, or both."
        )

    # Skip duplicates
    if surface in app._surfaces:
        return

    app._surfaces.append(surface)


def register_ambient_construct(
    app: Any,
    construct_factory: Any,
    *,
    name: str | None = None,
    predicate: Any = None,
) -> None:
    """Register a live construct that renders by default for eligible jobs.

    The ambient tier of the ``Live`` model: where ``live.add(...)`` is the
    job asking for a construct, this is a plugin providing one for every
    job that matches ``predicate`` — with no job-author code::

        register_ambient_construct(app,
            FlowVizConstruct,
            predicate=lambda descriptor: descriptor.uses_invoke,
        )

    Pass a **factory** (a class or zero-arg callable), not an instance:
    each run gets a fresh construct, so one job's state cannot bleed into
    the next.

    Args:
        construct_factory: Zero-arg callable returning a construct with
            ``__rich__()`` and, optionally, ``handle_event(event)``.
        name: Identifier used for suppression (``live.suppress(name)``,
            ``@job(suppress_live=[name])``, ``[live] suppress``). Defaults
            to the factory's ``name`` attribute, else its ``__name__``.
        predicate: Optional ``(JobDescriptor) -> bool`` gate. Omit for
            always-on. A predicate that raises is treated as False.
    """
    from functualize._engine.ambient import AmbientEntry

    if not callable(construct_factory):
        raise TypeError(
            "register_ambient_construct() expects a factory (a class or "
            "zero-arg callable) returning a construct, not an instance — "
            "each run needs its own construct state."
        )

    resolved = name or getattr(construct_factory, "name", None)
    if not isinstance(resolved, str) or not resolved:
        resolved = getattr(construct_factory, "__name__", "construct")

    if not hasattr(app, "_ambient_constructs"):
        app._ambient_constructs = []
    if any(entry.name == resolved for entry in app._ambient_constructs):
        return  # idempotent: a re-run plugin must not double-register
    app._ambient_constructs.append(
        AmbientEntry(factory=construct_factory, name=resolved, predicate=predicate)
    )


def update_run_context_configs(app: Any, run_contexts: list[Any]) -> None:
    """Re-resolve config for RunContext instances after config path changes.

    Called by JobRegistry.update_config_paths() to avoid the registry
    importing from _config directly (peer-layer independence).

    Args:
        run_contexts: List of RunContext instances to update.
    """
    from functualize._config.job_config import JobConfigView

    for rc in run_contexts:
        rc._config = JobConfigView(
            resolution_chain=app._resolution_chain,
            default_section_prefix=rc.name,
        )


def get_job(app: Any, name: str) -> JobDescriptor | None:
    """Retrieve a single job descriptor by name."""
    result: JobDescriptor | None = app._resolution_pipeline.resolve_one(name)
    if result is not None:
        return result
    try:
        descriptor: JobDescriptor = app.job_registry.get_descriptor(name)
    except KeyError:
        return None
    return descriptor


def install_substrate(app: Any, substrate: Any) -> None:
    """Set the app's substrate, refusing once the engine has resolved one.

    `store-substrate`/T5. A plugin installs a database at `APP_READY`, which is
    before the engine touches a store — the engine resolves lazily, on the first
    store access, which happens during a run.

    Installing later is **refused** rather than allowed to half-apply. The
    engine holds what it resolved, so a late install would leave some of a run's
    documents in one backend and some in the other: exactly the split brain
    spec AC-4 says must be unreachable, arriving through a different door.

    Lives here rather than on the facade because the refusal is real logic and
    `FunctualizeApp` has an executable-line budget that `test_facade_loc_limits`
    enforces — which is how this landed here: the guard pushed the facade nine
    lines over and the tripwire said so.
    """
    engine = getattr(app, "_execution_engine", None)
    if engine is not None and getattr(engine, "_substrate", None) is not None:
        raise RuntimeError(
            "the substrate is already in use by this app's engine; installing "
            "another now would leave some of a run's documents in one backend "
            "and some in the other. Set it during boot — a plugin's APP_READY "
            "hook is the intended place."
        )
    app._substrate = substrate
