"""Built-in CLI commands: cache, version, config.

These commands are registered on the ``func`` click.Group alongside job
commands. All imports are from the public API only.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from functualize._cli.parallel_output import OUTPUT_MODES
from functualize.app.utils import WORKFLOW_STATES, ExitCode, Family, is_failure


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
    #: Populated on the ``builtin`` root only, with the families beneath it.
    #: Its presence is what makes :meth:`needs_terminal` resolve a family
    #: before matching, rather than matching a bare name against every
    #: family's declarations at once.
    children: tuple[BuiltinCommand, ...] = ()

    @property
    def subcommand_map(self) -> dict[str, str]:
        """Ordered ``{subcommand: description}`` mapping."""
        return dict(self.subcommands)

    def needs_terminal(self, args: list[str]) -> bool:
        """Return True if invoking this command with ``args`` needs the terminal.

        On a **family** (``config``, ``skills``, …) ``args`` is that family's
        own subcommand path, and a plain membership test is the whole answer.

        On the **root**, ``args`` starts with a family name, so the family is
        resolved first and asked about the rest. Matching the flattened set
        instead would make any name declared by one family match inside every
        other: with ``plugin install`` terminal-owning, ``skills install``
        would answer True as well. Names cannot be chosen to avoid that —
        ``skills`` shipped an ``install`` after ``install``/``uninstall`` were
        picked precisely because nothing else used them.
        """
        if self.children and args:
            for child in self.children:
                if child.name == args[0]:
                    return child.needs_terminal(list(args[1:]))
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
        "Manage runtime state (fingerprints, history, session, scopes)",
        (
            ("show", "Show runtime state statistics"),
            ("clear", "Reset derived state; --scopes also discards workflow runs"),
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
        "skills",
        "Locate and install the AI agent skills shipped with this version",
        (
            ("path", "Print the directory holding this version's skills"),
            ("list", "List the shipped skills with their descriptions"),
            ("materialize", "Copy the skills into the XDG data directory"),
            ("install", "Install the skills into a project via the skills CLI"),
        ),
        requires_subcommand=True,
        # `skills install` shells out to `npx skills add`, which prompts. The
        # subprocess inherits fd 0/1/2, which is what makes it work from a real
        # terminal — and what breaks it on the TUI's worker path, where
        # `invoke_builtin` redirects only Python-level `sys.stdout` and the
        # child prompts onto the terminal underneath the interface.
        terminal_subcommands=("install",),
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
            ("list", "Survey workflow scopes, with filters"),
            ("show", "Show one scope in full — graph, results, gates"),
            ("answer", "Record input for a gate — partial, whole, or corrected"),
            ("resume", "Advance a scope, optionally answering a gate first"),
            ("gate-tool", "Run a tool a waiting gate offers"),
            ("cancel", "Cancel a workflow scope — terminal"),
            ("purge", "Delete finished scopes"),
        ),
        requires_subcommand=True,
    ),
    BuiltinCommand("parallel", "Run several jobs concurrently"),
    BuiltinCommand("history", "Show recent job and shell runs"),
    BuiltinCommand("env", "Export a job's resolved config as environment variables"),
    BuiltinCommand("shell-init", "Emit a static shell completion script"),
    BuiltinCommand("why", "Explain whether a job would run, and why"),
    BuiltinCommand("version", "Show the functualize version"),
    BuiltinCommand(
        "plugin",
        "Inspect and manage installed extensions",
        (
            ("list", "List every installed extension and what provides it"),
            ("available", "List plugins that exist, grouped by what they do"),
            ("install", "Install an extension, or --recommended for the set"),
            ("uninstall", "Remove an extension"),
        ),
        requires_subcommand=True,
        # Both mutating commands run a package manager that inherits fd 0/1/2 --
        # uv draws progress, an index can prompt for credentials. Same reason as
        # `self install`; `list` only reads metadata and stays on the worker.
        terminal_subcommands=("install", "uninstall"),
    ),
    BuiltinCommand(
        "self",
        "Inspect and manage this installation",
        (
            ("doctor", "Check this installation and report what is wrong"),
            ("update", "Upgrade this installation and restore what you added"),
            ("install", "Add a package to this installation's environment"),
            ("python", "Run this installation's interpreter, or print its path"),
            ("uv", "Run the uv this installation uses, or print its path"),
        ),
        requires_subcommand=True,
        # All four mutating-or-passthrough subcommands own the terminal. Each
        # runs a child that inherits fd 0/1/2 -- uv draws progress, pipx and an
        # index can prompt for credentials, and `self python -- ...` runs
        # whatever the user asked for. On the TUI's worker path only Python-level
        # `sys.stdout` is redirected, so the child would draw straight onto the
        # terminal underneath the interface. That is the `skills install` defect
        # P2 fixed, and `update` has it for exactly the same reason the other
        # three do.
        #
        # Bare `self python` also hands over the terminal to print one line,
        # which is cosmetic; `needs_terminal` is a single answer per subcommand
        # (`_types/commands.py:52-70`) and the passthrough is the form worth
        # getting right.
        terminal_subcommands=("update", "install", "python", "uv"),
    ),
    BuiltinCommand(
        "vault",
        "Sync and inspect this project's encrypted secrets vault",
        (
            ("sync", "Fetch every declared annotation and store it"),
            ("list", "List what is stored — names and freshness, never values"),
            ("status", "Show the key provider in use, the age, and the count"),
            ("clear", "Delete this project's vault"),
            ("keygen", "Print a fresh vault key"),
        ),
        requires_subcommand=True,
        # None of the five takes the terminal. `keygen` writes to stdout so it
        # can be piped, and the interactive key provider is the *keychain*,
        # which prompts through the OS rather than through this process.
    ),
    BuiltinCommand(
        "info",
        "Display app state, discovered jobs, and config",
        (
            ("jobs", "List discovered jobs, or show one in detail"),
            ("schema", "Print every job's input contract as JSON Schema"),
            ("all", "Everything info knows, as one document"),
        ),
        # Bare `info` is the overview and the documented first stop; the
        # subcommands narrow it. Requiring one would break every skill,
        # doc and habit that says "run func builtin info".
        requires_subcommand=False,
    ),
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
    # The children themselves, not a flattened set of their subcommand names.
    # `builtin config edit` still spawns $EDITOR on the controlling terminal
    # and a TUI front-end must still suspend itself around it, but the answer
    # now comes from `config` rather than from every family at once — see
    # `needs_terminal`. The root declares no `terminal_subcommands` of its
    # own: it owns no subcommands, only families.
    children=BUILTIN_COMMANDS,
)


#: The builtins whose job is to explain or repair a project that is broken.
#:
#: They boot the project like everything else, so a project-wide contradiction
#: — two files declaring ``GroupOptions`` for one group — used to stop them the
#: way it stops a run: exit 2, nothing on stdout. That made ``func builtin why``
#: unable to answer *"why is my job missing?"* in the one case where the answer
#: was the contradiction, and made ``builtin cache rebuild`` — the documented
#: way to clear a bad cache — die before its own scan (adj M4, decision D-4).
#:
#: Everything absent from this set stays fatal, ``builtin parallel`` included:
#: it runs jobs, and the rule is about not *running* under an ambiguity, not
#: about which door was used.
DIAGNOSTIC_BUILTINS: frozenset[str] = frozenset({"cache", "info", "self", "why"})


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

    from functualize.app.utils import display_value, reveal

    for f in env_vars:
        if not f.is_set:
            note = "REQUIRED — not set" if f.required else "not set"
            click.echo(f"# {f.env_name}=  # {note}")
            continue
        # `reveal` unwraps a `Secret`; whether that real value is shown is the
        # caller's opt-in, decided here rather than at resolution time.
        shown = (
            str(reveal(f.value))
            if include_secrets
            else display_value(f.value, secret=f.secret)
        )
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
        # `func builtin parallel` is a PROCESS surface: it terminates the
        # process with an exit code a shell reads. The family answers, this
        # site does not.
        #
        # This *changes* one answer, deliberately. The tuple that used to live
        # here counted BLOCKED as not-a-failure, so a batch in which a job
        # paused at a gate exited 0 — "all good" — and the pause was invisible
        # to anything reading only the exit code. That is the same false clean
        # as D-7, and the reason the exit-code table reserves 5 for it.
        if is_failure(status, family=Family.PROCESS):
            failed.append(result)

    if not failed:
        return

    # One batch, one exit code. With several distinct failures there is no
    # single honest answer, so the *first* one is reported rather than an
    # invented aggregate — it is the one whose message was printed first, and
    # re-running after fixing it surfaces the next.
    raise SystemExit(exit_code_for_status(failed[0].status))


def _state_location() -> tuple[Path, str, Path | None]:
    """The resolved state path, its mode, and the directory that decided it.

    One upward walk through the same function the engine uses, so the CLI
    cannot report a path the engine would not write to.
    """
    from functualize.app.utils import resolve_state_location

    return resolve_state_location(Path.cwd())


def _state_mode_line(mode: str, marker: Path | None) -> str:
    """Render the state-store mode for a human.

    Both modes name what put them there, because "which mode am I in" was
    undiscoverable and the answer decides where to look for the file. In
    standalone mode the line also names the switch — a project that wants its
    ledger versioned with the code only needs `mkdir .functualize`.
    """
    if mode == "project":
        return f"project (.functualize/ found at {marker})"
    return (
        "standalone (no .functualize/ found; create one to keep state in the project)"
    )


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
        """Build the cached provider over auto-discovered job directories.

        Built from the *resolved* discovery config -- including this
        invocation's own global flags, so `func --exclude '…' builtin cache
        rebuild` rebuilds under that exclusion rather than ignoring it.

        Passing no config made every `func builtin cache` command bare, and a
        bare provider persists `discovery_hash: null`. `cache rebuild` unlinks
        the file and then writes through such a provider, so the next command
        read a null fingerprint, called it a mismatch, and rescanned -- throwing
        away the rebuild it had just been asked for, in every project including
        one with no filters at all. See ADR-011.
        """
        from functualize._cli.config import resolve_cli_config
        from functualize._cli.dispatch import _extract_global_options
        from functualize.app.utils import build_discovery_cache_provider

        _global_opts, cli_flags = _extract_global_options(sys.argv)
        cli_config = resolve_cli_config(cli_flags=cli_flags)

        return build_discovery_cache_provider(discovery_config=cli_config.discovery)

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
        name="state",
        help=(
            "Manage runtime state — fingerprints, run history, the session "
            "precondition cache, and workflow scopes."
        ),
    )

    @state_app.command("show")
    def state_show() -> None:
        """Show runtime state statistics."""
        from functualize.app.utils import (
            SCOPES_VERSION,
            ScopeStoreUnreadableError,
            StateStore,
        )

        path, mode, marker = _state_location()
        store = StateStore(path)
        click.echo(f"Fingerprints: {len(store.fingerprint_keys())}")

        # `show` is the command someone runs to find out what is wrong, so it
        # reports an unreadable scope store as a line rather than dying on it —
        # every other statistic is still worth having. The exit code is still
        # 2: nothing here is fine.
        fault: ScopeStoreUnreadableError | None = None
        try:
            click.echo(f"Scopes: {len(store.scope_ids())}")
        except ScopeStoreUnreadableError as exc:
            fault = exc
            found = exc.found_version
            detail = (
                f"found version {found}, expected {exc.expected_version}"
                if found is not None
                else "contents could not be parsed"
            )
            count = "" if exc.scope_count is None else f"{exc.scope_count} scopes, "
            click.echo(f"Scopes:       unreadable — {count}{detail}")

        click.echo(f"History entries: {len(store.get_history())}")
        click.echo(f"State path: {path}")
        click.echo(f"Scopes path: {store.scopes_path}")
        click.echo(f"Scopes format: v{SCOPES_VERSION}")
        click.echo(f"Mode:       {_state_mode_line(mode, marker)}")

        if fault is not None:
            click.echo("")
            click.echo(
                "Error: run `func builtin state clear --scopes` to move the "
                "scope file aside and start fresh.",
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)

    @state_app.command("clear")
    @click.option(
        "--scopes",
        "clear_scopes",
        is_flag=True,
        help="Also discard persisted workflow scopes, including in-flight runs.",
    )
    def state_clear(clear_scopes: bool) -> None:
        """Reset derived runtime state — fingerprints, run history, and the
        session precondition cache.

        Workflow scopes are kept unless --scopes is passed: a scope is a run
        somebody is waiting on, not a cache. Never touches the discovery cache.
        """
        from pathlib import Path

        from functualize.app.utils import (
            ScopeStoreUnreadableError,
            StateStore,
            resolve_scopes_path,
            resolve_state_path,
        )

        path = resolve_state_path(Path.cwd())
        scopes_path = resolve_scopes_path(Path.cwd())
        if not path.exists() and not scopes_path.exists():
            raise SystemExit(0)

        store = StateStore(path)

        # Counted before clearing, and best-effort: an unreadable scope store
        # is exactly when --scopes matters most, so it must not block the one
        # command that resolves it.
        kept = None
        try:
            kept = len(store.scope_ids())
        except ScopeStoreUnreadableError:
            kept = None

        moved = store.clear(scopes=clear_scopes)
        click.echo("Cleared fingerprints, history and session state.")

        if clear_scopes:
            if moved is None:
                return
            noun = "scope" if kept == 1 else "scopes"
            count = "" if kept is None else f"{kept} workflow {noun}"
            click.echo(f"Cleared {count or 'the workflow scope file'}.")
            click.echo(f"  Moved aside to: {moved}")
        elif kept:
            noun = "scope" if kept == 1 else "scopes"
            click.echo(
                f"Kept {kept} workflow {noun} — pass --scopes to clear those too."
            )
        elif kept is None:
            click.echo(
                "Kept the workflow scope file, which could not be read — "
                "pass --scopes to move it aside."
            )

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

    #: One error code to exit code table. Both `builtin workflow` and the MCP
    #: tools use the same codes (`contracts.md` §7); only the CLI needs to turn
    #: them into exits, and doing it per-command is how two verbs end up
    #: disagreeing about what "ambiguous" is worth.
    _workflow_exits = {
        "workflow_not_found": 1,
        "gate_not_found": 1,
        "gate_not_answered": 1,
        "validation_error": 1,
        "gate_unresolvable": 1,
        "no_advanceable_scope": 1,
        "ambiguous_gate": int(ExitCode.USAGE),
        "ambiguous_scope": int(ExitCode.USAGE),
        "scope_cancelled": int(ExitCode.USAGE),
        "gate_already_answered": int(ExitCode.USAGE),
        "gate_already_consumed": int(ExitCode.USAGE),
        "tool_not_permitted": int(ExitCode.USAGE),
        "argument_not_permitted": int(ExitCode.USAGE),
    }

    def _workflow_store() -> Any:
        """The store the `builtin workflow` subcommands read.

        One place, so an unreadable scope store refuses identically for
        `list`, `show`, `resume` and `cancel` — the alternative is four
        opinions about the same file.
        """
        from pathlib import Path

        from functualize.app.utils import StateStore

        return StateStore.for_project(Path.cwd())

    @contextlib.contextmanager
    def _workflow_refusal() -> Any:
        """Exit 2 rather than a traceback when the scope store cannot be read."""
        from functualize.app.utils import ScopeStoreUnreadableError

        try:
            yield
        except ScopeStoreUnreadableError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(ExitCode.USAGE) from exc

    def _render_scope(detail: dict[str, Any]) -> None:
        """One scope as text — the same projection `--format json` emits.

        The text form summarizes; it does not *reduce*. Anything omitted here
        is reachable with `--format json`, and nothing is computed differently.
        """
        click.echo(f"Workflow: {detail['workflow']}")
        click.echo(f"State:    {detail['state']}  (status: {detail['status']})")
        click.echo(f"Position: {detail['current_position']}")

        results = detail.get("results") or {}
        if results:
            click.echo("Steps:")
            for name, record in results.items():
                click.echo(
                    f"  {name}: {record.get('status')} -> {record.get('return_value')!r}"
                )

        branches = detail.get("branches") or {}
        if branches:
            chosen = ", ".join(f"{src} -> {tgt}" for src, tgt in branches.items())
            click.echo(f"Branches: {chosen}")

        gates = detail.get("pending_gates") or []
        if not gates:
            click.echo("Pending gates: -")
        else:
            click.echo("Pending gates:")
            for gate in gates:
                missing = ", ".join(gate.get("unresolved_fields") or []) or "-"
                click.echo(f"  {gate['gate']} ({gate.get('model')}) needs: {missing}")
                draft = gate.get("draft")
                if draft:
                    click.echo(f"    draft: {draft}")
                for tool in gate.get("tools") or []:
                    bound = ", ".join(tool.get("bound") or []) or "-"
                    click.echo(f"    tool {tool['tool']} (fixed: {bound})")

        epilogue = detail.get("epilogue")
        if epilogue:
            click.echo(f"Epilogue: {epilogue.get('status')}")

    def _workflow_app_ref(ctx: click.Context) -> Any:
        """The booted app, which the projection needs for graph topology.

        `list`/`show` read the store, but the *graph* comes from the discovery
        cache (or the live declaration as a fallback), and both are reached
        through the app. That is the only reason these verbs touch it.
        """
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)
        return obj["app"]

    @workflow_app.command("list")
    @click.option(
        "--workflow", "workflow_name", default=None, help="Only runs of this workflow."
    )
    @click.option(
        "--state",
        "state",
        default=None,
        type=click.Choice(list(WORKFLOW_STATES)),
        help="Only runs in this derived state. Naming one widens the "
        "search to finished runs too.",
    )
    @click.option(
        "--blocked-on",
        "blocked_on",
        default=None,
        help="Only runs waiting at this gate.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the workflow scopes as a table or JSON.",
    )
    @click.pass_context
    def workflow_list(
        ctx: click.Context,
        workflow_name: str | None,
        state: str | None,
        blocked_on: str | None,
        fmt: str,
    ) -> None:
        """Survey workflow scopes.

        With no filters, lists the runs that are still running or blocked.
        Naming --state widens the search to finished runs, because asking for
        `completed` and receiving nothing would be a silently empty answer to a
        well-formed question.
        """
        from functualize.app.utils import list_scopes

        app = _workflow_app_ref(ctx)
        store = _workflow_store()
        with _workflow_refusal():
            items = list_scopes(
                app,
                store,
                workflow_name=workflow_name,
                state=state,
                blocked_on=blocked_on,
            )
        if fmt == "json":
            import json

            click.echo(json.dumps({"workflows": items}, indent=2))
            return
        if not items:
            click.echo("No matching workflows.")
            return
        for it in items:
            # A one-line summary is a *rendering* of the shared projection, not
            # a second projection. The moment it had its own shape, `--format
            # json` and the MCP survey stopped being the same rows.
            gates = ", ".join(g["gate"] for g in it["pending_gates"]) or "-"
            click.echo(
                f"{it['workflow_id']}  {it['workflow']}  {it['state']}  gates: {gates}"
            )

    @workflow_app.command("show")
    @click.argument("workflow_id")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the scope as a table or JSON.",
    )
    @click.pass_context
    def workflow_show(ctx: click.Context, workflow_id: str, fmt: str) -> None:
        """Show one workflow scope in full.

        Replaces `state`, which emitted five fields — id, workflow, status,
        position and gate names — over records that had held the graph, each
        step's return value and resolved inputs, and every gate's schema all
        along. Same argument, strictly more output, and `--format json` now
        returns exactly what the MCP `get_workflow_state` tool returns.
        """
        from functualize.app.utils import describe_scope

        app = _workflow_app_ref(ctx)
        with _workflow_refusal():
            detail = describe_scope(app, _workflow_store(), workflow_id)
        if detail is None:
            click.echo(f"Error: no workflow scope '{workflow_id}'.", err=True)
            raise SystemExit(1)
        if fmt == "json":
            import json

            click.echo(json.dumps(detail, indent=2))
            return
        _render_scope(detail)

    def _parse_set(pairs: tuple[str, ...]) -> dict[str, Any]:
        """``--set k=v`` pairs into a dict, values JSON-typed.

        JSON rather than strings: a gate model with an ``int`` or a ``bool``
        field would otherwise reject every value the flag could express, and
        quoting is the caller's existing habit from ``--input``. A bare word
        that is not valid JSON is kept as a string, because ``--set env=prod``
        is the common case and demanding ``env='"prod"'`` for it would be a
        tax on the majority to serve the minority.
        """
        import json

        out: dict[str, Any] = {}
        for pair in pairs:
            key, sep, raw = pair.partition("=")
            if not sep:
                click.echo(f"Error: --set expects KEY=VALUE, got '{pair}'.", err=True)
                raise SystemExit(ExitCode.USAGE)
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                out[key] = raw
        return out

    @workflow_app.command("answer")
    @click.argument("workflow_id")
    @click.argument("gate")
    @click.option(
        "--input",
        "input_json",
        default=None,
        help="Merge a whole JSON object into the draft.",
    )
    @click.option(
        "--set",
        "set_pairs",
        multiple=True,
        metavar="KEY=VALUE",
        help="Merge one field into the draft (repeatable).",
    )
    @click.option(
        "--unset",
        "unset_keys",
        multiple=True,
        metavar="KEY",
        help="Remove a field from the draft (repeatable).",
    )
    @click.option("--clear", is_flag=True, help="Discard the draft entirely.")
    @click.option(
        "--replace",
        is_flag=True,
        help="With --input: replace the draft rather than merging.",
    )
    @click.option(
        "--show",
        "show_only",
        is_flag=True,
        help="Print the draft and what is still missing; change nothing.",
    )
    @click.option(
        "--commit/--no-commit",
        default=True,
        help="Validate and answer when the draft is complete (default: on).",
    )
    @click.option(
        "--reopen",
        is_flag=True,
        help="Move an answered payload back into the draft to correct it.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the result as a table or JSON.",
    )
    @click.pass_context
    def workflow_answer(
        ctx: click.Context,
        workflow_id: str,
        gate: str,
        input_json: str | None,
        set_pairs: tuple[str, ...],
        unset_keys: tuple[str, ...],
        clear: bool,
        replace: bool,
        show_only: bool,
        commit: bool,
        reopen: bool,
        fmt: str,
    ) -> None:
        """Record input for a gate. Never runs anything.

        `answer` records; `resume` advances. One meaning each, on every surface.

        A field at a time, or all at once — the draft accumulates until it
        validates whole, and only then is the gate answered. So two actors can
        fill different fields of the same gate, and neither has to hold the
        whole answer.
        """
        import json

        from functualize.app.utils import answer_gate, gate_draft

        app = _workflow_app_ref(ctx)
        store = _workflow_store()

        values = _parse_set(set_pairs)
        if input_json is not None:
            try:
                values = {**json.loads(input_json), **values}
            except json.JSONDecodeError as exc:
                click.echo(f"Error: --input is not valid JSON: {exc}", err=True)
                raise SystemExit(ExitCode.USAGE) from exc

        with _workflow_refusal():
            if show_only:
                result = gate_draft(app, store, workflow_id, gate)
            else:
                result = answer_gate(
                    app,
                    store,
                    workflow_id,
                    gate,
                    values,
                    mode="replace" if replace else "merge",
                    unset=list(unset_keys),
                    clear=clear,
                    commit=commit,
                    reopen=reopen,
                )

        if fmt == "json":
            click.echo(json.dumps(result, indent=2))
        if "error" in result:
            if fmt != "json":
                click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        if fmt == "json":
            return
        if show_only:
            _render_draft(result)
            return
        click.echo(result["message"])

    def _render_draft(report: dict[str, Any]) -> None:
        """The draft, and — the part that makes it usable — what is missing."""
        click.echo(f"Gate:     {report['gate']} ({report['model']})")
        click.echo(f"Draft:    {report['draft'] or '-'}")
        click.echo(f"Complete: {report['complete']}")
        for entry in report["missing"]:
            detail = f" — {entry['description']}" if entry.get("description") else ""
            click.echo(
                f"  missing: {entry['field']} ({entry.get('type') or '?'}){detail}"
            )
        for entry in report["invalid"]:
            click.echo(f"  invalid: {entry['field']} — {entry['message']}")

    @workflow_app.command("resume")
    @click.argument("workflow_id")
    @click.option(
        "--input",
        "input_json",
        default=None,
        help="Gate input to record before advancing.",
    )
    @click.option(
        "--gate",
        "gate",
        default=None,
        help="Which pending gate --input answers, when several.",
    )
    @click.option(
        "--retry-epilogue",
        is_flag=True,
        help="Clear a stalled epilogue so the body re-runs.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the result as a table or JSON.",
    )
    @click.pass_context
    def workflow_resume(
        ctx: click.Context,
        workflow_id: str,
        input_json: str | None,
        gate: str | None,
        retry_epilogue: bool,
        fmt: str,
    ) -> None:
        """Advance a workflow scope, optionally answering a gate first.

        `resume` advances; `answer` records. This verb used to *deposit* — its
        own docstring said "Accepting input does not run the workflow" — so
        nothing on any surface could continue a blocked walk except re-invoking
        the job, which an agent over MCP cannot do.

        The exit code is the walk's, so a run that is still blocked exits 5.
        """
        import json

        from functualize.app.utils import resume_scope

        app = _workflow_app_ref(ctx)
        store = _workflow_store()

        payload = None
        if input_json is not None:
            try:
                payload = json.loads(input_json)
            except json.JSONDecodeError as exc:
                click.echo(f"Error: --input is not valid JSON: {exc}", err=True)
                raise SystemExit(ExitCode.USAGE) from exc

        with _workflow_refusal():
            result = resume_scope(
                app,
                store,
                workflow_id,
                input=payload,
                gate=gate,
                retry_epilogue=retry_epilogue,
                # This door is `func builtin workflow resume`. It was labelled
                # `app.execute` by `guarded_execute`'s hardcoded constant, so a
                # CLI resume and a programmatic one were the same run as far as
                # the request could say (rre F9).
                surface="func.builtin",
            )

        if fmt == "json":
            click.echo(json.dumps(result, indent=2))
        if "error" in result:
            if fmt != "json":
                click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        if fmt != "json":
            click.echo(result.get("message") or f"Walk ended: {result['status']}.")
        raise SystemExit(_resume_exit(result))

    def _resume_exit(result: dict[str, Any]) -> int:
        """The walk's own outcome as an exit code.

        A still-blocked run exits 5, the same code the job itself uses. This is
        a breaking change from the deposit-only verb, which always exited 0 —
        and it is the point: a script that resumes in a loop needs to know
        whether it finished.
        """
        from functualize.app.utils import (
            RunStatus,
            exit_code_for_status,
            status_from_wire,
        )

        raw = str(result.get("status") or "")

        # `resume` reports in **two vocabularies through one field**: the walk's
        # RunStatus when it ran, and the gate-answer state when it did not. The
        # gate states are not run statuses, and the old fallback papered over
        # that by answering 0 for them -- which is how a still-waiting gate came
        # to report success, in direct contradiction of this method's own
        # docstring. Translate the gate vocabulary first, explicitly.
        gate_states = {
            # The input was incomplete, so it was saved and the gate still
            # blocks. That is a blocked run, and a blocked run exits 5.
            "drafted": RunStatus.BLOCKED,
        }
        status = gate_states.get(raw.strip().lower()) or status_from_wire(raw)
        if status is None:
            # The verb reported something that names no RunStatus. The old
            # fallback special-cased two gate-state strings that are not run
            # statuses at all and returned 0 for them, and 1 for everything
            # else. Returning 0 for an unrecognised string is how a resume loop
            # concludes it has finished when it has not. USAGE says what
            # actually happened: the caller and the verb disagree about the
            # vocabulary.
            return int(ExitCode.USAGE)
        return int(exit_code_for_status(status))

    @workflow_app.command("gate-tool")
    @click.argument("workflow_id")
    @click.argument("tool")
    @click.option(
        "--args", "args_json", default="{}", help="Tool arguments as a JSON object."
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["table", "json"]),
        default="table",
        help="Render the result as a table or JSON.",
    )
    @click.pass_context
    def workflow_gate_tool(
        ctx: click.Context, workflow_id: str, tool: str, args_json: str, fmt: str
    ) -> None:
        """Run a tool a waiting gate offers, inside that gate's scope.

        Arguments the gate fixes cannot be supplied — a bound argument is
        refused, never silently overridden. The call is recorded on the scope
        but never memoized: calling twice runs twice.
        """
        import json

        from functualize.app.utils import GateToolPolicy, call_gate_tool

        app = _workflow_app_ref(ctx)
        store = _workflow_store()
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as exc:
            click.echo(f"Error: --args is not valid JSON: {exc}", err=True)
            raise SystemExit(ExitCode.USAGE) from exc

        with _workflow_refusal():
            result = call_gate_tool(
                app,
                store,
                workflow_id,
                tool,
                args,
                policy=GateToolPolicy(app, store=store),
            )

        if fmt == "json":
            click.echo(json.dumps(result, indent=2))
        if "error" in result:
            if fmt != "json":
                click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        if fmt != "json":
            click.echo(
                f"{result['tool']}: {result['status']} -> {result['return_value']!r}"
            )

    @workflow_app.command("cancel")
    @click.argument("workflow_id")
    def workflow_cancel(workflow_id: str) -> None:
        """Cancel a workflow scope. Terminal — it cannot be resumed."""
        from functualize.app.utils import cancel_scope

        with _workflow_refusal():
            result = cancel_scope(_workflow_store(), workflow_id)
        if "error" in result:
            click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        click.echo(result["message"])

    @workflow_app.command("purge")
    @click.option(
        "--state", "state", default=None, help="Only scopes in this finished state."
    )
    @click.option(
        "--older-than",
        "older_than",
        type=float,
        default=None,
        metavar="DAYS",
        help="Only scopes whose newest recorded result is older.",
    )
    def workflow_purge(state: str | None, older_than: float | None) -> None:
        """Delete finished workflow scopes.

        Never touches a running, waiting or ready scope, and --state cannot
        name one: this is a hard delete with no backup, unlike
        `state clear --scopes`, which moves the whole file aside.
        """
        from functualize.app.utils import purge_scopes

        with _workflow_refusal():
            result = purge_scopes(
                _workflow_store(), state=state, older_than_days=older_than
            )
        if "error" in result:
            click.echo(f"Error: {result['message']}", err=True)
            raise SystemExit(_workflow_exits.get(result["error"], 1))
        click.echo(result["message"])
        for scope_id in result["removed"]:
            click.echo(f"  {scope_id}")

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
    @click.option(
        "--json",
        "as_json",
        is_flag=True,
        default=False,
        help="Emit the verdict as one JSON object instead of prose.",
    )
    @click.pass_context
    def why_command(ctx: click.Context, job_name: str, as_json: bool) -> None:
        """Explain whether a job would run, and why.

        Exits non-zero when the job is not up to date, so a script can branch on
        the answer: 0 fresh, 4 stale, 3 refused, 5 blocked at a gate, 2 for a
        job that cannot be resolved. `ExitCode.STALE` had no producer at all
        before this — a pinned number in a table described as "a contract with
        scripts and agents".
        """
        import json as _json

        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(1)

        app = obj["app"]
        payload = app.explain_data(job_name)
        # Both forms come off one set of verdicts (`explain_verdicts`), so the
        # JSON and the prose cannot disagree about the same job — which is the
        # failure `func builtin why` itself exists to make impossible.
        click.echo(_json.dumps(payload) if as_json else app.explain(job_name))

        code = int(payload.get("exit_code", 0))
        if code:
            raise SystemExit(code)

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

    # --- Skills sub-group (agent skills shipped with this version) ---
    # A sibling of `cache` and `state`, not a `scaffold` template: scaffold
    # output is user-owned and edited afterwards, while these are framework-
    # owned and replaced wholesale on upgrade (ADR-006 §3).
    skills_app = click.Group(
        name="skills",
        help="Locate and install the AI agent skills shipped with this version.",
    )

    def _require_skills_locations() -> list[Any]:
        """Core's location first, then every registered third-party host.

        Plural since `third-party-host-seams`/4.1: a distribution can host its
        own skills through the `functualize.skills` entry point, and every
        command below reports all of them rather than only core's.
        """
        from functualize._cli.skills import resolve_skills_locations

        locations = resolve_skills_locations()
        if not locations:
            click.echo(
                "No skills directory found for this installation.",
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)
        return locations

    @skills_app.command("path")
    def skills_path() -> None:
        """Print each directory holding agent skills, one per line.

        Machine-readable on purpose — bare paths, no decoration — but **one
        line per location**, not one path. A third-party distribution can host
        its own skills, so a single path could only ever be core's, and
        answering with core's alone silently hides the rest.

        That makes `"$(func builtin skills path)"` wrong: it substitutes a
        multi-line string as one argument. Loop instead:

            func builtin skills path | while read -r dir; do
                npx skills add "$dir"
            done
        """
        for location in _require_skills_locations():
            click.echo(str(location.path))

    @skills_app.command("list")
    def skills_list() -> None:
        """List the available skills with their descriptions."""
        from functualize._cli.skills import list_skills

        locations = _require_skills_locations()
        total = 0
        for location in locations:
            skills = list_skills(location.path)
            if location.is_packaged:
                origin = f"{location.distribution} {location.version} (packaged)"
            elif location.origin == "entry-point":
                origin = (
                    f"{location.distribution} {location.version} (entry point)"
                    if location.version
                    else f"{location.distribution} (entry point)"
                )
            else:
                origin = f"source checkout at {location.path} (not version-pinned)"

            click.echo(f"Agent skills from {origin}")
            click.echo("")
            if not skills:
                click.echo(f"  (none found in {location.path})")
                click.echo("")
                continue
            for skill in skills:
                total += 1
                click.echo(f"  {skill.name}")
                click.echo(f"    {skill.summary}")
                click.echo(f"    {skill.path}")
                click.echo("")

        if total == 0:
            click.echo("No skills found.")
            return
        click.echo("Install into a project:  func builtin skills install")

    @skills_app.command("materialize")
    @click.option(
        "--prune",
        is_flag=True,
        default=False,
        help="Also delete materialized skills for other functualize versions.",
    )
    def skills_materialize(prune: bool) -> None:
        """Copy this version's skills into the XDG data directory.

        Useful when the environment holding the wheel is disposable (uvx, a
        PEP 723 script env) or when a project that does not depend on
        functualize needs a stable path to point an agent at.
        """
        from functualize import __version__
        from functualize._cli.skills import materialize_skills

        for location in _require_skills_locations():
            # The *owning* distribution's version, never functualize's. The
            # whole promise of a version-stamped copy is that it describes the
            # release it came from, and a shared stamp would make a third-party
            # skill claim functualize's (`_cli/skills.py` docstring).
            version = location.version or __version__
            destination, names = materialize_skills(
                location.path,
                version,
                prune=prune,
                distribution=location.distribution,
            )
            for name in names:
                click.echo(f"  {name}")
            click.echo(f"{len(names)} skill(s) → {destination}")

    @skills_app.command("install")
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Print the command that would run instead of running it.",
    )
    def skills_install(dry_run: bool) -> None:
        """Install the shipped skills into the current project.

        Shells out to the skills CLI rather than reimplementing its
        agent-path matrix (ADR-006 §2). The source is the local directory, so
        what lands is pinned to the installed functualize — not whatever
        master happens to say today.
        """
        locations = _require_skills_locations()
        commands = [["npx", "skills", "add", str(loc.path)] for loc in locations]
        rendered = [" ".join(command) for command in commands]

        if dry_run:
            for line in rendered:
                click.echo(line)
            return

        if shutil.which("npx") is None:
            manual = "\n".join(
                f"  cp -R {loc.path}/* .claude/skills/" for loc in locations
            )
            click.echo(
                "npx was not found on PATH. The skills CLI needs Node.\n"
                "\n"
                "Run these once Node is available:\n"
                + "\n".join(f"  {line}" for line in rendered)
                + "\n"
                "\n"
                "Or copy the directories into your agent's skills folder:\n" + manual,
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)

        # Stop at the first failure rather than pressing on: a half-installed
        # skill set is harder to reason about than one that stopped and said so.
        for command, line in zip(commands, rendered, strict=True):
            click.echo(f"$ {line}")
            code = subprocess.call(command)
            if code != 0:
                raise SystemExit(code)
        raise SystemExit(0)

    _mount(builtin_app, skills_app, "skills")

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

    # --- Vault sub-group (ADR-016) ---
    # Everything here reaches the store through `app.utils`, never `_config`:
    # `_cli` may import only the public API, and more to the point the CLI must
    # not grow its own opinion about which key wins or what an annotation is.
    #
    # Only `sync` needs an app. `list`, `status`, `clear` and `keygen` answer
    # from the filesystem, which is deliberate -- the moment you most want to
    # ask "what is in my vault?" is when the app will not boot.
    vault_app = click.Group(
        name="vault",
        help="Sync and inspect this project's encrypted secrets vault.",
    )

    def _vault_app(ctx: click.Context) -> Any:
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo(
                "Error: `vault sync` needs the application, and no app context "
                "is available here.",
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)
        return obj["app"]

    def _vault_json(payload: Any) -> None:
        import json

        click.echo(json.dumps(payload, indent=2, default=str))

    @vault_app.command("keygen")
    def vault_keygen() -> None:
        """Print a fresh 32-byte vault key, hex-encoded.

        Written to stdout alone so it can be piped or captured. Nothing is
        stored: where the key lives is the operator's decision, and a command
        that quietly wrote one into a dotfile would be making it for them.
        """
        from functualize.app.utils import generate_vault_key

        click.echo(generate_vault_key())

    @vault_app.command("list")
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit the entry list as JSON.",
    )
    def vault_list(json_out: bool) -> None:
        """List what the vault holds — names and freshness, never values.

        Needs no key. `key`, `annotation`, `provider` and `synced_at` are
        stored in clear on purpose so this command works on a machine that
        cannot open the store; only the value is encrypted.
        """
        from functualize.app.utils import vault_entries, vault_location

        entries = vault_entries()
        if json_out:
            _vault_json(
                {
                    "path": str(vault_location()),
                    "entries": [
                        {
                            "key": e.key,
                            "annotation": e.annotation,
                            "provider": e.provider,
                            "synced_at": e.synced_at.isoformat(),
                        }
                        for e in entries
                    ],
                }
            )
            return

        if not entries:
            click.echo("The vault is empty. Run `func builtin vault sync` to fill it.")
            return

        key_width = max(len(e.key) for e in entries)
        provider_width = max(len(e.provider) for e in entries)
        for entry in entries:
            click.echo(
                f"{entry.key:<{key_width}}  "
                f"{entry.provider:<{provider_width}}  "
                f"{entry.synced_at.isoformat(timespec='seconds')}  {entry.annotation}"
            )

    @vault_app.command("status")
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit the status report as JSON.",
    )
    @click.pass_context
    def vault_status_command(ctx: click.Context, json_out: bool) -> None:
        """Show the key provider in use, the vault's age, and what it holds.

        Answers even when the app cannot boot — that is when it is worth
        asking. The key is resolved non-interactively, so this never raises a
        keychain prompt.
        """
        from functualize.app.utils import vault_status

        obj = ctx.find_root().obj
        app = obj.get("app") if isinstance(obj, dict) else None
        report = vault_status(app)

        if json_out:
            _vault_json(
                {
                    "path": str(report.path),
                    "exists": report.exists,
                    "entries": report.entry_count,
                    "key_provider": report.key_provider,
                    "oldest_sync": (
                        report.oldest_sync.isoformat() if report.oldest_sync else None
                    ),
                    "age_seconds": (
                        int(report.age.total_seconds()) if report.age else None
                    ),
                    "max_age_seconds": int(report.max_age.total_seconds()),
                    "stale": report.stale,
                    "providers": list(report.providers),
                }
            )
            return

        from functualize.app.utils import vault_duration

        click.echo(f"Path:         {report.path}")
        click.echo(f"Exists:       {'yes' if report.exists else 'no'}")
        click.echo(f"Entries:      {report.entry_count}")
        click.echo(f"Key provider: {report.key_provider or '(none available)'}")
        if report.age is not None:
            marker = "  ← stale" if report.stale else ""
            click.echo(f"Last synced:  {vault_duration(report.age)} ago{marker}")
        else:
            click.echo("Last synced:  never")
        click.echo(f"Max age:      {vault_duration(report.max_age)}")
        click.echo(
            "Providers:    " + (", ".join(report.providers) or "(none registered)")
        )
        if report.stale:
            click.echo("")
            click.echo("Run `func builtin vault sync` to refresh it.")

    @vault_app.command("clear")
    @click.option(
        "--yes",
        "assume_yes",
        is_flag=True,
        default=False,
        help="Do not ask for confirmation.",
    )
    def vault_clear_command(assume_yes: bool) -> None:
        """Delete this project's vault.

        Confirms first. The values live authoritatively in the remote store and
        a sync refills the vault, but a secret whose remote entry has since
        been deleted is gone -- and this command cannot tell the two apart.
        """
        from functualize.app.utils import vault_clear, vault_location

        path = vault_location()
        if not path.exists():
            click.echo(f"No vault to clear at {path}")
            return
        if not assume_yes and not click.confirm(f"Delete {path}?", default=False):
            click.echo("Left alone.")
            return
        vault_clear()
        click.echo(f"Cleared {path}")

    @vault_app.command("sync")
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit the sync report as JSON.",
    )
    @click.pass_context
    def vault_sync_command(ctx: click.Context, json_out: bool) -> None:
        """Fetch every declared annotation from its provider and store it.

        The only command that contacts a remote configuration provider. A job
        run reads the vault and never the network (ADR-016), so the network
        cost and the credentials live here and nowhere else.

        Individual failures are reported and the rest still sync: one
        unreachable provider must not abandon the twelve secrets that would
        have worked. The exit code is non-zero when anything was declared and
        did not land, so a pipeline still notices.
        """
        from functualize.app.utils import VaultKeyUnavailableError, vault_sync

        app = _vault_app(ctx)
        try:
            report = vault_sync(app)
        except VaultKeyUnavailableError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(ExitCode.REFUSED) from exc

        if json_out:
            _vault_json(
                {
                    "path": str(report.path),
                    "scanned": report.scanned,
                    "synced": [{"key": k, "provider": p} for k, p in report.synced],
                    "failed": [{"key": k, "reason": r} for k, r in report.failed],
                    "unresolved": [
                        {
                            "key": u.key,
                            "value": u.value,
                            "providers": list(u.providers),
                        }
                        for u in report.unresolved
                    ],
                    "ok": report.ok,
                }
            )
        else:
            for key, provider in report.synced:
                click.echo(f"  synced   {key}  ({provider})")
            for key, reason in report.failed:
                click.echo(f"  FAILED   {key}  — {reason}", err=True)
            for item in report.unresolved:
                click.echo(
                    f"  MISSING  {item.key}  — no plugin registers "
                    f"{', '.join(item.providers)}",
                    err=True,
                )
            if not report.synced and not report.failed and not report.unresolved:
                click.echo(
                    f"Nothing declared remotely in {report.scanned} config "
                    f"values. Nothing to sync."
                )
            else:
                click.echo("")
                click.echo(
                    f"{len(report.synced)} synced, {len(report.failed)} failed, "
                    f"{len(report.unresolved)} unresolvable → {report.path}"
                )

        if not report.ok:
            raise SystemExit(ExitCode.REFUSED)

    _mount(builtin_app, vault_app, "vault")

    # --- Info sub-group (resolves app lazily from ctx.obj) ---
    # A group rather than a command, with `invoke_without_command=True`, so
    # bare `func builtin info` keeps printing the overview every doc and skill
    # points at while the subcommands add the structured views.
    def _info_app_and_config(ctx: click.Context) -> tuple[Any, Any]:
        obj = ctx.find_root().obj
        if obj is None or "app" not in obj:
            click.echo("Error: No app context available.", err=True)
            raise SystemExit(ExitCode.USAGE)
        return obj["app"], obj.get("cli_config")

    def _emit_json(payload: Any) -> None:
        import json

        click.echo(json.dumps(payload, indent=2, default=str))

    @click.group(
        name="info",
        invoke_without_command=True,
        help="Display app state, discovered jobs, and config.",
    )
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
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help=(
            "Emit the full report as JSON (same as `info all --json`). "
            "Set FUNCTUALIZE_CLI_OUTPUT=json to make it the default, or "
            "=plain for text without box-drawing."
        ),
    )
    @click.pass_context
    def info_group(
        ctx: click.Context, job: str | None, show_env_vars: bool, json_out: bool
    ) -> None:
        """Show current CLI configuration, discovered jobs, and resolved config."""
        if ctx.invoked_subcommand is not None:
            return

        from functualize._cli.info import (
            full_report,
            render_report_text,
            resolve_renderer,
        )

        app, cli_config = _info_app_and_config(ctx)
        renderer = resolve_renderer(json_out, cli_config)

        if renderer == "json":
            _emit_json(full_report(app, cli_config))
            return

        if renderer == "plain":
            for line in render_report_text(full_report(app, cli_config)):
                click.echo(line)
            return

        from functualize.app.adapters.cli import _show_info_impl

        _show_info_impl(app, job=job, show_env_vars=show_env_vars)

        # Display resolution info (import_libs, anchor, convention dirs)
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

        # Where freshness is remembered, and which of the two modes that is.
        # `resolve_state_path` has always walked upward for a `.functualize/`
        # and fallen back to the home cache, and nothing said which had
        # happened — so a project could spend its whole life in standalone
        # mode and then go looking for a `state.json` under a hashed directory
        # it had never seen.
        state_path, state_mode, state_marker = _state_location()
        click.echo("")
        click.echo("─── Runtime State ───")
        click.echo(f"  State path: {state_path}")
        # The scope file is reported here for the same reason the mode is: a
        # file whose location nothing prints is a file nobody finds.
        click.echo(f"  Scopes path: {state_path.with_name('scopes.json')}")
        click.echo(f"  Mode:       {_state_mode_line(state_mode, state_marker)}")

        # Agent skills. `info` is where the skills themselves tell an agent to
        # look first, so it is where the answer to "do skills exist, and
        # where?" belongs — the --help epilog only has room for the pointer.
        from functualize._cli.skills import list_skills, resolve_skills_locations

        locations = resolve_skills_locations()
        click.echo("")
        click.echo("─── Agent Skills ───")
        if not locations:
            click.echo("  (none found for this installation)")
        else:
            for location in locations:
                names = (
                    ", ".join(s.name for s in list_skills(location.path)) or "(none)"
                )
                stamp = (
                    f"{location.distribution} {location.version}"
                    if location.version
                    else location.distribution
                )
                click.echo(f"  {stamp} ({location.origin})")
                click.echo(f"    Path: {location.path}")
                click.echo(f"    Skills: {names}")
            click.echo("  Install: func builtin skills install")

        click.echo("")
        click.echo("Machine-readable: func builtin info schema | info jobs --json")

    @info_group.command("jobs")
    @click.argument("name", required=False)
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit JSON. Default it with FUNCTUALIZE_CLI_OUTPUT=json.",
    )
    @click.pass_context
    def info_jobs(ctx: click.Context, name: str | None, json_out: bool) -> None:
        """List discovered jobs, or show one in detail.

        With no NAME this is the catalog — every job with its one-line summary.
        With a NAME it is that job in full, including its input schema.
        """
        from functualize._cli.info import (
            job_catalog,
            job_detail,
            render_catalog_text,
            resolve_renderer,
        )

        app, cli_config = _info_app_and_config(ctx)
        renderer = resolve_renderer(json_out, cli_config)

        if name is not None:
            detail = job_detail(app, name)
            if detail is None:
                click.echo(f"Error: no job named '{name}'.", err=True)
                raise SystemExit(ExitCode.USAGE)
            if renderer == "json":
                _emit_json(detail)
                return
            click.echo(f"{detail['name']}  {detail['summary']}".rstrip())
            if detail["group"]:
                click.echo(f"  group: {detail['group']}")
            if detail["source_file"]:
                click.echo(f"  source: {detail['source_file']}")
            if detail["requires_tty"]:
                click.echo("  requires a terminal")
            if detail["dependencies"]:
                click.echo(f"  depends on: {', '.join(detail['dependencies'])}")
            click.echo("  parameters:")
            if not detail["parameters"]:
                click.echo("    (none)")
            for param in detail["parameters"]:
                flag = (
                    "required"
                    if param["required"]
                    else f"default={param.get('default')!r}"
                )
                click.echo(f"    {param['name']}: {param.get('type')} ({flag})")
            return

        catalog = job_catalog(app)
        if renderer == "json":
            _emit_json(catalog)
            return
        for line in render_catalog_text(catalog):
            click.echo(line)

    @info_group.command("schema")
    @click.argument("name", required=False)
    @click.option(
        "--kind",
        type=click.Choice(["job", "builtin", "plugin"]),
        default=None,
        help=(
            "Restrict to jobs, builtin commands, or plugin-registered "
            "commands. Default: all three."
        ),
    )
    @click.pass_context
    def info_schema(ctx: click.Context, name: str | None, kind: str | None) -> None:
        """Print every command's input contract as JSON Schema.

        Covers jobs *and* builtins: both are nodes in one command tree, and an
        agent should not have to walk `--help` for the builtin subtree either.
        Address one command by its dotted path — `demo.report`,
        `builtin.skills.materialize`.

        Always JSON — it is a contract, not a display. Built by the same core
        renderer the MCP plugin calls, so a tool definition and this command
        cannot describe a command differently.
        """
        from functualize._cli.info import command_schemas

        app, _ = _info_app_and_config(ctx)
        schemas = command_schemas(app, name, kind=kind)
        if name is not None and not schemas:
            click.echo(f"Error: no command named '{name}'.", err=True)
            raise SystemExit(ExitCode.USAGE)
        _emit_json(schemas[0] if name is not None else schemas)

    @info_group.command("all")
    @click.option(
        "--json",
        "json_out",
        is_flag=True,
        default=False,
        help="Emit JSON. Default it with FUNCTUALIZE_CLI_OUTPUT=json.",
    )
    @click.pass_context
    def info_all(ctx: click.Context, json_out: bool) -> None:
        """Everything info knows, as one document.

        Environment, config resolution, agent skills, and every job with its
        input schema — one fetch instead of four commands and three prose
        formats.
        """
        from functualize._cli.info import (
            full_report,
            render_report_text,
            resolve_renderer,
        )

        app, cli_config = _info_app_and_config(ctx)
        report = full_report(app, cli_config)

        # `all` is a document, not a display: there is no panelled version of
        # it, so `rich` and `plain` render the same text and only `json`
        # differs.
        if resolve_renderer(json_out, cli_config) == "json":
            _emit_json(report)
            return
        for line in render_report_text(report):
            click.echo(line)

    # Mounted from a sibling module rather than defined inline, following
    # `scaffold` and `skills`. `self doctor` is *also* intercepted pre-boot in
    # `_run_cli`; this mount is what makes it visible to `--help`, to the
    # registry mirror, to completion, and to a consumer app's CLI.
    from functualize._cli.plugin_cmd import plugin_app
    from functualize._cli.self_cmd import self_app

    _mount(builtin_app, plugin_app, "plugin")
    _mount(builtin_app, self_app, "self")

    _mount(builtin_app, info_group, "info")

    _mount(cli_group, builtin_app, "builtin")
