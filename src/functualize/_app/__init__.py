"""Composition root package for functualize.

The `_app/` package is the ONLY internal package allowed to import from
ALL peer layers (`_discovery`, `_config`, `_engine`, `_plugins`, `_events`,
`_primitives`, `_types`) to wire them together via dependency injection.

Contains:
- boot.py: Boot orchestration (provider wiring, config chain, plugin loading)
- impl.py: FunctualizeApp internal method implementations (heavy lifting)
- state.py: AppState thread-safe global state container

This package must NOT import from `_cli/` or any public folder
(`app/`, `job/`, `plugin/`, `types/`, `testing/`).
"""

from functualize._app.boot import (
    boot_standard,
    boot_static,
    build_resolution_chain,
    discover_config_path,
    init_observability,
    register_descriptors,
    resolve_and_register_jobs,
    wire_children_to_pipeline,
)
from functualize._app.impl import (
    build_cached_provider,
    build_resource_locator,
    create_workflow_scope,
    get_cache_stats,
    get_plugin,
    get_workflow_scope,
    is_fully_explicit,
    make_before_job_decorator,
    make_instrument_decorator,
    make_on_event_decorator,
    make_on_invoke_end_decorator,
    make_on_invoke_failure_decorator,
    make_on_invoke_start_decorator,
    make_on_job_failure_decorator,
    make_on_job_success_decorator,
    make_on_job_teardown_decorator,
    make_on_phase_complete_decorator,
    make_on_phase_failure_decorator,
    make_on_phase_start_decorator,
    make_on_ready_decorator,
    make_pre_execute_decorator,
    make_run_middleware_decorator,
    on_job_submit_event,
    register_dynamic_job,
    register_plugin_command,
    register_run_middleware,
    resolve_model,
    shutdown_plugins,
)
from functualize._app.state import AppState
from functualize._primitives.cache_format import find_functualize_dir

__all__ = [
    # Boot orchestration
    "boot_standard",
    "boot_static",
    "build_resolution_chain",
    "discover_config_path",
    "init_observability",
    "register_descriptors",
    "resolve_and_register_jobs",
    "wire_children_to_pipeline",
    # Implementation helpers
    "build_cached_provider",
    "build_resource_locator",
    "create_workflow_scope",
    "find_functualize_dir",
    "get_cache_stats",
    "get_plugin",
    "get_workflow_scope",
    "is_fully_explicit",
    "make_before_job_decorator",
    "make_instrument_decorator",
    "make_on_event_decorator",
    "make_on_invoke_end_decorator",
    "make_on_invoke_failure_decorator",
    "make_on_invoke_start_decorator",
    "make_on_job_failure_decorator",
    "make_on_job_success_decorator",
    "make_on_job_teardown_decorator",
    "make_on_ready_decorator",
    "make_on_phase_complete_decorator",
    "make_on_phase_failure_decorator",
    "make_on_phase_start_decorator",
    "make_pre_execute_decorator",
    "make_run_middleware_decorator",
    "on_job_submit_event",
    "register_dynamic_job",
    "register_plugin_command",
    "register_run_middleware",
    "resolve_model",
    "shutdown_plugins",
    # State
    "AppState",
]
