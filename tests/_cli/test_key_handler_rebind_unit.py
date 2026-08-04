"""Unit tests for KEYMAPS rebinding and KeyDispatcher routing.

Covers, at the KEYMAPS/KeyDispatcher unit level (no real Textual App):

- dead ``ctrl+i``/``ctrl+h`` entries removed from COMMAND/NORMAL.
- ``display_next`` rebound to ``ctrl+o``; ``display_prev`` stays
  ``ctrl+u``.
- ``ring_first`` rebound to ``ctrl+g`` (implementer's choice —
  see report) rather than removed.
- plain-``enter`` execute fallback in COMMAND mode, gated on
  readiness READY and the autocomplete dropdown being closed; does not fire
  in NORMAL/INSERT/FILTER modes or when the gate conditions are unmet.
- ``KeyDispatcher._is_autocomplete_visible`` no longer falls
  back to the broken ``functualize._cli.functualize_autocomplete`` import
  path — it returns ``False`` directly when the app-level checker is
  unavailable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.key_handler import KEYMAPS, KeyDispatcher

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_mock_event(key: str) -> MagicMock:
    event = MagicMock()
    event.key = key
    event.prevent_default = MagicMock()
    event.stop = MagicMock()
    return event


def _make_mock_app(
    *,
    autocomplete_visible: bool = False,
    execute_ready: bool = False,
    has_autocomplete_checker: bool = True,
    has_execute_ready_checker: bool = True,
    active_panel: MagicMock | None = None,
) -> MagicMock:
    app = MagicMock(spec_set=[] if False else None)
    app.screen_stack = [MagicMock()]
    app.active_panel = active_panel

    if has_autocomplete_checker:
        app.is_autocomplete_visible = MagicMock(return_value=autocomplete_visible)
    else:
        del app.is_autocomplete_visible

    if has_execute_ready_checker:
        app.is_execute_ready = MagicMock(return_value=execute_ready)
    else:
        del app.is_execute_ready

    return app


def _dispatch(app: MagicMock, mode: FocusMode, key: str) -> tuple[bool, MagicMock]:
    """Force FocusState into ``mode`` and dispatch a single key event."""
    focus_state = FocusState()
    focus_state.force(mode, FocusZone.PANEL)
    dispatcher = KeyDispatcher(focus_state, app)
    event = _make_mock_event(key)
    with patch.object(dispatcher, "_is_overlay_active", return_value=False):
        result = dispatcher.dispatch(event)
    return result, event


# ─── dead entries removed ───────────────────────────────────────


class TestDeadEntriesRemoved:
    def test_ctrl_i_removed_from_command_keymap(self) -> None:
        assert "ctrl+i" not in KEYMAPS[FocusMode.COMMAND]

    def test_ctrl_i_removed_from_normal_keymap(self) -> None:
        assert "ctrl+i" not in KEYMAPS[FocusMode.NORMAL]

    def test_ctrl_h_removed_from_command_keymap(self) -> None:
        assert "ctrl+h" not in KEYMAPS[FocusMode.COMMAND]

    def test_ctrl_h_removed_from_normal_keymap(self) -> None:
        assert "ctrl+h" not in KEYMAPS[FocusMode.NORMAL]


# ─── standing prohibition (guard also covered by) ────


class TestStandingProhibition:
    def test_no_ctrl_m_entry_anywhere(self) -> None:
        for keymap in KEYMAPS.values():
            assert "ctrl+m" not in keymap


# ─── display_next rebind ────────────────────────────────────────


class TestDisplayNextRebind:
    def test_command_ctrl_o_maps_to_display_next(self) -> None:
        assert KEYMAPS[FocusMode.COMMAND]["ctrl+o"] == "display_next"

    def test_normal_ctrl_o_maps_to_display_next(self) -> None:
        assert KEYMAPS[FocusMode.NORMAL]["ctrl+o"] == "display_next"

    def test_command_ctrl_u_still_maps_to_display_prev(self) -> None:
        assert KEYMAPS[FocusMode.COMMAND]["ctrl+u"] == "display_prev"

    def test_normal_ctrl_u_still_maps_to_display_prev(self) -> None:
        assert KEYMAPS[FocusMode.NORMAL]["ctrl+u"] == "display_prev"


# ─── ring_first resolution (rebind decision, see report) ───────


class TestRingFirstRebind:
    def test_command_ctrl_g_maps_to_ring_first(self) -> None:
        assert KEYMAPS[FocusMode.COMMAND]["ctrl+g"] == "ring_first"

    def test_normal_ctrl_g_maps_to_ring_first(self) -> None:
        assert KEYMAPS[FocusMode.NORMAL]["ctrl+g"] == "ring_first"


# ─── plain-enter execute fallback ──────────────────────────


class TestEnterExecuteFallback:
    def test_fires_when_command_ready_and_dropdown_closed(self) -> None:
        app = _make_mock_app(autocomplete_visible=False, execute_ready=True)
        app.action_execute = MagicMock()
        result, event = _dispatch(app, FocusMode.COMMAND, "enter")

        app.action_execute.assert_called_once()
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()
        assert result is True

    def test_does_not_fire_when_not_ready(self) -> None:
        app = _make_mock_app(autocomplete_visible=False, execute_ready=False)
        app.action_execute = MagicMock()
        _dispatch(app, FocusMode.COMMAND, "enter")

        app.action_execute.assert_not_called()

    def test_does_not_fire_when_autocomplete_open(self) -> None:
        app = _make_mock_app(autocomplete_visible=True, execute_ready=True)
        app.action_execute = MagicMock()
        app.action_autocomplete_accept = MagicMock()
        _dispatch(app, FocusMode.COMMAND, "enter")

        # Autocomplete intercept claims "enter" first (existing behavior);
        # the new fallback must never also fire execute.
        app.action_execute.assert_not_called()

    def test_does_not_fire_in_normal_mode(self) -> None:
        """NORMAL already claims plain enter for drill_down."""
        app = _make_mock_app(autocomplete_visible=False, execute_ready=True)
        app.action_execute = MagicMock()
        app.action_drill_down = MagicMock()
        _dispatch(app, FocusMode.NORMAL, "enter")

        app.action_execute.assert_not_called()
        app.action_drill_down.assert_called_once()

    def test_does_not_fire_in_insert_mode(self) -> None:
        """INSERT already claims plain enter for confirm_edit."""
        app = _make_mock_app(autocomplete_visible=False, execute_ready=True)
        app.action_execute = MagicMock()
        app.action_confirm_edit = MagicMock()
        _dispatch(app, FocusMode.INSERT, "enter")

        app.action_execute.assert_not_called()
        app.action_confirm_edit.assert_called_once()

    def test_does_not_fire_in_filter_mode(self) -> None:
        """FILTER already claims plain enter for apply_filter."""
        app = _make_mock_app(autocomplete_visible=False, execute_ready=True)
        app.action_execute = MagicMock()
        app.action_apply_filter = MagicMock()
        _dispatch(app, FocusMode.FILTER, "enter")

        app.action_execute.assert_not_called()
        app.action_apply_filter.assert_called_once()

    def test_missing_execute_ready_checker_disables_fallback(self) -> None:
        """If the app has no is_execute_ready(), the fallback must not fire."""
        app = _make_mock_app(
            autocomplete_visible=False,
            has_execute_ready_checker=False,
        )
        app.action_execute = MagicMock()
        _dispatch(app, FocusMode.COMMAND, "enter")

        app.action_execute.assert_not_called()


# ─── broken autocomplete fallback import removed ──────────────


class TestAutocompleteVisibleFallback:
    def test_returns_false_when_app_checker_unavailable(self) -> None:
        app = _make_mock_app(has_autocomplete_checker=False)
        focus_state = FocusState()
        dispatcher = KeyDispatcher(focus_state, app)

        assert dispatcher._is_autocomplete_visible() is False

    def test_does_not_reference_broken_import_path(self) -> None:
        """The removed fallback imported a module path that does not exist
        (functualize._cli.functualize_autocomplete). Assert the source no
        longer contains an import of it (mentioning the path in a comment
        explaining *why* it was removed is fine)."""
        import inspect

        from functualize._cli.tui import key_handler

        source = inspect.getsource(key_handler)
        assert "import functualize._cli.functualize_autocomplete" not in source
        assert "from functualize._cli.functualize_autocomplete" not in source
