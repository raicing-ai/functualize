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
from functualize.app.utils import (
    RUN_STATES,
    WORKFLOW_STATES,
    ExitCode,
    Family,
    is_failure,
)

from ._helpers import (
    _CONFIG_TEMPLATE,
    _completions_install_path,
    _determine_source,
    _emit_config_field,
    _env_exec,
    _env_print,
    _mount,
    _project_substrate,
    _render_history,
    _report_parallel,
    _resolve_editor,
    _resolve_env_vars,
    _state_location,
    _state_mode_line,
    _toml_value,
)


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
        "data",
        "Inspect and clear what this project keeps on disk",
        (
            ("show", "Show every store: path, count, size, mode"),
            (
                "clear",
                "Reset derived data; --scopes, --runs and --all widen the target",
            ),
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
            ("watch", "Follow a scope's graph as the walk advances it"),
            ("answer", "Record input for a gate — partial, whole, or corrected"),
            ("resume", "Advance a scope, optionally answering a gate first"),
            ("gate-tool", "Run a tool a waiting gate offers"),
            ("cancel", "Cancel a workflow scope — terminal"),
            ("purge", "Delete finished scopes"),
            ("reclaim", "Take an abandoned scope so it can be resumed"),
        ),
        requires_subcommand=True,
    ),
    BuiltinCommand(
        "run",
        "Read the run log — what executed, and how it ended",
        (
            ("list", "Survey runs, newest first, with filters"),
            ("show", "Show one run — its origin, outcome, tree and events"),
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
        "Store, inspect and sync this project's encrypted secrets",
        (
            ("init", "Ensure this machine has a vault key — never prints it"),
            ("put", "Store one secret at a canonical path"),
            ("inspect", "Explain a path: eligibility, provenance, readability"),
            ("remove", "Remove one entry — needs no vault key"),
            ("sync", "Fetch every declared annotation and store it"),
            ("list", "List what is stored — names and freshness, never values"),
            ("status", "Show the key provider in use, the age, and the count"),
            ("unlock", "Unlock the OS keyring for the vault key — never prints it"),
            ("clear", "Delete this project's vault"),
            ("keygen", "Print a fresh vault key"),
        ),
        requires_subcommand=True,
        # `put` prompts when it has a TTY and no explicit input option, but it
        # does not *take* the terminal in the sense this flag means: it reads
        # one masked line and returns. `keygen` writes to stdout so it can be
        # piped, and the interactive key provider is the keychain, which
        # prompts through the OS rather than through this process.
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


def register_builtin_commands(cli_group: Any) -> None:
    """Mount the reserved builtin subtree on a Click group."""
    import click

    from ._builtin import register_prefix, register_suffix
    from ._cache import register_cache
    from ._config import register_config
    from ._data import register_data
    from ._domains import register_domains
    from ._info import register_info
    from ._run import register_run
    from ._skills import register_skills
    from ._workflow import register_workflow

    builtin_app = click.Group(
        name="builtin", help="First-party commands, kept out of the job namespace."
    )
    register_cache(builtin_app)
    register_data(builtin_app)
    register_workflow(builtin_app)
    register_run(builtin_app)
    register_prefix(builtin_app)
    register_config(builtin_app)
    register_domains(builtin_app)
    register_skills(builtin_app)
    register_suffix(builtin_app)
    register_info(builtin_app)
    _mount(cli_group, builtin_app, "builtin")


__all__ = [
    "contextlib",
    "os",
    "platform",
    "shutil",
    "subprocess",
    "sys",
    "Path",
    "OUTPUT_MODES",
    "RUN_STATES",
    "WORKFLOW_STATES",
    "ExitCode",
    "Family",
    "is_failure",
    "_mount",
    "_CONFIG_TEMPLATE",
    "_completions_install_path",
    "_determine_source",
    "_emit_config_field",
    "_env_exec",
    "_env_print",
    "_project_substrate",
    "_render_history",
    "_report_parallel",
    "_resolve_editor",
    "_resolve_env_vars",
    "_state_location",
    "_state_mode_line",
    "_toml_value",
]
