"""SmartBar ↔ Config Table synchronization.

Pure-Python module (no Textual dependency) that keeps the SmartBar's CLI
text and a job's configured field values in sync in both directions.

Integration wiring:
    The ConfigTablePanel's `apply_value_edit`, `apply_source_edit`, and
    `action_reset_override` post messages (ValueEdited, SourceChanged,
    OverrideReset). The controller/app that owns both the SmartBar and the
    ConfigTablePanel should listen for these messages and call
    `sync_overrides_to_bar(command_path, fields)` to rebuild bar text, then
    update the SmartBar's saved state via `bar.save_state()` so that
    restore_state uses the most recent synced text.

    This is also the single source of truth for reconstructing bar text
    from field-level overrides — do not reimplement this in the app layer;
    `sync_pending_overrides_to_bar` covers the equivalent case where
    overrides live on a `PendingExecution` instead of `ConfigTablePanel`
    `FieldDef`s.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from functualize._cli.tui.cli_arg_parser import (
    group_option_specs_on_path,
    parse_cli_args_to_kwargs,
    resolve_tui_command,
    tokenize_bar_text,
)
from functualize._cli.tui.panels.config_table import EditOrigin, FieldDef

if TYPE_CHECKING:
    from functualize._cli.data.pending_execution import PendingExecution
    from functualize._cli.tui.cli_arg_parser import TuiCommandResolution

__all__ = [
    "build_command_line",
    "sync_bar_to_overrides",
    "sync_overrides_to_bar",
    "sync_pending_overrides_to_bar",
]


def _emit_positional_then_named(
    command_path: list[str],
    entries: list[tuple[str, str, bool, str | None]],
) -> str:
    """Join a command path with positional bare tokens then named flag tokens.

    Args:
        command_path: The command's path tokens, as the bar spells them —
            ``["deploy", "web", "run"]`` for a grouped job, ``["greet"]`` for
            an ungrouped one. A path, not a name: the bar's first token is the
            outermost *group* for anything under a group, and joining on the
            single first token is what truncated the path.
        entries: (name, value, positional, short_flag) tuples, in the order
            they should be emitted.
    """
    positional_parts: list[str] = []
    named_parts: list[str] = []
    for name, value, positional, short_flag in entries:
        if positional:
            positional_parts.append(_quoted(value))
            continue
        if short_flag:
            flag = short_flag if short_flag.startswith("-") else f"-{short_flag}"
        else:
            flag = f"--{name}"
        named_parts.append(flag)
        # One quoting rule for the job's values and the group's alike — see
        # `_quoted`. A second, looser copy here is what let `say "hi"` through.
        named_parts.append(_quoted(value))
    return " ".join([*command_path, *positional_parts, *named_parts])


def _quoted(value: str) -> str:
    """Quote a value the tokenizer would otherwise split or mangle.

    The inverse of ``tokenize_bar_text``, which is shlex-based — so the rule
    has to be shlex's, not "wrap it in double quotes if it has a space".
    ``say "hi"`` wrapped that way emits ``"say "hi""``, which shlex reads back
    as ``say hi`` and, mid-path, leaves a stray token where a path segment
    belongs.

    Double quotes are kept for the common case because that is the spelling
    every existing test and screenshot shows; ``shlex.quote`` takes over the
    moment the value contains a quote character of its own.
    """
    if not value:
        return value
    if '"' in value or "'" in value:
        return shlex.quote(value)
    return f'"{value}"' if any(c.isspace() for c in value) else value


def _group_flag_tokens(field: Any, value: Any) -> list[str]:
    """The tokens that spell one group option on the command line.

    The long form is used even where the declaration also offers a short flag:
    this text is read as much as it is re-parsed, and the two spellings are
    equivalent to the walk. Underscores hyphenate, matching what the click
    param builder renders and what ``_flag_aliases`` accepts.

    A boolean is a **presence flag**. Writing `--dry-run true` would put a bare
    `true` where the next path segment belongs, and the walk would try to step
    into a group by that name.
    """
    flag = f"--{field.name.replace('_', '-')}"
    if getattr(field, "type_annotation", "") == "bool":
        return [flag] if value not in (False, None, "", "false", "False") else []
    if value in (None, ""):
        return []
    return [flag, _quoted(str(value))]


def build_command_line(
    job_name: str,
    job_overrides: list[tuple[str, str, bool, str | None]],
    group_values: dict[str, Any],
    trie: Any | None = None,
    *,
    omit_defaults: bool = False,
) -> str:
    """Build the canonical CLI text for a job and the group flags around it.

    The single place that turns "which job, which values" back into a line the
    user could have typed::

        deploy --env prod web --region eu-west-1 run v1.2

    Group flags are **mid-path**: each sits beside the segment of the group
    that declared it, because that is the only position the CLI reads it in.
    A flag written after the job is the job's own — the docker/kubectl
    convention the walk already implements — so emitting a group's flag there
    would produce a line that parses as something else.

    Args:
        job_name: The job's canonical dotted name, e.g. ``deploy.web.run``.
        job_overrides: ``(name, value, positional, short_flag)`` for the job's
            own fields, in emission order.
        group_values: Group option values, flat and keyed by field name — the
            shape both the walk and the engine's own merge use.
        trie: The group trie. ``None`` degrades to the flat dotted spelling,
            which is what the trie-less resolver reads back.
        omit_defaults: Drop a group value equal to its declared default
            (SBR.3). **Off by default, deliberately.** ``group_values`` usually
            holds what the user actually typed, and dropping `--env staging`
            because staging is the default would delete their keystrokes. Turn
            it on only when passing fully *resolved* values, where every field
            is present and most of them are defaults nobody chose.

            Note that it cannot fire for a secret field: a credential's default
            is not written to the cache, so the comparison has nothing to
            compare against and the flag is always emitted.

    Returns:
        Bar text whose walk yields back ``job_name``, ``group_values`` and the
        job's own arguments — the fixed point the SmartBar depends on.
    """
    if trie is None:
        return _emit_positional_then_named([job_name], job_overrides)

    segments = job_name.split(".")
    specs = {spec.group: spec for spec in group_option_specs_on_path(trie, job_name)}

    path_tokens: list[str] = []
    emitted: set[str] = set()
    for depth in range(1, len(segments)):
        path_tokens.append(segments[depth - 1])
        spec = specs.get(".".join(segments[:depth]))
        if spec is None:
            continue
        for field_desc in spec.fields:
            name = field_desc.name
            if name in emitted or name not in group_values:
                continue
            # Outermost declaring level wins. Two levels may declare the same
            # name, and the values dict is flat by design — one value, so one
            # place to write it. Choosing the outermost makes that place
            # deterministic; choosing per-token would make the text depend on
            # where the user happened to type it last.
            emitted.add(name)
            value = group_values[name]
            if omit_defaults and value == getattr(field_desc, "default", None):
                continue
            path_tokens.extend(_group_flag_tokens(field_desc, value))
    path_tokens.append(segments[-1])

    return _emit_positional_then_named(path_tokens, job_overrides)


def sync_overrides_to_bar(
    job_name: str,
    fields: list[FieldDef],
    group_values: dict[str, Any] | None = None,
    trie: Any | None = None,
) -> str:
    """Rebuild SmartBar text from session overrides.

    Produces a string in the format:
        "{command} <positional_vals> --{field1} {value1} --{field2} {value2}"

    Only includes fields with edit_origin != NONE, ordered by their position
    in the field list — positional fields emit as bare tokens first, then
    named fields as `--{name} {value}` (or `-{short_flag} {value}` when a
    short flag is set). Named values containing whitespace are enclosed in
    double quotes. When no overrides exist, returns just the command.

    **The field list is partitioned on ``group_path`` first.** A row carrying
    one is not the job's argument — it belongs to an ancestor and is spelled
    beside that ancestor's segment — so it goes to ``group_values``, never to
    ``job_overrides``. Routing it the other way emits `deploy web run -e prod`,
    which parses as a *job* flag named `env`: the walk hands the value back as
    `{}`, the job runs on the group's unedited value, and the edit is lost with
    no error anywhere. Calling one emitter is not enough on its own — the
    emitter can only place a flag correctly if it is told which kind it is.

    Once the panel holds any group row it is **authoritative** for group
    values: a row the user has reset (``edit_origin == NONE``) is absent from
    the result, which is what makes `r` remove the flag from the bar rather
    than leave it standing. ``group_values`` is the fallback for a field list
    that carries no group rows at all.

    Args:
        job_name: The job's canonical dotted name. It is spelled back out as
            a path — `deploy web run` — by ``build_command_line``, which is
            what the shell reads and what its own resolver accepts.
        fields: The full field list from the ConfigTablePanel, in display order.
        group_values: Group option values to carry through, keyed by field
            name, used only when ``fields`` carries no group rows. Without
            them an edit to any field silently drops every group flag the user
            typed.
        trie: The group trie, for placing those flags mid-path.

    Returns:
        The formatted bar text string.
    """
    entries: list[tuple[str, str, bool, str | None]] = []
    panel_group_values: dict[str, Any] = {}
    has_group_rows = False

    for f in fields:
        if getattr(f, "group_path", None):
            has_group_rows = True
            if f.edit_origin != EditOrigin.NONE:
                panel_group_values[f.name] = f.value
            continue
        if f.edit_origin != EditOrigin.NONE:
            entries.append((f.name, f.value, f.positional, f.short_flag))

    effective = panel_group_values if has_group_rows else (group_values or {})
    return build_command_line(job_name, entries, effective, trie)


def sync_pending_overrides_to_bar(
    field_descriptors: list[Any],
    pending: PendingExecution,
    trie: Any | None = None,
) -> str:
    """Rebuild SmartBar text from a PendingExecution's overrides.

    Same output shape as `sync_overrides_to_bar`, but sources overridden
    values from `pending.overrides` (a plain dict keyed by field name)
    instead of `ConfigTablePanel` `FieldDef`s — used when only the job's
    raw field descriptors and a `PendingExecution` are available (no
    live `ConfigTablePanel` widget).

    Args:
        field_descriptors: The job's field descriptors, in declaration order.
        pending: The PendingExecution holding CLI/session overrides and the
            values of the group options on the job's path.
        trie: The group trie, so the group's flags land beside their own
            segment. Without it the output falls back to the dotted spelling
            — correct for an ungrouped project, and the pre-S6b behaviour
            everywhere else.

    Returns:
        The formatted bar text string.
    """
    entries: list[tuple[str, str, bool, str | None]] = []
    for fd in field_descriptors:
        if fd.name not in pending.overrides:
            continue
        val = pending.overrides[fd.name]
        if not val:
            continue
        entries.append(
            (
                fd.name,
                str(val),
                getattr(fd, "positional", False),
                getattr(fd, "short_flag", None),
            )
        )
    return build_command_line(
        pending.job_name, entries, pending.group_option_values, trie
    )


def sync_bar_to_overrides(
    bar_text: str,
    fields: list[FieldDef],
    *,
    resolution: TuiCommandResolution | None = None,
) -> bool:
    """Parse SmartBar CLI text and apply matching values onto fields.

    Mutates `fields` in place: any field whose name appears in the parsed
    tokens gets `value` updated (and `source` set to "cli") if the value
    changed.

    Args:
        bar_text: The current SmartBar text (a command path + CLI-style args).
        fields: The ConfigTablePanel's field list to update in place.
        resolution: The walk of `bar_text`, from ``resolve_tui_command``. Its
            ``args`` are the job's **own** tokens, with every path segment and
            mid-path group flag already consumed. Callers that can resolve
            must pass it: without one this degrades to the trie-less walk,
            which treats the whole line as a flat `<job> <args…>` — correct
            for an ungrouped project, and for a grouped job it hands the
            parser leading path segments whose first binds to the job's first
            positional.

    Returns:
        True if any field was actually changed, False otherwise — callers
        can use this to decide whether to reload a table display.
    """
    tokens = tokenize_bar_text(bar_text)
    if not tokens:
        return False

    if resolution is None:
        resolution = resolve_tui_command(None, tokens)
    provided = parse_cli_args_to_kwargs(resolution.args, fields=fields)
    changed = False
    for field in fields:
        if field.name in provided:
            new_val = provided[field.name]
            if new_val != field.value:
                field.value = new_val
                field.source = "cli"
                changed = True
    return changed
