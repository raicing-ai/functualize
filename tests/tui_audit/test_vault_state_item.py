"""Proof: the TUI shows the vault key state, and a hung probe never blocks the UI.

The state comes from `vault_key_state`, which may wait on a keyring backend.
Steering §2.5: sync work on the event loop freezes rendering and input, so the
probe runs in a thread worker and only its result is marshalled back. The
second test below makes the probe hang and proves the loop keeps answering.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from textual.widgets import Static

from functualize._cli.tui.bar_items import render_vault_state
from functualize.app.vault import VaultKeyState, VaultKeyStatus
from tests._cli._tui_fixtures import tui_app

if TYPE_CHECKING:
    from functualize._cli.tui.app import FunctualizeInlineTUI

__all__ = ["tui_app"]


class TestTheItemText:
    def test_no_vault_renders_nothing(self) -> None:
        assert render_vault_state(VaultKeyState(VaultKeyStatus.NOT_APPLICABLE)) is None
        assert render_vault_state(None) is None

    def test_locked_names_the_command_that_fixes_it(self) -> None:
        text = render_vault_state(VaultKeyState(VaultKeyStatus.LOCKED))
        assert text is not None
        assert "locked" in text
        assert "func builtin vault unlock" in text

    @pytest.mark.parametrize(
        "status",
        [VaultKeyStatus.UNLOCKED, VaultKeyStatus.UNKNOWN, VaultKeyStatus.NO_KEYRING],
    )
    def test_every_other_state_renders(self, status: VaultKeyStatus) -> None:
        assert render_vault_state(VaultKeyState(status))


def _status_text(app: FunctualizeInlineTUI) -> str:
    return str(app.query_one("#status-bar", Static).render())


async def test_the_state_reaches_the_status_bar(
    tui_app: FunctualizeInlineTUI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "functualize.app.vault.vault_key_state",
        lambda app=None, cwd=None: VaultKeyState(VaultKeyStatus.LOCKED),
    )
    async with tui_app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()
        assert "vault locked" in _status_text(tui_app)


async def test_a_hung_probe_does_not_block_the_event_loop(
    tui_app: FunctualizeInlineTUI, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def hung(app: Any = None, cwd: Any = None) -> VaultKeyState:
        release.wait(10)
        return VaultKeyState(VaultKeyStatus.UNKNOWN)

    monkeypatch.setattr("functualize.app.vault.vault_key_state", hung)
    # Timed from before start-up: the first probe is asked at mount, so a
    # probe on the loop thread would stall mount itself, not only later keys.
    started = time.monotonic()
    try:
        async with tui_app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            # Keystrokes reach the SmartBar only if the loop is running.
            await pilot.press("h", "i")
            await pilot.pause()
            assert tui_app._smart_bar.value == "hi"
            # The loop answered while the probe was still blocked.
            assert not release.is_set()
            assert time.monotonic() - started < 5.0
            release.set()
            await tui_app.workers.wait_for_complete()
    finally:
        release.set()
