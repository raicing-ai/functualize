"""CLI delivery adapter using Click.

This module provides the CliAdapter that builds a ``click.Group`` command tree
from JobDescriptor instances and plugin commands. Command *parameter*
construction lives in ``app/adapters/click_params.py`` (job signatures + config
models) and ``app/adapters/lazy_command.py`` (cached descriptors); this module
owns the group tree, the global-options callback, help-panel rendering, and the
fallback routing chain. The adapter is click-native.

Public API:
- ``CliAdapter`` — composable adapter (accepts an external click.Group or builds its own)
- ``FallbackGroup`` — click.Group that routes unmatched commands to a fallback chain
- ``register_discovered_jobs()`` — standalone helper for job registration
- ``register_plugin_commands()`` — standalone helper for plugin CLI commands
- ``check_name_conflicts()`` — raises on plugin/job name collisions
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from functualize._app.state import AppState
from functualize._primitives.group_options_detection import (
    is_group_options_subclass,
)
from functualize._types.enums import EnvironmentSource
from functualize.app.adapters.click_params import (
    create_callback_click_command,
    create_job_click_command,
    invoke_command_capturing,
    make_duality_group,
)
from functualize.app.adapters.lazy_command import make_lazy_command

if TYPE_CHECKING:
    from pydantic import BaseModel

    from functualize._types.descriptors import JobDescriptor
    from functualize._types.naming import TrieNode
    from functualize.app.core import FunctualizeApp
    from functualize.app.fallback import FallbackCommand

logger = logging.getLogger(__name__)

# Default panel label for jobs without a metadata category
_DEFAULT_JOBS_PANEL = "Jobs"

# The attribute create_job_click_command / make_lazy_command results carry so
# the root group's help renderer can section them (rich_help_panel).
_PANEL_ATTR = "_functualize_panel"


# ─── Sub-group management ────────────────────────────────────────────────


def _make_pure_group(name: str) -> NormalizingGroup:
    """A payload-less navigation group under the default Jobs panel."""
    sub = NormalizingGroup(name=name)
    setattr(sub, _PANEL_ATTR, _DEFAULT_JOBS_PANEL)
    return sub


# ─── Groups ──────────────────────────────────────────────────────────────


class NormalizingGroup(click.Group):
    """click.Group that resolves a command name through the naming policy.

    Jobs register under their canonical name (``build-wheel``), so this is what
    lets ``build_wheel`` and ``buildWheel`` reach them from anyone holding the
    command group directly — the public ``app.cli_command``, an embedded runner, a
    test — without going through ``_cli.dispatch``.

    One command is registered, so ``--help`` shows one name and there is still
    exactly one identity. This is resolution, not aliasing: a total function
    from what was typed to the name that exists.
    """

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        command = super().get_command(ctx, name)
        if command is not None:
            return command

        from functualize.app.utils import normalize_segment

        canonical = normalize_segment(name)
        if canonical == name:
            return None
        return super().get_command(ctx, canonical)

    def format_commands(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        """Group subcommands into panels (the ``rich_help_panel`` replacement).

        Commands carry an optional panel label at ``_functualize_panel``; those
        without one fall under a default section. Preserves click's plain-text
        help while restoring panel grouping for sectioned help output.
        """
        # Iterate in registration order (self.commands preserves insertion),
        # not click's alphabetical list_commands — so panels appear in the order
        # their first command was registered (jobs before builtins, etc.).
        panels: dict[str, list[tuple[str, click.Command]]] = {}
        for subcommand, cmd in self.commands.items():
            if cmd.hidden:
                continue
            panel = getattr(cmd, _PANEL_ATTR, None) or "Commands"
            panels.setdefault(panel, []).append((subcommand, cmd))

        if not panels:
            return

        for panel_name, entries in panels.items():
            limit = formatter.width - 6 - max(len(n) for n, _ in entries)
            rows = []
            for subcommand, cmd in entries:
                help_str = cmd.get_short_help_str(limit)
                rows.append((subcommand, help_str))
            if rows:
                with formatter.section(panel_name):
                    formatter.write_dl(rows)


class FallbackGroup(NormalizingGroup):
    """click.Group that routes unrecognized commands to a fallback chain.

    When click doesn't recognize a command, instead of printing "No such
    command", this group intercepts the error and routes through the fallback
    chain stored in ``ctx.obj``.

    The fallback chain is expected at ``ctx.obj["fallbacks"]`` and the
    FunctualizeApp at ``ctx.obj["app"]``.

    Usage::

        cli_group = FallbackGroup(name="func")
    """

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """Resolve command, routing unmatched args to fallback."""
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as _exc:
            if "No such command" not in str(_exc):
                raise

            @click.command(name=args[0], hidden=True)
            @click.pass_context
            @click.argument("remaining_args", nargs=-1, type=click.UNPROCESSED)
            def _fallback_cmd(ctx: click.Context, remaining_args: tuple) -> None:  # type: ignore[type-arg]
                """Route through the fallback chain."""
                obj = ctx.parent.obj if ctx.parent else None
                if obj and isinstance(obj, dict):
                    all_args = [args[0], *remaining_args]
                    app_obj = obj.get("app")
                    fallbacks = obj.get("fallbacks", [])
                    exit_code = _run_fallback_chain(all_args, app_obj, fallbacks)
                    raise SystemExit(exit_code)
                _show_command_not_found(args[0], None)
                raise SystemExit(1)

            return args[0], _fallback_cmd, args[1:]


# ─── Panel derivation ────────────────────────────────────────────────────


def _get_job_panel(descriptor: JobDescriptor) -> str:
    """Derive rich_help_panel label from the job's declared category.

    If the job has a ``@job(category="...")`` declaration, the category string
    (title-cased) is used as the panel label. Otherwise falls back to the
    default "Jobs" panel.

    Args:
        descriptor: The JobDescriptor to inspect.

    Returns:
        Panel label string for the rich_help_panel kwarg.
    """
    if descriptor.declaration is not None and descriptor.declaration.category:
        return descriptor.declaration.category.title()
    return _DEFAULT_JOBS_PANEL


# ─── Validation-error rendering ──────────────────────────────────────────


def _config_source_hint(app: Any, job_name: str) -> str:
    """One line explaining where config for ``job_name`` was looked for.

    A missing required config field is indistinguishable, from the error
    alone, between "I set the wrong value" and "my config file was never
    read". The second is easy to hit: discovery anchors on files matching
    ``config.<slot>.<ext>``, so a plain ``config.toml`` does not anchor it,
    and the fallback to the user config directory is silent.
    """
    try:
        files = app.config_files(job_name)
    except Exception:  # introspection must never mask the real error
        return ""

    # The env spelling must be the one that actually resolves. It used to name
    # `JOB__<FIELD>`, which contradicted the guide, `builtin env` and
    # `info --job` — a suggestion naming a variable that sets nothing is worse
    # than no suggestion at all.
    env_hint = f"{job_name.upper().replace('-', '_').replace('.', '_')}_<FIELD>"

    if files:
        names = ", ".join(str(getattr(f, "path", f)) for f in files)
        # Naming the variable matters *most* here. When no file was found the
        # user at least knows the file is the problem; when files were read and
        # a field is still missing, "which files" alone does not say what to do
        # about it.
        return (
            f"Config files read: {names}\n"
            f"Set the missing field with {env_hint} in the environment, or add "
            f"it to the [{job_name}] section. `func builtin env {job_name}` "
            f"lists every variable and which are set."
        )
    return (
        "No config files were discovered. Files must be named "
        "config.<slot>.<ext> (e.g. config.base.toml) — a plain config.toml is "
        "not read, and <ext> must be one a registered format provider handles "
        f"(.toml by default; a plugin can register more). You can also set "
        f"{env_hint} in the environment."
    )


def _print_validation_error(job_name: str, error: Any, app: Any = None) -> None:
    """Print a Pydantic ValidationError as a clean Rich-formatted panel.

    Args:
        job_name: Job whose validation failed.
        error: The Pydantic ValidationError.
        app: When given, the panel also reports which config files were read,
            which is what distinguishes a bad value from an unread file.
    """
    from rich.text import Text

    console = Console(stderr=True)

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Field", style="cyan")
    table.add_column("Error", style="red")
    table.add_column("Input", style="yellow")

    for err in error.errors():
        field_path = " → ".join(str(loc) for loc in err["loc"]) if err["loc"] else "—"
        msg = err["msg"]
        input_val = err.get("input", "—")
        input_repr = repr(input_val) if input_val != "—" else "—"
        if len(input_repr) > 40:
            input_repr = input_repr[:37] + "..."
        table.add_row(field_path, msg, input_repr)

    error_count = error.error_count()
    title = Text.assemble(
        ("✗ ", "bold red"),
        ("Validation failed for ", ""),
        (job_name, "bold cyan"),
        (f" ({error_count} error{'s' if error_count != 1 else ''})", "dim"),
    )

    body: Any = table
    hint = _config_source_hint(app, job_name) if app is not None else ""
    if hint:
        from rich.console import Group

        body = Group(table, Text(""), Text(hint, style="dim"))

    console.print()
    console.print(Panel(body, title=title, title_align="left", border_style="red"))
    console.print()


# ─── Standalone public helpers ───────────────────────────────────────────


def _build_job_command(
    descriptor: JobDescriptor,
    app: FunctualizeApp,
    group_option_values: dict[str, Any] | None = None,
) -> tuple[click.Command, str]:
    """Build the click command for one job descriptor + its CLI command name.

    LazyJobFunction proxies must NOT go through the live builder — it would
    introspect the proxy's empty signature. The descriptor path reconstructs
    the CLI signature from cached metadata and defers the module import to
    invocation.
    """
    try:
        registered = app.job_registry.get_job(descriptor.name)
        func = registered.function
        config_class = registered.config_class
    except Exception:
        func = None
        config_class = None

    # Grouped jobs register under their bare function name inside the
    # sub-group; top-level jobs register under their canonical name.
    command_name = descriptor.func_name if descriptor.group else descriptor.name

    if func is not None and not getattr(func, "__functualize_lazy__", False):
        command: click.Command = create_job_click_command(
            name=descriptor.name,
            function=func,
            job_config_class=config_class,
            app=app,
            command_name=command_name,
            group_option_values=group_option_values,
        )
    else:
        command = make_lazy_command(
            descriptor,
            app,
            command_name=command_name,
            group_option_values=group_option_values,
        )

    setattr(command, _PANEL_ATTR, _get_job_panel(descriptor))
    return command, command_name


def _group_option_params(
    spec: Any,
    sink: dict[str, Any],
) -> tuple[list[click.Parameter], Callable[..., None]]:
    """Render a group's declared options as click params + a depositing callback.

    The **adapter** path — an app's own entry point, `glab deploy --env prod
    web run v1.2` — never reaches ``_cli/main``'s ``walk_group_path``: click
    owns the tree here and parses each group before it resolves the
    sub-command. Without params of its own a group answered
    ``Error: No such option '--env'`` for the one spelling the feature exists
    for, so `func` and an app's own script disagreed about the same project.

    The params come from ``build_click_params_from_fields`` — the same renderer the
    job path uses (C-D1) — so a group flag is spelled exactly as the identical
    job flag would be.

    ``sink`` is the mutable dict shared with every job command beneath this
    node. Only values click reports as coming from the **command line** are
    deposited: ``group_option_values`` is the CLI layer, which outranks the
    group's config file, so depositing a click *default* would silently beat
    `[deploy] env = "staging"` with the same string and, worse, beat a real
    file value with a declared default.
    """
    from functualize.app.adapters.click_params import build_click_params_from_fields

    params = build_click_params_from_fields(list(spec.fields))
    names = {p.name for p in params if p.name}

    def _deposit(**kwargs: Any) -> None:
        ctx = click.get_current_context()
        for key, value in kwargs.items():
            if key not in names:
                continue
            source = ctx.get_parameter_source(key)
            if source is not None and source.name != "COMMANDLINE":
                continue
            sink[key] = value

    return params, _deposit


def _register_trie_node(
    parent: click.Group,
    node: TrieNode,
    jobs_by_path: dict[str, JobDescriptor],
    app: FunctualizeApp,
    group_option_specs: dict[str, Any] | None = None,
    group_option_values: dict[str, Any] | None = None,
    path: str = "",
) -> None:
    """Recursively mirror one namespace-trie node into the click command tree.

    - A payload-bearing **leaf** → the job command attached under ``parent``.
    - A payload-bearing node **with children** → a duality group (spec §2.A(5))
      that runs the job when no sub-command is given and hosts the children.
    - A payload-less node → a pure navigation group.

    One ``NormalizingGroup`` is created *per path segment*, so a job declared
    with ``group="infra.aws"`` yields nested ``infra`` → ``aws`` groups rather
    than a single group literally named ``infra.aws``.
    """
    descriptor = jobs_by_path.get(node.payload) if node.payload is not None else None
    node_path = f"{path}.{node.segment}" if path else node.segment

    if descriptor is not None and node.is_leaf:
        command, command_name = _build_job_command(
            descriptor, app, group_option_values=group_option_values
        )
        parent.add_command(command, name=command_name)
        return

    if descriptor is not None:
        # Duality: runnable AND navigable.
        job_command, _ = _build_job_command(
            descriptor, app, group_option_values=group_option_values
        )
        group: click.Group = make_duality_group(
            job_command, name=node.segment, panel=_get_job_panel(descriptor)
        )
    else:
        group = _make_pure_group(node.segment)

    # Mid-path group options (S6a) for *this* node, if it declared any.
    spec = (group_option_specs or {}).get(node_path)
    if spec is not None and group_option_values is not None:
        extra_params, deposit = _group_option_params(spec, group_option_values)
        _attach_group_options(group, extra_params, deposit)

    parent.add_command(group, name=node.segment)
    for child in sorted(node.children.values(), key=lambda c: c.segment):
        _register_trie_node(
            group,
            child,
            jobs_by_path,
            app,
            group_option_specs=group_option_specs,
            group_option_values=group_option_values,
            path=node_path,
        )


def _attach_group_options(
    group: click.Group,
    params: list[click.Parameter],
    deposit: Callable[..., None],
) -> None:
    """Add a group's declared options and chain its depositing callback.

    A duality group already has a callback (it runs the job when no
    sub-command follows). Chaining rather than replacing keeps both: the
    deposit runs first, then whatever the group already did. The job callback
    is handed only the params it already knew about, so a group flag never
    arrives as a job kwarg it never declared.
    """
    existing = group.callback
    known = {p.name for p in group.params if p.name}
    group.params = [*group.params, *params]
    added = {p.name for p in params if p.name}

    def _chained(**kwargs: Any) -> Any:
        deposit(**{k: v for k, v in kwargs.items() if k in added})
        if existing is None:
            return None
        return existing(**{k: v for k, v in kwargs.items() if k in known})

    group.callback = _chained
    group.invoke_without_command = group.invoke_without_command or False


def register_discovered_jobs(
    cli_group: click.Group,
    app: FunctualizeApp,
) -> None:
    """Register all discovered jobs on a click.Group.

    Panel grouping is derived from each job's ``@job(category=...)``
    annotation. Jobs without a category go under the default "Jobs" panel.
    Jobs with a ``group`` (JOB_GROUP) are placed under nested sub-groups — one
    ``click.Group`` per dotted segment — by walking the namespace trie
    (``_types/naming.py``), the sole source of namespace shape. This is the same
    structure ``_cli/dispatch`` resolves against, so a group name is nested
    identically whether reached through ``app.cli_command`` or the dispatcher.

    Args:
        cli_group: The click.Group to register commands on.
        app: The FunctualizeApp with discovered jobs.
    """
    from pathlib import Path

    from functualize.app.utils import (
        build_group_trie,
        read_group_options_from_cache,
        resolve_cache_path,
    )

    jobs = app.get_jobs()
    jobs_by_path = {descriptor.name: descriptor for descriptor in jobs}

    trie = build_group_trie(
        [(descriptor.group, descriptor.name, "job") for descriptor in jobs],
        builtin=False,
    )

    # Mid-path group options (S6a). `get_jobs()` above is the scan that writes
    # this cache section, so reading it here is warm and import-free.
    try:
        group_option_specs = read_group_options_from_cache(
            resolve_cache_path(Path.cwd())
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("register_discovered_jobs: no group options (%s)", exc)
        group_option_specs = {}

    # One mutable dict for the whole invocation, shared by every group node
    # that can fill it and every job command that reads it. click parses a
    # group's params before it resolves the sub-command, so it is filled by
    # the time any job callback runs — which is why the values cannot simply
    # be baked into each command at construction time.
    group_option_values: dict[str, Any] = {}

    for node in sorted(trie.root.children.values(), key=lambda c: c.segment):
        _register_trie_node(
            cli_group,
            node,
            jobs_by_path,
            app,
            group_option_specs=group_option_specs,
            group_option_values=group_option_values,
        )


def register_plugin_commands(
    cli_group: click.Group,
    app: FunctualizeApp,
) -> dict[str, click.Group]:
    """Register all plugin-contributed commands on a click.Group.

    Args:
        cli_group: The click.Group to register commands on.
        app: The FunctualizeApp with registered plugin commands.

    Returns:
        Dict of namespace -> sub-group (for further customization if needed).
    """
    plugin_sub_groups: dict[str, click.Group] = {}

    for cmd in app.get_plugin_commands():
        command = create_callback_click_command(cmd.name, cmd.callback, cmd.help_text)
        if cmd.namespace is not None:
            if cmd.namespace not in plugin_sub_groups:
                sub = NormalizingGroup(name=cmd.namespace)
                cli_group.add_command(sub, name=cmd.namespace)
                plugin_sub_groups[cmd.namespace] = sub
            plugin_sub_groups[cmd.namespace].add_command(command, name=cmd.name)
        else:
            cli_group.add_command(command, name=cmd.name)

    return plugin_sub_groups


def check_name_conflicts(app: FunctualizeApp) -> None:
    """Raise ValueError if any plugin command name collides with a job name.

    Implements Requirement 11.5 — name conflict detection.

    Args:
        app: The FunctualizeApp to check.

    Raises:
        ValueError: If a top-level plugin command shares a name with a job.
    """
    job_names = {d.name for d in app.get_jobs()}
    for cmd in app.get_plugin_commands():
        if cmd.namespace is None and cmd.name in job_names:
            raise ValueError(
                f"Plugin command name '{cmd.name}' conflicts with "
                f"a registered job name. Sources: plugin command "
                f"'{cmd.name}' and job '{cmd.name}'"
            )


# ─── Fallback chain execution ────────────────────────────────────────────


def _run_fallback_chain(
    args: list[str],
    app: object,
    fallbacks: list[FallbackCommand],
) -> int:
    """Try each fallback in order; first match wins.

    Falls back to discovered jobs as a last resort (handles the timing
    issue where jobs are registered after Click's command resolution).
    """
    for fallback in fallbacks:
        if fallback.matches(args, app):  # type: ignore[arg-type]
            return fallback.execute(args, app)  # type: ignore[arg-type]

    # Last resort: route through discovered jobs
    cmd = args[0] if args else ""
    if cmd and app is not None:
        exit_code = _try_discovered_job(cmd, args[1:], app)
        if exit_code is not None:
            return exit_code

    _show_command_not_found(cmd, app)
    return 1


def _try_discovered_job(cmd: str, remaining_args: list[str], app: object) -> int | None:
    """Attempt to execute a discovered job by name. Returns exit code or None."""
    from functualize.app import FunctualizeApp

    if not isinstance(app, FunctualizeApp):
        return None

    jobs = app.get_jobs()
    matching = [j for j in jobs if j.name == cmd]
    if not matching:
        return None

    descriptor = matching[0]

    try:
        # Materializes lazy entries (imports only this job's module) and
        # returns the live function + detected config_class.
        registered = app.execution_engine.materialize_job(descriptor.name)
        func = registered.function
        config_class = registered.config_class
    except Exception:
        return None

    if func is None:
        return None

    command = create_job_click_command(
        name=descriptor.name,
        function=func,
        job_config_class=config_class,
        app=app,
        command_name=cmd,
    )
    return invoke_command_capturing(command, remaining_args, "none", prog_name=cmd)


def _show_command_not_found(cmd: str, app: object) -> None:
    """Print a 'command not found' error with suggestions."""
    print(f"Error: Command '{cmd}' not found.", file=sys.stderr)

    try:
        from functualize.app import FunctualizeApp

        if isinstance(app, FunctualizeApp):
            jobs = app.get_jobs()
            job_names = [j.name for j in jobs]
            suggestions = _find_similar(cmd, job_names)
            if suggestions:
                print("\nDid you mean:", file=sys.stderr)
                for s in suggestions[:3]:
                    print(f"  {s}", file=sys.stderr)
    except Exception:
        pass

    print("\nRun 'func --help' to see available commands.", file=sys.stderr)


def _find_similar(target: str, candidates: list[str]) -> list[str]:
    """Find candidates sharing prefix or substring with target."""
    if not target:
        return []

    matches: list[tuple[int, str]] = []
    target_lower = target.lower()

    for name in candidates:
        name_lower = name.lower()
        if name_lower.startswith(target_lower) or target_lower.startswith(name_lower):
            matches.append((0, name))
        elif target_lower in name_lower or name_lower in target_lower:
            matches.append((1, name))

    matches.sort(key=lambda x: x[0])
    return [m[1] for m in matches]


# ─── CliAdapter class ────────────────────────────────────────────────────


class CliAdapter:
    """CLI delivery adapter using Click.

    Satisfies the AdapterPlugin Protocol. Two modes of operation:

    1. **Self-contained** (no ``cli_group`` provided):
       Adapter creates its own ``click.Group`` with a standard callback
       (log-level, dotenv-file, config-directory, perf-report/perf-filter).
       Used by ``app.run()`` and ``app.cli_command``.

    2. **Composable** (``cli_group`` provided):
       Adapter populates an externally-owned ``click.Group``. The caller is
       responsible for the callback and early parsing. Adapter adds jobs,
       plugin commands, and show-info onto the provided group.

    In both modes the adapter:
    - Registers discovered jobs (panel derived from declaration.category)
    - Registers plugin commands
    - Validates name conflicts on run()
    - Optionally registers show-info
    - Optionally wires fallback routing via FallbackGroup
    """

    name: str = "functualize-cli"
    version: str = "1.0.0"
    description: str = "Built-in CLI adapter using Click"
    adapter_type: str = "cli"

    def __init__(self) -> None:
        self._app: FunctualizeApp | None = None
        self._cli_group: click.Group | None = None
        self._plugin_sub_groups: dict[str, click.Group] = {}
        self._fallbacks: list[FallbackCommand] = []

    def __call__(
        self,
        app: FunctualizeApp,
        *,
        cli_group: click.Group | None = None,
        fallbacks: list[FallbackCommand] | None = None,
        register_callback: bool | None = None,
        register_builtins: bool = True,
    ) -> None:
        """Setup phase — wire the click command tree from app state.

        Args:
            app: The FunctualizeApp with jobs, plugins, and config.
            cli_group: BYO click.Group. If None, adapter creates its own.
            fallbacks: Fallback handlers for unmatched commands.
            register_callback: Register the standard global-options callback.
                Defaults to True when cli_group is None, False otherwise.
            register_builtins: Mount the reserved ``builtin`` subtree (cache,
                config, domains, scaffold, info, state, why, …) at the trie's
                ``builtin`` node. There is no top-level ``show-info`` any more —
                it is ``func builtin info`` (convergence §4.1).
        """
        self._app = app
        self._fallbacks = fallbacks or []

        caller_owns_group = cli_group is not None

        if caller_owns_group:
            self._cli_group = cli_group
        else:
            # NormalizingGroup is the floor, not an upgrade: name resolution
            # must not depend on whether a fallback chain happens to be wired.
            group_cls = FallbackGroup if self._fallbacks else NormalizingGroup
            self._cli_group = group_cls(name=app.name, invoke_without_command=True)

        should_register_callback = (
            register_callback
            if register_callback is not None
            else not caller_owns_group
        )

        if should_register_callback:
            self._register_callback()

        assert self._cli_group is not None
        register_discovered_jobs(self._cli_group, app)
        self._plugin_sub_groups = register_plugin_commands(self._cli_group, app)

        if register_builtins:
            # Lazy import: builtins live in ``_cli`` (which sits above ``app``),
            # so import at call time to keep the module graph acyclic — the same
            # pattern ``click_params``/``tui`` already use for ``_cli`` seams.
            from functualize._cli.builtins import register_builtin_commands

            register_builtin_commands(self._cli_group)

    @property
    def cli_command(self) -> click.Group:
        """The underlying click command group this adapter populated."""
        if self._cli_group is None:
            raise RuntimeError("CliAdapter not initialized. Call adapter(app) first.")
        return self._cli_group

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the click CLI application.

        Validates name conflicts before invoking.
        """
        if self._cli_group is None:
            raise RuntimeError("CliAdapter.run() called before __call__(app)")

        if self._app is not None:
            check_name_conflicts(self._app)

        self._cli_group()

    def shutdown(self) -> None:
        """No-op shutdown."""
        pass

    # ─── Private: Callback ───────────────────────────────────────────────

    def _register_callback(self) -> None:
        """Register the standard group callback with global options.

        Handles: --log-level, --dotenv-file, --config-directory,
        --perf-report, --perf-filter. Also wires ctx.obj for FallbackGroup.
        """
        assert self._app is not None
        assert self._cli_group is not None

        from pathlib import Path

        app_instance = self._app
        fallbacks = self._fallbacks

        def _callback(
            log_level: str = "INFO",
            dotenv_file: Path | None = None,
            config_directory: Path | None = None,
            perf_report: str | None = None,
            perf_filter: str | None = None,
            **generated: Any,
        ) -> None:
            """Global options processed before any sub-command.

            ``**generated`` absorbs the flags built from settings declaring
            ``cli_flag`` (C3.1). They arrive by destination name, which is why
            the spec list is re-read here rather than passed down: it is the
            one place that knows flag → dotted-name.
            """
            import time as _time

            _apply_setting_overrides(generated)

            ctx = click.get_current_context()

            if perf_report is not None:
                fmt = perf_report if perf_report else "text"
                if fmt not in ("text", "json"):
                    click.echo(
                        f"Error: --perf-report accepts 'text' or 'json', got '{fmt}'",
                        err=True,
                    )
                    raise SystemExit(1)

                def _print_perf_report() -> None:
                    report = app_instance.perf_timeline.report()
                    if not report.marks:
                        click.echo("No performance data available.")
                        return
                    if fmt == "json":
                        click.echo(report.to_json(include=perf_filter))
                    else:
                        click.echo(report.summary(include=perf_filter))

                ctx.call_on_close(_print_perf_report)

            with contextlib.suppress(Exception):
                app_instance.event_bus.emit(
                    "cli.parse.start",
                    resource="",
                    argv_count=len(sys.argv),
                )

            _cli_parse_start = _time.perf_counter()

            level = log_level.upper()
            logging.basicConfig(level=level, force=True)

            if dotenv_file is not None:
                if not dotenv_file.exists() or not dotenv_file.is_file():
                    click.echo(
                        f"Error: dotenv file '{dotenv_file}' does not exist.",
                        err=True,
                    )
                    raise SystemExit(1)
                load_dotenv(dotenv_file)
                AppState.set("dotenv_path", str(dotenv_file))

            if config_directory is not None:
                if not config_directory.exists() or not config_directory.is_dir():
                    click.echo(
                        f"Error: config directory '{config_directory}' does not exist.",
                        err=True,
                    )
                    raise SystemExit(1)
                AppState.set("config_directory", str(config_directory))
                app_instance._config_path = str(config_directory)
                app_instance.refresh()
            else:
                app_instance.job_registry.update_config_paths()

            ctx.obj = {
                "app": app_instance,
                "fallbacks": fallbacks,
            }

            # Bare invocation of a self-contained app (C3.3). `func` itself
            # never reaches here — its bare path is handled pre-boot by
            # `_cli/main.py::_handle_bare`, which is why this is additive
            # rather than a change to func's behavior.
            if ctx.invoked_subcommand is None:
                _handle_bare_invocation(ctx, app_instance)

            _cli_parse_duration_ms = (_time.perf_counter() - _cli_parse_start) * 1000
            _command = ctx.invoked_subcommand or ""
            with contextlib.suppress(Exception):
                app_instance.event_bus.emit(
                    "cli.parse.end",
                    resource="",
                    command=_command,
                    duration_ms=_cli_parse_duration_ms,
                )

        self._cli_group.callback = _callback
        self._cli_group.invoke_without_command = True
        self._cli_group.params = [
            click.Option(
                ["--log-level"],
                default="INFO",
                help="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
            ),
            click.Option(
                ["--dotenv-file"],
                type=click.Path(path_type=Path),
                default=None,
                help="Path to the .env file to load environment variables from.",
            ),
            click.Option(
                ["--config-directory"],
                type=click.Path(path_type=Path),
                default=None,
                help=(
                    "Path to the config directory. When not specified, searches "
                    "upward from CWD for config files, then falls back to the "
                    "OS-specific user config directory."
                ),
            ),
            click.Option(
                ["--perf-report"],
                default=None,
                help="Print performance report after command. Format: text or json.",
            ),
            click.Option(
                ["--perf-filter"],
                default=None,
                help="Filter pattern for --perf-report.",
            ),
            *_generated_setting_options(),
            *self._cli_group.params,
        ]


# ─── Bare invocation: launch the shell, or print help (C3.3) ────────────


def _inline_tui_enabled() -> bool:
    """The `cli.inline_tui` setting — does a bare TTY invocation open a shell?

    Defaults to true, so a project app gets the shell without configuring
    anything. Setting it false is the opt-out for a tool that wants a bare
    invocation to behave like a conventional CLI and print its help.
    """
    from functualize._cli.data.func_settings import FuncSettingsStore

    try:
        value = FuncSettingsStore.discover().effective_values().get("cli.inline_tui")
    except (OSError, ValueError):
        return True
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def _bare_tty_available() -> bool:
    """Whether a bare invocation has a terminal to open a shell on."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _handle_bare_invocation(ctx: click.Context, app: FunctualizeApp) -> None:
    """Launch the inline shell for a bare invocation, or print help.

    Three cases, and only the first is new behavior:

    - TTY and ``cli.inline_tui`` on → launch the shell, exit with its code.
    - ``cli.inline_tui`` off → print help, exit 0. The opt-out has to win even
      at a TTY, or it would not be an opt-out.
    - No TTY → print help. There is no terminal to hand a shell, and a piped
      or CI invocation wants something parseable, not a refusal.
    """
    if not _inline_tui_enabled() or not _bare_tty_available():
        click.echo(ctx.get_help())
        ctx.exit(0)

    ctx.exit(_launch_shell(app))


def _launch_shell(app: FunctualizeApp) -> int:
    """Launch the inline shell and return its exit code.

    A one-line indirection so the three things this branch depends on
    (`_inline_tui_enabled`, `_bare_tty_available`, and the launcher) all live
    on *this* module. Patching `functualize._cli.inline_tui.launch_inline_tui`
    across module boundaries proved order-dependent under the full suite.
    """
    from functualize._cli.inline_tui import launch_inline_tui

    return launch_inline_tui(app)


# ─── Generated root flags from the settings schema (C3.1) ───────────────


def _setting_flag_specs() -> list[tuple[str, str, str, str]]:
    """``(flag, dest, dotted name, help)`` for every setting declaring a flag.

    Reads the **live** settings schema, so a flag declared by a setting the
    shell (or a project app's own component) registered is generated too — the
    catalog is a live view precisely so this cannot go stale.

    ``_cli`` is imported lazily here for the same reason
    ``register_builtin_commands`` is: ``_cli`` sits above ``app``, so a
    module-level import would make the graph cyclic.
    """
    from functualize._cli.data.func_settings import FUNC_SCHEMA

    specs: list[tuple[str, str, str, str]] = []
    for setting in FUNC_SCHEMA.settings:
        flag = setting.cli_flag
        if not flag:
            # The whole point of the field: a setting without one stays
            # file/env-only and must not appear in `--help`.
            continue
        dest = flag.lstrip("-").replace("-", "_")
        specs.append((flag, dest, setting.name, setting.description or ""))
    return specs


def _generated_setting_options() -> list[click.Option]:
    """Root options for settings that declare ``cli_flag``."""
    return [
        click.Option([flag], default=None, help=help_text)
        for flag, _dest, _name, help_text in _setting_flag_specs()
    ]


def _apply_setting_overrides(values: dict[str, Any]) -> None:
    """Feed passed generated flags into the settings store's top rung.

    Only flags actually given are recorded: ``None`` means "not passed", which
    must leave file/env resolution exactly as it was. That is what keeps an app
    declaring no flags byte-identical to one that never had this code.
    """
    from functualize._cli.data.func_settings import FuncSettingsStore

    overrides = [
        (name, values[dest], flag)
        for flag, dest, name, _help in _setting_flag_specs()
        if values.get(dest) is not None
    ]
    if not overrides:
        return

    store = FuncSettingsStore.discover()
    for name, value, flag in overrides:
        store.set_cli_override(name, str(value), flag=flag)
    AppState.set("settings_store", store)


# ─── Helper functions for show-info ─────────────────────────────────────


def _show_info_impl(
    app: FunctualizeApp,
    *,
    job: str | None = None,
    show_env_vars: bool = False,
) -> None:
    """Show current CLI configuration, discovered jobs, and resolved config.

    Standalone implementation callable from both CliAdapter._register_show_info
    and _cli/main.py's lazily-registered show-info command.
    """
    console = Console()

    log_level = logging.getLevelName(logging.getLogger().getEffectiveLevel())
    environment = app.active_environment()
    env_source = app.environment_source()
    config_dir = AppState.get("config_directory") or app._config_path

    # Say where it came from: "DEV (default)" and "DEV (ENVIRONMENT)" mean
    # very different things when an overlay file isn't taking effect.
    if env_source is EnvironmentSource.DEFAULT:
        environment_display = f"{environment} (default)"
    else:
        environment_display = f"{environment} (${env_source.value})"

    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="bold cyan")
    info_table.add_column("Value")
    info_table.add_row("Log Level", log_level)
    info_table.add_row("Environment", environment_display)
    info_table.add_row("Config Directory", str(config_dir))

    console.print(
        Panel(info_table, title="[bold]General Info[/bold]", border_style="green")
    )

    _print_config_files(app, console)

    registered = app.job_registry._registered_commands
    if registered:
        jobs_table = Table(title="Discovered Jobs", border_style="blue")
        jobs_table.add_column("Command", style="bold")
        jobs_table.add_column("Group (JOB_GROUP)", style="cyan")
        jobs_table.add_column("Module Path", style="dim")

        for registry_key, module_path in registered.items():
            group, command_name = registry_key.split("::", 1)
            group_display = group if group != "__top__" else "(top-level)"
            jobs_table.add_row(command_name, group_display, module_path)

        console.print(jobs_table)
    else:
        console.print("[yellow]No jobs discovered.[/yellow]")

    children = getattr(app, "child_projects", [])
    if children:
        children_table = Table(
            title="Child Projects (Hierarchical)", border_style="magenta"
        )
        children_table.add_column("Namespace", style="bold")
        children_table.add_column("Path", style="dim")
        children_table.add_column("Jobs Dirs", style="cyan")
        children_table.add_column("Config", style="green")

        for child in children:
            children_table.add_row(
                child.name,
                child.path,
                ", ".join(child.jobs_directories),
                child.config_path or "(none)",
            )

        console.print(children_table)
    else:
        console.print("[yellow]No child projects mounted.[/yellow]")

    if job is not None:
        _show_job_config(app, console, job_name=job)

    dotenv_path = AppState.get("dotenv_path")
    if dotenv_path:
        console.print(
            Panel(
                f"[bold]Path:[/bold] {dotenv_path}",
                title="[bold]Dotenv File[/bold]",
                border_style="magenta",
            )
        )
        try:
            with open(dotenv_path) as f:
                dotenv_content = f.read()
            syntax = Syntax(dotenv_content, "ini", theme="monokai", line_numbers=False)
            console.print(syntax)
        except OSError:
            console.print(f"[red]Could not read dotenv file: {dotenv_path}[/red]")
    else:
        console.print("[yellow]No dotenv file loaded.[/yellow]")

    if show_env_vars:
        env_table = Table(title="Environment Variables", border_style="yellow")
        env_table.add_column("Key", style="bold")
        env_table.add_column("Value")
        for key, value in sorted(os.environ.items()):
            env_table.add_row(key, value)
        console.print(env_table)


def _show_job_config(app: FunctualizeApp, console: Console, job_name: str) -> None:
    """Display resolved JobConfig values for a specific job."""
    matching_keys = [
        key
        for key in app.job_registry._registered_commands
        if key.endswith(f"::{job_name}") or key == f"__top__::{job_name}"
    ]

    if not matching_keys:
        available = [
            key.split("::", 1)[1] for key in app.job_registry._registered_commands
        ]
        console.print(f"[red]Error: Job '{job_name}' not found.[/red]")
        if available:
            console.print(f"[yellow]Available jobs: {', '.join(available)}[/yellow]")
        return

    job_config_class = _find_job_config_class(app, job_name)

    if job_config_class is None:
        console.print(
            Panel(
                f"[dim]Job '{job_name}' has no JobConfig declared.[/dim]",
                title=f"[bold]JobConfig: {job_name}[/bold]",
                border_style="blue",
            )
        )
        return

    config_table = Table(
        title=f"JobConfig: {job_name}",
        border_style="blue",
    )
    config_table.add_column("Field", style="bold")
    config_table.add_column("Value")
    config_table.add_column("Source", style="dim italic")

    from functualize._config.resolved_field import resolve_job_fields
    from functualize._types.redaction import display_value

    # One resolver. This used to be `_resolve_field_with_source`, a private
    # re-implementation that knew one env convention, skipped coercion, and so
    # could report a value the run would not use.
    try:
        from functualize._config.job_config import JobConfigView

        fields = resolve_job_fields(
            job_config_class,
            job_name,
            JobConfigView(
                resolution_chain=app._resolution_chain,
                default_section_prefix=job_name,
            ),
        )
    except Exception:  # introspection must never mask the real error
        fields = []

    for f in fields:
        if f.is_missing_required:
            # The state an operator most needs to see. It used to render as
            # `••• model default` for a secret and `PydanticUndefined` for a
            # plain field, because the guard tested `default is not None`, and
            # a Pydantic v2 required field's default is `PydanticUndefined` —
            # neither None nor Ellipsis, so the "not set" branch was
            # unreachable for every required field.
            display = "[bold red]not set[/bold red]"
            source = f"required — set {f.origin}"
        elif not f.is_set:
            display = "(none)"
            source = f"not set — set {f.origin}"
        else:
            # Mask on presence, not on value: an empty secret still reads as a
            # secret, so a viewer cannot infer "unset" from a blank cell.
            display = display_value(f.value, secret=f.secret)
            source = _describe_source(f)
        config_table.add_row(f.name, display, source)

    console.print(config_table)


def _secret_keys_for_section(app: Any, section: str) -> set[str]:
    """Field names the job owning ``section`` declares secret.

    Read from the cached ``FieldDescriptor``s — the same boot-free answer the
    TUI panels use — so listing config files never imports a job module.
    """
    try:
        descriptor = app.get_job(section)
    except Exception:
        return set()
    if descriptor is None:
        return set()
    fields = getattr(descriptor, "config_fields", None) or []
    return {f.name for f in fields if getattr(f, "secret", False)}


def _render_file_values(app: Any, values: dict[str, Any]) -> str:
    """A file's parsed contents as TOML text, with declared secrets masked.

    This panel used to be built with ``configparser`` and
    ``ExtendedInterpolation`` over ``os.environ``, rendered as ``ini``. Two
    things were wrong with that after ADR-007: the format is TOML, and every
    value was echoed verbatim — so a credential written into a config file
    appeared here in full, two panels above the ``JobConfig`` table that
    carefully masks the very same value. The interpolation made it worse by
    expanding ``${VAR}`` from the environment before printing.
    """
    from functualize._types.redaction import display_value

    lines: list[str] = []
    scalars = {k: v for k, v in values.items() if not isinstance(v, dict)}
    for key, value in scalars.items():
        lines.append(f"{key} = {value!r}")
    if scalars:
        lines.append("")

    for section, section_values in values.items():
        if not isinstance(section_values, dict):
            continue
        secret_keys = _secret_keys_for_section(app, section)
        lines.append(f"[{section}]")
        for key, value in section_values.items():
            shown = display_value(value, secret=key in secret_keys)
            lines.append(
                f"{key} = {shown!r}" if isinstance(value, str) else f"{key} = {shown}"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def _print_unreadable_config_file(path: str, console: Console) -> None:
    """Say that a config-shaped file is being ignored, and what to do about it.

    Silence is the failure mode this whole area exists to remove. A project
    whose only config was ``config.base.ini`` ran on model defaults after
    ADR-007 with no error, no warning, and this command — the one an operator
    reaches for to ask "what config is in effect?" — reporting "No config files
    found".
    """
    from pathlib import Path

    extension = Path(path).suffix or "(none)"
    # The path goes in the *body*, not only the title: Rich ellipsizes a title
    # that does not fit and wraps a body that does not, so on a long path a
    # title-only report names no file at all.
    console.print(
        Panel(
            f"[bold red]Not read[/bold red] — no config format provider is "
            f"registered for [bold]{extension}[/bold], so nothing in this file "
            f"takes effect.\n\n"
            f"[bold]{path}[/bold]\n\n"
            f"Convert it to TOML, or register a provider from a plugin — "
            f"plugins load before the resolution chain is built (ADR-007).",
            title="[bold]Unreadable config file[/bold]",
            border_style="red",
        )
    )


def _print_config_files(app: Any, console: Console) -> None:
    """One panel per discovered config file, including the ones nothing read.

    A file the kernel found but no ``FormatProvider`` could parse is reported
    rather than omitted. Omitting it is how a project whose only config is
    ``config.base.ini`` silently ran on model defaults after ADR-007 made TOML
    the sole registered format: no error, no warning, and this command — the
    one an operator reaches for to ask "what config is in effect?" — did not
    mention the file at all.
    """
    try:
        infos = app.config_files()
    except Exception:
        infos = []

    # Files that look like config but that no registered provider can read.
    # Reported separately because they never even reach FileSource: anchoring
    # rejects them on extension, so they carry no role and no rank.
    unreadable = list(getattr(app, "_unreadable_config_files", None) or [])

    if not infos and not unreadable:
        console.print("[yellow]No config files found.[/yellow]")
        return

    for path in unreadable:
        _print_unreadable_config_file(path, console)

    for info in infos:
        if not info.parsed:
            _print_unreadable_config_file(info.path, console)
            continue

        body = _render_file_values(app, info.values)
        console.print(
            Panel(
                Syntax(body, "toml", theme="monokai", line_numbers=False)
                if body
                else "[dim](empty)[/dim]",
                title=f"[bold]{info.path}[/bold]",
                border_style="cyan",
            )
        )


def _describe_source(f: Any) -> str:
    """How `info --job` names where a value came from."""
    if f.source == "env":
        return f"env var ({f.origin})"
    if f.source == "default":
        return "model default"
    if f.source == "cli":
        return "CLI argument"
    return f"{f.source} ({f.origin})" if f.origin else f.source


def _find_job_config_class(
    app: FunctualizeApp, job_name: str
) -> type[BaseModel] | None:
    """Find the JobConfig class for a given job name.

    Primary source is the engine's RegisteredJob entry (populated at
    registration for live functions, at materialization for warm-cached
    lazy entries). Falls back to importing the job module and inspecting
    the function signature for entries the engine doesn't know.
    """
    import importlib

    from pydantic import BaseModel

    try:
        entry = app._execution_engine.materialize_job(job_name)
        if entry.config_class is not None:
            return entry.config_class
        return None
    except Exception:
        # Not in the engine registry (or materialization failed) — fall
        # back to the legacy module-scraping path below.
        pass

    for registry_key, module_path in app.job_registry._registered_commands.items():
        _, command_name = registry_key.split("::", 1)
        if command_name != job_name:
            continue

        try:
            if module_path in sys.modules:
                module = sys.modules[module_path]
            else:
                module = importlib.import_module(module_path)
        except Exception:
            continue

        func = getattr(module, job_name, None)
        if func is None or not callable(func):
            continue

        sig = inspect.signature(func)
        for param in sig.parameters.values():
            annotation = param.annotation
            if annotation is inspect.Parameter.empty:
                continue
            if (
                isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
                and annotation is not BaseModel
                # A GroupOptions parameter carries the *group's* flags, not
                # this job's config fields (see _discovery/sync.py).
                and not is_group_options_subclass(annotation)
            ):
                return annotation

    return None


__all__ = [
    "CliAdapter",
    "FallbackGroup",
    "NormalizingGroup",
    "_show_info_impl",
    "check_name_conflicts",
    "register_discovered_jobs",
    "register_plugin_commands",
]
