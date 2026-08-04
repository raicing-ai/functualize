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

from functualize.app.adapters.click_params import build_click_params_from_descriptor

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor


def make_lazy_command(
    descriptor: JobDescriptor,
    app: Any,
    *,
    command_name: str | None = None,
) -> click.Command:
    """Build a ``click.Command`` from cached schema — no module import needed.

    Construction does NOT trigger importlib.import_module(). The module is only
    imported when the returned command's callback is actually invoked.

    Args:
        descriptor: The cached job metadata describing the command signature.
        app: The FunctualizeApp instance (provides execution_engine).
        command_name: CLI command name if it differs from ``descriptor.name``
            (e.g. the bare function name for a grouped job).

    Returns:
        A ``click.Command`` whose callback materializes and runs the job on
        first invocation.
    """

    def lazy_wrapper(**kwargs: Any) -> Any:
        """Lazy command: materializes via the engine on first invocation."""
        from functualize._types.errors import JobMaterializationError

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

        engine = app.execution_engine
        try:
            entry = engine.materialize_job(descriptor.name)
        except KeyError:
            # Descriptor not registered with this app's engine — legacy
            # direct-import path (adapter used standalone).
            from functualize._discovery.lazy_wrapper import _detect_config_class

            try:
                module = importlib.import_module(descriptor.module_path)
            except Exception as exc:
                print(
                    f"Error: Failed to import module '{descriptor.module_path}': {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            func = getattr(module, descriptor.func_name)
            config_class = _detect_config_class(func)
        except JobMaterializationError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        else:
            func = entry.function
            config_class = entry.config_class

        # A job that declares `live: Live` renders into a rich stdout surface
        # for direct `func <job>` runs: push a StdoutSurface for the duration so
        # live.add(construct) binds to its live zone (and it supersedes a stray
        # self-rendering surface). Falls back to a no-op when the [cli] extra
        # (rich) is absent — the job then runs with Live degraded, never broken.
        #
        # A job that declares no `live: Live` still needs the surface when a
        # plugin registered an ambient construct eligible for it (otherwise the
        # construct has nothing to render into), or when an explicit STDOUT
        # preference (@surface_hint / the tui.default_surface setting) asks for
        # the rich stdout branch. With none of those this is exactly the old
        # `uses_live` gate, so plain `func <job>` output is unchanged. Shared
        # with create_job_click_command via adapters/surface_gate.py.
        from functualize.app.adapters.surface_gate import wants_stdout_surface

        live_ctx: Any = contextlib.nullcontext()
        if wants_stdout_surface(
            app, descriptor, uses_live=getattr(descriptor, "uses_live", False)
        ):
            with contextlib.suppress(ImportError):
                from functualize.ui import stdout_live_session

                live_ctx = stdout_live_session(app, descriptor)

        with live_ctx:
            return engine.execute(
                job_name=descriptor.name,
                function=func,
                config_class=config_class,
                kwargs=kwargs,
            )

    return click.Command(
        name=command_name or descriptor.name,
        params=build_click_params_from_descriptor(descriptor),
        callback=lazy_wrapper,
        help=descriptor.docstring or None,
    )
