"""Bar text → a job's arguments, with the CLI's own grammar (D8).

The SmartBar's tokens are parsed by the click command ``func <job>`` renders
(:func:`parse_job_args`), so the bar and the command line cannot disagree about
what a line of text means. The path walk (:func:`resolve_tui_command`) is the
CLI's ``walk_group_path``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)


def parse_job_args(
    args: Sequence[str],
    fields: Sequence[Any],
    *,
    raw: bool = False,
) -> dict[str, Any]:
    """Parse a job's own bar tokens with the click command ``func <job>`` renders.

    The bar has no grammar of its own (D8, B-18): the tokens go through the same
    click parameters the CLI builds from the job's fields, so repeated flags
    accumulate, short flags and ``--no-`` spellings resolve, positionals bind in
    the command's order, and a stray token is an error, as on the command line.

    Args:
        args: The job's own tokens, after the walk consumed its path.
        fields: The job's field descriptors (``get_descriptor_fields``).
        raw: ``False`` parses as ``func <job>`` does: values arrive with the
            CLI's types, and a call the CLI refuses raises the same
            ``click.UsageError``. ``True`` is for a bar that is still being
            typed: the same grammar over the raw tokens, which never refuses.
            Unknown options are ignored, a requirement is not enforced, and a
            trailing token click cannot place yet is set aside. A flag reads
            ``"true"``/``"false"``, a repeatable parameter a list of tokens.

    Returns:
        The parameters the tokens supplied, by name. A default fills nothing.

    Raises:
        click.UsageError: ``raw`` is false and ``func <job>`` would refuse the
            tokens. The message is click's own, so it reads as the CLI's does.
    """
    import click
    from click.core import ParameterSource

    from functualize.app.adapters.click_params import build_click_params_from_fields

    descriptors = [_descriptor(f) for f in fields]
    try:
        params = build_click_params_from_fields(descriptors)
    except (TypeError, ValueError):
        if not raw:
            raise
        # Mid-edit, one field click cannot render (a name no option can carry)
        # must not blank the whole bar: keep every field that does render.
        params = [p for d in descriptors for p in _renderable([d])]
    if raw:
        params = [_raw_param(param) for param in params]
    command = click.Command(
        "job",
        params=params,
        add_help_option=False,
        context_settings={"ignore_unknown_options": raw},
    )
    tokens = list(args)
    while True:
        try:
            ctx = command.make_context("job", list(tokens), resilient_parsing=raw)
            break
        except click.UsageError:
            if not raw:
                raise
            if not tokens:
                return {}
            tokens.pop()  # mid-typing: `--p` before its value, say
    provided: dict[str, Any] = {}
    for param in params:
        name = param.name or ""
        if ctx.get_parameter_source(name) is not ParameterSource.COMMANDLINE:
            continue
        value = ctx.params.get(name)
        if isinstance(value, tuple):
            value = list(value)
        if raw and isinstance(value, bool):
            value = "true" if value else "false"
        provided[name] = value
    return provided


def _descriptor(field: Any) -> Any:
    """A ``FieldDescriptor`` for a field-like row (the panel's ``FieldDef``, say).

    The click builder reads the descriptor's whole record. A row that carries
    only the fields it shows is copied into one, contract included, so every
    caller parses through the same rendering.
    """
    from functualize.types import FieldDescriptor

    if isinstance(field, FieldDescriptor):
        return field
    return FieldDescriptor(
        name=field.name,
        type_annotation=getattr(field, "type_annotation", "str") or "str",
        default=getattr(field, "default", None),
        description=getattr(field, "description", "") or "",
        required=bool(getattr(field, "required", False)),
        choices=getattr(field, "choices", None),
        positional=bool(getattr(field, "positional", False)),
        short_flag=getattr(field, "short_flag", None),
        contract=getattr(field, "contract", None),
    )


def _renderable(fields: list[Any]) -> list[Any]:
    """The click params for ``fields``, or none if click refuses to build them."""
    from functualize.app.adapters.click_params import build_click_params_from_fields

    try:
        return build_click_params_from_fields(fields)
    except (TypeError, ValueError):
        return []


def _raw_param(param: Any) -> Any:
    """The same parameter, keeping its token unconverted (flags stay flags)."""
    import copy

    import click

    if getattr(param, "is_flag", False):
        return param
    clone = copy.copy(param)
    clone.type = click.types.UNPROCESSED
    clone.callback = None
    return clone


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
    the pre-boot path that imports this module.
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
