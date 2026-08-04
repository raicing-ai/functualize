"""SmartBar ↔ Config Table synchronization.

Pure-Python module (no Textual dependency) that keeps the SmartBar's CLI
text and a job's configured field values in sync in both directions.

Integration wiring:
    The ConfigTablePanel's `apply_value_edit`, `apply_source_edit`, and
    `action_reset_override` post messages (ValueEdited, SourceChanged,
    OverrideReset). The controller/app that owns both the SmartBar and the
    ConfigTablePanel should listen for these messages and call
    `sync_overrides_to_bar(job_name, fields)` to rebuild bar text, then
    update the SmartBar's saved state via `bar.save_state()` so that
    restore_state uses the most recent synced text.

    This is also the single source of truth for reconstructing bar text
    from field-level overrides — do not reimplement this in the app layer;
    `sync_pending_overrides_to_bar` covers the equivalent case where
    overrides live on a `PendingExecution` instead of `ConfigTablePanel`
    `FieldDef`s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._cli.tui.cli_arg_parser import parse_cli_args_to_kwargs
from functualize._cli.tui.panels.config_table import EditOrigin, FieldDef

if TYPE_CHECKING:
    from functualize._cli.data.pending_execution import PendingExecution

__all__ = [
    "sync_bar_to_overrides",
    "sync_overrides_to_bar",
    "sync_pending_overrides_to_bar",
]


def _emit_positional_then_named(
    job_name: str,
    entries: list[tuple[str, str, bool, str | None]],
) -> str:
    """Join job_name with positional bare tokens then named --flag/​-x tokens.

    Args:
        job_name: The current job name (first token in the bar).
        entries: (name, value, positional, short_flag) tuples, in the order
            they should be emitted.
    """
    positional_parts: list[str] = []
    named_parts: list[str] = []
    for name, value, positional, short_flag in entries:
        if positional:
            positional_parts.append(value)
            continue
        if short_flag:
            flag = short_flag if short_flag.startswith("-") else f"-{short_flag}"
        else:
            flag = f"--{name}"
        named_parts.append(flag)
        if " " in value or "\t" in value:
            named_parts.append(f'"{value}"')
        else:
            named_parts.append(value)
    return " ".join([job_name, *positional_parts, *named_parts])


def sync_overrides_to_bar(job_name: str, fields: list[FieldDef]) -> str:
    """Rebuild SmartBar text from session overrides.

    Produces a string in the format:
        "{job_name} <positional_vals> --{field1} {value1} --{field2} {value2}"

    Only includes fields with edit_origin != NONE, ordered by their position
    in the field list — positional fields emit as bare tokens first, then
    named fields as `--{name} {value}` (or `-{short_flag} {value}` when a
    short flag is set). Named values containing whitespace are enclosed in
    double quotes. When no overrides exist, returns just the job name.

    Args:
        job_name: The current job name (first token in the bar).
        fields: The full field list from the ConfigTablePanel, in display order.

    Returns:
        The formatted bar text string.
    """
    entries = [
        (f.name, f.value, f.positional, f.short_flag)
        for f in fields
        if f.edit_origin != EditOrigin.NONE
    ]
    return _emit_positional_then_named(job_name, entries)


def sync_pending_overrides_to_bar(
    field_descriptors: list[Any],
    pending: PendingExecution,
) -> str:
    """Rebuild SmartBar text from a PendingExecution's overrides.

    Same output shape as `sync_overrides_to_bar`, but sources overridden
    values from `pending.overrides` (a plain dict keyed by field name)
    instead of `ConfigTablePanel` `FieldDef`s — used when only the job's
    raw field descriptors and a `PendingExecution` are available (no
    live `ConfigTablePanel` widget).

    Args:
        field_descriptors: The job's field descriptors, in declaration order.
        pending: The PendingExecution holding CLI/session overrides.

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
    return _emit_positional_then_named(pending.job_name, entries)


def sync_bar_to_overrides(bar_text: str, fields: list[FieldDef]) -> bool:
    """Parse SmartBar CLI text and apply matching values onto fields.

    Mutates `fields` in place: any field whose name appears in the parsed
    tokens gets `value` updated (and `source` set to "cli") if the value
    changed.

    Args:
        bar_text: The current SmartBar text (job name + CLI-style args).
        fields: The ConfigTablePanel's field list to update in place.

    Returns:
        True if any field was actually changed, False otherwise — callers
        can use this to decide whether to reload a table display.
    """
    tokens = bar_text.split() if bar_text.strip() else []
    if not tokens:
        return False

    provided = parse_cli_args_to_kwargs(
        tokens[1:] if len(tokens) > 1 else [], fields=fields
    )
    changed = False
    for field in fields:
        if field.name in provided:
            new_val = provided[field.name]
            if new_val != field.value:
                field.value = new_val
                field.source = "cli"
                changed = True
    return changed
