"""Pilot tests proving ShortcutSaveModal behaves as a real modal.

Mirrors the bug-documentation fixture in
``tests/tui_audit/test_modal_key_leak.py`` but asserts the FIXED
behavior once ``ShortcutSaveModal`` is migrated from a layered ``Widget``
to a ``ModalScreen[result]`` pushed via ``push_screen(..., callback)``:

- Escape dismisses the modal (``dismiss(None)``) and does NOT touch the
  SmartBar.
- The confirm key (``ctrl+j``) validates/writes/dismisses with the saved
  path on success, and stays open with an inline error on failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Input, TextArea

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.shortcut_save_modal import ShortcutSaveModal
from functualize.app.core import FunctualizeApp


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    """A real FunctualizeInlineTUI over a minimal app, isolated from $HOME/cwd."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="modalscreenapp")

    def greet(name: str = "world") -> None:  # pragma: no cover - never run
        pass

    func_app.register_dynamic_job("greet", greet)

    return FunctualizeInlineTUI(func_app)


async def test_shortcut_save_modal_is_a_modal_screen(tui_app) -> None:
    """ShortcutSaveModal is hosted as a ModalScreen, not a Widget."""
    from textual.screen import ModalScreen

    assert issubclass(ShortcutSaveModal, ModalScreen)


async def test_escape_dismisses_modal_and_preserves_smartbar(tui_app) -> None:
    """Escape calls dismiss(None) and leaves the SmartBar untouched."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()
        assert any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack), (
            "modal should be pushed onto the screen stack"
        )

        await pilot.press("escape")
        await pilot.pause()

        assert tui_app._smart_bar.value == "greet --name bob", (
            "Escape leaked past the modal and cleared the SmartBar underneath"
        )
        assert not any(
            isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
        ), "modal should have been dismissed by Escape"


async def test_ctrl_enter_confirms_modal_not_the_app_job(tui_app) -> None:
    """Ctrl+Enter while the modal is open never executes the app-level
    job underneath — it is consumed by the modal's own confirm action instead.

    Two things must both be true: the overlay guard still blocks the app's
    execute path, AND the modal's ``ctrl+enter`` binding
    actually works (the bug the footer text "Ctrl+Enter save" promised but
    the modal previously only listened for ``ctrl+j`` — real terminals
    deliver ``ctrl+enter`` as its own key name under the Kitty protocol).
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
            "Ctrl+Enter reached the app under the modal and executed the job"
        )
        assert not any(
            isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
        ), (
            "Ctrl+Enter should confirm the modal's own save action and "
            "dismiss it — it must not be a no-op"
        )


async def test_confirm_key_saves_and_dismisses_with_path(
    tui_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ctrl+j validates/writes/dismisses with the saved
    path on success, and that path is observable via push_screen's callback."""
    callback_results: list[str | None] = []
    monkeypatch.setattr(
        tui_app,
        "_on_shortcut_save_dismissed",
        lambda result: callback_results.append(result),
    )

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()

        modals = [s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)]
        assert modals, "modal should be on the screen stack after Ctrl+S"
        modal = modals[0]
        file_input = modal.query_one("#ssm-input-file")
        file_input.value = str(tmp_path / "shortcuts.py")
        await pilot.pause()

        await pilot.press("ctrl+j")
        await pilot.pause()

        assert not any(
            isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
        ), "modal should dismiss on successful confirm"
        written_file = tmp_path / "shortcuts.py"
        assert written_file.exists()

        # the ShortcutSaved-equivalent result (written path) is
        # observable by the push_screen callback, not just internally by the
        # modal.
        assert callback_results == [str(written_file)]


async def test_escape_cancel_path_writes_no_file_and_dismisses_with_none(
    tui_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escape (cancel path) dismisses with None and writes no file."""
    callback_results: list[str | None] = []
    monkeypatch.setattr(
        tui_app,
        "_on_shortcut_save_dismissed",
        lambda result: callback_results.append(result),
    )

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()

        modals = [s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)]
        assert modals, "modal should be on the screen stack after Ctrl+S"
        modal = modals[0]
        file_input = modal.query_one("#ssm-input-file")
        file_input.value = str(tmp_path / "shortcuts.py")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert not any(
            isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
        ), "modal should dismiss on Escape (cancel path)"
        assert list(tmp_path.iterdir()) == [], (
            "cancel path must not write any shortcut file"
        )
        assert callback_results == [None]


async def test_confirm_key_with_invalid_name_keeps_modal_open(
    tui_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 9 (invalid name): ctrl+j with an invalid name shows an inline
    error, writes no file, and does NOT dismiss the modal."""
    from textual.widgets import Input, Static

    callback_results: list[str | None] = []
    monkeypatch.setattr(
        tui_app,
        "_on_shortcut_save_dismissed",
        lambda result: callback_results.append(result),
    )

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()

        modals = [s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)]
        assert modals, "modal should be on the screen stack after Ctrl+S"
        modal = modals[0]

        name_input = modal.query_one("#ssm-input-name", Input)
        name_input.value = "123invalid"
        file_input = modal.query_one("#ssm-input-file", Input)
        file_input.value = str(tmp_path / "shortcuts.py")
        await pilot.pause()

        await pilot.press("ctrl+j")
        await pilot.pause()

        assert any(isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack), (
            "modal must remain open when the shortcut name is invalid"
        )
        assert list(tmp_path.iterdir()) == [], (
            "invalid-name confirm must not write a file"
        )
        assert callback_results == [], "invalid-name confirm must not dismiss"

        error_widget = modal.query_one("#ssm-error", Static)
        assert str(error_widget.content).strip() != "", (
            "an inline error message should be displayed in the modal's error area"
        )


# ===========================================================================
# Pilot Tests: UX fixes (default file, editable preview, append-not-overwrite)
# ===========================================================================


async def test_default_output_file_is_shortcuts_py(tui_app) -> None:
    """Requirement: the Output file input defaults to ``./shortcuts.py``."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()

        modals = [s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)]
        assert modals, "modal should be on the screen stack after Ctrl+S"
        modal = modals[0]
        file_input = modal.query_one("#ssm-input-file", Input)
        assert file_input.value == "./shortcuts.py"


async def test_textarea_present_and_prepopulated_on_open(tui_app) -> None:
    """Requirement 3: the preview is an editable TextArea pre-populated with
    the generated shortcut content, not a read-only RichLog."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()

        modals = [s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)]
        assert modals, "modal should be on the screen stack after Ctrl+S"
        modal = modals[0]

        preview = modal.query_one("#ssm-preview", TextArea)
        assert "def greet(" in preview.text
        assert "invoke(" in preview.text


async def test_typing_in_textarea_detaches_preview_from_auto_regen(
    tui_app,
) -> None:
    """Requirement 3: a real keystroke in the TextArea detaches the preview
    from auto-regeneration — subsequent name-field edits leave it alone."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        tui_app.action_save_shortcut()
        await pilot.pause()

        modals = [s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)]
        assert modals, "modal should be on the screen stack after Ctrl+S"
        modal = modals[0]

        preview = modal.query_one("#ssm-preview", TextArea)
        assert modal._preview_detached is False

        await pilot.click("#ssm-preview")
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()

        assert modal._preview_detached is True
        edited_text = preview.text
        assert edited_text.startswith("x")

        name_input = modal.query_one("#ssm-input-name", Input)
        name_input.value = "totally_different_name"
        await pilot.pause()

        assert preview.text == edited_text, (
            "auto-regen must not overwrite manually-edited preview content"
        )


async def test_confirming_same_shortcut_name_twice_appends_to_one_file(
    tui_app, tmp_path: Path
) -> None:
    """Requirement 2 (integration): opening the modal for the same job and
    confirming with the SAME shortcut name twice appends the second
    function definition to the existing file rather than overwriting it —
    the final file contains both function definitions and only one import
    line."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet --name bob"
        await pilot.pause()

        for _ in range(2):
            tui_app.action_save_shortcut()
            await pilot.pause()
            modal = next(
                s for s in tui_app.screen_stack if isinstance(s, ShortcutSaveModal)
            )
            modal.query_one("#ssm-input-file", Input).value = str(
                tmp_path / "shortcuts.py"
            )
            await pilot.pause()
            await pilot.press("ctrl+j")
            await pilot.pause()
            assert not any(
                isinstance(s, ShortcutSaveModal) for s in tui_app.screen_stack
            )

        written_file = tmp_path / "shortcuts.py"
        assert written_file.exists()
        content = written_file.read_text()
        assert content.count("def greet(") == 2
        assert content.count("from functualize.job import Invoke, Log") == 1
        assert content.count('JOB_GROUP = "shortcut"') == 1
        compile(content, "<test>", "exec")
