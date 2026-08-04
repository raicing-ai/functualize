"""Unit tests for get_available_actions on ConfigTablePanel and ConfigFilesPanel.

Tests verify return values for all three states of ConfigTablePanel:
- focused=False: unfocused hints
- focused=True with drill-down: drill-down hints
- focused=True at root level: full navigation hints

Also verifies ConfigFilesPanel unfocused return updated to new standardized hints.

Validates: Requirements R9-AC1, R9-AC2, R9-AC3, R9-AC4, R10-AC1
"""

from __future__ import annotations

from functualize._cli.tui.panels.config_files import ConfigFilesPanel
from functualize._cli.tui.panels.config_table import (
    ConfigTablePanel,
    FieldDef,
)

# ===========================================================================
# ConfigTablePanel.get_available_actions
# ===========================================================================


class TestConfigTablePanelGetAvailableActions:
    """Test ConfigTablePanel.get_available_actions returns correct hints for all states."""

    def _make_panel(self) -> ConfigTablePanel:
        """Create a ConfigTablePanel with minimal internal state (no mounting)."""
        panel = ConfigTablePanel.__new__(ConfigTablePanel)
        panel._fields = []
        panel._filtered_fields = []
        panel._active_filter_text = ""
        panel._cursor_row = 0
        panel._row_count = 0
        panel._table = None
        panel._populated = False
        panel._drill_down_field = None
        return panel

    def test_unfocused_returns_focus_and_cycle(self) -> None:
        """R9-AC2: When focused=False, returns Ctrl+R focus and Shift+Tab cycle."""
        panel = self._make_panel()
        actions = panel.get_available_actions(focused=False)
        assert actions == [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

    def test_focused_drill_down_returns_esc_back(self) -> None:
        """R9-AC3: When focused=True and _drill_down_field is not None, returns Esc back."""
        panel = self._make_panel()
        panel._drill_down_field = FieldDef(
            name="region", value="us-east-1", source="File"
        )
        actions = panel.get_available_actions(focused=True)
        assert actions == [("Esc", "back")]

    def test_focused_root_level_returns_full_hints(self) -> None:
        """R9-AC4: When focused=True and at root level, returns full navigation hints."""
        panel = self._make_panel()
        actions = panel.get_available_actions(focused=True)
        expected = [
            ("Ctrl+Enter", "run"),
            ("j/k", "navigate"),
            ("i", "edit"),
            ("r", "reset"),
            ("/", "filter"),
            ("Enter", "detail"),
            ("Esc", "back"),
        ]
        assert actions == expected

    def test_focused_root_level_after_clearing_drill_down(self) -> None:
        """After clearing drill-down, returns root-level hints again."""
        panel = self._make_panel()
        # Simulate entering drill-down
        panel._drill_down_field = FieldDef(name="port", value="8080", source="Default")
        assert panel.get_available_actions(focused=True) == [("Esc", "back")]
        # Simulate clearing drill-down (Esc pop)
        panel.clear_drill_down()
        expected = [
            ("Ctrl+Enter", "run"),
            ("j/k", "navigate"),
            ("i", "edit"),
            ("r", "reset"),
            ("/", "filter"),
            ("Enter", "detail"),
            ("Esc", "back"),
        ]
        assert panel.get_available_actions(focused=True) == expected


# ===========================================================================
# ConfigFilesPanel.get_available_actions — unfocused update
# ===========================================================================


class TestConfigFilesPanelGetAvailableActionsUnfocused:
    """Test ConfigFilesPanel unfocused hints updated to new standardized pattern."""

    def test_unfocused_returns_focus_and_cycle(self) -> None:
        """R10-AC1: When focused=False, returns Ctrl+R focus and Shift+Tab cycle."""
        panel = ConfigFilesPanel()
        actions = panel.get_available_actions(focused=False)
        assert actions == [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

    def test_focused_hints_unchanged_level_0(self) -> None:
        """R10-AC2: Focused hints at level 0 remain unchanged."""
        panel = ConfigFilesPanel()
        actions = panel.get_available_actions(focused=True)
        # Level 0 with no files: navigate + filter (no Enter)
        assert ("j/k", "navigate") in actions
        assert ("/", "filter") in actions
