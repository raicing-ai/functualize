"""Field priority ordering for pre-flight summary and config table display."""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._cli.tui.panels.config_table import ParamKind

if TYPE_CHECKING:
    from functualize._cli.tui.panels.config_table import FieldDef


def sort_fields_by_priority(fields: list[FieldDef]) -> list[FieldDef]:
    """Sort fields by priority for pre-flight summary and config table display.

    Priority order (highest first):
      P1: Plain parameters that are positional (positional=True)
      P2: Plain parameters that are named (flags)
      P3: Required config parameters that have NO value (empty, blocking execution)
      P4: Required config parameters that HAVE a value (resolved from chain)
      P5: Optional config parameters

    Within each priority group, original declaration order is maintained.
    """

    def _priority_key(item: tuple[int, FieldDef]) -> tuple[int, int]:
        idx, f = item
        if f.param_kind == ParamKind.PLAIN:
            if f.positional:
                return (0, idx)  # P1
            return (1, idx)  # P2
        # CONFIG
        if f.required and not f.value:
            return (2, idx)  # P3
        if f.required and f.value:
            return (3, idx)  # P4
        return (4, idx)  # P5

    indexed = list(enumerate(fields))
    indexed.sort(key=_priority_key)
    return [f for _, f in indexed]
