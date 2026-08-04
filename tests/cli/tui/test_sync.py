"""Unit tests for SmartBar ↔ Config Table sync logic."""

from __future__ import annotations

from functualize._cli.tui.panels.config_table import EditOrigin, FieldDef
from functualize._cli.tui.sync import sync_overrides_to_bar


def _make_field(
    name: str,
    value: str,
    source: str = "default",
    edit_origin: EditOrigin = EditOrigin.NONE,
) -> FieldDef:
    """Helper to create a FieldDef with minimal required fields."""
    return FieldDef(
        name=name,
        value=value,
        source=source,
        edit_origin=edit_origin,
        original_value=value,
        original_source=source,
    )


class TestSyncOverridesToBar:
    """Tests for sync_overrides_to_bar format logic."""

    def test_single_override(self) -> None:
        """Single override produces 'job --field value'."""
        fields = [
            _make_field("region", "eu-west-1", edit_origin=EditOrigin.VALUE),
        ]
        result = sync_overrides_to_bar("deploy", fields)
        assert result == "deploy --region eu-west-1"

    def test_multiple_overrides(self) -> None:
        """Multiple overrides are included in field list order."""
        fields = [
            _make_field("region", "eu-west-1", edit_origin=EditOrigin.VALUE),
            _make_field("replicas", "5", edit_origin=EditOrigin.VALUE),
        ]
        result = sync_overrides_to_bar("deploy", fields)
        assert result == "deploy --region eu-west-1 --replicas 5"

    def test_value_with_spaces_is_quoted(self) -> None:
        """Values containing spaces are enclosed in double quotes."""
        fields = [
            _make_field("name", "my service", edit_origin=EditOrigin.VALUE),
        ]
        result = sync_overrides_to_bar("deploy", fields)
        assert result == 'deploy --name "my service"'

    def test_value_with_tab_is_quoted(self) -> None:
        """Values containing tabs are enclosed in double quotes."""
        fields = [
            _make_field("desc", "col1\tcol2", edit_origin=EditOrigin.SOURCE),
        ]
        result = sync_overrides_to_bar("run", fields)
        assert result == 'run --desc "col1\tcol2"'

    def test_no_overrides_returns_job_name_only(self) -> None:
        """When all fields have edit_origin NONE, only job name is returned."""
        fields = [
            _make_field("region", "us-east-1"),
            _make_field("replicas", "3"),
        ]
        result = sync_overrides_to_bar("deploy", fields)
        assert result == "deploy"

    def test_field_order_matches_list_position(self) -> None:
        """Override fields appear in list order, skipping NONE fields."""
        fields = [
            _make_field("alpha", "a", edit_origin=EditOrigin.VALUE),
            _make_field("beta", "b"),  # NONE — skipped
            _make_field("gamma", "c", edit_origin=EditOrigin.SOURCE),
            _make_field("delta", "d", edit_origin=EditOrigin.VALUE),
        ]
        result = sync_overrides_to_bar("job", fields)
        assert result == "job --alpha a --gamma c --delta d"

    def test_empty_field_list(self) -> None:
        """Empty field list returns only the job name."""
        result = sync_overrides_to_bar("deploy", [])
        assert result == "deploy"

    def test_source_edit_origin_included(self) -> None:
        """Fields with SOURCE edit_origin are included (not just VALUE)."""
        fields = [
            _make_field("env", "production", edit_origin=EditOrigin.SOURCE),
        ]
        result = sync_overrides_to_bar("deploy", fields)
        assert result == "deploy --env production"
