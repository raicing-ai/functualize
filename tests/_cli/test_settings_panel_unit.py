"""Unit tests for SettingsPanel.

Tests the widget's internal logic: initial state, messages,
validation, available actions, update_setting API, and the
SmartBar-based INSERT mode flow (InsertRequested messages).

The panel rows are the full func-settings catalog (``[tui]``, ``[cli]``,
``[discovery]``, and the top-level keys), addressed by dotted name.

Feature: TUI Architecture v2 (Phase 5–6); reworked by
tui-environment-and-settings (settings fold into the real func config).
"""

from __future__ import annotations

from functualize._cli.data.func_settings import FUNC_SETTINGS
from functualize._cli.tui.panels.config_table import FieldDef
from functualize._cli.tui.settings_panel import (
    _DEFAULT_VALUES,
    _SETTINGS_ORDER,
    SettingsPanel,
)


def _row_of(panel: SettingsPanel, name: str) -> int:
    return panel._settings.index(name)


def _field(panel: SettingsPanel, name: str) -> FieldDef:
    return next(f for f in panel._fields if f.name == name)


# ===========================================================================
# Tests: Initial state
# ===========================================================================


class TestInitialState:
    """Test the initial state of the settings panel."""

    def test_exposes_the_full_catalog(self):
        """One row per catalog entry — not just the 9 TUI settings.

        The Settings panel is for everything you can put in a functualize
        setting; showing only the TUI's own knobs was the old parallel-store
        world.
        """
        panel = SettingsPanel()
        assert panel._settings == [s.name for s in FUNC_SETTINGS]
        assert {"tui.theme", "cli.output", "discovery.scan_depth", "dotenv"} <= set(
            panel._settings
        )

    def test_default_override_target_schema_shrunk(self):
        """default_override_target has no "session" choice."""
        from functualize._cli.tui.settings_validator import SETTING_SCHEMAS

        schema = SETTING_SCHEMAS["default_override_target"]
        assert schema.choices == ["file", "env"]

    def test_default_override_target_default_is_file(self):
        """tui.default_override_target defaults to "file"."""
        assert _DEFAULT_VALUES["tui.default_override_target"] == "file"

    def test_default_values_populated(self):
        """Settings with defaults show them; the rest display empty."""
        panel = SettingsPanel()
        for name in _SETTINGS_ORDER:
            assert name in panel._values
            assert panel._values[name] == _DEFAULT_VALUES.get(name, "")

    def test_default_sources_are_default(self):
        """All settings initially show 'default' as source."""
        panel = SettingsPanel()
        for name in _SETTINGS_ORDER:
            assert panel._sources[name] == "default"


# ===========================================================================
# Tests: get_cursor_field API (replaces EditableTable delegation)
# ===========================================================================


class TestGetCursorField:
    """Test get_cursor_field returns FieldDef for the current cursor row."""

    def test_returns_none_before_mount(self):
        """Before mount (no fields built), returns None."""
        panel = SettingsPanel()
        # Fields are built on_mount; before that _fields is empty
        assert panel.get_cursor_field() is None

    def test_returns_field_def_after_build(self):
        """After building fields, returns a FieldDef at cursor row."""
        panel = SettingsPanel()
        panel._build_fields()
        field = panel.get_cursor_field()
        assert field is not None
        assert isinstance(field, FieldDef)
        assert field.name == _SETTINGS_ORDER[0]

    def test_cursor_row_navigation(self):
        """action_cursor_down advances cursor and returns next field."""
        panel = SettingsPanel()
        panel._build_fields()
        panel.action_cursor_down()
        field = panel.get_cursor_field()
        assert field is not None
        assert field.name == _SETTINGS_ORDER[1]

    def test_cursor_wraps_at_end(self):
        """Cursor wraps from last row to first."""
        panel = SettingsPanel()
        panel._build_fields()
        for _ in range(len(_SETTINGS_ORDER) - 1):
            panel.action_cursor_down()
        assert panel.get_cursor_field().name == _SETTINGS_ORDER[-1]  # type: ignore[union-attr]
        # One more should wrap
        panel.action_cursor_down()
        assert panel.get_cursor_field().name == _SETTINGS_ORDER[0]  # type: ignore[union-attr]


# ===========================================================================
# Tests: InsertRequested message (replaces EditableTable flow)
# ===========================================================================


class TestInsertRequested:
    """Test that action_enter_insert posts InsertRequested with correct FieldDef."""

    def test_insert_on_value_column_posts_message(self, monkeypatch):
        """Pressing 'i' on value column posts InsertRequested."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel._cursor_col = 1  # Value column
        panel.action_enter_insert()

        assert len(posted) == 1
        assert isinstance(posted[0], SettingsPanel.InsertRequested)
        assert posted[0].field_def.name == _SETTINGS_ORDER[0]

    def test_insert_on_name_column_jumps_to_value(self, monkeypatch):
        """Pressing 'i' on name column jumps to value column and posts INSERT."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel._cursor_col = 0  # Name column
        panel.action_enter_insert()

        assert panel._cursor_col == 1  # Jumped to value
        assert len(posted) == 1
        assert isinstance(posted[0], SettingsPanel.InsertRequested)

    def test_insert_on_source_column_noop(self, monkeypatch):
        """Pressing 'i' on source column is a no-op for settings."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel._cursor_col = 2  # Source column
        panel.action_enter_insert()

        assert len(posted) == 0

    def test_field_def_has_choices_for_enum(self):
        """Enum settings expose choices on FieldDef for autocomplete."""
        panel = SettingsPanel()
        panel._build_fields()
        assert _field(panel, "tui.default_surface").choices == ["panel", "stdout"]
        assert _field(panel, "cli.output").choices == ["rich", "plain", "json"]

    def test_field_def_has_choices_for_bool(self):
        """Bool settings expose ['true', 'false'] as choices."""
        panel = SettingsPanel()
        panel._build_fields()
        assert _field(panel, "tui.show_session_stamp").choices == ["true", "false"]
        assert _field(panel, "dotenv").choices == ["true", "false"]


# ===========================================================================
# Tests: apply_value_edit with validation (req 12.2, 12.7)
# ===========================================================================


class TestApplyValueEdit:
    """Test apply_value_edit validates and applies values."""

    def test_valid_enum_value_applies(self, monkeypatch):
        """Valid enum value updates internal state and posts SettingChanged."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        field = _field(panel, "tui.default_surface")
        panel.apply_value_edit(field, "stdout")

        assert panel._values["tui.default_surface"] == "stdout"
        assert panel._sources["tui.default_surface"] == "unsaved"
        assert field.value == "stdout"
        assert field.source == "unsaved"
        # SettingChanged posted
        assert len(posted) == 1
        assert isinstance(posted[0], SettingsPanel.SettingChanged)
        assert posted[0].setting_name == "tui.default_surface"
        assert posted[0].value == "stdout"

    def test_invalid_enum_value_rejected(self, monkeypatch):
        """Invalid enum value does NOT update state or post message."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.default_surface"), "invalid_mode")

        assert (
            panel._values["tui.default_surface"]
            == _DEFAULT_VALUES["tui.default_surface"]
        )
        assert len(posted) == 0

    def test_invalid_int_value_rejected(self, monkeypatch):
        """Non-integer for int field is rejected."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.history_retention"), "not_a_number")

        assert (
            panel._values["tui.history_retention"]
            == _DEFAULT_VALUES["tui.history_retention"]
        )
        assert len(posted) == 0

    def test_int_out_of_range_rejected(self, monkeypatch):
        """Int value outside range is rejected."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.history_retention"), "5000")

        assert (
            panel._values["tui.history_retention"]
            == _DEFAULT_VALUES["tui.history_retention"]
        )
        assert len(posted) == 0

    def test_invalid_bool_value_rejected(self, monkeypatch):
        """Invalid bool value is rejected."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.show_session_stamp"), "yes")

        assert (
            panel._values["tui.show_session_stamp"]
            == _DEFAULT_VALUES["tui.show_session_stamp"]
        )
        assert len(posted) == 0

    def test_valid_bool_value_applies(self, monkeypatch):
        """Valid bool value applies correctly."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.show_session_stamp"), "false")

        assert panel._values["tui.show_session_stamp"] == "false"
        assert panel._sources["tui.show_session_stamp"] == "unsaved"
        assert len(posted) == 1

    def test_valid_int_value_applies(self, monkeypatch):
        """Valid int within range applies correctly."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.history_retention"), "500")

        assert panel._values["tui.history_retention"] == "500"
        assert panel._sources["tui.history_retention"] == "unsaved"
        assert len(posted) == 1

    def test_func_setting_is_editable_too(self, monkeypatch):
        """The non-TUI settings validate through the same catalog."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "cli.output"), "json")
        assert panel._values["cli.output"] == "json"

        panel.apply_value_edit(_field(panel, "cli.output"), "sparkly")
        assert panel._values["cli.output"] == "json"  # rejected

        assert len(posted) == 1


# ===========================================================================
# Tests: get_available_actions for DynamicFooter
# ===========================================================================


class TestGetAvailableActions:
    """Test get_available_actions returns correct tuples per state."""

    def test_not_focused_returns_empty(self):
        """When not focused, returns empty list."""
        panel = SettingsPanel()
        actions = panel.get_available_actions(focused=False)
        assert actions == []

    def test_focused_returns_actions(self):
        """When focused, returns action tuples."""
        panel = SettingsPanel()
        actions = panel.get_available_actions(focused=True)
        keys = [a[0] for a in actions]
        assert "j/k" in keys
        assert "i" in keys
        assert "Esc" in keys


# ===========================================================================
# Tests: update_setting external API
# ===========================================================================


class TestUpdateSetting:
    """Test external update_setting API."""

    def test_update_changes_value_and_source(self):
        """update_setting modifies internal state."""
        panel = SettingsPanel()
        panel._build_fields()
        panel.update_setting("tui.theme", "dark", "global config")
        assert panel._values["tui.theme"] == "dark"
        assert panel._sources["tui.theme"] == "global config"
        # Also updates the FieldDef
        theme_field = _field(panel, "tui.theme")
        assert theme_field.value == "dark"
        assert theme_field.source == "global config"

    def test_update_unknown_setting_is_ignored(self):
        """Unknown setting name is safely ignored."""
        panel = SettingsPanel()
        panel.update_setting("unknown_setting", "value", "source")
        assert "unknown_setting" not in panel._values


# ===========================================================================
# Tests: SettingChanged message structure
# ===========================================================================


class TestSettingChangedMessage:
    """Test the SettingChanged message carries correct data."""

    def test_message_carries_setting_name_value_target(self, monkeypatch):
        """SettingChanged carries setting_name, value, and target."""
        panel = SettingsPanel()
        panel._build_fields()
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(_field(panel, "tui.theme"), "dark")

        assert len(posted) == 1
        msg = posted[0]
        assert msg.setting_name == "tui.theme"
        assert msg.value == "dark"
        assert msg.target.type == "unsaved"
        assert "unsaved" in msg.target.label.lower()
