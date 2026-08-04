"""full KEYMAPS-entry Pilot coverage matrix.

For every ``FocusMode`` in ``key_handler.KEYMAPS``, a Pilot-driven test
presses the terminal-delivered key name for each entry (never the dead
``ctrl+i``/``ctrl+h`` aliases — those are removed by) against a
real, running ``FunctualizeInlineTUI`` instance and asserts the
corresponding ``action_*`` method fired.

Also covers the plain-``enter`` execute fallback's three disqualifying
states (called out as a risk in plan.md's risk table):
not READY, autocomplete open, and non-COMMAND modes — asserting
``action_execute`` does NOT fire in any of them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize._cli.tui.key_handler import KEYMAPS
from functualize.app.core import FunctualizeApp


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    """A real FunctualizeInlineTUI over a minimal app, isolated from $HOME/cwd."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="keymapcoverageapp")

    def greet(name: str = "world") -> None:  # pragma: no cover - never run
        pass

    func_app.register_dynamic_job("greet", greet)

    return FunctualizeInlineTUI(func_app)


def _zone_for(mode: FocusMode) -> FocusZone:
    return FocusZone.SMARTBAR if mode is FocusMode.COMMAND else FocusZone.PANEL


# Every (FocusMode, key, action) triple currently in KEYMAPS.
_ALL_KEYMAP_ENTRIES = [
    (mode, key, action)
    for mode, keymap in KEYMAPS.items()
    for key, action in keymap.items()
]
_ENTRY_IDS = [
    f"{mode.name}:{key}->{action}" for mode, key, action in _ALL_KEYMAP_ENTRIES
]


@pytest.mark.parametrize("mode,key,action", _ALL_KEYMAP_ENTRIES, ids=_ENTRY_IDS)
async def test_keymap_entry_fires_via_pilot(
    tui_app: FunctualizeInlineTUI, mode: FocusMode, key: str, action: str
) -> None:
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._focus_state.force(mode, _zone_for(mode))
        # Remove DOM focus so the key reaches App.on_key -> KeyDispatcher
        # directly, instead of being consumed by a focused widget's own
        # default Bindings (e.g. Input/OptionList arrow-key handling).
        # Mirrors the existing NORMAL-mode "safety net" in app.py.
        tui_app.set_focus(None)
        await pilot.pause()

        method = MagicMock()
        with patch.object(type(tui_app), f"action_{action}", method, create=True):
            await pilot.press(key)
            await pilot.pause()

        method.assert_called_once()


class TestEnterFallbackNegativePilot:
    """risk mitigation: enter fallback's three disqualifying
    states, driven through a real Pilot session."""

    async def test_enter_does_not_execute_when_not_ready(
        self, tui_app: FunctualizeInlineTUI
    ) -> None:
        async with tui_app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            tui_app._focus_state.force(FocusMode.COMMAND, FocusZone.SMARTBAR)
            tui_app._smart_bar._set_readiness(BarReadiness.GREY)
            await pilot.pause()

            method = MagicMock()
            with patch.object(type(tui_app), "action_execute", method, create=True):
                await pilot.press("enter")
                await pilot.pause()

            method.assert_not_called()

    async def test_enter_does_not_execute_when_autocomplete_open(
        self, tui_app: FunctualizeInlineTUI
    ) -> None:
        async with tui_app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            tui_app._focus_state.force(FocusMode.COMMAND, FocusZone.SMARTBAR)
            tui_app._smart_bar._set_readiness(BarReadiness.READY)
            await pilot.pause()

            method = MagicMock()
            with (
                patch.object(type(tui_app), "action_execute", method, create=True),
                patch.object(
                    type(tui_app),
                    "is_autocomplete_visible",
                    lambda self: True,
                ),
            ):
                await pilot.press("enter")
                await pilot.pause()

            method.assert_not_called()

    @pytest.mark.parametrize(
        "mode", [FocusMode.NORMAL, FocusMode.INSERT, FocusMode.FILTER]
    )
    async def test_enter_does_not_execute_outside_command_mode(
        self, tui_app: FunctualizeInlineTUI, mode: FocusMode
    ) -> None:
        # Each non-COMMAND mode already claims plain "enter" for its own
        # action (drill_down / confirm_edit / apply_filter) — stub that
        # real handler too, since forcing the mode directly (bypassing the
        # real enter_insert/enter_filter transition) skips state the real
        # handler would otherwise depend on (e.g. SmartBar.save_state()).
        # The point of this test is only that action_execute never fires.
        own_action = KEYMAPS[mode]["enter"]

        async with tui_app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            tui_app._focus_state.force(mode, _zone_for(mode))
            tui_app._smart_bar._set_readiness(BarReadiness.READY)
            tui_app.set_focus(None)
            await pilot.pause()

            method = MagicMock()
            own_stub = MagicMock()
            with (
                patch.object(type(tui_app), "action_execute", method, create=True),
                patch.object(
                    type(tui_app), f"action_{own_action}", own_stub, create=True
                ),
            ):
                await pilot.press("enter")
                await pilot.pause()

            method.assert_not_called()
