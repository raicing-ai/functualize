"""Early-dispatch mode detection for the func CLI.

Inspects sys.argv before Click processes anything to determine the
invocation mode. This enables single-file mode to bypass FallbackGroup
entirely, eliminating BF-1 (exception mismatch) and BF-2 (option eating).

This module is in the ``_cli/`` layer — it imports ONLY from public API.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._cli.builtins import BUILTIN_NAMES as _BUILTIN_NAMES

if TYPE_CHECKING:
    from collections.abc import Sequence

    # Annotation-only, and deliberately so: this module is on the pre-boot
    # routing fast path, where importing the public facade eagerly would undo
    # true-lazy boot. `_cli` imports public API only (lint-imports), which is
    # what this is when it does resolve.
    from functualize.app.utils import (
        GroupTrie,
        TrieNode,
    )

from functualize.app.utils import (
    GLOBAL_BOOL_FLAGS,
    GLOBAL_OPTIONS_ALWAYS_VALUE,
    GLOBAL_OPTIONS_WITH_VALUE,
    OPTIONAL_VALUE_VALID_SET,
    ExitCode,
    match_group_flag,
)


class Mode(enum.Enum):
    """CLI invocation mode detected from argv."""

    SINGLE_FILE = "single_file"
    """argv[1] is a .py file that exists on disk."""

    BUILTIN = "builtin"
    """argv[1] is a known builtin command name."""

    CLI = "cli"
    """Everything else — let Click handle (discovered jobs, global flags, etc.)."""

    JOB = "job"
    """argv[1] matches a discovered job name or alias."""

    GROUP = "group"
    """First positional matches a known group name (group-routed invocation)."""

    BARE = "bare"
    """No positional argument present — bare `func` invocation."""

    UNKNOWN = "unknown"
    """First positional does not match any file, builtin, job, or alias."""


# _BUILTIN_NAMES is imported from the single registry (see top of module).


def _names_a_group(token: str, group_names: set[str]) -> bool:
    """Does `token` address a navigable group? Exact spelling only, for now.

    Deliberately NOT the trie walk, even though the trie can answer this. Going
    through `resolve_name` per segment would accept the Python spelling here
    (`func data_ops` for the `data-ops` group), and that reorders classification
    against the job check below in two ways that are behavior changes, not
    refactors:

    * `data_ops` with a `data-ops` group and no matching job: UNKNOWN today,
      GROUP under the trie. Same job ultimately runs — UNKNOWN boots the app and
      recovers through Gap A in `_handle_job` — but the route differs.
    * `Deploy` where a `deploy` job and a `deploy` group both exist: JOB today,
      GROUP under the trie. Today's precedence is already inconsistent here
      (exact `func deploy` classifies GROUP, `func Deploy` classifies JOB); the
      trie makes it uniform, which is a decision to take in the open.

    TRANSITIONAL(cli-shell-convergence): the widening to a pre-boot trie walk
    (built from `read_routing_rows_from_cache` rows, with the reserved-name check)
    was scoped to A4.2's `builtin` subtree, but A4.2 shipped without it and the
    later phases did not pick it up — so this stays exact-spelling-only and the
    fold is currently deferred and unscheduled. `_dispatch_group` — where the
    greedy walk was load-bearing rather than dead — is already trie-driven (A4.1).
    """
    return token in group_names


def detect_mode(
    argv: list[str],
    job_names: set[str] | None = None,
    group_names: set[str] | None = None,
    aliases: dict[str, str] | None = None,
) -> tuple[Mode, list[str]]:
    """Detect the CLI invocation mode from argv with full job-name awareness.

    Scans argv (skipping argv[0] which is the program name) to find
    the first positional argument (skipping global options and their values).

    Priority order for first positional:
    1. .py file on disk → SINGLE_FILE
    2. builtin command → BUILTIN
    3. known group prefix → GROUP (greedy: consumes max matching segments)
    4. known job name → JOB
    5. known alias → JOB
    6. no positional → BARE
    7. otherwise → UNKNOWN

    Args:
        argv: The full sys.argv list.
        job_names: Known job names from lightweight enumeration.
                   If None, job/unknown detection is skipped (backward compat).
        group_names: Known group name strings (including ancestor prefixes for
                     nested groups). If None or empty, GROUP detection is skipped.
        aliases: Configured aliases mapping short names to job names.
                 If first positional is an alias, treated as Mode.JOB.

    Returns:
        Tuple of (mode, effective_args) where effective_args is the argv
        slice starting from the first positional argument.
        For SINGLE_FILE mode, effective_args = [file.py, ...remaining].
        For BUILTIN and CLI, effective_args is the original argv[1:].
        For GROUP, effective_args = [group_seg1, ..., sub?, ...remaining].
        For JOB, effective_args = [job_or_alias, ...remaining].
        For BARE, effective_args = [].
        For UNKNOWN, effective_args = [unknown_cmd, ...remaining].
    """
    if len(argv) <= 1:
        # Bare invocation: `func` with no args
        if job_names is not None:
            return (Mode.BARE, [])
        return (Mode.CLI, [])

    args = argv[1:]

    # Skip global options to find the first positional argument
    i = 0
    while i < len(args):
        arg = args[i]

        if arg in GLOBAL_BOOL_FLAGS:
            # Boolean flag — skip it, next arg is still available
            i += 1
            continue

        if arg in GLOBAL_OPTIONS_ALWAYS_VALUE:
            # Value-required flag — it consumes the next token as its value
            # unless a pre-boot-owned token stands there (a known global flag
            # or `--version`), which means the value is missing.
            nxt = args[i + 1] if i + 1 < len(args) else None
            i += 2 if value_required_takes_next(arg, nxt) else 1
            continue

        if arg.startswith("--") and "=" in arg:
            # --option=value style — skip it
            i += 1
            continue

        if arg.startswith("-") and not arg.startswith("--"):
            # Short option (not expected in our CLI, but skip defensively)
            i += 1
            continue

        # Found a positional argument
        break
    else:
        # All args were options, no positional
        if job_names is not None:
            return (Mode.BARE, [])
        return (Mode.CLI, args)

    first_positional = args[i]

    # Priority 1: Check if it's a .py file that exists
    if first_positional.endswith(".py"):
        file_path = Path(first_positional)
        if file_path.is_file():
            return (Mode.SINGLE_FILE, args[i:])

    # Priority 2: the single reserved `builtin` node.
    # TRANSITIONAL(cli-shell-convergence §2.B.1): dispatch is narrowed to
    # `_BUILTIN_NAMES == {"builtin"}`, so `func builtin …` routes through the
    # click group here rather than through ordinary trie resolution. The planned
    # end-state folds `builtin` into the trie and discriminates builtin-vs-job at
    # execution time via `NodeKind.BUILTIN`, retiring `Mode.BUILTIN`. That fold
    # was scoped to Phase C/C1 but outlived it — Phase C closed with this branch
    # intact — so it is currently deferred and unscheduled, not in-flight.
    if first_positional in _BUILTIN_NAMES:
        return (Mode.BUILTIN, args)

    # Priority 3: first positional names a group → GROUP.
    # Segment consumption is `_dispatch_group`'s job against the post-boot
    # trie; detect_mode only classifies the route.
    if group_names and _names_a_group(first_positional, group_names):
        return (Mode.GROUP, args[i:])

    # Priority 4+: Job/Unknown detection (only when job_names provided)
    if job_names is not None:
        # Check if it's a known job name (direct match takes precedence over alias)
        if first_positional in job_names:
            return (Mode.JOB, args[i:])

        # Job names are stored normalized (`build-wheel`), so accept the Python
        # spelling too — `func build_wheel` reaches the same job. This is
        # normalization, not aliasing: one name exists, and typing it the way
        # Python spells it still finds it.
        from functualize.app.utils import normalize_segment

        if normalize_segment(first_positional) in job_names:
            return (Mode.JOB, args[i:])

        # Priority 5: Check if it's an alias
        if aliases is not None and first_positional in aliases:
            return (Mode.JOB, args[i:])

        # Priority 7: Not matched — unknown command
        return (Mode.UNKNOWN, args[i:])

    # Backward compat: when job_names is None, let Click handle
    return (Mode.CLI, args)


# ---------------------------------------------------------------------------
# Global option extraction
# ---------------------------------------------------------------------------

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class ParsedGlobalOptions:
    """Result of extracting global options from argv before mode detection."""

    log_level: str | None = None
    import_libs: list[str] | None = field(default=None)
    dotenv_file: str | None = None
    no_dotenv: bool = False
    config_directory: str | None = None
    discovery_depth: int | None = None
    require_file_import: str | None = None
    require_file_prefix: str | None = None
    require_file_postfix: str | None = None
    require_file_marker: str | None = None
    require_job_prefix: str | None = None
    require_job_postfix: str | None = None
    require_job_decorators: list[str] | None = field(default=None)
    exclude: list[str] | None = field(default=None)
    perf_report: str | None = None
    perf_filter: str | None = None
    output: str | None = None  # --emit-format flag: json, text, or none
    prompt_gates: bool = False  # --prompt-gates: prompt for gate fields during walk
    force: bool = False  # --force: run even when up to date
    first_positional_index: int = -1  # index into argv[1:] of first positional


def _extract_global_options(
    argv: list[str],
) -> tuple[ParsedGlobalOptions, dict[str, Any]]:
    """Parse global options from argv without consuming positional args.

    Scans argv[1:] for recognized global flags and their values. Positional
    arguments and unrecognized flags are left untouched. The original argv
    list is NOT mutated.

    Returns:
        (parsed_options, cli_flags_dict) where cli_flags_dict contains only
        non-None overrides suitable for passing to resolve_cli_config().

    Raises:
        SystemExit: If --log-level has an invalid value.
    """
    first_positional_index: int = -1

    if len(argv) <= 1:
        opts = ParsedGlobalOptions(first_positional_index=-1)
        return opts, {}

    args = argv[1:]
    state = _OptionAccumulator()
    i = 0

    while i < len(args):
        arg = args[i]

        # Boolean flag: --no-dotenv
        if arg == "--no-dotenv":
            state.no_dotenv = True
            i += 1
            continue

        # Boolean flag: --force. Valueless, so deliberately NOT in
        # `GLOBAL_OPTIONS_ALWAYS_VALUE` — that set is for options that consume
        # the next token, and putting `--force` there would swallow the job
        # name. It **must** also be in `GLOBAL_BOOL_FLAGS`, which is the list
        # `detect_mode` skips when looking for the first positional: a flag
        # parsed here and unknown there is read as the command name, and
        # `func --force build` answers `Unknown command 'force'`.
        if arg == "--force":
            state.force = True
            i += 1
            continue

        # Boolean flag: --prompt-gates / --no-prompt-gates
        if arg == "--prompt-gates":
            state.prompt_gates = True
            i += 1
            continue
        if arg == "--no-prompt-gates":
            state.prompt_gates = False
            i += 1
            continue

        # Skip --help / -h (global, but produce no cli_flags — Click handles
        # them per-command for job/group help pages).
        if arg in ("--help", "-h"):
            i += 1
            continue

        # Handle --option=value style for recognized options
        if arg.startswith("--") and "=" in arg:
            flag_part, _, value_part = arg.partition("=")
            if flag_part in GLOBAL_OPTIONS_WITH_VALUE:
                _assign_option(flag_part, value_part, state)
                i += 1
                continue
            else:
                # Unrecognized --flag=value — this is a positional/unrecognized
                first_positional_index = i
                break

        # Handle --option VALUE style for recognized options
        if arg in GLOBAL_OPTIONS_ALWAYS_VALUE:
            next_index = i + 1
            next_token = args[next_index] if next_index < len(args) else None
            if not value_required_takes_next(arg, next_token):
                # Missing value: nothing follows, or a pre-boot-owned token
                # does — a flag's value may not eat a token the pre-boot
                # layer owns. A usage error, not a routing question.
                print(missing_value_message(arg), file=sys.stderr)
                raise SystemExit(ExitCode.USAGE)
            _assign_option(arg, args[next_index], state)
            i += 2
            continue

        # Unrecognized flag (starts with - but not in our sets) — stop.
        # This is NOT consumed; left for job-level parsing.
        if arg.startswith("-"):
            first_positional_index = i
            break

        # Found a positional argument — stop scanning.
        first_positional_index = i
        break

    # Validate --log-level
    if state.log_level is not None:
        normalized = state.log_level.upper()
        if normalized not in _VALID_LOG_LEVELS:
            print(
                f"Error: --log-level must be one of "
                f"{', '.join(sorted(_VALID_LOG_LEVELS))}, got '{state.log_level}'.",
                file=sys.stderr,
            )
            raise SystemExit(ExitCode.USAGE)
        state.log_level = normalized

    opts = ParsedGlobalOptions(
        log_level=state.log_level,
        import_libs=state.import_libs,
        dotenv_file=state.dotenv_file,
        no_dotenv=state.no_dotenv,
        config_directory=state.config_directory,
        discovery_depth=state.discovery_depth,
        require_file_import=state.require_file_import,
        require_file_prefix=state.require_file_prefix,
        require_file_postfix=state.require_file_postfix,
        require_file_marker=state.require_file_marker,
        require_job_prefix=state.require_job_prefix,
        require_job_postfix=state.require_job_postfix,
        require_job_decorators=state.require_job_decorators,
        exclude=state.exclude,
        perf_report=state.perf_report,
        perf_filter=state.perf_filter,
        output=state.output,
        prompt_gates=state.prompt_gates,
        force=state.force,
        first_positional_index=first_positional_index,
    )

    # Build cli_flags dict with only non-None values
    cli_flags: dict[str, Any] = {}
    if state.import_libs is not None:
        cli_flags["import_libs"] = state.import_libs
    if state.require_file_import is not None:
        cli_flags["require_file_import"] = state.require_file_import
    if state.require_file_prefix is not None:
        cli_flags["require_file_prefix"] = state.require_file_prefix
    if state.require_file_postfix is not None:
        cli_flags["require_file_postfix"] = state.require_file_postfix
    if state.require_file_marker is not None:
        cli_flags["require_file_marker"] = state.require_file_marker
    if state.require_job_prefix is not None:
        cli_flags["require_job_prefix"] = state.require_job_prefix
    if state.require_job_postfix is not None:
        cli_flags["require_job_postfix"] = state.require_job_postfix
    if state.require_job_decorators is not None:
        cli_flags["require_job_decorators"] = state.require_job_decorators
    if state.exclude is not None:
        cli_flags["exclude_patterns"] = state.exclude
    if state.discovery_depth is not None:
        cli_flags["scan_depth"] = state.discovery_depth
    if state.no_dotenv:
        cli_flags["dotenv"] = False
    if state.dotenv_file is not None:
        cli_flags["dotenv_path"] = state.dotenv_file
    if state.config_directory is not None:
        cli_flags["config_directory"] = state.config_directory

    return opts, cli_flags


class _OptionAccumulator:
    """Mutable accumulator for option parsing state."""

    __slots__ = (
        "log_level",
        "import_libs",
        "dotenv_file",
        "no_dotenv",
        "config_directory",
        "discovery_depth",
        "require_file_import",
        "require_file_prefix",
        "require_file_postfix",
        "require_file_marker",
        "require_job_prefix",
        "require_job_postfix",
        "require_job_decorators",
        "exclude",
        "perf_report",
        "perf_filter",
        "output",
        "prompt_gates",
        "force",
    )

    def __init__(self) -> None:
        self.log_level: str | None = None
        self.import_libs: list[str] | None = None
        self.dotenv_file: str | None = None
        self.no_dotenv: bool = False
        self.config_directory: str | None = None
        self.discovery_depth: int | None = None
        self.require_file_import: str | None = None
        self.require_file_prefix: str | None = None
        self.require_file_postfix: str | None = None
        self.require_file_marker: str | None = None
        self.require_job_prefix: str | None = None
        self.require_job_postfix: str | None = None
        self.require_job_decorators: list[str] | None = None
        self.exclude: list[str] | None = None
        self.perf_report: str | None = None
        self.perf_filter: str | None = None
        self.output: str | None = None
        self.prompt_gates: bool = False
        self.force: bool = False


def _assign_option(
    flag: str,
    value: str,
    state: _OptionAccumulator,
) -> None:
    """Assign a parsed flag value into the accumulator.

    For multi-value options (--import-libs, --exclude, --require-job-decorators),
    values are appended to a list. For scalar options, the value replaces any
    previous setting.
    """
    if flag == "--log-level":
        state.log_level = value
    elif flag == "--import-libs":
        if state.import_libs is None:
            state.import_libs = []
        state.import_libs.append(value)
    elif flag == "--dotenv-file":
        state.dotenv_file = value
    elif flag == "--config-directory":
        state.config_directory = value
    elif flag == "--discovery-depth":
        try:
            state.discovery_depth = int(value)
        except ValueError:
            print(
                f"Error: --discovery-depth must be a valid integer, got '{value}'.",
                file=sys.stderr,
            )
            raise SystemExit(ExitCode.USAGE) from None
    elif flag == "--require-file-import":
        state.require_file_import = value
    elif flag == "--require-file-prefix":
        state.require_file_prefix = value
    elif flag == "--require-file-postfix":
        state.require_file_postfix = value
    elif flag == "--require-file-marker":
        state.require_file_marker = value
    elif flag == "--require-job-prefix":
        state.require_job_prefix = value
    elif flag == "--require-job-postfix":
        state.require_job_postfix = value
    elif flag == "--require-job-decorators":
        if state.require_job_decorators is None:
            state.require_job_decorators = []
        state.require_job_decorators.append(value)
    elif flag == "--exclude":
        if state.exclude is None:
            state.exclude = []
        state.exclude.append(value)
    elif flag == "--perf-report":
        if value not in OPTIONAL_VALUE_VALID_SET["--perf-report"][0]:
            print(invalid_value_message(flag, value), file=sys.stderr)
            raise SystemExit(ExitCode.USAGE)
        state.perf_report = value
    elif flag == "--perf-filter":
        state.perf_filter = value
    elif flag == "--emit-format":
        if value not in OPTIONAL_VALUE_VALID_SET["--emit-format"][0]:
            print(invalid_value_message(flag, value), file=sys.stderr)
            raise SystemExit(ExitCode.USAGE)
        state.output = value


def invalid_value_message(flag: str, value: str) -> str:
    """The one sentence for a value a selection-table global does not accept.

    ``_assign_option`` reaches it for both spellings — ``--flag=value`` and
    ``--flag value`` — so the two ways of typing the same mistake get the
    same answer, naming the flag and its accepted values.
    """
    valid_values = OPTIONAL_VALUE_VALID_SET[flag][0]
    return (
        f"Error: {flag} must be one of "
        f"{{{', '.join(sorted(valid_values))}}}, got '{value}'."
    )


def missing_value_message(flag: str) -> str:
    """The one sentence for a value-required global whose value is absent.

    A flag with a selection table names its accepted values so the repair is
    on the same line; every other value-required flag gets the plain form.
    """
    valid_entry = OPTIONAL_VALUE_VALID_SET.get(flag)
    if valid_entry is None:
        return f"Error: {flag} requires a value."
    valid_values = valid_entry[0]
    return (
        f"Error: {flag} requires a value: one of {{{', '.join(sorted(valid_values))}}}."
    )


def scan_early_setting_flags(argv: list[str]) -> int:
    """Apply `phase="early"` setting flags from ``argv``, pre-boot (C3.2).

    Runs in ``main()`` before the app is constructed, so a setting marked early
    is already in effect for the first store anyone builds. Non-early flags are
    deliberately *not* handled here — they are ordinary click options on the
    root group and resolve at callback time, which is after boot.

    Returns the number of flags applied, so callers (and tests) can tell a
    no-op scan from a real one.

    Both `--flag value` and `--flag=value` are accepted, matching how click
    would have parsed them; anything else is left alone rather than guessed at,
    because this scan runs before the real parser and must not turn a
    would-be error into a silent misread.
    """
    from functualize._cli.data.func_settings import (
        early_flag_specs,
        set_preboot_override,
    )

    specs = dict(early_flag_specs())
    if not specs:
        # The common case — nothing ships `phase="early"`, so the scan costs
        # one catalog read and never walks argv.
        return 0

    applied = 0
    index = 0
    while index < len(argv):
        token = argv[index]
        flag, sep, inline = token.partition("=")
        name = specs.get(flag)
        if name is None:
            index += 1
            continue
        if sep:
            set_preboot_override(name, inline, flag=flag)
            applied += 1
        elif index + 1 < len(argv):
            set_preboot_override(name, argv[index + 1], flag=flag)
            applied += 1
            index += 1
        index += 1
    return applied


@dataclass(frozen=True)
class GroupWalk:
    """The result of a trie walk that consumed group-declared flags mid-path.

    Attributes:
        node: The deepest node reached.
        consumed: The path tokens consumed, as typed (flags excluded).
        remaining: Unconsumed tokens — the leaf command's own arguments.
        options: ``{field_name: raw_value}`` gathered from group flags, with
            the *nearest* declaration winning on a name clash (flat merge,
            §5 Model D). Values are raw strings (or bools for flag fields);
            typing happens when the owning Pydantic model validates them.
        bad_flag: The ``-``-prefixed token that stopped the walk because no
            consumed ancestor declares it. ``None`` when the walk ended for
            any other reason.
    """

    node: TrieNode
    consumed: tuple[str, ...]
    remaining: tuple[str, ...]
    options: dict[str, Any]
    bad_flag: str | None = None
    #: A more specific reason than "unknown option", when one is known — a
    #: boolean given an inline value is a *known* flag used wrongly, and
    #: saying "unknown option" would send the reader looking for a typo.
    bad_flag_hint: str | None = None


def walk_group_path(trie: GroupTrie, args: Sequence[str]) -> GroupWalk:
    """Walk ``args`` through ``trie``, consuming group-declared flags en route.

    A strict superset of :meth:`GroupTrie.resolve`: path tokens walk exactly
    as before, but a ``-``-prefixed token no longer ends the walk outright.
    It is consumed when some **already-consumed ancestor** declares it — the
    inheritance rule (``func deploy --env prod web run`` binds ``--env`` to
    the ``deploy`` declaration and keeps walking to ``deploy.web.run``) — and
    otherwise stops the walk and is reported in ``bad_flag`` so the caller
    can keep model A's error.

    Position is what separates a group flag from the leaf job's own flag: a
    group flag is only recognised *before* the walk reaches its command, so a
    trailing ``--env`` after the leaf is left in ``remaining`` for click. This
    is the docker/kubectl/gh convention.
    """
    node = trie.root
    path: list[str] = []
    consumed: list[str] = []
    options: dict[str, Any] = {}
    index = 0

    while index < len(args):
        token = args[index]

        if token.startswith("-"):
            matched = match_group_flag(token, trie.group_options_on_path(path))
            if matched is None:
                return GroupWalk(
                    node=node,
                    consumed=tuple(consumed),
                    remaining=tuple(args[index:]),
                    options=options,
                    bad_flag=token,
                )
            field, inline, negated = matched
            if field.type_annotation == "bool":
                # A boolean is a presence flag: it never eats the next token,
                # which would otherwise swallow the following path segment.
                #
                # An inline value is refused, on this surface as on the other.
                # `func` used to accept `--strict=false` here while click
                # refused the identical command on an app's own entry point —
                # one spelling working on exactly one of the two surfaces. The
                # `--no-` form is the replacement, and the hint names it.
                if inline is not None:
                    return GroupWalk(
                        node=node,
                        consumed=tuple(consumed),
                        remaining=tuple(args[index:]),
                        options=options,
                        bad_flag=token,
                        bad_flag_hint=(
                            f"'{token.split('=', 1)[0]}' is a flag and takes no "
                            f"value. Use '--no-{field.name.replace('_', '-')}' "
                            f"to turn it off."
                        ),
                    )
                options[field.name] = not negated
                index += 1
            elif inline is not None:
                options[field.name] = inline
                index += 1
            else:
                if index + 1 >= len(args):
                    # Missing value — stop and let the caller report it the
                    # same way an unknown flag is reported.
                    return GroupWalk(
                        node=node,
                        consumed=tuple(consumed),
                        remaining=tuple(args[index:]),
                        options=options,
                        bad_flag=token,
                    )
                options[field.name] = args[index + 1]
                index += 2
            continue

        walked = trie.step(node, token)
        if walked is None:
            break
        node = walked
        path.extend(token.split("."))
        consumed.append(token)
        index += 1

        if node.has_payload and node.is_leaf:
            # The walk has reached the command itself. Everything after it is
            # the job's own argv — including a flag whose name a group also
            # declares. Position is the scope delimiter (D-d), so stopping
            # here is what keeps `… web run --env dev` binding to the *job*
            # rather than overwriting the group's `--env`.
            break

    return GroupWalk(
        node=node,
        consumed=tuple(consumed),
        remaining=tuple(args[index:]),
        options=options,
    )


def is_known_global_flag(token: str) -> bool:
    """Is ``token`` one of func's own global flags (`--log-level`, `--emit-format`, …)?

    Accepts both ``--flag`` and ``--flag=value`` spellings. Used only to give a
    better error when a global is misplaced *after* the group name: global flags
    belong before the first positional (the git/click idiom), so a group walk
    that trips over one should say "move it before the group", not "unknown
    option". See ``_dispatch_group``.
    """
    flag = token.split("=", 1)[0]
    return flag in GLOBAL_OPTIONS_WITH_VALUE or flag in GLOBAL_BOOL_FLAGS


def is_reserved_pre_boot_token(token: str) -> bool:
    """A token the pre-boot layer owns, which no value flag may consume.

    `is_known_global_flag` plus `--version`: the version fast path is a
    pre-boot flag, but is deliberately absent from `GLOBAL_BOOL_FLAGS` (which
    Click also reads), so it is named here instead. A value-required flag
    whose value slot holds one of these tokens is missing its value, not
    holding a value that spells a flag.
    """
    return is_known_global_flag(token) or token.split("=", 1)[0] == "--version"


def value_required_takes_next(flag_token: str, next_token: str | None) -> bool:
    """Does ``--flag`` consume ``next_token`` as its value?

    The single statement of the pre-boot arity rule, shared by
    ``detect_mode``, ``_extract_global_options`` and ``version_requested``:
    a value-required flag takes the next token as its value unless nothing
    follows or a pre-boot-owned token stands there. Every other token —
    a job name, an unrecognized dash token, a negative number — is its value.
    """
    return next_token is not None and not is_reserved_pre_boot_token(next_token)


def version_requested(argv_tail: Sequence[str]) -> bool:
    """Is ``--version`` in the global prefix of ``argv_tail`` (pre-boot)?

    Position-aware: ``--version`` counts only before the first positional
    argument, the same convention as every other global flag. The walk
    advances over the prefix with ``value_required_takes_next`` — the same
    rule ``detect_mode`` and ``_extract_global_options`` apply — so a
    value-position ``--version`` is a missing value for the preceding flag,
    not the version command, and this scan answers False so the usage error
    is what the caller reports.
    """
    i = 0
    while i < len(argv_tail):
        token = argv_tail[i]
        if token == "--version":
            return True
        if token.startswith("-"):
            # A flag — skip it (and its value if it takes one)
            if "=" in token:
                i += 1
            elif token in GLOBAL_OPTIONS_ALWAYS_VALUE:
                nxt = argv_tail[i + 1] if i + 1 < len(argv_tail) else None
                if not value_required_takes_next(token, nxt):
                    # A usage error, not a version request.
                    return False
                i += 2  # skip flag + value
            else:
                i += 1  # unknown flag or bool flag (--no-dotenv, --help, -h)
        else:
            # First positional found — --version was not in the prefix
            return False
    return False
