"""Lazy command construction from cached job metadata.

Builds click commands from cached JobDescriptor metadata without importing job
modules — module import is deferred until the user actually invokes the command.
This enables sub-50ms warm boot for ``func --help`` and ``func tui``.

Lives in the adapter layer (not ``_discovery``) alongside ``click_params.py``,
which owns the descriptor → ``click.Parameter`` construction. This module imports
``click`` only (no engine at module scope), preserving warm-boot's
import-light property. The CLI-free lazy machinery (LazyJobFunction,
_detect_config_class) stays in ``functualize._discovery.lazy_wrapper``.
"""

from __future__ import annotations

import contextlib
import importlib
import sys
from typing import TYPE_CHECKING, Any

import click

from functualize.app.adapters.click_params import (
    _force_requested,
    build_click_params_from_descriptor,
)

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor
    from functualize._types.run_request import RunSurface


def make_lazy_command(
    descriptor: JobDescriptor,
    app: Any,
    *,
    command_name: str | None = None,
    group_option_values: dict[str, Any] | None = None,
    surface: RunSurface = "app.cli",
) -> click.Command:
    """Build a ``click.Command`` from cached schema — no module import needed.

    Construction does NOT trigger importlib.import_module(). The module is only
    imported when the returned command's callback is actually invoked.

    Args:
        descriptor: The cached job metadata describing the command signature.
        app: The FunctualizeApp instance (provides execution_engine).
        command_name: CLI command name if it differs from ``descriptor.name``
            (e.g. the bare function name for a grouped job).
        group_option_values: The mid-path group flags for this invocation
            (S6a). The adapter passes one **mutable** dict shared with the
            group nodes above this command: click parses a group's params
            before it resolves the sub-command, so the dict is filled by the
            time this callback runs. Baking the values in at construction
            time would freeze them empty.

    Returns:
        A ``click.Command`` whose callback materializes and runs the job on
        first invocation.
    """

    def lazy_wrapper(**kwargs: Any) -> Any:
        """Lazy command: materializes via the engine on first invocation."""
        from functualize._types.errors import JobMaterializationError

        # The same resolution the eager path makes, through the same
        # function, so a job behaves identically cold and warm. This wrapper
        # once threaded no scope id at all, which is why a gated `@workflow` on
        # an app blocked forever; `pitfalls.md` §23 is this exact pair of
        # constructors diverging.
        #
        # `--wf-status`/`--wf-show` exit from inside here without running the
        # job, which is why it sits above the engine call.
        scope_id = None
        if getattr(descriptor, "workflow", None) is not None:
            from functualize.app.adapters.workflow_flags import apply_workflow_flags

            scope_id = apply_workflow_flags(app, descriptor.name, kwargs)
        if scope_id is None:
            scope_id = getattr(app, "_workflow_scope_id", None)

        # Capability floor (surface-architecture.md §5): a job that owns the
        # terminal (declares `tty: TTY`) cannot run where there is none. Refuse
        # pre-flight with an actionable message rather than corrupt output or
        # crash mid-run with a signal-handler traceback. Read from the cached
        # descriptor flag, so this costs no import on the warm path.
        if getattr(descriptor, "requires_tty", False):
            from functualize._engine.capabilities.tty import terminal_available

            if not terminal_available():
                print(
                    f"Error: '{descriptor.name}' needs an interactive terminal "
                    f"(it declares `tty: TTY`). Run it from `func` at a real "
                    f"TTY — it cannot run over a pipe, in CI, or under MCP.",
                    file=sys.stderr,
                )
                sys.exit(1)
        # A job that declares `live: Live` renders into a rich stdout surface
        # for direct `func <job>` runs: push a StdoutSurface for the duration so
        # live.add(construct) binds to its live zone (and it supersedes a stray
        # self-rendering surface). Falls back to a no-op when the [cli] extra
        # (rich) is absent — the job then runs with Live degraded, never broken.
        # Shared with create_job_click_command via adapters/surface_gate.py.
        from functualize.app.adapters.surface_gate import wants_stdout_surface

        live_ctx: Any = contextlib.nullcontext()
        if wants_stdout_surface(
            app, descriptor, uses_live=getattr(descriptor, "uses_live", False)
        ):
            with contextlib.suppress(ImportError):
                from functualize.ui import stdout_live_session

                live_ctx = stdout_live_session(app, descriptor)

        from functualize.app.adapters.click_params import (
            deliver_job_result,
            scope_store_refusal,
        )

        engine = app.execution_engine
        try:
            engine.materialize_job(descriptor.name)
        except KeyError:
            # The descriptor is not registered with this app's engine — the
            # legacy direct-import path, where the adapter is used standalone.
            # `engine.run()` resolves by *name*, so the job has to exist in the
            # registry before it can be asked for: import the module, build the
            # entry, register it, and then take the one entry like everybody
            # else. Before T11 this branch called the engine's deleted
            # name-and-function entry directly, which is precisely the second
            # door the feature exists to remove.
            from functualize._discovery.lazy_wrapper import _detect_config_class
            from functualize._types.descriptors import RegisteredJob

            try:
                module = importlib.import_module(descriptor.module_path)
            except Exception as exc:
                print(
                    f"Error: Failed to import module '{descriptor.module_path}': {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            func = getattr(module, descriptor.func_name)
            engine.register_job(
                RegisteredJob(
                    name=descriptor.name,
                    function=func,
                    config_class=_detect_config_class(func),
                    group=getattr(descriptor, "group", None),
                    module_path=descriptor.module_path,
                    job_directory=getattr(descriptor, "job_directory", None),
                )
            )
        except JobMaterializationError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        # One contract, one entry — the same request the eager path in
        # click_params builds, handed to the same `engine.run()`
        # (`pitfalls.md` §23: two dispatch paths, one result-handling
        # contract). Neither path holds a job function any more.
        from functualize.app.adapters._request_builder import build_request

        with live_ctx, scope_store_refusal():
            request = build_request(
                job_name=descriptor.name,
                kwargs=kwargs,
                group_option_values=dict(group_option_values)
                if group_option_values
                else None,
                workflow_scope_id=scope_id,
                force=_force_requested(app),
                surface=surface,
            )
            result = engine.run(request)

        return deliver_job_result(result, descriptor.name, app)

    params = build_click_params_from_descriptor(descriptor)
    # module — which is the whole point of the descriptor.
    if getattr(descriptor, "workflow", None) is not None:
        from functualize.app.adapters.workflow_flags import workflow_flag_params

        params = workflow_flag_params(params)

    return click.Command(
        name=command_name or descriptor.name,
        params=params,
        callback=lazy_wrapper,
        help=descriptor.docstring or None,
    )
