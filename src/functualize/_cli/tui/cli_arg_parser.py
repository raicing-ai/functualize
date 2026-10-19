"""CLI-style argument token parsing for the inline TUI.

Parses SmartBar/command-line tokens (--key value, -short value, and bare
positional tokens) into a kwargs dict, using a job's field metadata to
resolve positional assignment and short-flag names.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_cli_args_to_kwargs(
    args: list[str],
    fields: list[Any] | None = None,
) -> dict[str, str]:
    """Parse CLI-style args (--key value, -short value, and positional) into a kwargs dict.

    Args:
        args: Token list (excluding the job name).
        fields: Optional list of FieldDescriptor-like objects with .name, .positional,
            and .short_flag attributes. When provided, enables:
            - Positional arg assignment (bare tokens → positional fields in order)
            - Short flag resolution (-g value → field name)
    """
    kwargs: dict[str, str] = {}

    # Build lookup tables from fields
    positional_names: list[str] = []
    short_to_name: dict[str, str] = {}
    if fields:
        for f in fields:
            if getattr(f, "positional", False):
                positional_names.append(f.name)
            short = getattr(f, "short_flag", None)
            if short:
                # Normalize: "-g" → "g"
                short_to_name[short.lstrip("-")] = f.name

    positional_idx = 0
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if "=" in key:
                k, v = key.split("=", 1)
                kwargs[k] = v
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                kwargs[key] = args[i + 1]
                i += 1
            else:
                kwargs[key] = "true"
        elif arg.startswith("-") and len(arg) >= 2 and not arg[1:].isdigit():
            # Short flag: -g value
            flag_char = arg.lstrip("-")
            field_name = short_to_name.get(flag_char)
            if field_name and i + 1 < len(args) and not args[i + 1].startswith("-"):
                kwargs[field_name] = args[i + 1]
                i += 1
            elif field_name:
                kwargs[field_name] = "true"
        elif positional_idx < len(positional_names):
            # Bare token → assign to next positional field
            kwargs[positional_names[positional_idx]] = arg
            positional_idx += 1
        i += 1
    return kwargs


def tokenize_bar_text(text: str) -> list[str]:
    """Split SmartBar text into tokens the way the emitters wrote it.

    The one owner of "how bar text becomes tokens". ``str.split()`` is not it:
    every emitter in ``sync.py`` quotes a value containing whitespace, and a
    plain split hands the opening quote back as part of the value and the rest
    as a stray path token. ``deploy --env "us east" web run`` then resolves to
    *no job at all* — the fixed point ``emit(resolve(text)) == text`` fails on
    the one input class the emitters go out of their way to produce.

    Delegates to the completion tokenizer, which is shlex-based and already
    tolerates the unclosed quote a user is mid-way through typing.
    """
    if not text.strip():
        return []
    from functualize._cli.completions.quote_handling import tokenize_smart_bar

    return tokenize_smart_bar(text)


def build_group_option_trie(func_app: Any) -> Any:
    """Build a ``GroupTrie`` over a booted app's jobs + cached group options.

    The same inputs the CLI's ``_dispatch_group`` feeds the trie (the job list
    plus the cached ``{group: GroupOptionsSpec}`` map), so
    ``group_options_on_path`` resolves inheritance identically wherever it is
    called (scrutiny D2 — one resolver). Jobs always form the navigation trie;
    absent group options leave its option map empty.

    The heavy imports are function-local so this module stays import-light on
    the pre-boot path that pulls in ``parse_cli_args_to_kwargs``.
    """
    try:
        from pathlib import Path

        from functualize.app.utils import (
            build_group_trie,
            discovery_hash_for,
            read_group_options_from_cache,
            resolve_cache_path,
        )

        # get_jobs() first: on a cold cache it is the scan that *writes* the
        # group-options section, so reading the cache before it would miss a
        # project's options on the very first call.
        jobs = func_app.get_jobs()
        try:
            specs = read_group_options_from_cache(
                resolve_cache_path(Path.cwd()),
                discovery_hash=discovery_hash_for(func_app),
            )
        except Exception as exc:
            logger.debug("build_group_option_trie: no group options (%s)", exc)
            specs = {}
        return build_group_trie(
            [(j.group, j.name, "job") for j in jobs],
            [],
            group_options=specs,
        )
    except Exception as exc:
        # Discovery or trie construction failed; the caller retains its
        # identity-based completion fallback.
        logger.debug("build_group_option_trie: no trie (%s)", exc)
        return None


def group_option_specs_on_path(trie: Any, job_name: str) -> list[Any]:
    """The group-option specs a job inherits, outermost first (or ``[]``).

    Find the identity in the trie, then use its actual path. A literal dot in
    one leaf is not a group boundary.
    """
    if trie is None:
        return []
    pending = list(trie.root.children.values())
    while pending:
        node = pending.pop()
        if node.payload == job_name:
            return list(trie.group_options_on_path(node.path[:-1]))
        pending.extend(node.children.values())
    return []


class TuiCommandResolution:
    """What a line of SmartBar tokens resolves to (S6b).

    Attributes:
        job_name: The resolved leaf job's canonical dotted name, or ``None``
            when the tokens do not reach a runnable job.
        args: Tokens after the command — the job's own arguments.
        group_values: Group options consumed **mid-path**, exactly as the CLI
            consumes them (``deploy --env prod web run``).
        dotted_token: A path token the user spelled with a dot
            (``deploy.web.run``). The TUI navigates by spaces, so this is a
            refusal, reported rather than silently accepted.
        dotted_path: The trie's full path for ``dotted_token`` — the spelling
            the refusal offers instead. Set exactly when ``dotted_token`` is.
        bad_flag: A ``-``-prefixed token no consumed ancestor declares.
    """

    __slots__ = (
        "args",
        "bad_flag",
        "bad_flag_hint",
        "dotted_path",
        "dotted_token",
        "group_values",
        "job_name",
    )

    def __init__(
        self,
        job_name: str | None,
        args: list[str],
        group_values: dict[str, Any],
        dotted_token: str | None = None,
        bad_flag: str | None = None,
        bad_flag_hint: str | None = None,
        dotted_path: tuple[str, ...] | None = None,
    ) -> None:
        self.job_name = job_name
        self.args = args
        self.group_values = group_values
        self.dotted_token = dotted_token
        self.dotted_path = dotted_path
        self.bad_flag = bad_flag
        self.bad_flag_hint = bad_flag_hint


def resolve_tui_command(trie: Any, tokens: list[str]) -> TuiCommandResolution:
    """Walk space-separated tokens to a job, consuming mid-path group flags.

    The TUI navigates groups the way the CLI does — ``deploy web run``, one
    segment per token — so this delegates to the CLI's own ``walk_group_path``
    rather than giving the shell a second navigation model. Mid-path group
    flags fall out of that reuse: ``deploy --env prod web run`` binds ``--env``
    to the ``deploy`` declaration here exactly as it does on the command line.

    A dotted token crossing group edges is reported in ``dotted_token`` for
    the caller to explain. A literal dot inside one leaf stays valid.

    ``trie`` may be ``None`` if discovery failed; the first token is then
    treated as a job identity by the existing fallback.
    """
    if not tokens:
        return TuiCommandResolution(None, [], {})

    from functualize._cli.dispatch import walk_group_path

    if trie is None:
        return TuiCommandResolution(tokens[0], list(tokens[1:]), {})

    walk = walk_group_path(trie, tokens)

    if walk.bad_path is not None:
        return TuiCommandResolution(
            None,
            [],
            {},
            dotted_token=walk.remaining[0],
            dotted_path=walk.bad_path,
        )

    node = walk.node
    job_name = node.payload if getattr(node, "has_payload", False) else None
    return TuiCommandResolution(
        job_name=job_name,
        args=list(walk.remaining),
        group_values=dict(walk.options),
        bad_flag=walk.bad_flag,
        bad_flag_hint=walk.bad_flag_hint,
    )
