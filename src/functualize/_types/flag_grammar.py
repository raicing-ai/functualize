"""The single authority for flag vocabulary and alias matching.

The value-flag tables, optional-value tables, bool-flag set, and the alias
matchers that resolve a token to a field — currently scattered across
``_cli/dispatch.py`` and ``_types/naming.py`` — live here so every surface
that renders or matches a flag asks one source.

**The** ``--perf-report`` **lookahead deliberately stays in** ``_cli/dispatch.py``.
That lookahead is not data — it is behavior tightly coupled to the pre-boot
argv scan (``detect_mode`` and ``_extract_global_options``), where the next
token is consumed only if it is in the valid set. Moving the table without
moving the lookahead would split the rule from its enforcement; moving the
lookahead would drag pre-boot dispatch logic into this low-level module, which
must stay importable from ``_cli`` without a cycle. So the tables are here,
the lookahead stays there, and both reference the same vocabulary.

Pure data + pure functions, stdlib-only, importable from ``_cli``, ``app`` and
``_engine`` alike without a cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec

__all__ = [
    "GLOBAL_OPTIONS_ALWAYS_VALUE",
    "GLOBAL_OPTIONS_OPTIONAL_VALUE",
    "OPTIONAL_VALUE_VALID_SET",
    "GLOBAL_OPTIONS_WITH_VALUE",
    "GLOBAL_BOOL_FLAGS",
    "flag_aliases",
    "negative_aliases",
    "match_group_flag",
    "negative_flag_for",
]


# ---------------------------------------------------------------------------
# Flag vocabulary
# ---------------------------------------------------------------------------

# Global options that always consume the next token as their value.
GLOBAL_OPTIONS_ALWAYS_VALUE = frozenset(
    {
        "--log-level",
        "--dotenv-file",
        "--config-directory",
        "--discovery-depth",
        "--require-file-import",
        "--require-file-prefix",
        "--require-file-postfix",
        "--require-file-marker",
        "--require-job-prefix",
        "--require-job-postfix",
        "--require-job-decorators",
        "--exclude",
        "--perf-filter",
        "--import-libs",
    }
)

# Global options that MAY take a value from a known set; if the next token
# is not in that set, the flag assumes its default value (lookahead).
GLOBAL_OPTIONS_OPTIONAL_VALUE = frozenset(
    {
        "--perf-report",
        "--output",
    }
)

# Mapping: flag -> (valid_values_frozenset, default_value)
OPTIONAL_VALUE_VALID_SET: dict[str, tuple[frozenset[str], str]] = {
    "--perf-report": (frozenset({"text", "json"}), "text"),
    # §C.2 serialization vocabulary for ``out.emit()``. "auto" (dispatch by the
    # emitted value's type) is both the default *and* a typeable value: a bare
    # ``--output`` falls back to it via the lookahead, and that fallback is fed
    # back through validation, so it has to be a legal value — spelling it also
    # lets a user name the default explicitly.
    "--output": (frozenset({"auto", "json", "ndjson", "raw", "none"}), "auto"),
}

# Union set for backward compatibility (used for --option=value detection).
GLOBAL_OPTIONS_WITH_VALUE = GLOBAL_OPTIONS_ALWAYS_VALUE | GLOBAL_OPTIONS_OPTIONAL_VALUE

# Global options that are boolean flags (no value after the flag).
# NOTE: --version is NOT here — it is handled by the pre-boot fast path in
# main.py (position-aware: only before the first positional). --help/-h are
# here because Click needs to see them for per-command help rendering.
GLOBAL_BOOL_FLAGS = frozenset(
    {
        "--no-dotenv",
        "--prompt-gates",
        "--no-prompt-gates",
        "--force",
        "--help",
        "-h",
    }
)


# ---------------------------------------------------------------------------
# Alias matchers
# ---------------------------------------------------------------------------


def flag_aliases(field: FieldDescriptor) -> tuple[str, ...]:
    """Every spelling that selects ``field`` **positively**.

    The long form is derived from the field name with underscores hyphenated
    (``dry_run`` -> ``--dry-run``), matching what the click param builder
    renders, plus the undecorated ``--dry_run`` so the name as written also
    works. A short flag is included when the ``Option`` marker declared one.
    """
    names = [f"--{field.name.replace('_', '-')}"]
    if "_" in field.name:
        names.append(f"--{field.name}")
    if field.short_flag:
        names.append(field.short_flag)
    return tuple(names)


def negative_aliases(
    field: FieldDescriptor, siblings: Sequence[str]
) -> tuple[str, ...]:
    """Every spelling that selects ``field`` **negatively**, for a bool.

    Empty for a non-boolean, and empty when a sibling literally named
    ``no_<name>`` owns the spelling — the same rule the click builders render
    from. Two surfaces asking one function is the point: if they decided
    independently, ``--no-cache`` would mean different things depending on how
    the program was invoked.
    """
    if (field.type_annotation or "") != "bool":
        return ()

    negative = negative_flag_for(field.name, siblings)
    if negative is None:
        return ()
    names = [negative]
    if "_" in field.name:
        names.append(f"--no_{field.name}")
    return tuple(names)


def match_group_flag(
    token: str, specs: Sequence[GroupOptionsSpec]
) -> tuple[FieldDescriptor, str | None, bool] | None:
    """Find the field a mid-path ``token`` selects, if any declares it.

    Searched nearest-declaration-first so a nested group may shadow an
    ancestor's flag. Returns ``(field, inline_value, negated)`` where
    ``inline_value`` is the right-hand side of a ``--flag=value`` spelling and
    ``negated`` says the ``--no-`` spelling was used.

    ``negated`` is a third element rather than a synthesised ``inline="false"``
    because the caller must tell ``--no-strict`` from ``--strict=false``: the
    first is the supported spelling and the second is refused.
    """
    name, separator, inline = token.partition("=")
    for spec in reversed(specs):
        siblings = [f.name for f in spec.fields]
        for spec_field in spec.fields:
            if name in flag_aliases(spec_field):
                return spec_field, (inline if separator else None), False
            if name in negative_aliases(spec_field, siblings):
                return spec_field, (inline if separator else None), True
    return None


# ---------------------------------------------------------------------------
# Negative-flag rule
# ---------------------------------------------------------------------------


def negative_flag_for(name: str, siblings: Iterable[str] = ()) -> str | None:
    """The ``--no-`` spelling that turns boolean field ``name`` off.

    Returns ``None`` when a **sibling field is literally called** ``no_<name>``.
    That field owns the spelling, and ``name`` renders with no negative form.

    The rule exists because click will not enforce one. Declaring both ``cache``
    and ``no_cache`` gives two parameters contending for ``--no-cache``, and
    click raises nothing — it binds whichever was declared first, so the same
    two fields produce opposite results depending on the order they were
    written in. That silent, order-dependent shadowing is the defect; this
    function's guarantee is **determinism**, not detection. A user gets a
    working CLI in which one field simply has no negative spelling.

    Lives here, and is re-exported through ``functualize.app.utils``, because
    two surfaces must agree on it: the click param builders render the flag,
    and ``func``'s pre-boot dispatch parser matches it mid-path. If they decided
    this independently, ``--no-cache`` would come to mean different things
    depending on how the program was invoked — the divergence class that
    already produced three disagreeing dependency resolvers here.

    Args:
        name: The boolean field's Python name (``dry_run``, not ``--dry-run``).
        siblings: Every field name visible on the same command, this one
            included. Passing only some of them re-opens the collision.

    Returns:
        ``--no-<hyphenated-name>``, or ``None`` when a sibling owns it.
    """
    if f"no_{name}" in siblings:
        return None
    return f"--no-{name.replace('_', '-')}"
