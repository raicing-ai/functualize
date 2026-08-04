"""Integration tests for cross-panel state synchronization.

Verifies that:
1. Edit applied → overrides[...] written directly + _refresh_all_views called
2. Reset override → PendingExecution.clear_override called + _refresh_all_views called
3. Snapshot load from DiffView → overrides applied + all views refreshed
4. FileSaved → PendingExecution rebuilt + all views refreshed
5. PanelHost activated → preflight hidden
6. PanelHost collapsed → preflight shown

Requirements: R1-AC4, R1-AC5, R8-AC1, R8-AC2, R8-AC3, R8-AC4, R8-AC5, R8-AC6
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.data.resolved_value_compat import ResolvedValueCompat
from functualize._cli.tui.app import FunctualizeInlineTUI

# =============================================================================
# Helpers
# =============================================================================


def _make_field_descriptor(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    positional: bool = False,
    short_flag: str | None = None,
    type_annotation: str = "str",
    description: str = "",
    choices: list[str] | None = None,
) -> SimpleNamespace:
    """Create a mock field descriptor."""
    return SimpleNamespace(
        name=name,
        required=required,
        default=default,
        positional=positional,
        short_flag=short_flag,
        type_annotation=type_annotation,
        description=description,
        choices=choices,
    )


def _make_job_descriptor(name: str, fields: list[SimpleNamespace]) -> SimpleNamespace:
    """Create a mock JobDescriptor with given fields."""
    return SimpleNamespace(
        name=name,
        config_fields=fields,
        parameters=fields,
        docstring="Test job",
        group=None,
        source_path=None,
    )


def _make_func_app(jobs: list[SimpleNamespace]) -> MagicMock:
    """Create a mock FunctualizeApp with given job descriptors."""
    app = MagicMock()
    app.name = "test-app"
    app.get_jobs.return_value = jobs
    app.get_job.side_effect = lambda name: next(
        (j for j in jobs if j.name == name), None
    )
    return app


def _make_pending(
    job_name: str = "serve", fields: dict[str, str] | None = None
) -> PendingExecution:
    """Create a PendingExecution with given field defaults."""
    if fields is None:
        fields = {"port": "8080", "host": "localhost"}
    resolved = {
        name: ResolvedValueCompat(value=val, source_type="default")
        for name, val in fields.items()
    }
    return PendingExecution(job_name=job_name, resolved_values=resolved)


def _make_tui_stub(pending: PendingExecution | None = None) -> FunctualizeInlineTUI:
    """Create a minimal TUI stub with mocked internals for unit testing."""
    with patch.object(FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None):
        tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

    # Set up minimal required attributes
    tui._pending = pending
    tui._smart_bar = MagicMock()
    tui._smart_bar.value = "serve"
    tui._smart_bar.readiness = MagicMock()
    tui._panel_host = MagicMock()
    tui._panel_host.is_active = False
    tui._panel_host.breadcrumb_depth = 0
    tui._panel_host.current_panel_widget = None
    tui._active_ring = "command"
    tui._focus_state = MagicMock()
    tui._display_slot = MagicMock()
    tui._display_slot.has_visible_displays = False
    tui._func_app = _make_func_app([])
    tui._snapshot_store = MagicMock()
    # The input-row host (C1b.2). `on_input_changed` keeps the active input
    # mode in step with the typed text, so the stub needs one; a MagicMock is
    # enough because these tests assert on the command path, not on mode swaps.
    tui._input_bar = MagicMock()
    # `on_input_changed` asks the mode registry whether the first character is
    # a sigil (C1b.3). A MagicMock's `__contains__` answers False, which is the
    # right answer for the ordinary command text these tests drive.
    tui._completer = MagicMock()

    return tui


# =============================================================================
# Test: Edit applied → set_override + refresh (R1-AC4, R8-AC1, R8-AC2)
# =============================================================================


class TestEditAppliedSync:
    """Verify _on_insert_edit_applied writes overrides and refreshes all views."""

    def test_edit_writes_override_directly(self) -> None:
        """Editing a field writes overrides[...] directly.

        Under the SmartBar-as-CLI model there is no per-field target
        bookkeeping — the value is just a CLI override.
        """
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        # Mock the field being edited
        field = SimpleNamespace(name="port")

        with patch.object(tui, "_refresh_all_views"):
            tui._on_insert_edit_applied(field, "9090")

        # Verify the override was written directly (no target bookkeeping)
        assert pending.overrides["port"] == "9090"

    def test_refresh_all_views_called_on_edit(self) -> None:
        """R1-AC4: After set_override, all panels are notified to refresh."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        field = SimpleNamespace(name="host")

        with patch.object(tui, "_refresh_all_views") as mock_refresh:
            tui._on_insert_edit_applied(field, "0.0.0.0")

        mock_refresh.assert_called_once()

    def test_set_override_not_called_without_pending(self) -> None:
        """No crash when _pending is None (e.g., no job recognized yet)."""
        tui = _make_tui_stub(pending=None)

        field = SimpleNamespace(name="port")

        # Should not raise
        with patch.object(tui, "_refresh_all_views") as mock_refresh:
            tui._on_insert_edit_applied(field, "9090")

        # _refresh_all_views still called for UI consistency
        mock_refresh.assert_called_once()

    def test_panel_apply_value_edit_called(self) -> None:
        """The active panel's apply_value_edit is still called for display update."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        mock_panel = MagicMock()
        mock_panel.apply_value_edit = MagicMock()

        # Patch active_panel property
        with (
            patch.object(
                type(tui),
                "active_panel",
                new_callable=PropertyMock,
                return_value=mock_panel,
            ),
            patch.object(tui, "_refresh_all_views"),
        ):
            field = SimpleNamespace(name="port")
            tui._on_insert_edit_applied(field, "9090")

        mock_panel.apply_value_edit.assert_called_once_with(field, "9090")


# =============================================================================
# Test: Reset override → clear_override + refresh (R1-AC5)
# =============================================================================


class TestResetOverrideSync:
    """Verify action_reset_override calls clear_override and refreshes."""

    def test_clear_override_called_on_reset(self) -> None:
        """R1-AC5: Resetting override calls PendingExecution.clear_override()."""
        pending = _make_pending()
        pending.overrides["port"] = "9090"
        tui = _make_tui_stub(pending)

        # Mock panel with get_cursor_field and action_reset_override
        from functualize._cli.tui.panels.config_table import EditOrigin

        field = SimpleNamespace(name="port", edit_origin=EditOrigin.VALUE)
        mock_panel = MagicMock()
        mock_panel.get_cursor_field.return_value = field
        mock_panel.action_reset_override = MagicMock()

        with (
            patch.object(
                type(tui),
                "active_panel",
                new_callable=PropertyMock,
                return_value=mock_panel,
            ),
            patch.object(tui, "_refresh_all_views") as mock_refresh,
        ):
            tui.action_reset_override()

        # Panel's action_reset_override was called
        mock_panel.action_reset_override.assert_called_once()
        # PendingExecution cleared
        assert "port" not in pending.overrides
        # All views refreshed
        mock_refresh.assert_called_once()

    def test_refresh_all_views_called_on_reset(self) -> None:
        """R1-AC5: After clear_override, all panels are notified to refresh."""
        pending = _make_pending()
        pending.overrides["host"] = "0.0.0.0"
        tui = _make_tui_stub(pending)

        from functualize._cli.tui.panels.config_table import EditOrigin

        field = SimpleNamespace(name="host", edit_origin=EditOrigin.VALUE)
        mock_panel = MagicMock()
        mock_panel.get_cursor_field.return_value = field
        mock_panel.action_reset_override = MagicMock()

        with (
            patch.object(
                type(tui),
                "active_panel",
                new_callable=PropertyMock,
                return_value=mock_panel,
            ),
            patch.object(tui, "_refresh_all_views") as mock_refresh,
        ):
            tui.action_reset_override()

        mock_refresh.assert_called_once()

    def test_no_crash_without_pending(self) -> None:
        """No crash when _pending is None during reset."""
        tui = _make_tui_stub(pending=None)

        from functualize._cli.tui.panels.config_table import EditOrigin

        field = SimpleNamespace(name="port", edit_origin=EditOrigin.VALUE)
        mock_panel = MagicMock()
        mock_panel.get_cursor_field.return_value = field
        mock_panel.action_reset_override = MagicMock()

        with (
            patch.object(
                type(tui),
                "active_panel",
                new_callable=PropertyMock,
                return_value=mock_panel,
            ),
            patch.object(tui, "_refresh_all_views"),
        ):
            tui.action_reset_override()

        # Still called panel's reset even without pending
        mock_panel.action_reset_override.assert_called_once()


# =============================================================================
# Test: Session load → overrides applied + all views refreshed (R8-AC3)
# =============================================================================


class TestSessionLoadSync:
    """Verify session load from DiffView applies overrides and refreshes."""

    def test_session_overrides_applied(self) -> None:
        """Loading a snapshot writes overrides[...] directly.

        Restored values become plain CLI overrides — no per-field target
        bookkeeping.
        """
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        snapshot = SimpleNamespace(values={"port": "3000", "host": "prod.example.com"})
        event = SimpleNamespace(snapshot=snapshot)

        with patch.object(tui, "_refresh_all_views"):
            tui.on_diff_view_widget_load_session_requested(event)

        assert pending.overrides["port"] == "3000"
        assert pending.overrides["host"] == "prod.example.com"

    def test_refresh_all_views_called_after_session_load(self) -> None:
        """R8-AC3: All views are refreshed after session load."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        snapshot = SimpleNamespace(values={"port": "3000"})
        event = SimpleNamespace(snapshot=snapshot)

        with patch.object(tui, "_refresh_all_views") as mock_refresh:
            tui.on_diff_view_widget_load_session_requested(event)

        mock_refresh.assert_called_once()

    def test_no_crash_without_pending(self) -> None:
        """No crash when _pending is None during session load."""
        tui = _make_tui_stub(pending=None)

        snapshot = SimpleNamespace(values={"port": "3000"})
        event = SimpleNamespace(snapshot=snapshot)

        # Should not raise
        with patch.object(tui, "_refresh_all_views") as mock_refresh:
            tui.on_diff_view_widget_load_session_requested(event)

        # _refresh_all_views NOT called since we return early
        mock_refresh.assert_not_called()


# =============================================================================
# Test: FileSaved → PendingExecution rebuilt + refresh (R8-AC4)
# =============================================================================


class TestFileSavedSync:
    """Verify FileSaved rebuilds PendingExecution and refreshes all views."""

    def test_pending_rebuilt_on_file_saved(self) -> None:
        """R8-AC4: FileSaved re-resolves the PendingExecution."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        # Mock _build_pending_execution to return a new pending
        new_pending = _make_pending(fields={"port": "3000", "host": "newhost"})

        with (
            patch.object(
                tui, "_build_pending_execution", return_value=new_pending
            ) as mock_build,
            patch.object(tui, "_refresh_all_views"),
        ):
            event = SimpleNamespace()
            tui.on_config_files_panel_file_saved(event)

        mock_build.assert_called_once_with("serve")
        assert tui._pending is new_pending

    def test_refresh_all_views_called_after_file_saved(self) -> None:
        """R8-AC4: All views refreshed after file save."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)

        new_pending = _make_pending()
        with (
            patch.object(tui, "_build_pending_execution", return_value=new_pending),
            patch.object(tui, "_refresh_all_views") as mock_refresh,
        ):
            event = SimpleNamespace()
            tui.on_config_files_panel_file_saved(event)

        mock_refresh.assert_called_once()


# =============================================================================
# Test: PanelHost activated → preflight hidden (R8-AC5)
# =============================================================================


class TestPreflightVisibility:
    """Verify preflight summary visibility based on panel host state."""

    def test_preflight_hidden_when_panel_host_active(self) -> None:
        """R8-AC5: When PanelHost is activated, PreFlightSummary hides."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)
        tui._panel_host.is_active = True

        # Mock query_one to return a RichLog-like object
        mock_summary = MagicMock()
        mock_summary.display = True
        tui.query_one = MagicMock(return_value=mock_summary)

        # Mock SmartBar readiness to PENDING (would normally show preflight)
        from functualize._cli.tui.bar import BarReadiness

        tui._smart_bar.readiness = BarReadiness.PENDING

        tui._update_preflight_summary()

        # Should hide since panel_host is active
        assert mock_summary.display is False

    def test_preflight_shown_when_panel_host_collapsed(self) -> None:
        """R8-AC6: When PanelHost collapses, PreFlightSummary shows."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)
        tui._panel_host.is_active = False

        # Mock query_one to return a RichLog-like object
        mock_summary = MagicMock()
        mock_summary.display = False
        tui.query_one = MagicMock(return_value=mock_summary)

        # Mock SmartBar readiness to PENDING (should show preflight)
        from functualize._cli.tui.bar import BarReadiness

        tui._smart_bar.readiness = BarReadiness.PENDING

        # Mock _render_preflight_summary to avoid deeper calls
        with patch.object(tui, "_render_preflight_summary"):
            tui._update_preflight_summary()

        # Should show since panel_host is collapsed and readiness is PENDING
        assert mock_summary.display is True

    def test_preflight_hidden_when_grey_readiness(self) -> None:
        """Preflight hidden when readiness is GREY regardless of panel state."""
        pending = _make_pending()
        tui = _make_tui_stub(pending)
        tui._panel_host.is_active = False

        mock_summary = MagicMock()
        mock_summary.display = True
        tui.query_one = MagicMock(return_value=mock_summary)

        from functualize._cli.tui.bar import BarReadiness

        tui._smart_bar.readiness = BarReadiness.GREY

        tui._update_preflight_summary()

        # Should hide since readiness is GREY
        assert mock_summary.display is False


# =============================================================================
# Test: GAP-1 — stale SmartBar-token clearing does not depend on override_targets
# =============================================================================


class TestStaleTokenClearing:
    """on_input_changed clears an override whose bar token disappeared.

    Under the SmartBar-as-CLI model a value has no life apart from its bar
    token: once a table-edit override's token is removed from the bar, the
    override is popped unconditionally. This must not read override_targets
    (which T5 removes), so the path stays crash-free.
    """

    def _make_command_tui(self, pending: PendingExecution) -> FunctualizeInlineTUI:
        from functualize._cli.tui.bar import BarReadiness
        from functualize._cli.tui.focus import FocusMode

        tui = _make_tui_stub(pending)
        tui._focus_state = MagicMock()
        tui._focus_state.mode = FocusMode.NORMAL
        tui._last_recognized_job = pending.job_name
        tui._command_panels = []
        tui._smart_bar.evaluate = MagicMock()
        tui._smart_bar.readiness = BarReadiness.PENDING
        tui._get_job_names = MagicMock(return_value=[pending.job_name])
        tui._get_required_fields = MagicMock(return_value=[])
        tui._get_job_fields = MagicMock(return_value=[])
        tui._sync_config_table_from_smartbar = MagicMock()
        tui._update_preflight_summary = MagicMock()
        return tui

    def test_stale_token_after_table_edit_is_cleared(self) -> None:
        """A table-edit override is dropped when its bar token disappears."""
        pending = _make_pending()
        tui = self._make_command_tui(pending)

        # Simulate a table edit that wrote an override directly.
        with patch.object(tui, "_refresh_all_views"):
            tui._on_insert_edit_applied(SimpleNamespace(name="port"), "9090")
        assert pending.overrides["port"] == "9090"

        # The bar now shows only the job name — the "port" token is gone.
        event = SimpleNamespace(input=SimpleNamespace(id="smart-bar"), value="serve")
        tui.on_input_changed(event)  # must not raise

        # The stale override is cleared because its token disappeared.
        assert "port" not in pending.overrides

    def test_stale_token_clearing_survives_missing_override_targets(self) -> None:
        """Clearing does not touch override_targets (forward-compatible with T5)."""
        pending = _make_pending()
        pending.overrides["port"] = "9090"
        tui = self._make_command_tui(pending)

        event = SimpleNamespace(input=SimpleNamespace(id="smart-bar"), value="serve")
        tui.on_input_changed(event)

        assert "port" not in pending.overrides
