"""Unit tests for DiffViewWidget (DataTable-based redesign).

Tests the widget's rendering logic: color-coded diff entries (top section),
DataTable session history (bottom section), action methods for navigation,
LoadSessionRequested/BackRequested message posting, and footer actions.

Feature: TUI Config Inspector — Diff View Redesign
"""

from __future__ import annotations

import time
from typing import Any

from functualize._cli.data.config_snapshot_store import ConfigSnapshot
from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.tui.diff_view_widget import DiffViewWidget
from functualize._config.chain import ResolvedValue

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _resolved(value: Any, source_type: str = "file") -> ResolvedValue:
    """Create a ResolvedValue for testing."""
    return ResolvedValue(
        value=value,
        source_type=source_type,
        source_id="test",
        key="test_key",
        alternatives=[],
    )


def _pending(
    fields: dict[str, Any], overrides: dict[str, Any] | None = None
) -> PendingExecution:
    """Create a PendingExecution with given fields."""
    resolved = {name: _resolved(val) for name, val in fields.items()}
    return PendingExecution(
        job_name="test_job",
        resolved_values=resolved,
        overrides=overrides or {},
    )


def _snapshot(
    values: dict[str, Any],
    outcome: str = "success",
    timestamp: float | None = None,
) -> ConfigSnapshot:
    """Create a ConfigSnapshot for testing."""
    return ConfigSnapshot(
        job_name="test_job",
        timestamp=timestamp or time.time(),
        values=values,
        outcome=outcome,
    )


class FakeStatic:
    """Fake Static widget that captures update() calls."""

    def __init__(self) -> None:
        self.content: str = ""

    def update(self, content: str) -> None:
        self.content = content


class FakeDataTable:
    """Fake DataTable for testing action methods without Textual runtime."""

    def __init__(self) -> None:
        self.cursor_row: int = 0
        self.cursor_column: int = 0
        self._rows: list[list[str]] = []
        self._columns: list[str] = []
        self._cleared: bool = False

    @property
    def row_count(self) -> int:
        return len(self._rows)

    def clear(self, columns: bool = False) -> None:
        self._rows = []
        self._cleared = True
        if columns:
            self._columns = []

    def add_column(self, label: str, *, key: str | None = None) -> None:
        self._columns.append(key or label)

    def add_row(self, *cells: str, **kwargs: Any) -> None:
        self._rows.append(list(cells))

    def move_cursor(self, *, row: int | None = None, column: int | None = None) -> None:
        if row is not None:
            self.cursor_row = row
        if column is not None:
            self.cursor_column = column

    def action_cursor_down(self) -> None:
        if self._rows and self.cursor_row < len(self._rows) - 1:
            self.cursor_row += 1

    def action_cursor_up(self) -> None:
        if self.cursor_row > 0:
            self.cursor_row -= 1

    def action_cursor_right(self) -> None:
        if self._columns and self.cursor_column < len(self._columns) - 1:
            self.cursor_column += 1

    def action_cursor_left(self) -> None:
        if self.cursor_column > 0:
            self.cursor_column -= 1

    def _scroll_cursor_into_view(self, animate: bool = True) -> None:
        pass  # No-op in tests


def _widget_with_fake_table(
    history: list[ConfigSnapshot] | None = None,
    pending: PendingExecution | None = None,
    previous: ConfigSnapshot | None = None,
) -> tuple[DiffViewWidget, FakeDataTable, FakeStatic, FakeStatic]:
    """Create a DiffViewWidget with a fake DataTable and Statics for unit testing.

    Returns (widget, fake_table, entries_static, no_prev_static).
    """
    widget = DiffViewWidget()
    fake_table = FakeDataTable()
    entries_static = FakeStatic()
    no_prev_static = FakeStatic()
    history_title_static = FakeStatic()

    # Inject fake table
    widget._table = fake_table  # type: ignore[assignment]

    # Monkeypatch query_one for the Static widgets
    def fake_query_one(selector: str, cls: Any = None) -> Any:
        mapping: dict[str, Any] = {
            "#dv-entries": entries_static,
            "#dv-no-previous": no_prev_static,
            "#dv-history-title": history_title_static,
            "#dv-history-table": fake_table,
        }
        return mapping.get(selector, FakeStatic())

    widget.query_one = fake_query_one  # type: ignore[assignment]

    # Populate if data provided
    if history is not None:
        p = pending or _pending({"env": "staging"})
        widget.show_diff(p, previous, history)

    return widget, fake_table, entries_static, no_prev_static


# ===========================================================================
# Unit Tests: Diff entries color-coding (top section — unchanged behavior)
# ===========================================================================


class TestDiffViewShowDiffColorCoding:
    """Test show_diff renders diff entries with correct Rich color markup."""

    def test_changed_field_rendered_in_yellow(self):
        """Changed field uses [yellow] markup with ~ prefix."""
        pending = _pending({"env": "production"})
        previous = _snapshot({"env": "staging"})
        widget, _, entries_static, _ = _widget_with_fake_table(
            history=[], pending=pending, previous=previous
        )

        assert "[yellow]" in entries_static.content
        assert "~" in entries_static.content
        assert "staging" in entries_static.content
        assert "production" in entries_static.content

    def test_unchanged_field_rendered_in_dim(self):
        """Unchanged field uses [dim] markup."""
        pending = _pending({"env": "staging"})
        previous = _snapshot({"env": "staging"})
        widget, _, entries_static, _ = _widget_with_fake_table(
            history=[], pending=pending, previous=previous
        )

        assert "[dim]" in entries_static.content
        assert "[yellow]" not in entries_static.content
        assert "[green]" not in entries_static.content
        assert "[red]" not in entries_static.content

    def test_new_field_rendered_in_green(self):
        """New field uses [green] markup with + prefix."""
        pending = _pending({"env": "staging", "new_field": "value"})
        previous = _snapshot({"env": "staging"})
        widget, _, entries_static, _ = _widget_with_fake_table(
            history=[], pending=pending, previous=previous
        )

        assert "[green]" in entries_static.content
        assert "+" in entries_static.content
        assert "new_field" in entries_static.content

    def test_removed_field_rendered_in_red(self):
        """Removed field uses [red] markup with - prefix."""
        pending = _pending({"env": "staging"})
        previous = _snapshot({"env": "staging", "old_field": "gone"})
        widget, _, entries_static, _ = _widget_with_fake_table(
            history=[], pending=pending, previous=previous
        )

        assert "[red]" in entries_static.content
        assert "-" in entries_static.content
        assert "old_field" in entries_static.content


# ===========================================================================
# Unit Tests: "No previous sessions" message
# ===========================================================================


class TestDiffViewNoPreviousSessions:
    """Test 'No previous sessions' message when previous is None."""

    def test_no_previous_shows_message(self):
        """When previous is None, shows informational message."""
        _, _, _, no_prev_static = _widget_with_fake_table(
            history=[], pending=_pending({"env": "staging"}), previous=None
        )
        assert "No previous sessions" in no_prev_static.content

    def test_with_previous_no_message(self):
        """When previous is provided, no 'No previous sessions' message."""
        previous = _snapshot({"env": "staging"})
        _, _, _, no_prev_static = _widget_with_fake_table(
            history=[], pending=_pending({"env": "staging"}), previous=previous
        )
        assert no_prev_static.content == ""


# ===========================================================================
# Unit Tests: DataTable population with correct columns and rows
# ===========================================================================


class TestDiffViewDataTablePopulation:
    """Test DataTable is populated with correct columns and rows."""

    def test_table_has_correct_columns(self):
        """DataTable columns: When, Result, + one per field key."""
        history = [
            _snapshot({"city": "Tokyo", "days": "3"}, timestamp=1705325400.0),
        ]
        _, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert fake_table._columns == ["when", "result", "city", "days"]

    def test_table_has_correct_row_data(self):
        """Rows contain formatted timestamp, outcome icon, and field values."""
        import datetime

        ts = 1705325400.0
        history = [_snapshot({"city": "Tokyo", "days": "3"}, timestamp=ts)]
        _, fake_table, _, _ = _widget_with_fake_table(history=history)

        expected_ts = datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).strftime(
            "%Y-%m-%d %H:%M"
        )
        assert len(fake_table._rows) == 1
        row = fake_table._rows[0]
        assert row[0] == expected_ts
        assert row[1] == "✓"
        assert row[2] == "Tokyo"
        assert row[3] == "3"

    def test_failure_outcome_shows_cross(self):
        """Failure outcome shows ✗ in Result column."""
        history = [
            _snapshot({"city": "Tokyo"}, outcome="failure", timestamp=1705325400.0)
        ]
        _, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert fake_table._rows[0][1] == "✗"

    def test_multiple_rows_most_recent_first(self):
        """Multiple snapshots populate as multiple rows, maintaining order from store."""
        snap1 = _snapshot({"env": "prod"}, timestamp=1705325400.0)
        snap2 = _snapshot({"env": "staging"}, timestamp=1705325460.0)
        _, fake_table, _, _ = _widget_with_fake_table(history=[snap1, snap2])

        assert len(fake_table._rows) == 2
        # Order matches input (store returns reverse-chronological)
        assert fake_table._rows[0][2] == "prod"
        assert fake_table._rows[1][2] == "staging"

    def test_history_capped_at_10(self):
        """History is capped at 10 rows."""
        history = [
            _snapshot({"env": f"val_{i}"}, timestamp=1705325400.0 + i * 60)
            for i in range(15)
        ]
        _, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert len(fake_table._rows) == 10

    def test_empty_history_no_rows(self):
        """Empty history results in no rows and informational title."""
        widget, fake_table, _, _ = _widget_with_fake_table(history=[])

        assert len(fake_table._rows) == 0
        assert widget._row_count == 0

    def test_union_of_field_keys_across_snapshots(self):
        """Columns are the union of all field keys across all snapshots."""
        snap1 = _snapshot({"city": "Tokyo", "days": "3"}, timestamp=1705325400.0)
        snap2 = _snapshot(
            {"city": "Paris", "api_url": "http://x"}, timestamp=1705325460.0
        )
        _, fake_table, _, _ = _widget_with_fake_table(history=[snap1, snap2])

        # Columns: when, result, city, days, api_url
        assert "city" in fake_table._columns
        assert "days" in fake_table._columns
        assert "api_url" in fake_table._columns

    def test_missing_field_values_show_dash(self):
        """Missing field values in a snapshot show '—' in the cell."""
        snap1 = _snapshot({"city": "Tokyo", "days": "3"}, timestamp=1705325400.0)
        snap2 = _snapshot({"city": "Paris"}, timestamp=1705325460.0)
        _, fake_table, _, _ = _widget_with_fake_table(history=[snap1, snap2])

        # snap2 doesn't have "days" — should show "—"
        # Columns are: when, result, city, days
        row2 = fake_table._rows[1]
        days_col_idx = fake_table._columns.index("days")
        assert row2[days_col_idx] == "—"


# ===========================================================================
# Unit Tests: action_cursor_down/up — row navigation with wrapping
# ===========================================================================


class TestDiffViewRowNavigation:
    """Test j/k (action_cursor_down/up) row navigation."""

    def test_cursor_down_moves_row(self):
        """action_cursor_down moves to next row."""
        history = [
            _snapshot({"env": "a"}, timestamp=1705325400.0),
            _snapshot({"env": "b"}, timestamp=1705325460.0),
            _snapshot({"env": "c"}, timestamp=1705325520.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert fake_table.cursor_row == 0
        widget.action_cursor_down()
        assert fake_table.cursor_row == 1

    def test_cursor_down_wraps_at_end(self):
        """action_cursor_down wraps from last row to first."""
        history = [
            _snapshot({"env": "a"}, timestamp=1705325400.0),
            _snapshot({"env": "b"}, timestamp=1705325460.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        fake_table.cursor_row = 1
        widget.action_cursor_down()
        assert fake_table.cursor_row == 0

    def test_cursor_up_moves_row(self):
        """action_cursor_up moves to previous row."""
        history = [
            _snapshot({"env": "a"}, timestamp=1705325400.0),
            _snapshot({"env": "b"}, timestamp=1705325460.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        fake_table.cursor_row = 1
        widget.action_cursor_up()
        assert fake_table.cursor_row == 0

    def test_cursor_up_wraps_at_start(self):
        """action_cursor_up wraps from first row to last."""
        history = [
            _snapshot({"env": "a"}, timestamp=1705325400.0),
            _snapshot({"env": "b"}, timestamp=1705325460.0),
            _snapshot({"env": "c"}, timestamp=1705325520.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert fake_table.cursor_row == 0
        widget.action_cursor_up()
        assert fake_table.cursor_row == 2

    def test_no_op_with_empty_history(self):
        """Navigation does nothing with empty history."""
        widget, fake_table, _, _ = _widget_with_fake_table(history=[])

        widget.action_cursor_down()
        assert fake_table.cursor_row == 0
        widget.action_cursor_up()
        assert fake_table.cursor_row == 0


# ===========================================================================
# Unit Tests: action_cursor_left/right — column navigation (no wrap)
# ===========================================================================


class TestDiffViewColumnNavigation:
    """Test h/l (action_cursor_left/right) column navigation."""

    def test_cursor_right_moves_column(self):
        """action_cursor_right moves to next column."""
        history = [
            _snapshot({"city": "Tokyo", "days": "3"}, timestamp=1705325400.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert fake_table.cursor_column == 0
        widget.action_cursor_right()
        assert fake_table.cursor_column == 1

    def test_cursor_right_stops_at_last_column(self):
        """action_cursor_right does not wrap — stops at last column."""
        history = [
            _snapshot({"city": "Tokyo"}, timestamp=1705325400.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)
        # Columns: when, result, city → 3 columns, last index = 2
        fake_table.cursor_column = 2
        widget.action_cursor_right()
        assert fake_table.cursor_column == 2  # No change

    def test_cursor_left_moves_column(self):
        """action_cursor_left moves to previous column."""
        history = [
            _snapshot({"city": "Tokyo"}, timestamp=1705325400.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        fake_table.cursor_column = 2
        widget.action_cursor_left()
        assert fake_table.cursor_column == 1

    def test_cursor_left_stops_at_first_column(self):
        """action_cursor_left does not wrap — stops at first column."""
        history = [
            _snapshot({"city": "Tokyo"}, timestamp=1705325400.0),
        ]
        widget, fake_table, _, _ = _widget_with_fake_table(history=history)

        assert fake_table.cursor_column == 0
        widget.action_cursor_left()
        assert fake_table.cursor_column == 0  # No change


# ===========================================================================
# Unit Tests: action_drill_down posts LoadSessionRequested
# ===========================================================================


class TestDiffViewDrillDown:
    """Test Enter (action_drill_down) posts LoadSessionRequested."""

    def test_enter_posts_load_session_requested(self):
        """action_drill_down posts LoadSessionRequested with correct snapshot."""
        ts = 1705325400.0
        snap = _snapshot({"env": "staging"}, outcome="success", timestamp=ts)
        widget, fake_table, _, _ = _widget_with_fake_table(history=[snap])

        posted: list[Any] = []
        widget.post_message = lambda msg: posted.append(msg)  # type: ignore[assignment]

        widget.action_drill_down()

        assert len(posted) == 1
        msg = posted[0]
        assert isinstance(msg, DiffViewWidget.LoadSessionRequested)
        assert msg.snapshot.timestamp == ts
        assert msg.snapshot.values == {"env": "staging"}

    def test_enter_on_second_row(self):
        """Navigating to row 1 and pressing Enter loads second snapshot."""
        snap1 = _snapshot({"env": "prod"}, timestamp=1705325400.0)
        snap2 = _snapshot({"env": "staging"}, timestamp=1705325460.0)
        widget, fake_table, _, _ = _widget_with_fake_table(history=[snap1, snap2])

        posted: list[Any] = []
        widget.post_message = lambda msg: posted.append(msg)  # type: ignore[assignment]

        # Move to row 1
        widget.action_cursor_down()
        widget.action_drill_down()

        assert len(posted) == 1
        msg = posted[0]
        assert isinstance(msg, DiffViewWidget.LoadSessionRequested)
        assert msg.snapshot.values == {"env": "staging"}

    def test_enter_no_op_empty_history(self):
        """action_drill_down does nothing with empty history."""
        widget, _, _, _ = _widget_with_fake_table(history=[])

        posted: list[Any] = []
        widget.post_message = lambda msg: posted.append(msg)  # type: ignore[assignment]

        widget.action_drill_down()

        assert len(posted) == 0


# ===========================================================================
# Unit Tests: action_exit_panel posts BackRequested
# ===========================================================================


class TestDiffViewExitPanel:
    """Test Esc (action_exit_panel) posts BackRequested."""

    def test_escape_posts_back_requested(self):
        """action_exit_panel posts BackRequested message."""
        widget = DiffViewWidget()

        posted: list[Any] = []
        widget.post_message = lambda msg: posted.append(msg)  # type: ignore[assignment]

        widget.action_exit_panel()

        assert len(posted) == 1
        assert isinstance(posted[0], DiffViewWidget.BackRequested)


# ===========================================================================
# Unit Tests: get_available_actions for footer
# ===========================================================================


class TestDiffViewFooterActions:
    """Test get_available_actions returns correct footer hints."""

    def test_focused_with_history(self):
        """Focused with history shows navigate, scroll, load, back."""
        history = [
            _snapshot(
                {"city": "Tokyo", "days": "3", "api": "x"}, timestamp=1705325400.0
            ),
        ]
        widget, _, _, _ = _widget_with_fake_table(history=history)

        actions = widget.get_available_actions(focused=True)

        keys = [k for k, _ in actions]
        assert "j/k" in keys
        assert "h/l" in keys
        assert "Enter" in keys
        assert "Esc" in keys

    def test_focused_no_history(self):
        """Focused with no history shows only back."""
        widget, _, _, _ = _widget_with_fake_table(history=[])

        actions = widget.get_available_actions(focused=True)

        keys = [k for k, _ in actions]
        assert "j/k" not in keys
        assert "Esc" in keys

    def test_unfocused(self):
        """Unfocused shows Ctrl+R and Shift+Tab hints."""
        widget, _, _, _ = _widget_with_fake_table(history=[])

        actions = widget.get_available_actions(focused=False)

        keys = [k for k, _ in actions]
        assert "Ctrl+R" in keys
        assert "Shift+Tab" in keys

    def test_scroll_hint_only_with_multiple_columns(self):
        """h/l hint only shown when there are more than 2 columns (When + Result)."""
        # Only 1 field → 3 columns total (When, Result, field) → show h/l
        history = [
            _snapshot({"city": "Tokyo", "days": "3", "x": "1"}, timestamp=1705325400.0)
        ]
        widget, _, _, _ = _widget_with_fake_table(history=history)

        actions = widget.get_available_actions(focused=True)
        keys = [k for k, _ in actions]
        assert "h/l" in keys


# ===========================================================================
# Unit Tests: Deferred population pattern
# ===========================================================================


class TestDiffViewDeferredPopulation:
    """Test deferred population pattern works correctly."""

    def test_show_diff_before_table_exists(self):
        """show_diff before table is set doesn't crash."""
        widget = DiffViewWidget()
        # _table is None before compose
        widget._table = None

        pending = _pending({"env": "staging"})
        history = [_snapshot({"env": "staging"}, timestamp=1705325400.0)]

        # Should not raise
        widget.show_diff(pending, None, history)

        # Data is stored for later population
        assert widget._history == history
        assert widget._populated is False

    def test_on_mount_populates_after_show_diff(self):
        """on_mount populates table if show_diff was called pre-mount."""
        widget = DiffViewWidget()
        fake_table = FakeDataTable()

        # Simulate pre-mount: no table yet
        widget._table = None
        pending = _pending({"env": "staging"})
        history = [_snapshot({"env": "staging"}, timestamp=1705325400.0)]
        widget.show_diff(pending, None, history)

        # Now simulate mount: inject table and call on_mount
        widget._table = fake_table  # type: ignore[assignment]
        widget._populated = False
        widget._populate_table()

        assert len(fake_table._rows) == 1
        assert widget._populated is True


# ===========================================================================
# Unit Tests: No on_key method
# ===========================================================================


class TestDiffViewNoOnKey:
    """Test that DiffViewWidget does NOT have a custom on_key method."""

    def test_no_on_key_method(self):
        """Widget does not define on_key — all dispatch via action_* methods."""
        # Check that on_key is not defined directly on DiffViewWidget
        assert "on_key" not in DiffViewWidget.__dict__
