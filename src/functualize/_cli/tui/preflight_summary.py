"""Pre-flight summary line formatting for the inline TUI.

Pure text formatting — given a field's metadata and its currently-provided
value, produces a single compact display line with source/type annotations
and truncation to fit the available terminal width.

This is the panel a user reads immediately before pressing Ctrl+Enter, so it is
also the one that must never render a credential. Masking is driven by the
descriptor's ``secret`` flag — the model's answer, carried through the discovery
cache — never by the field's *name*. A name-matching regex used to live in a
second, unmounted preflight widget: it missed ``credential``/``pat``/``bearer``
and masked ``sort_key``/``keywords``, and it was deleted rather than fixed.
"""

from __future__ import annotations

import re
from typing import Any

from functualize.app.utils import display_value

# Truncation cap (R3-AC3, R3-AC4, R3-AC5): plain params are never truncated,
# config params are capped at TRUNCATION_CAP - len(plain_fields).
TRUNCATION_CAP = 8


def _strip_rich_markup(text: str) -> str:
    """Strip Rich markup tags for plain-text length calculation."""
    return re.sub(r"\[/?[^\]]*\]", "", text)


def format_preflight_field_line(
    fd: Any,
    provided: dict[str, str],
    avail_width: int = 80,
    resolved_source: str | None = None,
) -> str:
    """Format a single field as a compact pre-flight summary line.

        Format: {indicator}{req_mark} {kind_label}{name}{short}: {value} ({source})  {type}  {desc}

        Args:
            fd: A field descriptor (SimpleNamespace or similar) with name, required,
                default, positional, short_flag, type_annotation, description, param_kind.
            provided: Dict of CLI-provided values keyed by field name.
            avail_width: Terminal width for truncation.
            resolved_source: The real resolved source_type for this field
                (``env``/``file``/``remote``/``default``), used when the field has
                no SmartBar value instead of a blind ``default``/blank fallback
    .

        Returns:
            A formatted single-line string for the pre-flight summary.
    """
    name = fd.name
    value = provided.get(name, "")
    required = getattr(fd, "required", False)
    description = getattr(fd, "description", "") or ""
    default = getattr(fd, "default", None)
    type_ann = getattr(fd, "type_annotation", "str") or "str"
    is_positional = getattr(fd, "positional", False)
    short = getattr(fd, "short_flag", None)
    param_kind = getattr(fd, "param_kind", None)

    # Determine if this is a plain param (check both enum and string value)
    is_plain = False
    if param_kind is not None:
        if hasattr(param_kind, "value"):
            is_plain = param_kind.value == "plain"
        else:
            is_plain = str(param_kind) == "plain"

    # Indicator: ● filled, ○ empty+required, · optional+empty
    if value or default is not None:
        indicator = "●"
    elif required:
        indicator = "○"
    else:
        indicator = "·"

    # Required marker
    req_mark = "*" if required else " "

    # Kind label: [arg] for positional plain params only (R2-AC2)
    kind_label = "\\[arg] " if (is_positional and is_plain) else ""

    # Display name mirrors the CLI spelling: option flags hyphenate the
    # underscored Python name (``dry_run`` → ``--dry-run``), so the pre-flight
    # shows what the user actually types. Positional args carry no flag, so
    # their bare name is shown as-is. (Value lookups still use ``name``.)
    display_name = name if is_positional else name.replace("_", "-")

    # Short flag display
    short_label = f"/{short}" if short else ""

    # Source determination (R2-AC3, R2-AC4)
    if is_plain:
        # Plain params: omit source if empty; "cli" or "default" only
        if value:
            source = "cli"
        elif default is not None:
            source = "default"
        else:
            source = ""
    else:
        # Config params: full source label.
        # for an unfilled field, show its real resolved
        # source_type (env/file/remote/default) instead of a blind
        # default/blank fallback. A SmartBar value still wins ("cli").
        if value:
            source = "cli"
        elif resolved_source:
            source = resolved_source
        elif default is not None:
            source = "default"
        else:
            source = ""

    # A secret is masked whether it came from the bar or from a non-empty
    # default: `Field(default="dev-key", json_schema_extra={"secret": True})`
    # would otherwise render on screen with nothing typed at all. An *empty*
    # secret stays empty — see `display_value`, which every surface shares.
    raw_value = value or (str(default) if default is not None else "")
    shown = display_value(raw_value, secret=bool(getattr(fd, "secret", False)))

    # Build the line prefix (everything before description)
    # Format: "  {indicator}{req_mark} {kind_label}{name}{short}: {value} ({source})  {type}  "
    prefix = f"  {indicator}{req_mark} {kind_label}{display_name}{short_label}:"
    if shown:
        prefix += f" {shown}"
        if source:
            prefix += f" ({source})"
    elif source:
        prefix += f" ({source})"

    prefix += f"  {type_ann}"

    # Add description with truncation (R2-AC5)
    if description:
        full_line = f"{prefix}  {description}"
        # Strip Rich markup for length calculation
        plain_len = len(_strip_rich_markup(full_line))
        if plain_len > avail_width:
            # Truncate description to fit
            overhead = len(_strip_rich_markup(f"{prefix}  ")) + 1  # +1 for ellipsis
            max_desc_len = avail_width - overhead
            if max_desc_len > 0:
                line = f"{prefix}  {description[:max_desc_len]}…"
            else:
                line = prefix
        else:
            line = full_line
    else:
        line = prefix

    return line


def build_preflight_lines(
    fields: list[Any],
    provided: dict[str, str],
    avail_width: int,
    resolved_sources: dict[str, str] | None = None,
) -> list[str]:
    """Compute the pre-flight summary field lines, applying the truncation cap.

    Splits fields into plain (never truncated) and config (capped) groups.
    When the total field count exceeds TRUNCATION_CAP, plain fields are
    always shown in full, config fields are capped at
    ``TRUNCATION_CAP - len(plain_fields)``, and a trailing truncation
    indicator line is appended when any config fields were hidden.

    Args:
        fields: The job's fields, in priority-sorted display order.
        provided: Dict of CLI-provided values keyed by field name.
        avail_width: Terminal width for per-line truncation.
        resolved_sources: Optional map of field name -> real resolved
            source_type, threaded through to ``format_preflight_field_line``
            for unfilled config params.

    Returns:
        The formatted lines to write, in display order.
    """
    resolved_sources = resolved_sources or {}

    def _line(fd: Any) -> str:
        return format_preflight_field_line(
            fd,
            provided,
            avail_width,
            resolved_source=resolved_sources.get(getattr(fd, "name", "")),
        )

    plain_fields = []
    config_fields = []
    for fd in fields:
        pk = getattr(fd, "param_kind", None)
        is_plain = False
        if pk is not None:
            if hasattr(pk, "value"):
                is_plain = pk.value == "plain"
            else:
                is_plain = str(pk) == "plain"
        if is_plain:
            plain_fields.append(fd)
        else:
            config_fields.append(fd)

    # Calculate how many config fields we can show
    config_cap = max(0, TRUNCATION_CAP - len(plain_fields))
    total_fields = len(plain_fields) + len(config_fields)

    lines: list[str] = []
    if total_fields <= TRUNCATION_CAP:
        # No truncation needed — show all fields in original order
        for fd in fields:
            lines.append(_line(fd))
    else:
        # Show all plain params first, then capped config params
        # Maintain sorted order: plain first, then config (matching priority sort)
        for fd in plain_fields:
            lines.append(_line(fd))
        shown_config = config_fields[:config_cap]
        for fd in shown_config:
            lines.append(_line(fd))

        # Truncation indicator line
        hidden_count = len(config_fields) - len(shown_config)
        if hidden_count > 0:
            lines.append(f"[dim]... +{hidden_count} more — Ctrl+R for all[/dim]")

    return lines
