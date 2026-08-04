"""Unit tests for KeyDispatcher's generalized overlay guard.

Proves the guard is a single code path (``_is_overlay_active``) that
covers ANY non-base screen on ``screen_stack`` — not two parallel checks
for CommandPalette vs. ShortcutSaveModal. Regression coverage for
CommandPalette is required per plan.md's risk row ("KeyDispatcher overlay
guard generalization breaks CommandPalette handling").
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.key_handler import KeyDispatcher


def _make_event(key: str) -> MagicMock:
    event = MagicMock()
    event.key = key
    event.prevent_default = MagicMock()
    event.stop = MagicMock()
    return event


def _make_app(screen_stack: list) -> MagicMock:
    app = MagicMock()
    app.screen_stack = screen_stack
    app.is_autocomplete_visible = MagicMock(return_value=False)
    app.active_panel = None
    return app


class TestOverlayGuardSingleCodePath:
    """Both CommandPalette and ShortcutSaveModal are handled by one guard."""

    def test_base_screen_only_does_not_block_dispatch(self) -> None:
        """A single base screen on the stack does not trigger the overlay guard."""
        fs = FocusState()
        fs.force(FocusMode.COMMAND, FocusZone.SMARTBAR)
        base_screen = MagicMock()
        app = _make_app([base_screen])
        app.action_ring_next = MagicMock()

        dispatcher = KeyDispatcher(fs, app)
        event = _make_event("ctrl+j")
        result = dispatcher.dispatch(event)

        assert result is True
        app.action_ring_next.assert_called_once()

    def test_command_palette_on_stack_blocks_dispatch(self) -> None:
        """Regression: CommandPalette pushed on the stack still blocks dispatch."""
        fs = FocusState()
        fs.force(FocusMode.COMMAND, FocusZone.SMARTBAR)
        base_screen = MagicMock()
        palette = MagicMock()
        palette.__class__.__name__ = "CommandPalette"
        app = _make_app([base_screen, palette])
        app.action_execute = MagicMock()

        dispatcher = KeyDispatcher(fs, app)
        event = _make_event("ctrl+enter")
        result = dispatcher.dispatch(event)

        assert result is False
        app.action_execute.assert_not_called()
        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()

    def test_shortcut_save_modal_on_stack_blocks_dispatch(self) -> None:
        """a pushed ShortcutSaveModal screen blocks dispatch too."""
        from functualize._cli.tui.shortcut_save_modal import ShortcutSaveModal

        fs = FocusState()
        fs.force(FocusMode.COMMAND, FocusZone.SMARTBAR)
        base_screen = MagicMock()
        modal = ShortcutSaveModal("greet", {})
        app = _make_app([base_screen, modal])
        app.action_execute = MagicMock()

        dispatcher = KeyDispatcher(fs, app)
        event = _make_event("ctrl+enter")
        result = dispatcher.dispatch(event)

        assert result is False
        app.action_execute.assert_not_called()
        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()

    def test_both_cases_use_the_same_guard_method(self) -> None:
        """Only one private guard method exists; no separate palette-only check."""
        fs = FocusState()
        app = _make_app([MagicMock()])
        dispatcher = KeyDispatcher(fs, app)

        assert hasattr(dispatcher, "_is_overlay_active")
        assert not hasattr(dispatcher, "_is_command_palette_active"), (
            "generalized guard must fold the old palette-only check into "
            "_is_overlay_active, not keep two parallel code paths"
        )

    @pytest.mark.parametrize(
        "stack_len",
        [1, 2, 3],
    )
    def test_overlay_active_reflects_stack_depth(self, stack_len: int) -> None:
        """_is_overlay_active is a pure function of screen_stack depth."""
        fs = FocusState()
        app = _make_app([MagicMock() for _ in range(stack_len)])
        dispatcher = KeyDispatcher(fs, app)

        assert dispatcher._is_overlay_active() is (stack_len > 1)
