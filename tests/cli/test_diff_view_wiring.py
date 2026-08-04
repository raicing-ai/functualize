"""Tests for DiffViewWidget wiring into the command ring.

Verifies that:
1. DiffViewWidget appears as Panel 3 with title "Diff View" (R3-AC1)
2. show_diff is called when DiffView becomes active via ring navigation (R3-AC2)
3. LoadSessionRequested applies snapshot values as overrides (R3-AC3)
4. BackRequested collapses panel host and returns to COMMAND mode (R3-AC4)

Requirements: R3-AC1, R3-AC2, R3-AC3, R3-AC4
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from functualize._cli.data.config_snapshot_store import (
    ConfigSnapshot,
    ConfigSnapshotStore,
)
from functualize._cli.data.pending_execution import PendingExecution
from functualize._cli.data.resolved_value_compat import ResolvedValueCompat
from functualize._cli.tui.diff_view_widget import DiffViewWidget
from functualize._cli.tui.focus import FocusState

# =============================================================================
# Helpers
# =============================================================================


def _make_pending(
    job_name: str = "deploy", fields: dict[str, str] | None = None
) -> PendingExecution:
    """Create a PendingExecution with resolved values."""
    resolved = {}
    for name, value in (fields or {"port": "8080", "host": "localhost"}).items():
        resolved[name] = ResolvedValueCompat(value=value, source_type="default")
    return PendingExecution(job_name=job_name, resolved_values=resolved)


def _make_snapshot(
    job_name: str = "deploy",
    values: dict[str, object] | None = None,
    outcome: str = "success",
    timestamp: float = 1000.0,
) -> ConfigSnapshot:
    """Create a ConfigSnapshot for testing."""
    return ConfigSnapshot(
        job_name=job_name,
        timestamp=timestamp,
        values=values or {"port": "3000", "host": "prod.example.com"},
        outcome=outcome,
    )


def _make_tui_for_build():
    """Create a real (fully-constructed) TUI app suitable for testing
    _build_command_panels().

    Uses the real ``FunctualizeInlineTUI.__init__`` (via a minimal
    ``FunctualizeApp``) so Textual's App plumbing (e.g. ``self.log``,
    reactive attributes) is initialized correctly — bypassing ``__init__``
    via ``__new__`` leaves those uninitialized and breaks any code path
    that touches them (see contributor/guides/steering_textual_tui.md
    section 4.2).
    """
    from functualize._cli.tui.app import FunctualizeInlineTUI
    from functualize.app.core import FunctualizeApp

    func_app = FunctualizeApp(name="testapp")
    tui = FunctualizeInlineTUI(func_app)

    # Set up minimum state
    smart_bar = MagicMock()
    smart_bar.readiness = MagicMock()
    smart_bar.readiness.__eq__ = lambda self, other: False  # Not GREY
    smart_bar.value = "deploy --port 8080"
    tui._smart_bar = smart_bar
    tui._panel_id_seq = 0
    tui._pending = _make_pending()
    tui._snapshot_store = ConfigSnapshotStore()

    # Mock _find_job_descriptor to return a descriptor with fields
    descriptor = MagicMock()
    descriptor.group = None
    field = MagicMock()
    field.name = "port"
    field.default = "8080"
    field.required = False
    field.choices = None
    field.description = "Port number"
    field.positional = False
    field.short_flag = None
    field.type_annotation = "int"
    descriptor.config_fields = [field]
    descriptor.parameters = None
    tui._find_job_descriptor = MagicMock(return_value=descriptor)

    return tui


# =============================================================================
# Test: DiffViewWidget appears as Panel 3 with title "Diff View" (R3-AC1)
# =============================================================================


class TestDiffViewAsPanel3:
    """DiffViewWidget is added as the third panel in the command ring."""

    def test_diff_view_is_third_panel(self) -> None:
        """_build_command_panels returns DiffView as the third (index 2) panel."""
        tui = _make_tui_for_build()

        # Patch BarReadiness.GREY check to pass
        from functualize._cli.tui.bar import BarReadiness

        tui._smart_bar.readiness = BarReadiness.PENDING

        panels = tui._build_command_panels()

        assert len(panels) >= 3
        title, widget = panels[2]
        assert title == "Diff View"
        assert isinstance(widget, DiffViewWidget)

    def test_panel_order_is_config_table_config_files_diff_view(self) -> None:
        """Command ring panels are ordered: Config Table, Config Files, Diff View."""
        tui = _make_tui_for_build()

        from functualize._cli.tui.bar import BarReadiness

        tui._smart_bar.readiness = BarReadiness.PENDING

        panels = tui._build_command_panels()

        assert len(panels) >= 3
        assert panels[0][0] == "Config Table"
        assert panels[1][0] == "Config Files"
        assert panels[2][0] == "Diff View"

    def test_diff_view_has_unique_id(self) -> None:
        """DiffViewWidget is assigned a unique panel ID."""
        tui = _make_tui_for_build()

        from functualize._cli.tui.bar import BarReadiness

        tui._smart_bar.readiness = BarReadiness.PENDING

        panels = tui._build_command_panels()

        _, diff_widget = panels[2]
        assert diff_widget.id is not None
        assert "diff-view" in diff_widget.id


# =============================================================================
# Test: show_diff called when DiffView becomes active (R3-AC2)
# =============================================================================


class TestShowDiffCalledOnActivation:
    """show_diff is called with current PendingExecution and snapshot data."""

    def test_show_diff_called_on_ring_next_to_diff_view(self) -> None:
        """When ring navigation lands on DiffViewWidget, show_diff is called."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        # Set up panel host mock
        diff_view = MagicMock(spec=DiffViewWidget)
        diff_view.__class__ = DiffViewWidget

        panel_host = MagicMock()
        panel_host.is_active = True
        panel_host.breadcrumb_depth = 0
        panel_host.current_panel_widget = diff_view
        tui._panel_host = panel_host
        tui._focus_state = FocusState()

        # Set up pending execution and snapshot store
        pending = _make_pending()
        tui._pending = pending
        snapshot_store = MagicMock()
        snapshot_store.get_last_snapshot.return_value = _make_snapshot()
        snapshot_store.get_snapshots.return_value = [_make_snapshot()]
        tui._snapshot_store = snapshot_store

        tui.action_ring_next()

        panel_host.navigate_next.assert_called_once()
        diff_view.show_diff.assert_called_once_with(
            pending,
            snapshot_store.get_last_snapshot.return_value,
            snapshot_store.get_snapshots.return_value,
        )

    def test_show_diff_called_on_ring_prev_to_diff_view(self) -> None:
        """When ring_prev lands on DiffViewWidget, show_diff is called."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        diff_view = MagicMock(spec=DiffViewWidget)
        diff_view.__class__ = DiffViewWidget

        panel_host = MagicMock()
        panel_host.is_active = True
        panel_host.breadcrumb_depth = 0
        panel_host.current_panel_widget = diff_view
        tui._panel_host = panel_host
        tui._focus_state = FocusState()

        pending = _make_pending()
        tui._pending = pending
        snapshot_store = MagicMock()
        snapshot_store.get_last_snapshot.return_value = None
        snapshot_store.get_snapshots.return_value = []
        tui._snapshot_store = snapshot_store

        tui.action_ring_prev()

        panel_host.navigate_prev.assert_called_once()
        diff_view.show_diff.assert_called_once_with(pending, None, [])

    def test_show_diff_not_called_when_active_panel_is_not_diff_view(self) -> None:
        """When ring navigation lands on non-DiffView panel, show_diff is NOT called."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        config_panel = MagicMock()
        config_panel.__class__ = type("ConfigTablePanel", (), {})

        panel_host = MagicMock()
        panel_host.is_active = True
        panel_host.breadcrumb_depth = 0
        panel_host.current_panel_widget = config_panel
        tui._panel_host = panel_host
        tui._focus_state = FocusState()

        tui._pending = _make_pending()
        tui._snapshot_store = MagicMock()

        tui.action_ring_next()

        # show_diff should not be called on non-DiffView panels
        assert (
            not hasattr(config_panel, "show_diff") or not config_panel.show_diff.called
        )

    def test_show_diff_not_called_when_pending_is_none(self) -> None:
        """When no PendingExecution exists, show_diff is not called."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        diff_view = MagicMock(spec=DiffViewWidget)
        diff_view.__class__ = DiffViewWidget

        panel_host = MagicMock()
        panel_host.is_active = True
        panel_host.breadcrumb_depth = 0
        panel_host.current_panel_widget = diff_view
        tui._panel_host = panel_host
        tui._focus_state = FocusState()

        tui._pending = None
        tui._snapshot_store = MagicMock()

        tui.action_ring_next()

        diff_view.show_diff.assert_not_called()


# =============================================================================
# Test: LoadSessionRequested applies overrides (R3-AC3)
# =============================================================================


class TestLoadSessionRequestedAppliesOverrides:
    """LoadSessionRequested handler applies snapshot values as session overrides."""

    def test_applies_all_snapshot_values_as_overrides(self) -> None:
        """All values from snapshot are applied via set_override."""
        tui = _make_tui_for_build()

        pending = _make_pending()
        tui._pending = pending
        tui._snapshot_store = MagicMock()

        # Mock _refresh_all_views to avoid calling complex logic
        tui._refresh_all_views = MagicMock()

        snapshot = _make_snapshot(values={"port": "9090", "host": "staging.io"})
        event = MagicMock()
        event.snapshot = snapshot

        tui.on_diff_view_widget_load_session_requested(event)

        # Verify overrides were applied
        assert pending.overrides["port"] == "9090"
        assert pending.overrides["host"] == "staging.io"

    def test_refresh_all_views_called_after_applying(self) -> None:
        """_refresh_all_views is called after applying overrides."""
        tui = _make_tui_for_build()

        tui._pending = _make_pending()
        tui._snapshot_store = MagicMock()
        tui._refresh_all_views = MagicMock()

        snapshot = _make_snapshot(values={"port": "3000"})
        event = MagicMock()
        event.snapshot = snapshot

        tui.on_diff_view_widget_load_session_requested(event)

        tui._refresh_all_views.assert_called_once()

    def test_no_op_when_pending_is_none(self) -> None:
        """Handler is a no-op when no PendingExecution exists."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        tui._pending = None
        tui._refresh_all_views = MagicMock()

        event = MagicMock()
        event.snapshot = _make_snapshot()

        tui.on_diff_view_widget_load_session_requested(event)

        tui._refresh_all_views.assert_not_called()

    def test_no_op_when_snapshot_missing_on_event(self) -> None:
        """Handler is a no-op when event has no snapshot attribute."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        tui._pending = _make_pending()
        tui._refresh_all_views = MagicMock()

        event = MagicMock(spec=[])  # No attributes
        event.snapshot = None

        tui.on_diff_view_widget_load_session_requested(event)

        tui._refresh_all_views.assert_not_called()


# =============================================================================
# Test: BackRequested collapses panel host (R3-AC4)
# =============================================================================


class TestBackRequestedCollapsesHost:
    """BackRequested handler collapses the panel host and returns to COMMAND mode."""

    def test_collapse_called_and_ring_cleared(self) -> None:
        """Panel host is collapsed and _active_ring is set to None."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        panel_host = MagicMock()
        tui._panel_host = panel_host
        tui._active_ring = "command"
        tui._focus_state = MagicMock()
        tui._smart_bar = MagicMock()
        tui._update_preflight_summary = MagicMock()

        with patch("functualize._cli.tui.app.exit_to_command_mode") as mock_exit:
            event = MagicMock()
            tui.on_diff_view_widget_back_requested(event)

            mock_exit.assert_called_once_with(tui, tui._focus_state, tui._smart_bar)

        panel_host.collapse.assert_called_once()
        assert tui._active_ring is None

    def test_preflight_summary_updated_after_collapse(self) -> None:
        """_update_preflight_summary is called after collapse."""
        from functualize._cli.tui.app import FunctualizeInlineTUI

        with patch.object(
            FunctualizeInlineTUI, "__init__", lambda self, *a, **kw: None
        ):
            tui = FunctualizeInlineTUI.__new__(FunctualizeInlineTUI)

        tui._panel_host = MagicMock()
        tui._active_ring = "command"
        tui._focus_state = MagicMock()
        tui._smart_bar = MagicMock()
        tui._update_preflight_summary = MagicMock()

        with patch("functualize._cli.tui.app.exit_to_command_mode"):
            event = MagicMock()
            tui.on_diff_view_widget_back_requested(event)

        tui._update_preflight_summary.assert_called_once()
