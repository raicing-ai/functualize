"""CLI entry point and unified routing.

Deterministic direct-dispatch architecture: classifies every CLI invocation
into one of five modes (SINGLE_FILE, BUILTIN, JOB, BARE, UNKNOWN) before
any application boot occurs, then routes to the appropriate handler.

No FallbackGroup, no exception-based routing, no CliAdapter in the critical path.

This module imports ONLY from public API packages.
"""

from __future__ import annotations

# Record earliest possible timestamp before any heavy imports
import time as _time

_module_import_start_ns = _time.perf_counter_ns()

import contextlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import click
except ModuleNotFoundError as exc:  # pragma: no cover - no-extra install only
    # The `func`/`functualize` console scripts are declared unconditionally,
    # but click lives in the `cli` extra. Without this guard a bare
    # `pip install functualize` gives first-time users a raw traceback.
    if exc.name != "click":
        raise
    sys.stderr.write(
        "functualize: the `func` command requires the CLI extra, "
        "which is not installed.\n\n"
        "    pip install 'functualize[cli]'\n\n"
    )
    raise SystemExit(1) from None

logger = logging.getLogger(__name__)

# ─── click group for BUILTIN mode (plain Group, no FallbackGroup) ────────


class _LeftMarginEpilogGroup(click.Group):
    """The root ``func`` group, carrying the agent block at the left margin.

    The rendering rule and the text both live in
    ``_primitives/agent_epilog.py``; this is only the click seam. The
    adapter's ``AgentEpilogGroup`` is the same three lines over the same
    helper — sharing the *class* instead would mean importing
    ``app/adapters/cli.py`` (and rich) at ``main.py`` import time, which is
    what the lazy-boot work exists to avoid.

    Imported inside the method, not at module scope, for the same reason: a
    warm boot must not pay for help text nobody asked to render.
    """

    def format_epilog(self, ctx: click.Context, formatter: Any) -> None:
        from functualize.app.utils import write_agent_epilog

        write_agent_epilog(ctx.find_root().info_name or "func", formatter)


@click.group(
    name="func",
    cls=_LeftMarginEpilogGroup,
    invoke_without_command=True,
)
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
)
@click.option(
    "--dotenv-file",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to the .env file to load environment variables from.",
)
@click.option(
    "--no-dotenv",
    is_flag=True,
    default=False,
    help="Suppress .env file loading entirely.",
)
@click.option(
    "--config-directory",
    default=None,
    type=click.Path(path_type=Path),
    help=(
        "Path to the config directory. When not specified, searches upward from "
        "CWD for config files, then falls back to the OS-specific user config "
        "directory."
    ),
)
@click.option(
    "--discovery-depth",
    default=None,
    type=int,
    help="Max directory levels below CWD to scan for jobs (0-5).",
)
@click.option(
    "--require-file-import",
    default=None,
    help="Only discover files that import this module.",
)
@click.option(
    "--require-file-prefix",
    default=None,
    help="Only discover files whose name starts with this prefix.",
)
@click.option(
    "--require-file-postfix",
    default=None,
    help="Only discover files whose name ends with this postfix.",
)
@click.option(
    "--require-file-marker",
    default=None,
    help="Only discover files declaring this module-level marker variable.",
)
@click.option(
    "--require-job-prefix",
    default=None,
    help="Only discover jobs whose function name starts with this prefix.",
)
@click.option(
    "--require-job-postfix",
    default=None,
    help="Only discover jobs whose function name ends with this postfix.",
)
@click.option(
    "--require-job-decorators",
    multiple=True,
    help="Only discover jobs decorated with these decorator names.",
)
@click.option(
    "--exclude",
    multiple=True,
    help="Glob patterns to exclude from discovery (max 20).",
)
@click.option(
    "--perf-report",
    default=None,
    help="Print performance report after command. Format: text or json.",
)
@click.option(
    "--perf-filter",
    default=None,
    help="Filter pattern for --perf-report.",
)
@click.option(
    "--import-libs",
    multiple=True,
    help="Directories to add to sys.path before importing jobs.",
)
@click.pass_context
def cli_app(
    ctx: click.Context,
    log_level: str,
    dotenv_file: Path | None,
    no_dotenv: bool,
    config_directory: Path | None,
    discovery_depth: int | None,
    require_file_import: str | None,
    require_file_prefix: str | None,
    require_file_postfix: str | None,
    require_file_marker: str | None,
    require_job_prefix: str | None,
    require_job_postfix: str | None,
    require_job_decorators: tuple[str, ...],
    exclude: tuple[str, ...],
    perf_report: str | None,
    perf_filter: str | None,
    import_libs: tuple[str, ...],
) -> None:
    """Functualize CLI — run jobs from anywhere."""
    import contextlib
    import time as _time

    # ── Validation ───────────────────────────────────────────────────────

    if len(exclude) > 20:
        click.echo(
            f"Error: --exclude accepts at most 20 patterns, got {len(exclude)}.",
            err=True,
        )
        raise SystemExit(1)

    if dotenv_file is not None and (
        not dotenv_file.exists() or not dotenv_file.is_file()
    ):
        click.echo(
            f"Error: --dotenv-file '{dotenv_file}' does not exist.",
            err=True,
        )
        raise SystemExit(1)

    if config_directory is not None and (
        not config_directory.exists() or not config_directory.is_dir()
    ):
        click.echo(
            f"Error: --config-directory '{config_directory}' does not exist.",
            err=True,
        )
        raise SystemExit(1)

    # ── Perf report setup ────────────────────────────────────────────────

    if perf_report is not None:
        fmt = perf_report if perf_report else "text"
        if fmt not in ("text", "json"):
            click.echo(
                f"Error: --perf-report accepts 'text' or 'json', got '{fmt}'",
                err=True,
            )
            raise SystemExit(1)

        _perf_filter = perf_filter

        def _print_perf_report() -> None:
            app_obj = ctx.obj
            if app_obj is None:
                return
            from functualize.app import FunctualizeApp

            _app: FunctualizeApp | None = app_obj.get("app")
            if _app is None:
                return
            report = _app.perf_timeline.report()
            if not report.marks:
                click.echo("No performance data available.")
                return
            if fmt == "json":
                click.echo(report.to_json(include=_perf_filter))
            else:
                click.echo(report.summary(include=_perf_filter))

        ctx.call_on_close(_print_perf_report)

    # ── Logging initialization ───────────────────────────────────────────

    _cli_parse_start = _time.perf_counter()
    level = log_level.upper()
    logging.basicConfig(level=level, force=True)

    # ── Boot app context for builtins that need it (show-info, tui) ──────

    from functualize._cli.config import resolve_cli_config
    from functualize.app import FunctualizeApp
    from functualize.app.config import ConfigSources
    from functualize.app.utils import auto_discover

    # Build CLI flags dict for resolve_cli_config
    cli_flags: dict[str, object] = {}
    if require_file_import is not None:
        cli_flags["require_file_import"] = require_file_import
    if require_file_prefix is not None:
        cli_flags["require_file_prefix"] = require_file_prefix
    if require_file_postfix is not None:
        cli_flags["require_file_postfix"] = require_file_postfix
    if require_file_marker is not None:
        cli_flags["require_file_marker"] = require_file_marker
    if require_job_prefix is not None:
        cli_flags["require_job_prefix"] = require_job_prefix
    if require_job_postfix is not None:
        cli_flags["require_job_postfix"] = require_job_postfix
    if require_job_decorators:
        cli_flags["require_job_decorators"] = list(require_job_decorators)
    if exclude:
        cli_flags["exclude_patterns"] = list(exclude)
    if import_libs:
        cli_flags["import_libs"] = list(import_libs)

    cli_config = resolve_cli_config(cli_flags=cli_flags)

    # ── .env loading ─────────────────────────────────────────────────────
    # Resolved config drives dotenv behavior, so this must come after
    # resolve_cli_config. Consequence: .env values cannot influence the
    # CLI config resolution itself (documented limitation).

    _load_dotenv(
        dotenv_enabled=cli_config.dotenv,
        dotenv_path=cli_config.dotenv_path,
        dotenv_file_flag=str(dotenv_file) if dotenv_file is not None else None,
        no_dotenv_flag=no_dotenv,
    )

    # Apply import_libs to sys.path before app construction
    _apply_import_libs(cli_config.import_libs)

    # Resolve scan_depth: CLI flag > config > default (0)
    if discovery_depth is not None:
        effective_scan_depth = discovery_depth
    else:
        effective_scan_depth = cli_config.scan_depth

    cwd = Path.cwd()
    discovery_result = auto_discover(
        cwd, overrides={"scan_depth": effective_scan_depth}
    )

    # Construct FunctualizeApp
    app = FunctualizeApp(
        name="functualize",
        job_sources=discovery_result.job_sources,
        discovery_config=cli_config.discovery,
        config_sources=ConfigSources(
            dotenv=cli_config.dotenv,
            dotenv_path=cli_config.dotenv_path,
        ),
    )

    # Wire config_directory on the app if provided
    if config_directory is not None:
        app._config_path = str(config_directory)
        app.refresh()
    else:
        app.job_registry.update_config_paths()

    # ── Wire ctx.obj for builtin commands that need app context ───────────

    ctx.obj = {
        "app": app,
        "cli_config": cli_config,
        "anchor": cli_config.anchor,
    }

    # ── Emit parse event ─────────────────────────────────────────────────

    _cli_parse_duration_ms = (_time.perf_counter() - _cli_parse_start) * 1000
    _command = ctx.invoked_subcommand or ""
    with contextlib.suppress(Exception):
        app.event_bus.emit(
            "cli.parse.end",
            resource="",
            command=_command,
            duration_ms=_cli_parse_duration_ms,
        )

    # ── Bare invocation (shouldn't reach here in new architecture) ───────
    # In the new flow, BARE mode is handled by _handle_bare() directly.
    # This only triggers if Click is invoked for BUILTIN mode but no
    # subcommand was provided (e.g. `func --log-level DEBUG` with no command).
    if ctx.invoked_subcommand is None:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()
        if is_tty:
            from functualize._cli.inline_tui import launch_inline_tui

            exit_code = launch_inline_tui(app)
            raise SystemExit(exit_code)
        else:
            # Non-TTY: print discovered jobs as parseable list
            jobs = app.get_jobs()
            if jobs:
                for job in sorted(jobs, key=lambda j: j.name):
                    desc = ""
                    if job.docstring:
                        desc = job.docstring.strip().split("\n")[0]
                    if desc:
                        click.echo(f"{job.name} — {desc}")
                    else:
                        click.echo(job.name)
            else:
                click.echo("No jobs discovered.")
            raise SystemExit(0)


# ─── Dotenv loading ──────────────────────────────────────────────────────


def _load_dotenv(
    *,
    dotenv_enabled: bool,
    dotenv_path: str | None,
    dotenv_file_flag: str | None,
    no_dotenv_flag: bool,
) -> str | None:
    """Load a .env file based on resolved configuration and CLI flags.

    Resolution logic:
    1. ``--no-dotenv`` flag suppresses all loading → returns None.
    2. ``--dotenv-file`` flag takes precedence: load that path.
    3. If ``dotenv_path`` is set in config: load that path (opportunistic).
    4. If ``dotenv_enabled`` is True: auto-discover .env from CWD.

    Returns the path of the loaded .env file, or None if nothing was loaded.
    """
    if no_dotenv_flag:
        return None

    from dotenv import load_dotenv

    if dotenv_file_flag is not None:
        explicit_path = Path(dotenv_file_flag)
        if not explicit_path.is_file():
            print(
                f"Error: --dotenv-file '{dotenv_file_flag}' does not exist.",
                file=sys.stderr,
            )
            sys.exit(1)
        load_dotenv(str(explicit_path), override=False)
        return str(explicit_path)

    if dotenv_path is not None:
        config_path = Path(dotenv_path)
        if config_path.is_file():
            load_dotenv(str(config_path), override=False)
            return str(config_path)
        print(
            f"Warning: dotenv_path '{dotenv_path}' not found, skipping.",
            file=sys.stderr,
        )
        return None

    if dotenv_enabled:
        cwd_env = Path.cwd() / ".env"
        if cwd_env.is_file():
            load_dotenv(str(cwd_env), override=False)
            return str(cwd_env)
        return None

    return None


# ─── Import libs sys.path insertion ──────────────────────────────────────


def _apply_import_libs(import_libs: tuple[str, ...] | list[str]) -> None:
    """Insert import_libs paths into sys.path.

    Inserts each path at the front of sys.path (in order), skipping
    paths that are already present. All paths should be absolute.

    Args:
        import_libs: Tuple/list of absolute path strings to insert.
    """
    for path_str in reversed(import_libs):
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


def _print_perf_report(app: Any, fmt: str, filter_pattern: str | None) -> None:
    """Print performance report to stderr.

    Mirrors the perf report logic in ``_builtin_callback()`` but writes
    to stderr so piped stdout is never contaminated.

    Args:
        app: A FunctualizeApp instance (or any object with perf_timeline).
        fmt: Report format — "text" or "json".
        filter_pattern: Optional prefix filter for phases.
    """
    from functualize.app import FunctualizeApp

    if not isinstance(app, FunctualizeApp):
        return
    report = app.perf_timeline.report()
    if not report.marks:
        return
    if fmt == "json":
        print(report.to_json(include=filter_pattern), file=sys.stderr)
    else:
        print(report.summary(include=filter_pattern), file=sys.stderr)


def _handle_bare(
    anchor: Path,
    merged_config: dict[str, Any],
    effective: dict[str, list[str]],
    cli_flags: dict[str, Any],
    *,
    _app_ref: list[Any] | None = None,
) -> None:
    """Handle bare ``func`` invocation (no positional arguments).

    TTY: launch interactive TUI.
    Non-TTY: print parseable job list (one per line).

    Args:
        anchor: Project anchor directory.
        merged_config: Merged project config dict.
        effective: Resolved effective directories.
        cli_flags: Parsed global CLI flags for resolve_cli_config.
        _app_ref: Optional mutable container; if provided, the constructed
            FunctualizeApp is appended so callers can access it for perf reporting.
    """
    from functualize._cli.config import resolve_cli_config
    from functualize.app import FunctualizeApp
    from functualize.app.config import ConfigSources, JobSources, PluginSources

    # Apply import_libs to sys.path before importing job modules
    _apply_import_libs(effective.get("import_libs", []))

    # Boot FunctualizeApp using already-resolved effective directories
    cli_config = resolve_cli_config(cli_flags=cli_flags)

    _base_dirs = list(effective.get("all_directories") or effective["jobs_directories"])
    job_sources = JobSources(
        directories=_base_dirs
        + (
            [str(Path.cwd().resolve())]
            if str(Path.cwd().resolve()) not in _base_dirs
            else []
        ),
        lazy=True,
    )

    # Extract disabled plugins from config
    _plugins_section = merged_config.get("plugins")
    _disabled_plugins = (
        list(_plugins_section.get("disabled", []))
        if isinstance(_plugins_section, dict)
        else []
    )

    # Detect TTY early — if interactive, suppress log output to stderr
    # during the entire app boot + TUI session. Log lines printed to the
    # terminal corrupt Textual's inline line-position tracking.
    is_tty = sys.stdin.isatty() and sys.stdout.isatty()

    if is_tty:
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers = [
            h
            for h in root_logger.handlers
            if not isinstance(h, logging.StreamHandler)
            or getattr(h, "stream", None) not in (sys.stderr, sys.stdout)
        ]

    app = FunctualizeApp(
        name="functualize",
        job_sources=job_sources,
        discovery_config=cli_config.discovery,
        config_sources=ConfigSources(
            dotenv=cli_config.dotenv,
            dotenv_path=cli_config.dotenv_path,
        ),
        plugin_sources=PluginSources(disabled=_disabled_plugins)
        if _disabled_plugins
        else None,
    )

    # Deposit app reference for perf reporting by caller
    if _app_ref is not None:
        _app_ref.append(app)

    if is_tty:
        from functualize._cli.inline_tui import launch_inline_tui

        try:
            exit_code = launch_inline_tui(app)
        finally:
            root_logger.handlers = original_handlers
        raise SystemExit(exit_code)

    # Non-TTY: print parseable job list
    jobs = app.get_jobs()
    plugin_commands = list(app.get_plugin_commands())
    if not jobs and not plugin_commands:
        click.echo("No jobs discovered.")
        return

    for job in sorted(jobs, key=lambda j: j.name):
        desc = ""
        if job.docstring:
            desc = job.docstring.strip().split("\n")[0]
        if desc:
            click.echo(f"{job.name} — {desc}")
        else:
            click.echo(job.name)

    # Plugin-registered command namespaces + un-namespaced commands (post-boot).
    namespace_counts: dict[str, int] = {}
    for cmd in plugin_commands:
        namespace = getattr(cmd, "namespace", None)
        if namespace is None:
            desc = (cmd.help_text or "").strip()
            click.echo(f"{cmd.name} — {desc}" if desc else cmd.name)
        else:
            top = namespace.split(".")[0]
            namespace_counts[top] = namespace_counts.get(top, 0) + 1
    for namespace in sorted(namespace_counts):
        n = namespace_counts[namespace]
        plural = "s" if n != 1 else ""
        click.echo(
            f"{namespace} — {n} command{plural} (run 'func {namespace}' to list)"
        )


#: Job-level discovery settings. Their presence anywhere — env, project config,
#: or CLI flag — is what makes the pre-boot routing read pay for a full config
#: resolution; when none is in play the fast path stays untouched.
_JOB_LEVEL_SETTINGS = (
    "require_job_prefix",
    "require_job_postfix",
    "require_job_decorators",
)


def _build_routing_job_filter(
    cli_flags: dict[str, Any], merged_config: dict[str, Any]
) -> Any:
    """Build the job-level filter for pre-boot routing, or None if unused.

    Routing reads job names straight from the discovery cache, which is written
    as a superset (job-level filters apply on read). Without applying the same
    filter here, ``func <name>`` would route to a job the booted app refuses to
    resolve, and completions would offer jobs that cannot run.

    Resolving the full config costs more than the ~3ms routing read allows, so
    it is only done when a job-level setting is actually configured somewhere.
    """
    discovery_section = merged_config.get("discovery")
    if not isinstance(discovery_section, dict):
        discovery_section = {}

    import os

    in_play = any(
        key in cli_flags
        or key in discovery_section
        or f"FUNCTUALIZE_DISCOVERY_{key.upper()}" in os.environ
        for key in _JOB_LEVEL_SETTINGS
    )
    if not in_play:
        return None

    from functualize._cli.config import resolve_cli_config
    from functualize.app.utils import build_job_filter

    cli_config = resolve_cli_config(cli_flags=cli_flags)
    return build_job_filter(cli_config.discovery)


def _extract_aliases(merged_config: dict[str, Any]) -> dict[str, str]:
    """Extract user-configured aliases: global config, then project config.

    Precedence (lowest -> highest): ``~/.config/functualize/config.toml``
    ``[aliases]``, then project-file ``[aliases]`` — mirroring the precedence
    ``resolve_cli_config`` applies for ``config show``. Direct job names still
    win over any alias (``detect_mode`` checks job names first).

    Aliases are a *user* concern only. ``@job(aliases=)`` used to supply a
    base layer beneath these; it was removed, because an author-declared
    alternate spelling is a second name for one job, and one job having two
    names is the divergence this codebase keeps paying for. A user who wants a
    short name says so in their own config, where it cannot surprise anyone
    reading the job.

    Args:
        merged_config: The merged project configuration dictionary
            (from ``auto_discover``).

    Returns:
        Mapping of alias name -> target job name.
    """
    import tomllib

    from functualize.app.utils import resolve_user_config_dir

    result: dict[str, str] = {}

    try:
        content = (resolve_user_config_dir() / "config.toml").read_bytes()
        global_aliases = tomllib.loads(content.decode("utf-8")).get("aliases")
        if isinstance(global_aliases, dict):
            result.update(global_aliases)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        pass

    aliases = merged_config.get("aliases")
    if isinstance(aliases, dict):
        result.update(aliases)
    return result


# ─── Unknown command handling ────────────────────────────────────────────


def _levenshtein(s: str, t: str) -> int:
    """Compute Levenshtein distance between two strings.

    Uses the standard dynamic programming approach with O(min(m, n)) space.

    Args:
        s: First string.
        t: Second string.

    Returns:
        Edit distance (insertions + deletions + substitutions).
    """
    if len(s) < len(t):
        return _levenshtein(t, s)

    if not t:
        return len(s)

    previous_row = list(range(len(t) + 1))
    for i, sc in enumerate(s):
        current_row = [i + 1]
        for j, tc in enumerate(t):
            # Cost is 0 if characters match, 1 otherwise
            cost = 0 if sc == tc else 1
            current_row.append(
                min(
                    current_row[j] + 1,  # insertion
                    previous_row[j + 1] + 1,  # deletion
                    previous_row[j] + cost,  # substitution
                )
            )
        previous_row = current_row

    return previous_row[-1]


def _fuzzy_suggest(cmd: str, job_names: set[str], max_results: int = 5) -> list[str]:
    """Compute fuzzy suggestions for an unknown command.

    Strategy (scored, highest first):
    1. Exact prefix match (score=3): job starts with cmd
    2. Substring match (score=2): cmd is contained within job name
    3. Levenshtein distance ≤ 2 (score=1): handles transpositions/typos

    Args:
        cmd: The unrecognized command string.
        job_names: Set of valid job names to search.
        max_results: Maximum number of suggestions to return.

    Returns:
        Up to *max_results* suggestions sorted by score descending,
        then alphabetically for ties.
    """
    scored: list[tuple[int, str]] = []
    for name in job_names:
        if name.startswith(cmd):
            scored.append((3, name))
        elif cmd in name:
            scored.append((2, name))
        elif _levenshtein(cmd, name) <= 2:
            scored.append((1, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored[:max_results]]


def _handle_unknown(args: list[str], job_names: set[str]) -> None:
    """Print 'command not found' with fuzzy suggestions.

    Does NOT boot FunctualizeApp — provides instant feedback for typos.

    Args:
        args: [unknown_command, ...remaining]. Only args[0] is used.
        job_names: Set of valid job names for suggestion matching.
    """
    cmd = args[0] if args else ""

    print(f"Error: Unknown command '{cmd}'.", file=sys.stderr)

    suggestions = _fuzzy_suggest(cmd, job_names)
    if suggestions:
        print("\nDid you mean:", file=sys.stderr)
        for suggestion in suggestions:
            print(f"  func {suggestion}", file=sys.stderr)
        print(file=sys.stderr)

    print("Run 'func' to see all available commands.", file=sys.stderr)


# ─── Group handler ───────────────────────────────────────────────────────


def _plugin_namespace_names(plugin_commands: list[Any]) -> set[str]:
    """Return namespaces (plus dotted ancestor prefixes) of plugin commands.

    Plugin commands registered at APP_READY (e.g. the ``mcp`` namespace) are
    invisible to pre-boot mode detection, which only AST-scans jobs for
    ``JOB_GROUP``. This mirrors the ancestor-expansion done for job groups
    (see ``utils.read_routing_names_from_cache``) so a dotted plugin namespace
    like ``a.b.c`` also registers ``a`` and ``a.b`` as navigable prefixes.

    Args:
        plugin_commands: Result of ``app.get_plugin_commands()`` (duck-typed;
            each item exposes a ``namespace`` attribute).

    Returns:
        Set of namespace names including every ancestor prefix.
    """
    names: set[str] = set()
    for cmd in plugin_commands:
        namespace = getattr(cmd, "namespace", None)
        if not namespace:
            continue
        parts = namespace.split(".")
        for i in range(1, len(parts) + 1):
            names.add(".".join(parts[:i]))
    return names


def _job_trie_path(job: Any) -> str:
    """The dotted path a job occupies in the group trie.

    Normally just ``job.name``, which already carries its group as a prefix.
    Mirrors the trie's own leaf derivation for the degenerate case where a
    descriptor's ``group`` is not a prefix of its ``name`` — there the trie
    nests the whole name under the group, and a lookup keyed on ``name`` alone
    would miss it.
    """
    group = getattr(job, "group", None)
    if group and not job.name.startswith(f"{group}."):
        return f"{group}.{job.name}"
    return str(job.name)


def _run_adhoc_command(
    name: str,
    fn: Any,
    remaining_args: list[str],
    output_format: str,
    *,
    help_text: str | None = None,
) -> int:
    """Execute a raw plugin callback through an ad-hoc one-off click.Command.

    Mirrors ``register_plugin_commands`` (``adapters/click_params.py``): builds
    a click command directly from the callback's signature and captures its
    return value for ``--output`` parity. Jobs go through
    ``create_job_click_command`` at their call sites instead.

    Args:
        name: The command name to register the callback under.
        fn: The raw plugin callback (its signature drives option parsing).
        remaining_args: CLI args passed after the command name.
        output_format: The ``--output`` flag value (json, text, or none).
        help_text: Optional help string.

    Returns:
        Exit code (0 = success).
    """
    from functualize.app.adapters.click_params import (
        create_callback_click_command,
        invoke_command_capturing,
    )

    command = create_callback_click_command(name, fn, help_text)
    return invoke_command_capturing(
        command, remaining_args, output_format, prog_name=name, emit_return=True
    )


def _materialize_for_dispatch(
    app: Any, job_descriptor: Any
) -> tuple[Any, Any, str | None]:
    """Resolve a live function + config_class for a descriptor via the engine.

    Under lazy boot (warm cache) descriptors carry ``function=None``; the
    engine materializes the registered entry, importing ONLY the target
    job's module. Falls back to the descriptor's own live function when
    the engine doesn't know the job (exotic provider paths).

    Returns:
        (function, config_class, None) on success;
        (None, None, error_message) on failure.
    """
    from functualize.app.utils import DIValidationError, JobMaterializationError

    try:
        registered = app.execution_engine.materialize_job(job_descriptor.name)
        return registered.function, registered.config_class, None
    except KeyError:
        if job_descriptor.function is not None:
            return job_descriptor.function, None, None
        return None, None, "job is not registered with the execution engine"
    except (JobMaterializationError, DIValidationError) as exc:
        return None, None, str(exc)


def _render_group_option_rows(specs: list[Any]) -> list[tuple[str, str]]:
    """``(flag spelling, help)`` rows for a group listing's Options section.

    Rendered from the **click parameters** the same fields produce, not from a
    second reading of the cached records (C-D1): the listing then cannot
    describe a flag differently from the way it parses. A bool's negative form
    is shown too, since click accepts it.
    """
    from functualize.app.adapters.click_params import build_click_params_from_fields

    rows: list[tuple[str, str]] = []
    for spec in specs:
        for param in build_click_params_from_fields(spec.fields):
            opts = list(param.opts) + list(param.secondary_opts)
            flag = ", ".join(opts) if opts else param.name or ""
            metavar = getattr(param, "is_flag", False)
            if not metavar and param.type is not None:
                type_name = getattr(param.type, "name", "").upper()
                if type_name and type_name != "BOOLEAN":
                    flag = f"{flag} {type_name}"
            rows.append((flag, getattr(param, "help", "") or ""))
    return rows


def _dispatch_group(
    app: Any,
    args: list[str],
    group_names: set[str],
    *,
    output_format: str = "none",
) -> int:
    """Resolve and execute a group sub-command against an already-booted app.

    Post-boot half of GROUP handling, also reused by the UNKNOWN fallback in
    ``_handle_job``. Because the app is already booted, this sees both job
    groups (from ``JOB_GROUP``) and plugin-registered command groups (from
    ``app.get_plugin_commands()``), so ``func mcp serve`` resolves here.

    Navigation is a single walk of the group trie (A4), which replaced a greedy
    dotted-prefix loop over a merged name set. The trie carries job groups,
    plugin namespaces and the caller's pre-boot group names in one shape, so
    ``func infra aws launch`` is one descent instead of a prefix match followed
    by a separate qualified-name lookup.

    A node is a **command** when it carries a payload and has no children;
    everything else — including a duality node that is both runnable and
    navigable — is a group. That is what the pre-trie code did (a duality name
    appears in ``group_names``, so its segment was consumed as a group and the
    listing printed), and A4.1 is a zero-behavioral-diff task. Letting a
    payload win over its own subtree is the change
    :attr:`TrieResolution.is_group_listing` encodes, and it is deliberately not
    taken here.

    Precedence within a group (D3): a job wins over a plugin command on an
    exact path conflict — applied when the trie is built, so a shadowed plugin
    command is absent rather than skipped at each lookup.

    Args:
        app: The already-booted FunctualizeApp (duck-typed).
        args: ``[group_segment_1, ..., sub_command?, ...remaining_args]``.
        group_names: Known job group names (including ancestor prefixes).
        output_format: The ``--output`` flag value (auto, json, ndjson, raw, none).

    Returns:
        Exit code (0 = success).
    """
    # Jobs reached through a group must honor `--output` too: deposit it here as
    # well, since this is also entered directly from `_handle_job`'s UNKNOWN
    # fallback, not only from `_handle_group` (which already set it).
    app._output_format = output_format

    from functualize._cli.dispatch import is_known_global_flag, walk_group_path
    from functualize.app.adapters.click_params import (
        create_job_click_command,
        invoke_command_capturing,
    )
    from functualize.app.utils import build_group_trie, read_group_options_from_cache

    all_jobs = app.get_jobs()
    plugin_commands = app.get_plugin_commands()

    jobs_by_path = {_job_trie_path(j): j for j in all_jobs}
    plugins_by_path: dict[str, Any] = {}
    plugin_rows: list[tuple[str | None, str]] = []
    for cmd in plugin_commands:
        namespace = getattr(cmd, "namespace", None)
        path = f"{namespace}.{cmd.name}" if namespace else cmd.name
        if path in jobs_by_path:
            logger.debug(
                "Plugin command '%s' in namespace '%s' shadowed by a job; skipping",
                cmd.name,
                namespace,
            )
            continue
        if path in plugins_by_path:
            continue
        plugins_by_path[path] = cmd
        plugin_rows.append((namespace, cmd.name))

    # Per-group declared flags (S6a). Read from the cache — the section is
    # written by the same scan that produced the jobs above, and reading it
    # here costs no import.
    from functualize.app.utils import resolve_cache_path

    group_option_specs = read_group_options_from_cache(resolve_cache_path(Path.cwd()))

    trie = build_group_trie(
        [(job.group, job.name, "job") for job in all_jobs],
        plugin_rows,
        # The caller's pre-boot group names can name a group that no booted job
        # sits under (the cold-boot AST sweep reads JOB_GROUP independently of
        # what discovery ends up registering). They were navigable before the
        # trie; keep them navigable.
        groups=[g for g in group_names if g and all(g.split("."))],
        builtin=False,
        group_options=group_option_specs,
    )

    # Global flags belong *before* the group name (the git/click idiom:
    # `func --log-level DEBUG infra deploy`), where `_extract_global_options`
    # has already consumed them — so they never reach `args` here. Anything
    # that stops the walk on a non-leaf node is therefore a token in the wrong
    # place: either a misplaced global or an unknown flag. Both are errors
    # (killing the silent-listing-exit-0), told apart only for the hint.
    #
    # The one exception, and the reason this is `walk_group_path` rather than
    # `trie.resolve`: a flag *declared by a consumed ancestor group* is legal
    # mid-path and is consumed as a group option (`func deploy --env prod web
    # run`). Everything else still errors exactly as before.
    walk = walk_group_path(trie, args)
    node = walk.node
    remaining = list(walk.remaining)
    consumed = list(walk.consumed)
    # The group-CLI layer (S6a): handed to the engine, which resolves each
    # declared GroupOptions class against its *group* (default < config file <
    # env < these). Flat and nearest-first already — see `walk_group_path`.
    group_option_values = dict(walk.options)
    if group_option_values:
        logger.debug("Group options consumed mid-path: %s", group_option_values)

    if not node.is_leaf:
        for token in remaining:
            if token.startswith("-"):
                if token in ("--help", "-h"):
                    # `git remote --help` is what everyone types, and the
                    # "move it before the group" advice below is simply wrong
                    # for this one flag: `func --help deploy` prints func's
                    # help, not deploy's. A group's help is its listing, so
                    # fall through to it rather than erroring (S6a T-GO-5 —
                    # the listing is where the group's own options are
                    # documented, so it has to be reachable by asking).
                    remaining = []
                    break
                if is_known_global_flag(token):
                    group_name = consumed[0] if consumed else args[0]
                    print(
                        f"Error: global option '{token}' must come before "
                        f"the group name '{group_name}'.\n"
                        f"Global options go before the group; "
                        f"job options follow the job name.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"Error: unknown option '{token}' before a command.\n"
                        f"Global options go before the group name; "
                        f"job options must follow the job name.",
                        file=sys.stderr,
                    )
                return 2
    # Echo the tokens as typed, not the canonical path: a user who wrote
    # `func infra.aws` should read their own spelling back in the usage line.
    cli_path = " ".join(consumed) if consumed else args[0]

    # ── A command node → execute it, remaining tokens are its arguments ───
    if node.has_payload and node.is_leaf:
        job_descriptor = jobs_by_path.get(node.payload or "")
        if job_descriptor is not None:
            function, config_class, error = _materialize_for_dispatch(
                app, job_descriptor
            )
            if function is None:
                print(
                    f"Error: Job '{job_descriptor.name}' could not be loaded: {error}",
                    file=sys.stderr,
                )
                return 1
            command = create_job_click_command(
                name=job_descriptor.name,
                function=function,
                job_config_class=config_class,
                app=app,
                command_name=job_descriptor.func_name,
                group_option_values=group_option_values,
            )
            return invoke_command_capturing(
                command, remaining, output_format, prog_name=job_descriptor.func_name
            )

        plugin_cmd = plugins_by_path.get(node.payload or "")
        if plugin_cmd is not None:
            return _run_adhoc_command(
                plugin_cmd.name,
                plugin_cmd.callback,
                remaining,
                output_format,
                help_text=plugin_cmd.help_text,
            )

    # ── A group node ──────────────────────────────────────────────────────
    children = sorted(node.children.values(), key=lambda child: child.segment)
    sub_groups = sorted(child.segment for child in children if child.children)
    entries: list[tuple[str, str]] = []
    for child in children:
        if not child.has_payload:
            continue
        job = jobs_by_path.get(child.payload or "")
        if job is not None:
            entries.append(
                (child.segment, (job.docstring or "").strip().split("\n")[0])
            )
            continue
        cmd = plugins_by_path.get(child.payload or "")
        if cmd is not None:
            entries.append((child.segment, (cmd.help_text or "").strip()))

    # No sub-command (or only flags left) → list what is here.
    if not remaining or remaining[0].startswith("-"):
        print(f"Usage: func {cli_path} <command> [options]")
        # The group's own flags, plus every ancestor's — inherited options are
        # legal here (`func deploy --env prod web run`), so a listing that
        # showed only this node's own declarations would under-report what the
        # user may type. Outermost-first, matching the order they appear in.
        option_specs = trie.group_options_on_path(
            [segment for token in consumed for segment in token.split(".")]
        )
        option_rows = _render_group_option_rows(option_specs)
        if option_rows:
            print("\nOptions:")
            width = max(len(flag) for flag, _ in option_rows)
            for flag, description in option_rows:
                print(f"  {flag.ljust(width)}  {description}".rstrip())
        if sub_groups:
            print("\nSub-groups:")
            for sub_group in sub_groups:
                print(f"  {sub_group}")
        if entries:
            print("\nCommands:")
            for cmd_name, desc in sorted(entries, key=lambda e: e[0]):
                print(f"  {cmd_name}  {desc}")
        if not sub_groups and not entries:
            print("No commands available.")
        return 0

    print(
        f"Error: Unknown command '{remaining[0]}' in group '{cli_path}'.",
        file=sys.stderr,
    )
    available = [name for name, _ in entries] + sub_groups
    if available:
        print(f"Available: {', '.join(sorted(available))}", file=sys.stderr)
    return 1


def _handle_group(
    args: list[str],
    anchor: Path,
    merged_config: dict[str, Any],
    effective: dict[str, list[str]],
    cli_flags: dict[str, Any],
    group_names: set[str],
    *,
    output_format: str = "none",
    _app_ref: list[Any] | None = None,
    scope_id: str | None = None,
    prompt_gates: bool = False,
    force: bool = False,
) -> int:
    """Handle Mode.GROUP: boot app, then delegate to _dispatch_group.

    Boots the full app (plugins included) and hands off to _dispatch_group,
    which greedily consumes the group path and lists or executes the target
    job or plugin command. Group-path consumption happens post-boot so it can
    see plugin-registered command groups (e.g. ``mcp``) alongside job groups.

    Args:
        args: [group_segment_1, ..., sub_command?, ...remaining_args]
        anchor: Project anchor directory.
        merged_config: Merged project config dict.
        effective: Resolved effective directories.
        cli_flags: Parsed global CLI flags for resolve_cli_config.
        group_names: Set of known group names (including ancestor prefixes).
        output_format: The --output flag value (json, text, or none).
        _app_ref: Optional mutable container; if provided, the constructed
            FunctualizeApp is appended so callers can access it for perf reporting.

    Returns:
        Exit code (0 = success).
    """
    from functualize._cli.config import resolve_cli_config
    from functualize.app import FunctualizeApp
    from functualize.app.config import ConfigSources, JobSources, PluginSources

    # ── Boot app (same pattern as _handle_job) ───────────────────────────
    _apply_import_libs(effective.get("import_libs", []))
    cli_import_libs = cli_flags.get("import_libs", [])
    if cli_import_libs:
        resolved_cli_libs = []
        for lib_path in cli_import_libs:
            p = Path(lib_path)
            if not p.is_absolute():
                p = anchor / p
            resolved_cli_libs.append(str(p.resolve()))
        _apply_import_libs(resolved_cli_libs)

    cli_config = resolve_cli_config(cli_flags=cli_flags)

    cwd_str = str(Path.cwd().resolve())
    all_dirs = list(effective.get("all_directories") or effective["jobs_directories"])
    if cwd_str not in all_dirs:
        all_dirs.append(cwd_str)

    job_sources = JobSources(
        directories=all_dirs,
        lazy=True,
    )

    # Extract disabled plugins from config
    _plugins_section = merged_config.get("plugins")
    _disabled_plugins = (
        list(_plugins_section.get("disabled", []))
        if isinstance(_plugins_section, dict)
        else []
    )

    app = FunctualizeApp(
        name="functualize",
        job_sources=job_sources,
        discovery_config=cli_config.discovery,
        config_sources=ConfigSources(
            dotenv=cli_config.dotenv,
            dotenv_path=cli_config.dotenv_path,
        ),
        plugin_sources=PluginSources(disabled=_disabled_plugins)
        if _disabled_plugins
        else None,
    )
    app._output_format = output_format
    app._prompt_gates = prompt_gates
    app._force = force

    # Deposit app reference for perf reporting by caller
    if _app_ref is not None:
        _app_ref.append(app)

    # Post-boot resolution (job groups + plugin command groups) lives in
    # _dispatch_group, shared with the UNKNOWN fallback in _handle_job.
    return _dispatch_group(app, args, group_names, output_format=output_format)


# ─── Direct job handler ──────────────────────────────────────────────────


def _handle_job(
    args: list[str],
    anchor: Path,
    merged_config: dict[str, Any],
    effective: dict[str, list[str]],
    cli_flags: dict[str, Any],
    *,
    output_format: str = "none",
    _app_ref: list[Any] | None = None,
    scope_id: str | None = None,
    prompt_gates: bool = False,
    force: bool = False,
) -> int:
    """Handle Mode.JOB: boot app, find job, parse args, execute.

    Separation of concerns:
    - ROUTING: already done by detect_mode() before this is called
    - PARSING: local Click instance (for --help, type coercion, validation)
    - EXECUTION: FunctualizeApp.execution_engine (DI, hooks, middleware)

    Args:
        args: [job_name, ...remaining_args]
        anchor: Project anchor directory.
        merged_config: Merged project config dict.
        effective: Resolved effective directories.
        cli_flags: Parsed global CLI flags for resolve_cli_config.
        output_format: The --output flag value (json, text, or none).
        _app_ref: Optional mutable container; if provided, the constructed
            FunctualizeApp is appended so callers can access it for perf reporting.

    Returns:
        Exit code (0 = success).
    """
    from functualize._cli.config import resolve_cli_config
    from functualize.app import FunctualizeApp
    from functualize.app.config import ConfigSources, PluginSources

    # Extract user-configured aliases and determine the target job name.
    aliases = _extract_aliases(merged_config)
    raw_name = args[0]
    # Alias expansion happens here; shadowing (direct job name wins) is
    # already handled by detect_mode which checks job_names before aliases.
    job_name = aliases.get(raw_name, raw_name)
    # Jobs register under the normalized name, so canonicalize before anything
    # downstream looks the job up. `detect_mode` already accepted the Python
    # spelling; without this it would route `func build_wheel` to a Click app
    # that only knows `build-wheel`, turning a recognized job into "no such
    # command" — recognized in one breath and denied in the next.
    from functualize.app.utils import normalize_segment

    job_name = ".".join(normalize_segment(part) for part in job_name.split("."))
    remaining_args = args[1:]

    # Apply import_libs to sys.path before importing any job modules
    # Merge CLI-provided import_libs (highest priority) with effective import_libs
    _apply_import_libs(effective.get("import_libs", []))
    cli_import_libs = cli_flags.get("import_libs", [])
    if cli_import_libs:
        # CLI import_libs are relative to CWD, resolve them against anchor
        resolved_cli_libs = []
        for lib_path in cli_import_libs:
            p = Path(lib_path)
            if not p.is_absolute():
                p = anchor / p
            resolved_cli_libs.append(str(p.resolve()))
        _apply_import_libs(resolved_cli_libs)

    # Resolve full CLI config (uses cli_flags for precedence)
    cli_config = resolve_cli_config(cli_flags=cli_flags)

    # Build job sources from the already-resolved effective directories
    # plus CWD (auto_discover always scans CWD at depth 0 for .py files)
    from functualize.app.config import JobSources as _JobSources

    cwd_str = str(Path.cwd().resolve())
    all_dirs = list(effective.get("all_directories") or effective["jobs_directories"])
    if cwd_str not in all_dirs:
        all_dirs.append(cwd_str)

    job_sources = _JobSources(
        directories=all_dirs,
        lazy=True,
    )

    # Extract disabled plugins from config
    _plugins_section = merged_config.get("plugins")
    _disabled_plugins = (
        list(_plugins_section.get("disabled", []))
        if isinstance(_plugins_section, dict)
        else []
    )

    # Boot FunctualizeApp with full DI, hooks, and plugin support
    app = FunctualizeApp(
        name="functualize",
        job_sources=job_sources,
        discovery_config=cli_config.discovery,
        config_sources=ConfigSources(
            dotenv=cli_config.dotenv,
            dotenv_path=cli_config.dotenv_path,
        ),
        plugin_sources=PluginSources(disabled=_disabled_plugins)
        if _disabled_plugins
        else None,
    )
    app._output_format = output_format
    app._prompt_gates = prompt_gates
    app._force = force

    # Deposit app reference for perf reporting by caller
    if _app_ref is not None:
        _app_ref.append(app)

    # Look up job by name from the booted app
    jobs = app.get_jobs()
    job_descriptor = None
    for j in jobs:
        if j.name == job_name:
            job_descriptor = j
            break

    if job_descriptor is None:
        # ── Gap A: plugin-registered command dispatch (post-boot) ─────────
        # Plugin command groups (e.g. `mcp`) and ungrouped plugin commands
        # are invisible to pre-boot mode detection, so they land here in
        # UNKNOWN mode with the app already booted. Resolve them now, before
        # emitting the error. Precedence: pre-boot resolution already gave
        # `.py` files / builtins / job groups / job names / aliases priority,
        # so reaching here means nothing else matched (D3).
        plugin_commands = app.get_plugin_commands()
        plugin_namespaces = _plugin_namespace_names(plugin_commands)
        # Recompute job group names (+ ancestors) so mixed job/plugin groups
        # behave identically to GROUP mode.
        job_group_names: set[str] = set()
        for j in jobs:
            if j.group:
                parts = j.group.split(".")
                for i in range(1, len(parts) + 1):
                    job_group_names.add(".".join(parts[:i]))
        merged_group_names = job_group_names | plugin_namespaces
        group_first_segments = {g.split(".")[0] for g in merged_group_names}

        # First segment of any (job or plugin) group → group dispatch.
        if job_name in group_first_segments:
            return _dispatch_group(
                app,
                [job_name, *remaining_args],
                merged_group_names,
                output_format=output_format,
            )

        # Ungrouped plugin command matching the name → execute directly.
        ungrouped_cmd = next(
            (
                c
                for c in plugin_commands
                if getattr(c, "namespace", None) is None and c.name == job_name
            ),
            None,
        )
        if ungrouped_cmd is not None:
            return _run_adhoc_command(
                ungrouped_cmd.name,
                ungrouped_cmd.callback,
                remaining_args,
                output_format,
                help_text=ungrouped_cmd.help_text,
            )

        if raw_name in aliases:
            # Alias target not found
            print(
                f"Error: Alias '{raw_name}' maps to job '{job_name}', "
                f"which was not found.",
                file=sys.stderr,
            )
        else:
            print(
                f"Error: Unknown command '{job_name}'.",
                file=sys.stderr,
            )
        # Show fuzzy suggestions from the fully-discovered job set, enriched
        # with ungrouped plugin command names + plugin/job group first segments.
        discovered_names = {j.name for j in jobs}
        discovered_names |= {
            c.name for c in plugin_commands if getattr(c, "namespace", None) is None
        }
        discovered_names |= group_first_segments
        suggestions = _fuzzy_suggest(job_name, discovered_names)
        if suggestions:
            print("\nDid you mean:", file=sys.stderr)
            for suggestion in suggestions:
                print(f"  func {suggestion}", file=sys.stderr)
            print(file=sys.stderr)
        print("Run 'func' to see all available commands.", file=sys.stderr)
        return 1

    # Materialize the ONE target job via the engine (lazy boot leaves
    # cache-only descriptors with function=None; this imports only the
    # invoked job's module)
    function, config_class, error = _materialize_for_dispatch(app, job_descriptor)
    if function is None:
        print(
            f"Error: Job '{job_name}' could not be loaded: {error}",
            file=sys.stderr,
        )
        return 1

    # Build a click.Command directly from the job's signature + config model
    # and run it, capturing its return value for --output emission.
    from functualize.app.adapters.click_params import (
        create_job_click_command,
        invoke_command_capturing,
    )

    command = create_job_click_command(
        name=job_descriptor.name,
        function=function,
        job_config_class=config_class,
        app=app,
        workflow_scope_id=scope_id,
    )

    return invoke_command_capturing(
        command,
        remaining_args,
        output_format,
        prog_name=job_descriptor.name,
        on_start=lambda: app.perf_timeline.mark("job.execute.start"),
        on_end=lambda: app.perf_timeline.mark("job.execute.end"),
    )


# ─── Main entry point ────────────────────────────────────────────────────


def _detect_config_class(
    function: Callable[..., Any],
) -> type[Any] | None:
    """The single-file peer path's entry point to the one config-class rule.

    Delegates to the shared detector, reached through the `app.utils`
    re-export because `_cli` may import public folders only.

    Behavior change: this copy lacked the `GroupOptions` guard the other two
    had, so a `GroupOptions` parameter was taken as the job's own config class
    here — leaking the group's flags into the job's `--help` on this path
    alone. Delegating fixes that.
    """
    from functualize.app.utils import detect_config_class

    return detect_config_class(function)


def _register_single_file_peers(
    file_path: Path,
    target_fn: Callable[..., Any],
    app: Any,
    *,
    module_name: str = "",
) -> None:
    import inspect
    import sys

    from functualize.app.utils import normalize_segment

    module = sys.modules.get(module_name)
    if module is None:
        return
    for fn_name, fn in inspect.getmembers(module, inspect.isfunction):
        if fn_name.startswith("_") or fn.__module__ != module_name:
            continue
        if fn is target_fn:
            continue
        config_cls = _detect_config_class(fn)
        app.register_dynamic_job(
            name=normalize_segment(fn_name),
            function=fn,
            config_class=config_cls,
        )


def _handle_single_file(
    file_args: list[str],
    *,
    output_format: str = "none",
    _app_ref: list[Any] | None = None,
    scope_id: str | None = None,
    prompt_gates: bool = False,
    force: bool = False,
) -> int:
    """Handle single-file execution mode directly (no FallbackGroup).

    This bypasses Click's group routing for .py file invocations, eliminating
    BF-1 (exception mismatch) and BF-2 (option eating).

    Args:
        file_args: argv slice starting from the .py file
            [file.py, function_name?, ...remaining_args]
        output_format: The --output flag value (json, text, or none).
        _app_ref: Optional mutable container; if provided, the constructed
            FunctualizeApp is appended so callers can access it for perf reporting.

    Returns:
        Exit code (0 = success).
    """
    from functualize._cli.pep723 import maybe_delegate_to_uv, parse_script_metadata
    from functualize.app.utils import import_job

    file_path = Path(file_args[0]).resolve()
    # Parsed once and threaded through: a second parse would re-print any
    # `[tool.functualize]` warning, and the same warning twice reads as two
    # separate problems.
    metadata = parse_script_metadata(file_path)

    # T41. A script that declares `[tool.functualize] job` *is* that job, so
    # everything after the filename is the job's own command line. Without
    # this, the first argument is read as a function name — which makes a
    # shebang script unable to take flags (`./s.py --url x` → "Function
    # '--url' not found") and makes a bare `./s.py` print a listing rather
    # than run. Both are wrong for something invoked as a program.
    entry_point = metadata.job if metadata is not None else None
    if entry_point is not None:
        function_name: str | None = entry_point
        remaining_args = file_args[1:]
    else:
        function_name = file_args[1] if len(file_args) > 1 else None
        remaining_args = file_args[2:] if len(file_args) > 2 else []

    # PEP 723 dependency check (BEFORE importing)
    maybe_delegate_to_uv(file_path, file_args, metadata=metadata)

    # Resolve config and apply import_libs before importing the job file
    from functualize._cli.config import resolve_cli_config

    cli_config = resolve_cli_config()
    _apply_import_libs(cli_config.import_libs)

    try:
        if function_name is not None:
            result = import_job(file_path, function_name)
            assert callable(result)
            target_fn = result
        else:
            result = import_job(file_path)
            assert isinstance(result, list)
            if not result:
                print(f"No qualifying functions found in '{file_path}'.")
                return 1

            # List discovered functions and exit
            print(f"Available functions in {file_path.name}:")
            print()
            for fn in sorted(result, key=lambda f: f.__name__):
                doc = (fn.__doc__ or "").strip().split("\n")[0]
                if doc:
                    print(f"  {fn.__name__}  — {doc}")
                else:
                    print(f"  {fn.__name__}")
            return 0
    except (ImportError, LookupError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Construct FunctualizeApp for execution context
    from functualize.app import FunctualizeApp
    from functualize.app.config import ConfigSources
    from functualize.app.utils import auto_discover

    cwd = Path.cwd()
    discovery_result = auto_discover(cwd)

    app = FunctualizeApp(
        name="functualize",
        job_sources=discovery_result.job_sources,
        discovery_config=cli_config.discovery,
        config_sources=ConfigSources(
            dotenv=cli_config.dotenv,
            dotenv_path=cli_config.dotenv_path,
        ),
    )
    app._output_format = output_format
    app._prompt_gates = prompt_gates
    app._force = force

    # Deposit app reference for perf reporting by caller
    if _app_ref is not None:
        _app_ref.append(app)

    # Register peer functions from the single-file module so rc.invoke()
    # can cross-call within the same file.
    _register_single_file_peers(file_path, target_fn, app, module_name=file_path.stem)

    # Execute through the engine via a click command built directly from the
    # target function's signature (handles DI, config, hooks).
    from functualize.app.adapters.click_params import (
        create_job_click_command,
        invoke_command_capturing,
    )

    command = create_job_click_command(
        name=function_name or "",
        function=target_fn,
        app=app,
        command_name=function_name,
        workflow_scope_id=scope_id,
    )

    return invoke_command_capturing(
        command, remaining_args, output_format, prog_name=function_name
    )


@contextlib.contextmanager
def _quiet_broken_pipe() -> Any:
    """Swallow a ``BrokenPipeError`` escaping the CLI, exiting 0.

    The **job** path is not what this catches — the engine turns every job
    exception into a ``JobResult``, so a broken pipe inside a job is handled at
    the callback (``click_params._exit_quietly_on_broken_pipe``) and that is the
    path `tests/pipeline/test_exit_codes.py` pins. This is the net for output
    produced *outside* a job: group listings, `--help`, schema dumps.

    Deliberately not `signal.SIG_DFL`: restoring the default disposition kills
    the process with 141, and the contract is a quiet **0**. Redirecting the fd
    to ``/dev/null`` before the interpreter's shutdown flush is what stops it
    printing "Exception ignored in: …" to stderr.
    """
    try:
        yield
    except BrokenPipeError:
        import os

        with contextlib.suppress(OSError, ValueError):
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0) from None


def main() -> None:
    """Console entry point — the pipe guard wraps every routing path.

    Thin on purpose: `_run_cli` has many `raise SystemExit` exits, and a
    downstream reader can close the pipe during any of them, so the guard has
    to sit outside all of them rather than at one chosen write site.
    """
    with _quiet_broken_pipe():
        _run_cli()


#: The one-time nudge after an installation first registers.
FIRST_RUN_HINT = (
    "Note: first run — 'func builtin self doctor' gives you a health check."
)


def _emit_first_run_hint(stream: Any) -> bool:
    """Print the hint, but only to a terminal. Returns whether it printed.

    **stderr is not a free channel.** `--perf-report json` writes its document
    there, and an unconditional hint corrupted it — two integration tests
    failed on a `JSONDecodeError` at char 0. stdout is worse still, since
    piping job output is the documented way to consume it.

    So the hint is gated on stderr being a terminal, which is the only case
    where a human is reading it. Everywhere else it is silently skipped: a
    convenience must never damage output somebody is parsing.
    """
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    print(FIRST_RUN_HINT, file=stream)
    return True


def _register_this_installation() -> None:
    """Record this installation in the user-global registry, once.

    **The warm path is one `stat()` and imports nothing.** `_cli.manifest`
    defines dataclasses, and creating a frozen dataclass costs ~0.9ms of
    codegen at import — far more than reading the registry it manages (~39us
    for ten installations). So the fast path computes the marker path with
    stdlib and stats it; the module is imported only on the miss.

    The marker key covers `(binary_path, version)`, so an in-place upgrade
    misses it and refreshes its record instead of being masked forever.

    **Every failure here is silent.** A read-only config directory, a
    container, a sandbox — registration becomes impossible and the command the
    user typed must not care. Bookkeeping never interferes.
    """
    try:
        from pathlib import Path

        import functualize
        from functualize.app.utils import resolve_user_config_dir

        version = functualize.__version__
        config_dir = resolve_user_config_dir()

        # Mirrors `_cli.manifest.resolve_binary_path`, recomputed here rather
        # than imported so the warm path stays free of that module's dataclass
        # codegen. `tests/_cli/test_manifest.py` asserts the two agree.
        argv0 = sys.argv[0] if sys.argv else ""
        if not argv0:
            binary_path = ""
        elif "/" in argv0 or "\\" in argv0:
            binary_path = str(Path(argv0).resolve())
        else:
            binary_path = str(Path(sys.executable).parent / argv0)

        import hashlib

        digest = hashlib.sha256(f"{binary_path}\0{version}".encode()).hexdigest()[:16]
        if (config_dir / "installs" / digest).exists():
            return  # already recorded — nothing imported, nothing parsed

        from functualize._cli import manifest as _manifest
        from functualize._cli.runtime import detect_from_process

        # Nothing recorded yet at all means this is the very first run of any
        # functualize on this machine — the one moment the hint is useful.
        first_ever = not _manifest.manifest_path(config_dir).exists()

        detection = detect_from_process()
        _manifest.register(
            config_dir,
            binary_path=binary_path,
            runtime_mode=detection.mode.value,
            owning_distribution=detection.owning_distribution,
            python_version=(
                f"{sys.version_info.major}.{sys.version_info.minor}"
                f".{sys.version_info.micro}"
            ),
            functualize_version=version,
        )
        if first_ever:
            _emit_first_run_hint(sys.stderr)
    except Exception:  # noqa: BLE001 - see the docstring: never interfere
        return


def _run_cli() -> None:
    """Entry point — deterministic routing, no exception-based dispatch.

    Architecture:
    1. _extract_global_options(sys.argv) → parse global flags
    2. auto_discover(cwd, overrides=typed_config) → unified discovery
    3. enumerate_job_names(jobs_directories) → candidate names
    4. _extract_aliases(merged_config) → load aliases
    5. detect_mode(sys.argv, job_names=job_names, aliases=aliases) → mode
    6. Route based on mode: direct handlers, no FallbackGroup

    Non-zero exit on unresolvable input.
    """
    # `--version` answers before anything is constructed: no app boot, no
    # discovery, no DI. Read straight from the installed distribution metadata
    # rather than `from functualize import __version__`, which would import the
    # package and defeat the point — this stays inside the pre-boot budget the
    # warm-boot-zero-imports test guards.
    #
    # Position-aware: only recognize --version when it appears BEFORE the first
    # positional argument (the command name). `func --version` prints the
    # version; `func deploy --version v1` passes --version to the job. This is
    # the same convention as other global flags (--log-level, --output, etc.)
    # and unlike --help which Click handles per-command.
    from functualize._cli.dispatch import (
        _GLOBAL_OPTIONS_ALWAYS_VALUE,
        _GLOBAL_OPTIONS_OPTIONAL_VALUE,
    )

    _argv_tail = sys.argv[1:]
    _first_positional = len(_argv_tail)  # default: no positional found
    _i = 0
    while _i < len(_argv_tail):
        _tok = _argv_tail[_i]
        if _tok == "--version":
            # Found it in the prefix → print and return
            import importlib.metadata

            try:
                version = importlib.metadata.version("functualize")
            except importlib.metadata.PackageNotFoundError:
                version = "unknown"
            print(f"functualize {version}")
            return
        if _tok.startswith("-"):
            # A flag — skip it (and its value if it takes one)
            if "=" in _tok:
                _i += 1
            elif _tok in _GLOBAL_OPTIONS_ALWAYS_VALUE:
                _i += 2  # skip flag + value
            elif _tok in _GLOBAL_OPTIONS_OPTIONAL_VALUE:
                _i += 1  # conservative: don't consume the next token
            else:
                _i += 1  # unknown flag or bool flag (--no-dotenv, --help)
        else:
            # First positional found — --version was not in the prefix
            break
        continue

    # `self doctor` answers here for the same reason `--version` does, plus a
    # sharper one: `cli_app` boots a full `FunctualizeApp` before any builtin
    # subcommand runs, so a doctor mounted only under the click group would be
    # unreachable in exactly the case it exists for — an installation too
    # broken to boot. Intercepting pre-boot is what lets it report that instead
    # of dying with it.
    #
    # Matched positionally rather than with `in`, so a job named `doctor` or an
    # argument spelled `self` cannot trigger it. The command stays mounted on
    # the group as well (see `builtins.register_builtin_commands`); this is the
    # earlier of two doors to the same code, not a second implementation.
    if _argv_tail[:3] == ["builtin", "self", "doctor"]:
        from functualize._cli.self_cmd import doctor

        doctor.main(_argv_tail[3:], prog_name="func builtin self doctor")
        return

    _register_this_installation()

    # Settings declaring `phase="early"` are read here, beside `--version`,
    # because "early" means *before the app exists* — a flag that changes
    # discovery or config resolution cannot wait for the click callback, which
    # runs after boot. No shipped setting declares one, so this is a single
    # catalog read that does not walk argv (C3.2).
    from functualize._cli.dispatch import scan_early_setting_flags

    scan_early_setting_flags(sys.argv[1:])

    from functualize.app import get_perf_timeline

    perf_timeline = get_perf_timeline()

    # Inject the module-level start mark (captured before click import)
    perf_timeline._marks.insert(0, ("cli.module_import.start", _module_import_start_ns))
    perf_timeline.mark("cli.module_import.end")

    perf_timeline.mark("cli.dispatch_imports.start")
    from functualize._cli.builtins import register_builtin_commands
    from functualize._cli.dispatch import Mode, _extract_global_options, detect_mode
    from functualize.app.utils import (
        DiscoveryOverrides,
        auto_discover,
        enumerate_group_names,
        enumerate_job_names,
        read_routing_names_from_cache,
    )

    perf_timeline.mark("cli.dispatch_imports.end")

    # Phase 0: Extract global options from argv (needed for overrides)
    global_opts, cli_flags = _extract_global_options(sys.argv)

    # Phase 1: Unified discovery with CLI overrides
    perf_timeline.mark("cli.discovery.start")
    cwd = Path.cwd()
    typed_config = DiscoveryOverrides(
        scan_depth=cli_flags.get("scan_depth"),
        import_libs=cli_flags.get("import_libs"),
        jobs_directories=cli_flags.get("jobs_directories"),
        extra_directories=cli_flags.get("extra_directories"),
        exclude_patterns=cli_flags.get("exclude_patterns"),
    )
    discovery_result = auto_discover(cwd, overrides=typed_config)
    anchor = discovery_result.anchor
    merged_config = discovery_result.merged_config
    # Build effective dict for downstream handlers (_handle_job, _handle_bare)
    effective: dict[str, list[str]] = {
        "jobs_directories": discovery_result.jobs_directories,
        "import_libs": discovery_result.import_libs,
        # Every scan root auto_discover resolved — jobs_directories plus
        # extra_directories and the CWD pre-filter results. Handlers must boot
        # the app over these, or extra_directories jobs silently vanish.
        "all_directories": list(discovery_result.job_sources.directories or []),
    }
    # Phase 1b: Pre-boot name resolution (cache-first)
    # Resolve from cwd — the same starting point build_cached_provider uses —
    # so the reader and the cache writer agree on the file location.
    from functualize.app.utils import resolve_cache_path

    cache_path = resolve_cache_path(cwd)
    _routing_job_filter = _build_routing_job_filter(cli_flags, merged_config)
    cached = read_routing_names_from_cache(cache_path, job_filter=_routing_job_filter)

    if cached is not None:
        job_names, group_names = cached
    else:
        # Cold boot: AST scan fallback
        _scan_roots = effective["all_directories"] or effective["jobs_directories"]
        job_names = enumerate_job_names(_scan_roots)
        group_names = enumerate_group_names(_scan_roots)

    # Apply log level from global_opts before any app boot
    # Default to INFO (matches old behavior) so rc.log() output is visible
    log_level = global_opts.log_level if global_opts.log_level is not None else "INFO"
    # When --output is json or text, explicitly route logging to stderr
    # to ensure log output does not contaminate stdout pipe data.
    # Python's logging.basicConfig() defaults to stderr, but we make it
    # explicit here for clarity and safety.
    logging.basicConfig(
        level=log_level,
        force=True,
        stream=sys.stderr,
    )

    # Load aliases (declaration cache + config) for dispatch
    aliases = _extract_aliases(merged_config)

    # Phase 2: Mode detection with full awareness
    mode, effective_args = detect_mode(
        sys.argv, job_names=job_names, group_names=group_names, aliases=aliases
    )
    perf_timeline.mark("cli.discovery.end")

    # Special case: --help flag should always go through Click for help display
    # If there's a positional that's a JOB or potential job (UNKNOWN may be a
    # function-level job), let _handle_job deal with --help.
    # Otherwise route to BUILTIN for top-level help.
    if (
        ("--help" in sys.argv[1:] or "-h" in sys.argv[1:])
        and mode is not Mode.JOB
        and mode is not Mode.SINGLE_FILE
        and mode is not Mode.UNKNOWN
        and mode is not Mode.GROUP
    ):
        register_builtin_commands(cli_app)
        cli_app()
        return

    # Resolve output format from global options. Unset → "auto": the emitter
    # resolves it by surface at emit time (piped → §C.2 serialize, TTY →
    # nothing), so a raw stdout dump never lands on an interactive terminal.
    output_format = global_opts.output if global_opts.output is not None else "auto"

    # ── Perf report setup for direct-dispatch modes ──────────────────────
    perf_format = global_opts.perf_report  # None, "text", or "json"
    perf_filter = global_opts.perf_filter
    app_ref: list[Any] = []  # handlers deposit FunctualizeApp here

    # ── Workflow gate flags ────────────────────────────────────────────────
    scope_id = global_opts.scope_id
    prompt_gates = global_opts.prompt_gates
    force = global_opts.force

    # Phase 3: Direct routing — no FallbackGroup
    if mode is Mode.SINGLE_FILE:
        try:
            exit_code = _handle_single_file(
                effective_args,
                output_format=output_format,
                _app_ref=app_ref,
                scope_id=scope_id,
                prompt_gates=prompt_gates,
                force=force,
            )
        finally:
            if perf_format is not None and app_ref:
                _print_perf_report(app_ref[0], perf_format, perf_filter)
        raise SystemExit(exit_code)

    if mode is Mode.JOB:
        try:
            exit_code = _handle_job(
                effective_args,
                anchor,
                merged_config,
                effective,
                cli_flags,
                output_format=output_format,
                _app_ref=app_ref,
                scope_id=scope_id,
                prompt_gates=prompt_gates,
                force=force,
            )
        finally:
            if perf_format is not None and app_ref:
                _print_perf_report(app_ref[0], perf_format, perf_filter)
        raise SystemExit(exit_code)

    if mode is Mode.GROUP:
        try:
            exit_code = _handle_group(
                effective_args,
                anchor=anchor,
                merged_config=merged_config,
                effective=effective,
                cli_flags=cli_flags,
                group_names=group_names,
                output_format=output_format,
                _app_ref=app_ref,
                scope_id=scope_id,
                prompt_gates=prompt_gates,
                force=force,
            )
        finally:
            if perf_format is not None and app_ref:
                _print_perf_report(app_ref[0], perf_format, perf_filter)
        sys.exit(exit_code)

    if mode is Mode.BARE:
        try:
            _handle_bare(anchor, merged_config, effective, cli_flags, _app_ref=app_ref)
        finally:
            if perf_format is not None and app_ref:
                _print_perf_report(app_ref[0], perf_format, perf_filter)
        return

    if mode is Mode.UNKNOWN:
        # The lightweight enumeration only finds file-stem jobs. CWD scanning
        # may discover function-level jobs (e.g., `run` inside `dummy.py`).
        # Try to execute as a job first; if the full app boot can't find it
        # either, _handle_job returns 1 with its own error message.
        #
        # `scope_id`/`prompt_gates` must be forwarded here exactly as Mode.JOB
        # forwards them. UNKNOWN is the same job about to run — the only
        # difference is that the cheap enumeration had not yet learned the
        # name. Omitting them made `--scope-id` silently ignored on a cold
        # discovery cache and honoured on every warm run afterwards, so a
        # workflow minted a generated scope id on its first invocation and the
        # caller's id addressed nothing.
        try:
            exit_code = _handle_job(
                effective_args,
                anchor,
                merged_config,
                effective,
                cli_flags,
                output_format=output_format,
                _app_ref=app_ref,
                scope_id=scope_id,
                prompt_gates=prompt_gates,
                force=force,
            )
        finally:
            if perf_format is not None and app_ref:
                _print_perf_report(app_ref[0], perf_format, perf_filter)
        raise SystemExit(exit_code)

    # BUILTIN mode: plain Click group (no FallbackGroup)
    register_builtin_commands(cli_app)
    cli_app()
