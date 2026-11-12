"""Root CLI flags, generated from a settings declaration.

``func``'s root group and an embedded app's root group answer one question —
"which settings may a command line override?" — so both call
:func:`generated_setting_options` instead of keeping a decorator list each.
The declaration stays the single statement: a setting that declares
``cli_flag`` gets exactly one option, on every surface, with the help text the
declaration already carries.

Un-passed and passed-as-empty stay distinguishable: every option defaults to
``None``, and ``None``/``()`` both mean "not given", so a generated flag can
never invent a precedence rung nobody asked for.

:func:`early_setting_flags` answers the same question *before* there is a
parser: a setting that declares ``phase="early"`` changes what the app is
constructed with, so its value has to be read from argv ahead of boot. ``func``
and an embedded app both call it with their own declaration.

Imports click and nothing heavier — ``_cli/main.py`` builds its root options
at import time, on the lazy-boot path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from functualize._types.settings import AppSettingsSchema, Setting

__all__ = [
    "declared_flag_settings",
    "early_setting_flags",
    "generated_setting_options",
    "option_name_for",
    "passed_setting_flags",
]


def declared_flag_settings(schema: AppSettingsSchema) -> tuple[Setting, ...]:
    """Every setting the declaration makes reachable from a root flag."""
    return tuple(setting for setting in schema.settings if setting.cli_flag)


def option_name_for(setting: Setting) -> str:
    """The click parameter name a declared flag arrives as.

    ``--require-file-prefix`` becomes ``require_file_prefix``, which is click's
    own convention for that option — named explicitly so a caller can look the
    value up without re-deriving it.
    """
    flag = setting.cli_flag
    if flag is None:
        raise ValueError(f"setting '{setting.name}' declares no cli_flag")
    return flag.lstrip("-").replace("-", "_")


def _click_type(setting: Setting) -> Any:
    """The click type that lets the resolver see what the author declared.

    ``int`` converts at parse time so a non-numeric value is a usage error
    rather than a setting that silently keeps its default. Booleans arrive as
    text — the resolver's own coercion accepts ``true``/``false``/``1``/``0`` —
    restricted to those spellings so a typo cannot become the literal string
    ``"yes"``.
    """
    if setting.type == "int":
        return int
    if setting.type == "bool":
        return click.Choice(["true", "false", "1", "0"], case_sensitive=False)
    if setting.type == "enum" and setting.choices:
        return click.Choice(setting.choices)
    return str


def generated_setting_options(schema: AppSettingsSchema) -> list[click.Option]:
    """One root option per setting that declares a flag, in declaration order."""
    options: list[click.Option] = []
    for setting in declared_flag_settings(schema):
        kwargs: dict[str, Any] = {
            "type": _click_type(setting),
            "default": None,
            "help": setting.description,
        }
        if setting.type == "list":
            kwargs["multiple"] = True
        # The second declaration is click's way of naming the parameter, so
        # the value arrives under the name `passed_setting_flags` looks up
        # rather than one click guessed from the flag.
        options.append(
            click.Option([str(setting.cli_flag), option_name_for(setting)], **kwargs)
        )
    return options


def passed_setting_flags(
    schema: AppSettingsSchema, values: Mapping[str, Any]
) -> dict[str, Any]:
    """The declared settings a command line actually set, keyed by dotted name.

    Keyed by ``Setting.name`` because that is what
    :func:`functualize.plugin.resolve_settings` looks up first, so these values
    enter the resolved ladder as the ``cli`` layer without a second vocabulary.
    """
    passed: dict[str, Any] = {}
    for setting in declared_flag_settings(schema):
        value = values.get(option_name_for(setting))
        if value is None or value == ():
            continue
        passed[setting.name] = value
    return passed


def early_setting_flags(
    schema: AppSettingsSchema, argv: Sequence[str]
) -> dict[str, Any]:
    """The ``phase="early"`` flags ``argv`` passes, keyed by declared setting name.

    Read before the app exists, so the result can go straight into
    :func:`functualize.plugin.resolve_settings` as ``flags`` and the first
    snapshot already carries it. Keyed like :func:`passed_setting_flags`, but
    there is no click type yet: a scalar is the text as typed (the last
    occurrence wins, as it does for click) and the resolver coerces it; a list
    setting collects every occurrence into a tuple.

    Both ``--flag value`` and ``--flag=value`` are read. Anything else is left
    alone rather than guessed at: ordinary flags are click's at callback time,
    and an early flag with nothing after it is a usage error the real parser
    reports — this scan runs first and must not turn it into a silent misread.
    """
    early = {
        str(setting.cli_flag): setting
        for setting in declared_flag_settings(schema)
        if setting.phase == "early"
    }
    passed: dict[str, Any] = {}
    if not early:
        return passed
    index = 0
    while index < len(argv):
        flag, sep, inline = argv[index].partition("=")
        setting = early.get(flag)
        if setting is None:
            index += 1
            continue
        if sep:
            value = inline
        elif index + 1 < len(argv):
            index += 1
            value = argv[index]
        else:
            break
        if setting.type == "list":
            passed[setting.name] = (*passed.get(setting.name, ()), value)
        else:
            passed[setting.name] = value
        index += 1
    return passed
