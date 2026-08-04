"""TUI subpackage — UI widgets, state machines, and UI logic."""

from __future__ import annotations

from functualize._cli.data.func_settings import register_settings, tui_settings
from functualize._cli.tui.bar import BarReadiness, SavedBarState, SmartBar
from functualize._cli.tui.breadcrumb_header_widget import BreadcrumbHeader
from functualize._cli.tui.config_diff import compute_config_diff
from functualize._cli.tui.config_target_discovery import discover_config_targets
from functualize._cli.tui.diff_view_widget import DiffViewWidget
from functualize._cli.tui.display_affinity import (
    find_related_displays,
    is_display_related,
)
from functualize._cli.tui.display_slot import DisplaySlot
from functualize._cli.tui.dynamic_footer import render_footer
from functualize._cli.tui.dynamic_footer_widget import DynamicFooterWidget
from functualize._cli.tui.editable_table import EditableTable
from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.functualize_autocomplete import FunctualizeAutoComplete
from functualize._cli.tui.integration import (
    action_zone_cycle,
    enter_normal_mode,
    exit_to_command_mode,
)
from functualize._cli.tui.key_handler import KEYMAPS, KeyDispatcher
from functualize._cli.tui.missing_args import get_missing_required_args
from functualize._cli.tui.panel_host import PanelHost
from functualize._cli.tui.path_field_editor import PathFieldEditor
from functualize._cli.tui.path_suggestion_scanner import PathSuggestionScanner
from functualize._cli.tui.preflight_widget import PreFlightWidget
from functualize._cli.tui.settings_panel import SettingsPanel
from functualize._cli.tui.settings_validator import validate_setting
from functualize._cli.tui.shortcut_save_modal import ShortcutSaveModal
from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
from functualize._cli.tui.sync import sync_overrides_to_bar
from functualize._cli.tui.theme_manager import ThemeManager
from functualize._cli.tui.type_hint_formatter import format_type_hint

__all__ = [
    # State machines and core TUI infrastructure
    "BarReadiness",
    "FocusMode",
    "FocusState",
    "FocusZone",
    "KEYMAPS",
    "KeyDispatcher",
    "SavedBarState",
    "SmartBar",
    "action_zone_cycle",
    "enter_normal_mode",
    "exit_to_command_mode",
    "sync_overrides_to_bar",
    # Widget classes
    "BreadcrumbHeader",
    "DiffViewWidget",
    "DisplaySlot",
    "DynamicFooterWidget",
    "EditableTable",
    "FunctualizeAutoComplete",
    "PanelHost",
    "PathFieldEditor",
    "PathSuggestionScanner",
    "PreFlightWidget",
    "SettingsPanel",
    "ShortcutSaveModal",
    "SmartBarAutoComplete",
    "ThemeManager",
    # Key helper functions
    "compute_config_diff",
    "discover_config_targets",
    "find_related_displays",
    "format_type_hint",
    "get_missing_required_args",
    "is_display_related",
    "render_footer",
    "validate_setting",
]


# The shell contributes its own settings (C2.4). Importing this package *is*
# the shell being present, which is the condition the catalog should reflect:
# a project app that never launches a shell resolves no `tui.*`.
#
# Placed after the imports rather than before them because nothing above needs
# the settings to exist yet — `settings_panel` binds `FUNC_SETTINGS` with a
# plain `from` import, and that is a *live view*, so it picks these up whenever
# they land. Registration is idempotent per name, so a re-import cannot
# duplicate a row.
register_settings(*tui_settings())
