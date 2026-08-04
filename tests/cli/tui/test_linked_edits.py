"""Unit tests for ConfigTablePanel linked edits (Task 5.5).

Tests apply_value_edit, apply_source_edit, action_reset_override,
and visual markers based on EditOrigin.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8
"""

from __future__ import annotations

from functualize._cli.tui.panels.config_table import (
    ChainEntry,
    ConfigTablePanel,
    EditOrigin,
    FieldDef,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_panel_with_field(field: FieldDef) -> ConfigTablePanel:
    """Create a ConfigTablePanel with one field, bypassing Textual mount."""
    panel = ConfigTablePanel.__new__(ConfigTablePanel)
    panel._fields = [field]
    panel._row_count = 1
    panel._cursor_row = 0
    panel._cursor_col = 1
    panel._table = None  # No mounted DataTable
    return panel


def _make_field(
    name: str = "port",
    value: str = "8080",
    source: str = "file",
    chain: list[ChainEntry] | None = None,
) -> FieldDef:
    """Create a FieldDef with sensible defaults."""
    return FieldDef(
        name=name,
        value=value,
        source=source,
        chain=chain or [],
        original_value=value,
        original_source=source,
    )


# ===========================================================================
# Tests: apply_value_edit
# ===========================================================================


class TestApplyValueEdit:
    """Req 5.1: Value edit sets value, source='cli', edit_origin=VALUE."""

    def test_sets_value(self, monkeypatch):
        """apply_value_edit sets field.value to new_value."""
        field = _make_field()
        panel = _make_panel_with_field(field)
        monkeypatch.setattr(panel, "post_message", lambda msg: None)

        panel.apply_value_edit(field, "9090")

        assert field.value == "9090"

    def test_sets_source_to_cli(self, monkeypatch):
        """apply_value_edit sets field.source to 'cli'."""
        field = _make_field(source="env")
        panel = _make_panel_with_field(field)
        monkeypatch.setattr(panel, "post_message", lambda msg: None)

        panel.apply_value_edit(field, "9090")

        assert field.source == "cli"

    def test_sets_edit_origin_to_value(self, monkeypatch):
        """apply_value_edit sets field.edit_origin to VALUE."""
        field = _make_field()
        panel = _make_panel_with_field(field)
        monkeypatch.setattr(panel, "post_message", lambda msg: None)

        panel.apply_value_edit(field, "9090")

        assert field.edit_origin == EditOrigin.VALUE

    def test_posts_value_edited_message(self, monkeypatch):
        """apply_value_edit posts a ValueEdited message with old value."""
        field = _make_field(value="8080")
        panel = _make_panel_with_field(field)
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_value_edit(field, "9090")

        assert len(posted) == 1
        msg = posted[0]
        assert isinstance(msg, ConfigTablePanel.ValueEdited)
        assert msg.field_def is field
        assert msg.old_value == "8080"


# ===========================================================================
# Tests: apply_source_edit
# ===========================================================================


class TestApplySourceEdit:
    """Req 5.2, 5.8: Source edit with chain value sets source/value/origin."""

    def test_sets_source_and_value_from_chain(self, monkeypatch):
        """apply_source_edit sets source and pulls value from chain."""
        field = _make_field(
            value="8080",
            source="file",
            chain=[
                ChainEntry(source="env", value="3000"),
                ChainEntry(source="file", value="8080"),
            ],
        )
        panel = _make_panel_with_field(field)
        monkeypatch.setattr(panel, "post_message", lambda msg: None)

        panel.apply_source_edit(field, "env")

        assert field.source == "env"
        assert field.value == "3000"

    def test_sets_edit_origin_to_source(self, monkeypatch):
        """apply_source_edit sets edit_origin to SOURCE."""
        field = _make_field(
            chain=[ChainEntry(source="env", value="3000")],
        )
        panel = _make_panel_with_field(field)
        monkeypatch.setattr(panel, "post_message", lambda msg: None)

        panel.apply_source_edit(field, "env")

        assert field.edit_origin == EditOrigin.SOURCE

    def test_posts_source_changed_message(self, monkeypatch):
        """apply_source_edit posts a SourceChanged message."""
        field = _make_field(
            source="file",
            chain=[ChainEntry(source="env", value="3000")],
        )
        panel = _make_panel_with_field(field)
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_source_edit(field, "env")

        assert len(posted) == 1
        msg = posted[0]
        assert isinstance(msg, ConfigTablePanel.SourceChanged)
        assert msg.field_def is field
        assert msg.old_source == "file"

    def test_guard_empty_chain_value_no_op(self, monkeypatch):
        """Req 5.8: Source edit with empty chain value → no change."""
        field = _make_field(
            value="8080",
            source="file",
            chain=[ChainEntry(source="env", value="")],  # empty value
        )
        panel = _make_panel_with_field(field)
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_source_edit(field, "env")

        # Field unchanged
        assert field.value == "8080"
        assert field.source == "file"
        assert field.edit_origin == EditOrigin.NONE
        # No message posted
        assert len(posted) == 0

    def test_guard_unknown_source_no_op(self, monkeypatch):
        """Source not in chain → no change."""
        field = _make_field(
            value="8080",
            source="file",
            chain=[ChainEntry(source="env", value="3000")],
        )
        panel = _make_panel_with_field(field)
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.apply_source_edit(field, "nonexistent")

        assert field.value == "8080"
        assert field.source == "file"
        assert len(posted) == 0


# ===========================================================================
# Tests: action_reset_override
# ===========================================================================


class TestActionResetOverride:
    """Req 5.6, 5.7: Reset restores originals; no-op on NONE."""

    def test_reset_restores_original_values(self, monkeypatch):
        """Req 5.6: Reset restores original value and source."""
        field = _make_field(value="8080", source="file")
        # Simulate a prior value edit
        field.value = "9090"
        field.source = "cli"
        field.edit_origin = EditOrigin.VALUE

        panel = _make_panel_with_field(field)
        monkeypatch.setattr(panel, "post_message", lambda msg: None)

        panel.action_reset_override()

        assert field.value == "8080"
        assert field.source == "file"
        assert field.edit_origin == EditOrigin.NONE

    def test_reset_posts_override_reset_message(self, monkeypatch):
        """Reset posts an OverrideReset message."""
        field = _make_field()
        field.edit_origin = EditOrigin.VALUE
        field.value = "changed"
        field.source = "cli"

        panel = _make_panel_with_field(field)
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.action_reset_override()

        assert len(posted) == 1
        assert isinstance(posted[0], ConfigTablePanel.OverrideReset)
        assert posted[0].field_def is field

    def test_reset_noop_on_none(self, monkeypatch):
        """Req 5.7: Reset on edit_origin NONE → no-op."""
        field = _make_field()
        assert field.edit_origin == EditOrigin.NONE

        panel = _make_panel_with_field(field)
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.action_reset_override()

        # No message, no change
        assert len(posted) == 0
        assert field.value == "8080"
        assert field.source == "file"

    def test_reset_noop_on_empty_fields(self, monkeypatch):
        """Reset with no fields → no-op."""
        panel = ConfigTablePanel.__new__(ConfigTablePanel)
        panel._fields = []
        panel._row_count = 0
        panel._cursor_row = 0
        panel._cursor_col = 1
        panel._table = None
        posted: list = []
        monkeypatch.setattr(panel, "post_message", lambda msg: posted.append(msg))

        panel.action_reset_override()

        assert len(posted) == 0


# ===========================================================================
# Tests: Visual markers (_format_field_cells)
# ===========================================================================


class TestVisualMarkers:
    """Req 5.3, 5.4, 5.5: Visual markers based on edit_origin."""

    def test_value_origin_markers(self):
        """Req 5.3: edit_origin VALUE — value and source are plain (markers handled at render layer)."""
        field = _make_field(value="9090", source="cli")
        field.edit_origin = EditOrigin.VALUE

        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field
        )

        assert value_display == "9090"
        assert source_display == "cli"

    def test_source_origin_markers(self):
        """Req 5.4: edit_origin SOURCE — value and source are plain (markers handled at render layer)."""
        field = _make_field(value="3000", source="env")
        field.edit_origin = EditOrigin.SOURCE

        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field
        )

        assert value_display == "3000"
        assert source_display == "env"

    def test_none_origin_no_markers(self):
        """Req 5.5: edit_origin NONE → plain value and source."""
        field = _make_field(value="8080", source="file")
        field.edit_origin = EditOrigin.NONE

        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field
        )

        assert value_display == "8080"
        assert source_display == "file"
