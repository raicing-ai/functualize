"""Built-in CLI commands: cache, version, config.

These commands are registered on the ``func`` click.Group alongside job
commands. All imports are from the public API only.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from functualize._cli.parallel_output import OUTPUT_MODES
from functualize.app.utils import ExitCode


@dataclass(frozen=True)
class BuiltinCommand:
    """Metadata for a built-in ``func`` command.

    This registry is the single source of truth for the set of builtin
    command names, their descriptions, and their first-level subcommands.
    Every other module that needs to know "what are the builtins?" derives
    its answer from :data:`BUILTIN_COMMANDS` rather than re-listing them, so
    the lists cannot drift.
    """

    name: str
    description: str
    subcommands: tuple[tuple[str, str], ...] = ()
    requires_subcommand: bool = False
    #: Subcommands that take over the controlling terminal (e.g. by spawning
    #: an editor). A TUI front-end must suspend itself around these rather
    #: than capturing their output.
    terminal_subcommands: tuple[str, ...] = ()

    @property
    def subcommand_map(self) -> dict[str, str]:
        """Ordered ``{subcommand: description}`` mapping."""
        return dict(self.subcommands)

    def needs_terminal(self, args: list[str]) -> bool:
        """Return True if invoking this command with ``args`` needs the terminal."""
        return any(arg in self.terminal_subcommands for arg in args)


# The canonical registry. Descriptions here are authoritative; the click
# help strings in register_builtin_commands() and the subcommand lists must
# mirror these (a test asserts the derived lists match).
BUILTIN_COMMANDS: tuple[BuiltinCommand, ...] = (
    BuiltinCommand(
        "cache",
        "Manage the job metadata cache",
        (
            ("show", "Show cache statistics"),
            ("clear", "Delete the cache file"),
            ("rebuild", "Delete and rebuild the cache"),
            ("check", "Report stale cache entries"),
        ),
        requires_subcommand=True,
    ),
    BuiltinCommand(
        "state",
        "Manage the runtime state store (fingerprints, history, scopes)",
        (
            ("show", "Show runtime state statistics"),
            ("clear", "Reset runtime state (fingerprints, history, scopes)"),
        ),
        requires_subcommand=True,
    ),
    BuiltinCommand(
        "config",
        "Inspect and manage CLI tool configuration",
        (
            ("show", "Display resolved configuration"),
            ("path", "Show config file locations"),
            ("edit", "Open config in your editor"),
            ("migrate", "Convert an INI config file to TOML"),
        ),
        # Bare ``config`` prints subcommand help — a legitimate invocation.
        requires_subcommand=False,
        # ``config edit`` spawns $EDITOR on the controlling terminal.
        terminal_subcommands=("edit",),
    ),
    BuiltinCommand(
        "domains",
        "Inspect registered domain SDKs",
        (("list", "List registered domain SDKs"),),
        requires_subcommand=True,
    ),
    BuiltinCommand(
        "scaffold",
        "Generate project scaffolding",
        (
            ("init", "Initialize a new functualize project"),
            ("add", "Add a job, plugin, screen, or domain"),
            ("list", "List scaffoldable resources"),
        ),
        requires_subcommand=True,
    ),
    BuiltinCommand(
        "workflow",
        "Inspect and resume persisted workflow scopes",
        (
            ("list", "List active workflow scopes"),
            ("state", "Show one scope's status and pending gates"),
            ("resume", "Deposit input for a blocked gate"),
            ("cancel", "Cancel a workflow scope"),
        ),
        requires_subcommand=True,
    ),
    BuiltinCommand("parallel", "Run several jobs concurrently"),
    BuiltinCommand("history", "Show recent job and shell runs"),
    BuiltinCommand("env", "Export a job's resolved config as environment variables"),
    BuiltinCommand("shell-init", "Emit a static shell completion script"),
    BuiltinCommand("why", "Explain whether a job would run, and why"),
    BuiltinCommand("version", "Show the functualize version"),
    BuiltinCommand("info", "Display app state, discovered jobs, and config"),
)
"""Every first-party command. These are the children of ``builtin`` — none of
them is a top-level name any more, so none of them is a name a job cannot have.
"""

#: The one reserved top-level segment. Kept as a frozenset because every caller
#: asks "is this token a builtin?"; the answer is now a single name, which is
#: the point — a user job called ``cache``, ``why`` or ``version`` runs
#: top-level like any other. Mirrors ``_types.naming.BUILTIN_SEGMENT``, which
#: rejects the same name for jobs, groups and plugin namespaces.
BUILTIN_ROOT: str = "builtin"

BUILTIN_ROOT_COMMAND: BuiltinCommand = BuiltinCommand(
    BUILTIN_ROOT,
    "First-party commands, kept out of the job namespace",
    tuple((c.name, c.description) for c in BUILTIN_COMMANDS),
    requires_subcommand=True,
    # Inherited from the children: `builtin config edit` still spawns $EDITOR
    # on the controlling terminal, and a TUI front-end must still suspend
    # itself around it. Dropping this on the way under the subtree would have
    # let the TUI capture an interactive editor.
    terminal_subcommands=tuple(
        sub for c in BUILTIN_COMMANDS for sub in c.terminal_subcommands
    ),
)


# Derived lookups — import these instead of re-listing builtin names.
BUILTIN_NAMES: frozenset[str] = frozenset({BUILTIN_ROOT})


def builtin_descriptions() -> dict[str, str]:
    """Return ``{name: description}`` for what a builtin occupies at top level.

    That is now the single ``builtin`` group. Callers use this to answer "which
    names are first-party here?" — and the answer is deliberately one name.
    """
    return {BUILTIN_ROOT: BUILTIN_ROOT_COMMAND.description}


def builtin_child_descriptions() -> dict[str, str]:
    """Return ``{name: description}`` for every command *under* ``builtin``."""
    return {c.name: c.description for c in BUILTIN_COMMANDS}


def builtin_subcommands() -> dict[str, dict[str, dict[str, str]]]:
    """Return two-level nested subcommand maps.

    Outer key → middleware key → inner subcommand map. With the subtree,
    the outer is ``builtin`` mapping to its children, and each child maps to
    its own subcommand map (empty for leaf commands). Callers drill one level
    to list children, two to list grandchildren.
    """
    return {
        BUILTIN_ROOT: {child.name: child.subcommand_map for child in BUILTIN_COMMANDS}
    }


def builtin_subcommand_names() -> dict[str, dict[str, tuple[str, ...]]]:
    """Return two-level nested subcommand-name tuples.

    Outer key → middleware key → inner subcommand names. Membership in any
    level doubles as "is a builtin" for the completion parser, which walks
    one level per token.
    """
    return {
        BUILTIN_ROOT: {
            child.name: tuple(name for name, _ in child.subcommands)
            for child in BUILTIN_COMMANDS
        }
    }


def get_builtin(name: str) -> BuiltinCommand | None:
    """Return the :class:`BuiltinCommand` for ``name``, or ``None``.

    Answers for ``builtin`` itself and for each command under it, so callers
    holding either half of ``func builtin config edit`` can ask.
    """
    if name == BUILTIN_ROOT:
        return BUILTIN_ROOT_COMMAND
    for command in BUILTIN_COMMANDS:
        if command.name == name:
            return command
    return None


def _resolve_editor() -> str | None:
    """Resolve editor from $VISUAL → $EDITOR → platform default.

    Returns the editor command string, or None if no editor is found.
    """
    # Check $VISUAL first, then $EDITOR
    editor = os.environ.get("VISUAL", "").strip()
    if editor:
        return editor

    editor = os.environ.get("EDITOR", "").strip()
    if editor:
        return editor

    # Platform default
    system = platform.system()
    if system == "Windows":
        return "notepad"
    elif system == "Darwin":
        # macOS: use 'open -t' for default text editor? No, requirement says vi.
        # Requirement 16.3: platform default is vi on POSIX
        if shutil.which("vi"):
            return "vi"
        return None
    else:
        # Linux / other POSIX: vi
        if shutil.which("vi"):
            return "vi"
        return None


# Template for initial global config file
_CONFIG_TEMPLATE = """\
# Functualize global configuration
# See: https://functualize.dev/docs/cli/config

[discovery]
# require_file_prefix = "job_"
# require_file_postfix = "_task"
# require_file_import = "functualize"
# require_file_marker = "__functualize__"
# require_job_decorators = ["job", "workflow"]
# require_job_prefix = "run_"
# require_job_postfix = "_job"
# extra_directories = ["~/.config/functualize/jobs"]
# exclude_patterns = ["**/test_*.py", "**/migrations/*.py"]

[cli]
# output = "rich"      # "rich" | "plain" | "json"
# show_timing = false

[aliases]
# d = "deploy"
# r = "run"
"""


def _toml_value(value: Any) -> str:
    """Format a Python value as a TOML value string."""
    if value is None:
        return "# (not set)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list | tuple):
        if not value:
            return "[]"
        items = ", ".join(f'"{v}"' for v in value)
        return f"[{items}]"
    return str(value)


def _determine_source(
    key: str,
    resolved_value: Any,
    project_config: dict[str, Any],
    global_config: dict[str, Any],
    section: str,
) -> str:
    """Determine which source a resolved value came from."""
    # Check project config
    proj_section = project_config.get(section, {})
    if isinstance(proj_section, dict) and key in proj_section:
        return "project"

    # Check global config
    glob_section = global_config.get(section, {})
    if isinstance(glob_section, dict) and key in glob_section:
        return "global"

    # Check env var
    env_key = f"FUNCTUALIZE_{section.upper()}_{key.upper()}"
    if os.environ.get(env_key):
        return "env"

    return "default"


def _emit_config_field(
    lines: list[str],
    key: str,
    display_value: Any,
    resolved_value: Any,
    project_config: dict[str, Any],
    global_config: dict[str, Any],
    section: str,
) -> None:
    """Emit a config field line with source annotation."""
    source = _determine_source(
        key, resolved_value, project_config, global_config, section
    )
    toml_val = _toml_value(display_value)
    if display_value is None:
        lines.append(f"# {key} = (not set)")
    else:
        lines.append(f"{key} = {toml_val}  # source: {source}")


def _resolve_env_vars(app: Any, job_name: str) -> list[Any]:
    """A job's config as :class:`ResolvedField` rows, for export (T43).

    Reads the one resolution seam, so the names and values match a real run and
    ``info --job``. Two things this deliberately does *not* do:

    - It does not construct the Pydantic model, so a job with a required field
      that nothing sets is reported rather than raising ``ValidationError``.
      The command exists to tell an operator what is missing; a traceback in
      exactly that case made it useless when it was most needed.
    - It does not drop unresolved fields. They are the answer, not noise.
    """
    from functualize.app.utils import job_config_fields

    return job_config_fields(app, job_name)


def _env_print(env_vars: list[Any], include_secrets: bool) -> None:
    """Print ``export NAME=value`` lines for ``eval`` (T43).

    A secret is masked unless the caller opted in, so the default output is safe
    to paste into a bug report or read off a shared screen; ``eval``-ing it with
    a masked secret would set the variable to ``•••``, which is the point — the
    real value takes a deliberate ``--include-secrets``.

    An unresolved field is emitted **commented out**, with why. Masking used to
    make a set secret and an unset one byte-identical (``SYNC_TOKEN='•••'``
    either way), so the one command an operator would reach for to answer "is
    the credential configured?" could not answer it. Commenting the unset ones
    also makes the output a ready ``.env`` skeleton, which is what the
    ``--template`` flag was going to be for.
    """
    import shlex

    import click

    from functualize.app.utils import MASK, reveal

    for f in env_vars:
        if not f.is_set:
            note = "REQUIRED — not set" if f.required else "not set"
            click.echo(f"# {f.env_name}=  # {note}")
            continue
        # `reveal` unwraps a `Secret`; whether that real value is shown is the
        # caller's opt-in, decided here rather than at resolution time.
        real = str(reveal(f.value))
        shown = real if (include_secrets or not f.secret) else MASK
        source = f"  # source: {f.source}" if f.source else ""
        click.echo(f"export {f.env_name}={shlex.quote(shown)}{source}")


def _env_exec(
    env_vars: list[Any],
    command: list[str],
    include_secrets: bool,
) -> None:
    """Run ``command`` with the resolved vars injected (T43).

    A secret is **omitted** from the child environment unless the caller opted
    in — never masked, because ``•••`` is not the value the tool needs and a
    masked secret silently breaks it. Omission is the honest default: the tool
    sees the non-secret config and fails loudly on the missing credential,
    rather than mysteriously on a corrupted one.
    """
    import os
    import subprocess

    import click

    from functualize.app.utils import reveal

    child_env = dict(os.environ)
    for f in env_vars:
        if not f.is_set:
            continue
        if f.secret and not include_secrets:
            continue
        child_env[f.env_name] = str(reveal(f.value))

    try:
        completed = subprocess.run(command, env=child_env, check=False)
    except FileNotFoundError:
        click.echo(f"Error: command not found: {command[0]}", err=True)
        raise SystemExit(ExitCode.USAGE) from None
    raise SystemExit(completed.returncode)


def _completions_install_path(shell: str) -> Path:
    """Where ``--install`` writes ``init.{bash,zsh,fish}`` (T44b).

    ``<cache dir>/completions/init.<shell>``, where the cache dir is exactly
    what ``resolve_cache_path`` resolves to (its parent) — so the completion
    script lands beside the discovery cache in project mode and under the XDG
    cache in standalone mode, with **no** second path-resolution rule to drift
    from the one the rest of the tool uses.
    """
    from pathlib import Path

    from functualize.app.utils import resolve_cache_path

    cache_dir = resolve_cache_path(Path.cwd()).parent
    return cache_dir / "completions" / f"init.{shell}"


def _render_history(records: list[dict[str, Any]]) -> list[str]:
    """One line per run record, across both namespaces (T42).

    The ring holds two record shapes — a job run (``job`` + ``status`` +
    ``duration_ms``) and a shell command (``command`` + ``exit_code``) — because
    both are "something that ran here". Rather than a schema-per-namespace
    renderer that would need editing every time a namespace is added, each line
    is built from whatever fields a record carries: the namespace tag, the
    timestamp, an outcome, and a label. A record missing a field degrades to a
    blank column, never a crash — this is a convenience log, and a malformed
    entry must not make the whole command unusable.
    """
    lines: list[str] = []
    for record in records:
        namespace = str(record.get("namespace", "-"))
        at = str(record.get("at", ""))
        # Outcome: a job carries a status word; a shell command carries an exit
        # code. Show whichever is present so both read as "did it work?".
        if "status" in record:
            outcome = str(record["status"])
        elif "exit_code" in record:
            code = record["exit_code"]
            outcome = "ok" if code == 0 else f"exit {code}"
        else:
            outcome = "-"
        # Label: the job name, or the shell command line.
        label = str(record.get("job") or record.get("command") or "-")
        duration = record.get("duration_ms")
        timing = f"  {duration:.0f}ms" if isinstance(duration, (int, float)) else ""
        lines.append(f"{namespace:<7} {outcome:<9} {label}{timing}  {at}")
    return lines


def _report_parallel(job_names: tuple[str, ...], results: list[Any]) -> None:
    """Print the per-job summary and exit non-zero if any job failed (T40).

    The summary goes to **stderr** and the exit code carries the verdict, so a
    batch stays composable: ``func builtin parallel a b | jq`` still sees only
    what the jobs emitted. A summary written to stdout would corrupt exactly
    the pipelines this command exists to feed.
    """
    import click

    from functualize.app.utils import RunStatus, exit_code_for_status

    failed: list[Any] = []
    for name, result in zip(job_names, results, strict=False):
        status = getattr(result, "status", RunStatus.UNKNOWN)
        detail = ""
        if status is not RunStatus.SUCCESS and result.exception is not None:
            detail = f" — {type(result.exception).__name__}: {result.exception}"
        click.echo(f"{status.value:<8} {name}{detail}", err=True)
        if status not in (RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED):
            failed.append(result)

    if not failed:
        return

    # One batch, one exit code. With several distinct failures there is no
    # single honest answer, so the *first* one is reported rather than an
    # invented aggregate — it is the one whose message was printed first, and
    # re-running after fixing it surfaces the next.
    raise SystemExit(exit_code_for_status(failed[0].status))


def _mount(cli_group: Any, command: Any, name: str) -> None:
    """Add a builtin command/group under the 'Functualize Commands' help panel."""
    command._functualize_panel = "Functualize Commands"
    cli_group.add_command(command, name=name)


def register_builtin_commands(cli_group: Any) -> None:
    """Mount the reserved ``builtin`` subtree on a click.Group.

    Every first-party command lives under ``func builtin …`` — ``cache``,
    ``state``, ``why``, ``config``, ``domains``, ``scaffold``, ``version`` and
    ``info`` (renamed from ``show-info``). Nothing first-party sits at the top
    level any more.

    The reason is the namespace, not tidiness: every top-level name was a name a
    user's job could not have. A project with a job called ``cache`` or ``why``
    could not run it, and adding a builtin later would silently shadow an
    existing job. Now exactly one name is reserved — ``builtin`` itself, which
    the group trie rejects for jobs, groups and plugin namespaces — and
    collisions are structurally impossible rather than merely unlikely.

    There are **no top-level spellings and no deprecation aliases**: keeping
    them would keep the names reserved, which is the entire thing being fixed.

    Args:
        cli_group: The click.Group to register commands on.
    """
    import click

    # Function-local, not module-top: importing `completions.shell_init` pulls
    # `completions/__init__` → `provenance` → back into this module, which is
    # a circular import at *module* load time but fine here, at call time, when
    # `builtins` is already fully initialized.
    from functualize._cli.completions.shell_init import SHELLS

    builtin_app = click.Group(
        name="builtin", help="First-party commands, kept out of the job namespace."
    )

    # --- Cache sub-group ---
    cache_app = click.Group(name="cache", help="Manage the job metadata cache.")

    def _build_provider_for_cwd() -> Any:
        """Build the cached provider over auto-discovered job directories."""
        from functualize.app.utils import build_discovery_cache_provider

        return build_discovery_cache_provider()

    @cache_app.command("show")
    def cache_show() -> None:
        """Display cache statistics (entry count, stale entries, file size)."""
        stats = _build_provider_for_cwd().stats()

        click.echo(f"Entries: {stats.entry_count}")
        click.echo(f"Stale entries: {stats.stale_count}")
        click.echo(f"File size: {stats.file_size_bytes} bytes")
        if stats.cache_path:
            click.echo(f"Cache path: {stats.cache_path}")
        else:
            click.echo("Cache path: N/A")

    @cache_app.command("clear")
    def cache_clear() -> None:
        """Delete the cache file."""
        import contextlib
        from pathlib import Path

        from functualize.app.utils import resolve_cache_path

        cache_path = resolve_cache_path(Path.cwd())

        if not cache_path.exists():
            raise SystemExit(0)

        with contextlib.suppress(OSError):
            cache_path.unlink()

        click.echo("Cache cleared.")

    @cache_app.command("rebuild")
    def cache_rebuild() -> None:
        """Delete and rebuild the cache from a full re-scan."""
        import contextlib
        from pathlib import Path

        from functualize.app.utils import resolve_cache_path

        cache_path = resolve_cache_path(Path.cwd())
        if cache_path.exists():
            with contextlib.suppress(OSError):
                cache_path.unlink()

        provider = _build_provider_for_cwd()
        jobs = provider.list_jobs()
        click.echo(f"Cache rebuilt with {len(jobs)} entries.")

    @cache_app.command("check")
    def cache_check() -> None:
        """Report stale cache entries without modifying the cache."""
        from pathlib import Path

        from functualize.app.utils import resolve_cache_path

        cache_path = resolve_cache_path(Path.cwd())
        if not cache_path.exists():
            click.echo("No cache file found.")
            return

        stats = _build_provider_for_cwd().stats()

        if stats.entry_count == 0:
            click.echo("Cache is empty.")
            return

        if stats.stale_count == 0:
            click.echo(f"All {stats.entry_count} cache entries are valid.")
        else:
            click.echo(
                f"{stats.stale_count} stale entries out of {stats.entry_count} total."
            )

    _mount(builtin_app, cache_app, "cache")

    # --- state (runtime state store, Part F) ---
    # Deliberately separate from `cache`: the discovery cache answers "what jobs
    # exist" and is rebuilt on any source change; runtime state answers "what
    # ran last, against which inputs". Clearing one never clears the other
    # (§D.3 Fix 2) — a shared command would recreate exactly the spurious-
    # rebuild bug up-to-date checking exists to prevent.
    state_app = click.Group(
        name="state", help="Manage the runtime state store (fingerprints, history)."
    )

    @state_app.command("show")
    def state_show() -> None:
        """Show runtime state statistics."""
        from pathlib import Path

        from functualize.app.utils import StateStore, resolve_state_path

        path = resolve_state_path(Path.cwd())
        store = StateStore(path)
        click.echo(f"Fingerprints: {len(store.fingerprint_keys())}")
        click.echo(f"Scopes: {len(store.scope_ids())}")
        click.echo(f"History entries: {len(store.get_history())}")
        click.echo(f"State path: {path}")

    @state_app.command("clear")
    def state_clear() -> None:
        """Reset runtime state. Does not touch the discovery cache."""
        from pathlib import Path

        from functualize.app.utils import StateStore, resolve_state_path

        path = resolve_state_path(Path.cwd())
        if not path.exists():
            raise SystemExit(0)
        StateStore(path).clear()
        click.echo("Runtime state cleared.")

    _mount(builtin_app, state_app, "state")

    # --- Workflow sub-group (D2b: MCP↔CLI parity over the state store) ---
    # These mirror the MCP workflow tools. `list`/`state`/`cancel` read the
    # state store directly (public, no boot); `resume` deposits gate input
    # through the SAME lifted `deposit_gate_input` the MCP `resume_gate` tool
    # calls, so there is one notion of "accept input for a gate".
    #
    # `--format` is domain-aware and command-owned: `list`/`state` know their
    # items are workflow scopes, so `json` emits structured scope objects — a
    # different concern from the global `--output`, which only serializes the
    # dispatch layer's return value.
    workflow_app = click.Group(
        name="workflow", help="Inspect and resume persisted workflow scopes."
    )
    _live_statuses = ("running", "blocked")

    def _workflow_store() -> Any:
        from pathlib import Path

        from functualize.app.utils import StateStore

        return StateStore.for_project(Path.cwd())

    def _scope_summary(scope_id: str, scope: dict[str, Any]) -> dict[str, Any]:
        from functualize.app.utils import pending_gates

        return {
            "workflow_id": scope_id,
            "workflow": scope.get("workflow"),
            "status": scope.get("status"),
            "position": scope.get("position"),
            "pending_gates": [name for name, _ in pending_gates(scope)],
        }

    @workflow_app.command("list")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the workflow scopes as a table or JSON.",
    )
    def workflow_list(fmt: str) -> None:
        """List active (running or blocked) workflow scopes."""
        store = _workflow_store()
        items = [
            _scope_summary(sid, scope)
            for sid in store.scope_ids()
            if (scope := store.get_scope(sid)) is not None
            and scope.get("status") in _live_statuses
        ]
        if fmt == "json":
            import json

            click.echo(json.dumps({"workflows": items}, indent=2))
            return
        if not items:
            click.echo("No active workflows.")
            return
        for it in items:
            gates = ", ".join(it["pending_gates"]) or "-"
            click.echo(
                f"{it['workflow_id']}  {it['workflow']}  {it['status']}  gates: {gates}"
            )

    @workflow_app.command("state")
    @click.argument("workflow_id")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the scope as a table or JSON.",
    )
    def workflow_state(workflow_id: str, fmt: str) -> None:
        """Show one workflow scope's status, position, and pending gates."""
        scope = _workflow_store().get_scope(workflow_id)
        if scope is None:
            click.echo(f"Error: no workflow scope '{workflow_id}'.", err=True)
            raise SystemExit(1)
        detail = _scope_summary(workflow_id, scope)
        if fmt == "json":
            import json

            click.echo(json.dumps(detail, indent=2))
            return
        click.echo(f"Workflow: {detail['workflow']}")
        click.echo(f"Status:   {detail['status']}")
        click.echo(f"Position: {detail['position']}")
        click.echo(f"Pending gates: {', '.join(detail['pending_gates']) or '-'}")

    @workflow_app.command("resume")
    @click.argument("workflow_id")
    @click.argument("gate")
    @click.option(
        "--input",
        "input_json",
        default="{}",
        help="Gate input as a JSON object, e.g. '{\"approved\": true}'.",
    )
    @click.pass_context
    def workflow_resume(
        ctx: click.Context, workflow_id: str, gate: str, input_json: str
    ) -> None:
        """Deposit input for a blocked gate (mirrors the MCP resume_gate tool).

        Accepting input does not run the workflow — invoke the workflow job with
        the same scope_id to continue past the gate.
        """
        import json

        from functualize.app.utils import deposit_gate_input

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)
        try:
            payload = json.loads(input_json)
        except json.JSONDecodeError as exc:
            click.echo(f"Error: --input is not valid JSON: {exc}", err=True)
            raise SystemExit(2) from exc

        result = deposit_gate_input(
            obj["app"], _workflow_store(), workflow_id, gate, payload
        )
        if "error" in result:
            click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(1)
        click.echo(result["message"])

    @workflow_app.command("cancel")
    @click.argument("workflow_id")
    def workflow_cancel(workflow_id: str) -> None:
        """Cancel a workflow scope."""
        store = _workflow_store()
        if store.get_scope(workflow_id) is None:
            click.echo(f"Error: no workflow scope '{workflow_id}'.", err=True)
            raise SystemExit(1)
        store.set_scope_status(workflow_id, "cancelled")
        click.echo(f"Workflow '{workflow_id}' cancelled.")

    _mount(builtin_app, workflow_app, "workflow")

    # --- parallel (T40) ---
    # `Invoke.parallel` has existed since S1 and was reachable only from inside
    # a job, so "run these four jobs at once" required writing a job whose only
    # purpose was to call it. This is the same operation from the command line,
    # over the same code — not a second implementation.
    @builtin_app.command("parallel")
    @click.argument("job_names", nargs=-1, required=True)
    @click.option(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Seconds before unfinished jobs are reported as timed out "
            "(default 300; 0 waits indefinitely)."
        ),
    )
    @click.option(
        "--output",
        "output_mode",
        type=click.Choice(OUTPUT_MODES),
        default="interleaved",
        show_default=True,
        help="How to present the output of jobs that all run at once.",
    )
    @click.pass_context
    def parallel_command(
        ctx: click.Context,
        job_names: tuple[str, ...],
        timeout: float | None,
        output_mode: str,
    ) -> None:
        """Run several jobs concurrently and report on all of them."""
        from functualize._cli.parallel_output import ParallelOutput

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)

        app = obj["app"]
        try:
            with ParallelOutput(output_mode) as router:
                results = app.execute_parallel(
                    job_names,
                    timeout=timeout,
                    observer=router if output_mode != "interleaved" else None,
                )
        except ValueError as exc:
            # The >32 guard, and anything else the capability rejects up front.
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(ExitCode.USAGE) from exc

        _report_parallel(job_names, results)

    # --- history (T42) ---
    # The engine appends a record per top-level run to the same ring the shell
    # surface writes to, so one command answers "what has run here lately?"
    # across both. `--namespace` narrows to one kind when the mix is noise.
    @builtin_app.command("history")
    @click.option(
        "--namespace",
        default=None,
        help="Show only one namespace (e.g. job, shell).",
    )
    @click.option(
        "--limit",
        type=int,
        default=None,
        help="Show at most this many of the most recent records.",
    )
    def history_command(namespace: str | None, limit: int | None) -> None:
        """Show recent runs, newest first."""
        from pathlib import Path

        from functualize.app.utils import StateStore, resolve_state_path

        path = resolve_state_path(Path.cwd())
        # Read directly, not via `for_project`: history is inspected far more
        # often than it is written, and reading must not create a state file in
        # a project that has never run anything.
        if not path.exists():
            click.echo("No history recorded yet.", err=True)
            return

        records = StateStore(path).get_history()
        if namespace is not None:
            records = [r for r in records if r.get("namespace") == namespace]
        if limit is not None:
            records = records[:limit]

        if not records:
            where = f" in namespace '{namespace}'" if namespace else ""
            click.echo(f"No history recorded yet{where}.", err=True)
            return

        for line in _render_history(records):
            click.echo(line)

    # --- env (T43) ---
    # A job's resolved config, as environment variables — so a tool that is not
    # functualize can consume it. Two forms over one resolution: print exports
    # to eval, or exec a command with the vars injected. Secrets are gated:
    # masked in the printed form, omitted from the exec env, unless the caller
    # opts in with --include-secrets. The default output is therefore safe to
    # paste into a bug report; the real secret takes a deliberate flag.
    @builtin_app.command(
        "env",
        context_settings={"ignore_unknown_options": True},
    )
    @click.argument("job_name")
    @click.argument("command", nargs=-1, type=click.UNPROCESSED)
    @click.option(
        "--include-secrets",
        is_flag=True,
        default=False,
        help="Include real secret values (default: masked / omitted).",
    )
    @click.pass_context
    def env_command(
        ctx: click.Context,
        job_name: str,
        command: tuple[str, ...],
        include_secrets: bool,
    ) -> None:
        """Export a job's resolved config as environment variables.

        \b
        Print form:  eval $(func builtin env deploy)
        Exec form:   func builtin env deploy -- kubectl apply -f -
        """
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)

        env_vars = _resolve_env_vars(obj["app"], job_name)

        # `--` is consumed by click; a leading token that is not an option is
        # the command. `ignore_unknown_options` lets `kubectl -f` through.
        exec_command = list(command)

        if exec_command:
            _env_exec(env_vars, exec_command, include_secrets)
        else:
            _env_print(env_vars, include_secrets)

    # --- shell-init (T44b) ---
    # Boot once, bake the word lists into a static shell script, and put zero
    # Python in the TAB path (the direnv model). Warm boot is ~400ms — a
    # completion that ran `func` per keystroke would be unusable.
    @builtin_app.command("shell-init")
    @click.argument("shell", type=click.Choice(SHELLS))
    @click.option(
        "--install",
        is_flag=True,
        default=False,
        help="Write the script under the cache dir instead of printing it.",
    )
    @click.pass_context
    def shell_init_command(ctx: click.Context, shell: str, install: bool) -> None:
        """Emit a static shell completion script (bash, zsh, or fish)."""
        from functualize._cli.completions.data import extract_completion_data
        from functualize._cli.completions.shell_init import render_completion_script

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)

        data = extract_completion_data(obj["app"])
        script = render_completion_script(data, shell)

        if not install:
            click.echo(script, nl=False)
            return

        path = _completions_install_path(shell)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script, encoding="utf-8")
        # The path and the source line go to stderr so `--install` composes: a
        # user who redirects stdout still gets a clean file, and the hint is
        # advice, not data.
        click.echo(f"Wrote {shell} completion to {path}", err=True)
        click.echo(f"Add to your shell startup:  source {path}", err=True)

    # --- why (explainability, §D.6) ---
    # The renderer shipped at the S3 stage gate with tests and no command to
    # reach it, so "why did this job run?" had no answer on the command line
    # while the code to answer it sat unused.
    @builtin_app.command("why")
    @click.argument("job_name")
    @click.pass_context
    def why_command(ctx: click.Context, job_name: str) -> None:
        """Explain whether a job would run, and why."""
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)

        click.echo(obj["app"].explain(job_name))

    # --- Config sub-group ---
    @click.group(
        name="config",
        help="Inspect and manage CLI tool configuration.",
        invoke_without_command=True,
    )
    @click.pass_context
    def config_app(ctx: click.Context) -> None:
        """Inspect and manage CLI tool configuration."""
        if ctx.invoked_subcommand is None:
            # Show help with subcommand descriptions
            click.echo("Usage: func config <subcommand>\n")
            click.echo("Subcommands:")
            click.echo(
                "  show   Display resolved config in TOML with source annotations"
            )
            click.echo("  path   Show config file paths with status")
            click.echo("  edit   Open global config in your editor")
            click.echo("  migrate  Convert an INI config file to TOML")
            click.echo("\nRun 'func config <subcommand> --help' for details.")

    @config_app.command("show")
    def config_show() -> None:
        """Display resolved config in TOML with source annotations."""
        from functualize._cli.config import read_global_config, resolve_cli_config
        from functualize.app.utils import (
            resolve_project_config,
            resolve_user_config_dir,
        )

        cli_config = resolve_cli_config()
        config_dir = resolve_user_config_dir()
        global_config = read_global_config(config_dir)
        _anchor, project_config = resolve_project_config(Path.cwd())

        # Build TOML output with source annotations
        lines: list[str] = []
        lines.append("[discovery]")

        dc = cli_config.discovery
        _emit_config_field(
            lines,
            "exclude_patterns",
            list(dc.exclude_patterns),
            dc.exclude_patterns,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "extra_directories",
            list(dc.extra_directories),
            dc.extra_directories,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_prefix",
            dc.require_file_prefix,
            dc.require_file_prefix,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_postfix",
            dc.require_file_postfix,
            dc.require_file_postfix,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_import",
            dc.require_file_import,
            dc.require_file_import,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_file_marker",
            dc.require_file_marker,
            dc.require_file_marker,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_job_decorators",
            list(dc.require_job_decorators) if dc.require_job_decorators else None,
            dc.require_job_decorators,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_job_prefix",
            dc.require_job_prefix,
            dc.require_job_prefix,
            project_config,
            global_config,
            "discovery",
        )
        _emit_config_field(
            lines,
            "require_job_postfix",
            dc.require_job_postfix,
            dc.require_job_postfix,
            project_config,
            global_config,
            "discovery",
        )

        lines.append("")
        lines.append("[cli]")
        _emit_config_field(
            lines,
            "output",
            cli_config.output,
            cli_config.output,
            project_config,
            global_config,
            "cli",
        )
        _emit_config_field(
            lines,
            "show_timing",
            cli_config.show_timing,
            cli_config.show_timing,
            project_config,
            global_config,
            "cli",
        )

        lines.append("")
        lines.append("[aliases]")
        for alias_name, alias_target in sorted(cli_config.aliases.items()):
            source = _determine_source(
                alias_name, alias_target, project_config, global_config, "aliases"
            )
            lines.append(f'{alias_name} = "{alias_target}"  # source: {source}')

        if not cli_config.aliases:
            lines.append("# (none configured)")

        click.echo("\n".join(lines))

    @config_app.command("path")
    def config_path() -> None:
        """Show config file paths with status (✓ used / ○ found / ✗ missing)."""
        from functualize.app.utils import resolve_user_config_dir

        config_dir = resolve_user_config_dir()
        global_path = config_dir / "config.toml"
        cwd = Path.cwd()
        pyproject_path = cwd / "pyproject.toml"
        functualize_toml_path = cwd / ".functualize.toml"

        # Determine global config status
        if global_path.exists():
            try:
                import tomllib as _tomllib

                content = global_path.read_bytes()
                data = _tomllib.loads(content.decode("utf-8"))
                # Check if any section has actual key-value pairs
                has_values = any(
                    (isinstance(v, dict) and v) or (not isinstance(v, dict))
                    for v in data.values()
                )
                if has_values:
                    click.echo(f"  ✓ used    {global_path}")
                else:
                    click.echo(f"  ○ found   {global_path}")
            except Exception:
                click.echo(f"  ○ found   {global_path}")
        else:
            click.echo(f"  ✗ missing {global_path}")

        # Determine project config status
        pyproject_has_functualize = False
        if pyproject_path.exists():
            try:
                import tomllib as _tomllib

                content = pyproject_path.read_bytes()
                data = _tomllib.loads(content.decode("utf-8"))
                tool_section = data.get("tool", {})
                if isinstance(tool_section, dict) and "functualize" in tool_section:
                    pyproject_has_functualize = True
                    click.echo(f"  ✓ used    {pyproject_path} [tool.functualize]")
                else:
                    click.echo(f"  ○ found   {pyproject_path} (no [tool.functualize])")
            except Exception:
                click.echo(f"  ○ found   {pyproject_path}")
        else:
            click.echo(f"  ✗ missing {pyproject_path}")

        # .functualize.toml: only relevant if pyproject doesn't have [tool.functualize]
        if not pyproject_has_functualize:
            if functualize_toml_path.exists():
                click.echo(f"  ✓ used    {functualize_toml_path}")
            else:
                click.echo(f"  ✗ missing {functualize_toml_path}")

    @config_app.command("edit")
    def config_edit() -> None:
        """Open global config in $VISUAL / $EDITOR / platform default."""
        from functualize.app.utils import resolve_user_config_dir

        config_dir = resolve_user_config_dir()
        config_path = config_dir / "config.toml"

        # Resolve editor: $VISUAL → $EDITOR → platform default
        editor = _resolve_editor()
        if not editor:
            click.echo(
                "Error: No editor found. Set $VISUAL or $EDITOR environment variable.",
                err=True,
            )
            raise SystemExit(1)

        # Create parent directory if needed
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create template config if file doesn't exist
        if not config_path.exists():
            config_path.write_text(_CONFIG_TEMPLATE)

        # Open in editor
        try:
            subprocess.run([editor, str(config_path)], check=True)  # noqa: S603
        except FileNotFoundError:
            click.echo(f"Error: Editor '{editor}' not found on PATH.", err=True)
            raise SystemExit(1) from None
        except subprocess.CalledProcessError as exc:
            click.echo(f"Error: Editor exited with code {exc.returncode}.", err=True)
            raise SystemExit(exc.returncode) from None

    @config_app.command("migrate")
    @click.argument("source", type=click.Path(exists=False, dir_okay=False))
    @click.argument("destination", type=click.Path(dir_okay=False), required=False)
    def config_migrate(source: str, destination: str | None) -> None:
        """Convert an INI config file to TOML.

        TOML is the only format Functualize registers by default (ADR-007).
        This converts a file that predates that decision. The source is left
        in place — nothing is deleted for you.
        """
        from functualize.app.utils import MigrationError, migrate_ini_to_toml

        target = destination or str(Path(source).with_suffix(".toml"))

        if Path(target).exists():
            click.echo(f"Error: '{target}' already exists.", err=True)
            raise SystemExit(1)

        try:
            migrate_ini_to_toml(source, target)
        except MigrationError as exc:
            click.echo(f"Error: {exc}", err=True)
            click.echo(
                "INI interpolation has no TOML equivalent — "
                "resolve the reference by hand, then re-run.",
                err=True,
            )
            raise SystemExit(1) from None
        except OSError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from None

        click.echo(f"Wrote {target}")
        click.echo(f"Review it, then remove {source}.")

    _mount(builtin_app, config_app, "config")

    # --- Domains sub-group ---
    domains_app = click.Group(name="domains", help="Discover and inspect domain SDKs.")

    @domains_app.command("list")
    def domains_list() -> None:
        """Display all discovered domains with providers and active selection."""
        from functualize.plugin import discover_domains, scan_domain_providers

        domains = discover_domains()

        if not domains:
            click.echo("No domains discovered.")
            click.echo("")
            click.echo("Install a domain SDK package to get started:")
            click.echo("  pip install functualize-state")
            click.echo("  pip install functualize-ai")
            click.echo("  pip install functualize-tasks")
            return

        click.echo("Discovered Domains:")
        click.echo("")

        for meta in sorted(domains, key=lambda d: d.name):
            providers = scan_domain_providers(meta)
            provider_names = sorted(providers.keys()) if providers else []

            # A single installed provider auto-wires at boot; with multiple
            # installed and none configured, none is wired — the honest
            # "installed but not wired" state the signpost below explains.
            active_provider: str | None = None
            if len(provider_names) == 1:
                active_provider = provider_names[0]

            click.echo(f"  {meta.display_name} ({meta.name})")

            if provider_names:
                providers_display = []
                for pname in provider_names:
                    if pname == active_provider:
                        providers_display.append(f"{pname} (active)")
                    else:
                        providers_display.append(pname)
                click.echo(f"    Providers: {', '.join(providers_display)}")
                if active_provider is None:
                    # Installed but not wired — tell the user how to wire one.
                    click.echo(
                        f"    Not wired: multiple providers installed; set "
                        f'provider = "<name>" in the [{meta.config_section}] '
                        f"config section to activate one."
                    )
            else:
                click.echo("    Providers: (none installed)")

            click.echo("")

    _mount(builtin_app, domains_app, "domains")

    # --- Scaffold sub-group ---
    from functualize._cli.scaffold.cli import scaffold_app

    _mount(builtin_app, scaffold_app, "scaffold")

    # --- Top-level version command ---
    @click.command("version")
    def version_command() -> None:
        """Show the functualize version."""
        from functualize import __version__

        click.echo(f"functualize {__version__}")

    _mount(builtin_app, version_command, "version")

    # --- Show-info command (resolves app lazily from ctx.obj) ---
    @click.command("show-info")
    @click.option(
        "--job",
        default=None,
        help="Show resolved JobConfig values for a specific job.",
    )
    @click.option(
        "--show-env-vars",
        is_flag=True,
        default=False,
        help="Display all current process environment variables.",
    )
    @click.pass_context
    def show_info_command(
        ctx: click.Context, job: str | None, show_env_vars: bool
    ) -> None:
        """Show current CLI configuration, discovered jobs, and resolved config."""
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)

        from functualize.app.adapters.cli import _show_info_impl

        _show_info_impl(obj["app"], job=job, show_env_vars=show_env_vars)

        # Display resolution info (import_libs, anchor, convention dirs)
        cli_config = obj.get("cli_config")
        if cli_config is not None:
            click.echo("")
            click.echo("─── Config Resolution ───")
            anchor = getattr(cli_config, "anchor", None)
            if anchor is not None:
                click.echo(f"  Anchor: {anchor}")

            import_libs = getattr(cli_config, "import_libs", ())
            if import_libs:
                click.echo("  import_libs:")
                for lib_path in import_libs:
                    click.echo(f"    - {lib_path}")
            else:
                click.echo("  import_libs: (none)")

            # Show convention directories detected
            if anchor is not None:
                conv_dirs: list[str] = []
                for subdir in ("jobs", "lib", "plugins"):
                    conv_path = anchor / ".functualize" / subdir
                    if conv_path.is_dir():
                        conv_dirs.append(f".functualize/{subdir}/")
                if conv_dirs:
                    click.echo("  Convention dirs:")
                    for d in conv_dirs:
                        click.echo(f"    - {d}")
                else:
                    click.echo("  Convention dirs: (none detected)")

    _mount(builtin_app, show_info_command, "info")

    _mount(cli_group, builtin_app, "builtin")
