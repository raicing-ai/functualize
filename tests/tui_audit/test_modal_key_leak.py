"""Proof (historical) + inversion: ShortcutSaveModal modality.

Originally, ``ShortcutSaveModal`` was an overlay ``Widget`` mounted via
``self.mount(modal)`` and never given focus. Its ``on_key`` only ever fired
for keys that bubble from a focused descendant — so while focus stayed on
the SmartBar, EVERY key went to the app's ``KeyDispatcher`` instead:

- Escape hit ``KEYMAPS[COMMAND]["escape"] = "smartbar_clear"``: the user's
  typed command was wiped and the modal stayed open (escape could not
  close it).
- Ctrl+Enter still executed the job *underneath* the open modal.

This was fixed by migrating ``ShortcutSaveModal`` to a real
``ModalScreen[result]`` pushed via ``push_screen(..., callback)``
and by generalizing ``KeyDispatcher``'s overlay guard
from a CommandPalette-only check to "any non-base screen on the stack". Because these two tests exercised the REAL production
app (not a toy model, unlike ``test_blocking_worker.py``'s ``HeartbeatApp``),
they could not remain unchanged once the fix landed — asserting the old
buggy behavior would simply be false now. By design, they are inverted
here (same test names/fixture, assertions flipped to the corrected
behavior) rather than deleted, so this file continues to document the
defect's history while standing as a permanent regression guard against
its reintroduction.

See also ``tests/_cli/test_shortcut_save_modal_screen_integration.py`` and
``tests/_cli/test_key_dispatcher_overlay_guard_unit.py`` for additional,
non-experiment-scoped coverage of the same fix.

this file is the historical origin of the real-app Pilot
``tui_app`` fixture recipe. It has been promoted into a shared, reusable
fixture at ``tests/_cli/_tui_fixtures.py`` (parametrizable by job
name/kwargs via ``make_tui_app``); this file now imports that shared
fixture instead of keeping its own local copy, so the two files stay in
sync automatically instead of silently drifting.
"""

from __future__ import annotations

from functualize._cli.tui.shortcut_save_modal import ShortcutSaveModal
from tests._cli._tui_fixtures import tui_app

__all__ = ["tui_app"]


async def test_escape_leaks_past_open_modal(tui_app) -> None:
    """inversion: Escape now dismisses the modal, SmartBar untouched.

    Formerly ``test_escape_leaks_past_open_modal`` proved Escape cleared
    the SmartBar and left the (Widget-based) modal open. Post-R3, the
    modal is a ``ModalScreen`` that captures Escape itself.
    """
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()  # what Ctrl+S dispatches to
        await pilot.pause()
        assert any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack), (
            "modal should be pushed onto the screen stack"
        )

        await pilot.press("escape")
        await pilot.pause()

        # The keypress was captured by the modal's own on_key, not the
        # app's KEYMAPS["escape"] = "smartbar_clear":
        assert tui_app._smart_bar.value == "greet --name bob", (
            "escape should have been captured by the modal — "
            "the SmartBar underneath must be untouched"
        )
        assert not any(
            isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
        ), "modal should have dismissed on Escape"


async def test_ctrl_enter_executes_job_under_open_modal(tui_app) -> None:
    """inversion: Ctrl+Enter no longer executes the job under an open modal.

    Formerly ``test_ctrl_enter_executes_job_under_open_modal`` proved
    Ctrl+Enter reached the app and executed the job underneath the
    (Widget-based) modal. Post-R3, ``KeyDispatcher``'s generalized overlay
    guard blocks all app-/panel-level dispatch while any
    screen is pushed on top of the base screen.

    A follow-up manual check (post-merge) found the modal's OWN
    ``ctrl+enter`` confirm binding was also broken — it only listened for
    ``ctrl+j``, so the footer's "Ctrl+Enter save" hint never actually
    worked. That is now fixed too: Ctrl+Enter confirms the modal's own
    save action (dismissing it), rather than being a complete no-op.
    """
    from textual.widgets import RichLog

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet"
        await pilot.pause()
        assert tui_app._smart_bar.readiness.name == "READY"

        tui_app.action_save_shortcut()
        await pilot.pause()
        assert any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack)

        output_log = tui_app.query_one("#output-log", RichLog)
        assert not output_log.has_class("visible")

        await pilot.press("ctrl+enter")
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()

        assert not output_log.has_class("visible"), (
            "Ctrl+Enter must not reach the app under an open modal "
            " — modality must be enforced"
        )
        assert not any(
            isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
        ), "Ctrl+Enter should confirm-and-dismiss the modal, not be a no-op"


async def test_modal_key_leak_defect_stays_fixed_end_to_end(tui_app) -> None:
    """Combined regression guard: both leak paths stay closed in one session.

    New test added alongside the inverted pair above,
    exercising Escape-then-reopen-then-Ctrl+Enter in a single Pilot
    session to guard against a regression that only reintroduces the leak
    for one of the two keys.
    """
    from textual.widgets import RichLog

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        # First: open, Escape, confirm clean dismissal.
        tui_app.action_save_shortcut()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert tui_app._smart_bar.value == "greet --name bob"
        assert not any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack)

        # Reset command to a bare job name and re-open the modal.
        tui_app._smart_bar.value = "greet"
        await pilot.pause()
        tui_app.action_save_shortcut()
        await pilot.pause()
        assert any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack)

        output_log = tui_app.query_one("#output-log", RichLog)

        # Second: Ctrl+Enter must not execute the app job — it confirms the
        # modal's own save action instead (dismissing it).
        await pilot.press("ctrl+enter")
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()

        assert not output_log.has_class("visible")
        assert not any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack)
