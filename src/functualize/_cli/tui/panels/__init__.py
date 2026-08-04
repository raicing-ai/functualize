"""TUI panels subpackage — PanelRing and panel widgets."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from functualize._cli.tui.panels.config_files import (
    ConfigFileEntry,
    ConfigFilesPanel,
    discover_config_files,
)
from functualize._cli.tui.panels.config_table import (
    ChainEntry,
    ConfigTablePanel,
    EditOrigin,
    FieldDef,
)
from functualize._cli.tui.panels.job_browser import JobBrowserPanel
from functualize._cli.tui.panels.ring import PanelRing
from functualize._cli.tui.panels.settings_files import (
    SettingsFilesPanel,
    build_settings_file_entries,
)

__all__: list[str] = [
    "ChainEntry",
    "ConfigFileEntry",
    "ConfigFilesPanel",
    "ConfigTablePanel",
    "EditOrigin",
    "FieldDef",
    "Filterable",
    "JobBrowserPanel",
    "PanelActions",
    "PanelRing",
    "SettingsFilesPanel",
    "build_settings_file_entries",
    "discover_config_files",
]


@runtime_checkable
class Filterable(Protocol):
    """Panel capability: supports text-based filtering of displayed content.

    Panels that wrap a DataTable (or any list-like view) should implement
    this protocol to opt into the "/" filter workflow. Panels that do NOT
    implement this protocol will silently ignore "/" in NORMAL mode.
    """

    @property
    def active_filter(self) -> str:
        """The currently applied filter text. Empty string means no filter."""
        ...

    def apply_filter(self, query: str) -> None:
        """Apply a case-insensitive substring filter. Empty string resets."""
        ...


@runtime_checkable
# NOTE: public contract with fan-in from app.py's message
# handlers, KeyDispatcher._resolve_target, and every concrete panel that
# implements a subset of these methods.
# fan_in >= 3 (app.py handlers, KeyDispatcher target resolution,
# individual panel implementations); public API boundary for panel/app
# interaction — a panel relying on this Protocol staying stable.
class PanelActions(Protocol):
    """Panel capability: optional panel-owned action surface.

    Declares the optional methods that ``app.py``/``KeyDispatcher`` previously
    probed for via ad hoc ``hasattr(panel, "...")`` duck typing. No single
    panel implementation is expected to satisfy every member of this
    Protocol — each concrete panel implements the subset relevant to its own
    behavior (e.g. ``ConfigTablePanel`` implements field-editing actions,
    ``ConfigFilesPanel`` only ``action_drill_down``). Call sites use
    per-method presence checks (``getattr(panel, "method_name", None)``)
    rather than ``isinstance(panel, PanelActions)`` for that reason — a full
    ``isinstance`` match would require a panel to implement every method
    simultaneously, which no current panel does.
    """

    def get_cursor_field(self) -> Any:
        """Return the field definition at the current cursor position."""
        ...

    def action_reset_override(self) -> None:
        """Reset the override for the currently selected field."""
        ...

    def apply_value_edit(self, field: Any, new_value: str) -> None:
        """Apply an edited value to the given field."""
        ...

    def action_enter_persist(self) -> None:
        """Enter persist-mode override application for the current field."""
        ...

    def action_drill_down(self) -> None:
        """Drill down into nested config for the current selection."""
        ...

    def clear_drill_down(self) -> None:
        """Clear any active drill-down state."""
        ...

    def exit_detail_view(self) -> None:
        """Exit the panel's detail sub-view, if one is active."""
        ...
