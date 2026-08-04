"""Unit tests for ConfigTablePanel.apply_filter row filtering.

Rows are displayed with the hyphenated CLI-flag name (``dry-run``) while the
underlying field name is underscored (``dry_run``), so the filter must treat
``-`` and ``_`` as equivalent — a user typing either spelling matches the row.
Regression guard tied to the pre-flight / config-table name-spelling fix.
"""

from __future__ import annotations

from types import SimpleNamespace

from functualize._cli.tui.panels.config_table import ConfigTablePanel


def _panel() -> ConfigTablePanel:
    """Build an unmounted panel with two fields and a no-op table reload."""
    panel = ConfigTablePanel.__new__(ConfigTablePanel)
    panel._table = None
    panel._cursor_row = 0
    panel._row_count = 0
    panel._active_filter_text = ""
    panel._fields = [  # type: ignore[list-item]
        SimpleNamespace(name="dry_run"),
        SimpleNamespace(name="image"),
    ]
    # _reload_table drives a mounted DataTable; there is none here.
    panel._reload_table = lambda: None  # type: ignore[method-assign]
    return panel


class TestFilterHyphenUnderscoreEquivalence:
    def test_hyphen_query_matches_underscore_field(self) -> None:
        panel = _panel()
        panel.apply_filter("dry-run")
        assert [f.name for f in panel._filtered_fields] == ["dry_run"]

    def test_underscore_query_still_matches(self) -> None:
        panel = _panel()
        panel.apply_filter("dry_run")
        assert [f.name for f in panel._filtered_fields] == ["dry_run"]

    def test_partial_query_matches(self) -> None:
        panel = _panel()
        panel.apply_filter("dry")
        assert [f.name for f in panel._filtered_fields] == ["dry_run"]

    def test_empty_query_shows_all(self) -> None:
        panel = _panel()
        panel.apply_filter("")
        assert [f.name for f in panel._filtered_fields] == ["dry_run", "image"]
