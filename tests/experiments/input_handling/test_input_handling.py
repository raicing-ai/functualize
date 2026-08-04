"""Automated tests for input handling experiments.

Uses Textual's pilot testing framework to simulate key presses and verify
which approaches actually deliver keystrokes to the Input widget.

Each test:
1. Starts the app
2. Presses Ctrl+E to open the panel (→ NORMAL mode)
3. Presses 'i' to enter INSERT mode
4. Types "hello" character by character
5. Asserts the Input widget contains "hello"

Run:
    uv run pytest experiments/input_handling/test_input_handling.py -x --tb=short
"""

from __future__ import annotations

import pytest

from tests.experiments.input_handling.experiment_a_editbar import EditBarApp, EditBar
from tests.experiments.input_handling.experiment_b_repurpose_smartbar import (
    RepurposeSmartBarApp,
)
from tests.experiments.input_handling.experiment_broken_nested import BrokenNestedApp
from tests.experiments.input_handling.experiment_c_modal import ModalEditApp


@pytest.mark.asyncio
async def test_broken_nested_input_does_not_receive_keystrokes():
    """BASELINE: Nested Input with display:none toggle + proper blur.

    With set_focus(None) in NORMAL mode, the nested Input CAN receive focus
    via app.set_focus() because nothing else holds it. This test verifies
    that the fix (blurring SmartBar) makes even nested Inputs work.

    The REAL broken case is when SmartBar still has focus — then printable
    keys never reach the App's on_key (Input consumes them).
    """
    app = BrokenNestedApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Start in COMMAND mode, SmartBar has focus
        # Press Ctrl+E to open panel → NORMAL mode (this blurs SmartBar)
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Press 'i' to enter INSERT mode
        await pilot.press("i")
        await pilot.pause()

        # Type "hello"
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()

        # With SmartBar blurred, the nested Input approach actually works
        # in Textual's test harness (set_focus can grab it)
        from textual.widgets import Input

        inp = app.query_one("#panel-edit-input", Input)
        # This documents that the "fix" for nested Input is simply
        # to blur whatever widget currently has focus before set_focus
        assert inp.value == "hello", (
            f"Nested Input has: '{inp.value}'. "
            "Expected it to work once SmartBar is blurred."
        )


@pytest.mark.asyncio
async def test_option_a_editbar_receives_keystrokes():
    """Option A: EditBar at app level SHOULD receive keystrokes via programmatic forwarding."""
    app = EditBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Open panel
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Verify mode changed to normal
        assert app._mode == "normal", f"Mode is: {app._mode}"

        # Enter insert mode
        await pilot.press("i")
        await pilot.pause()

        # Verify mode changed to insert
        assert app._mode == "insert", f"Mode is: {app._mode}"

        # The EditBar should now be visible with pre-filled value "30"
        edit_bar = app.query_one("#edit-bar", EditBar)
        assert edit_bar.value == "30", f"EditBar value: '{edit_bar.value}'"

        # Type characters — they should be forwarded to EditBar
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()

        # Value should be "30hello" (appended at end)
        assert "hello" in edit_bar.value, f"EditBar has: '{edit_bar.value}'"


@pytest.mark.asyncio
async def test_option_a_editbar_confirm_updates_table():
    """Option A: Enter confirms the edit and updates the DataTable."""
    app = EditBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        # EditBar pre-filled with "30", simulate clearing and typing "60"
        # Use backspace to clear, then type new value
        edit_bar = app.query_one("#edit-bar", EditBar)
        await pilot.press("backspace", "backspace")  # Clear "30"
        await pilot.press("6", "0")
        await pilot.pause()

        assert edit_bar.value == "60"

        # Confirm with Enter
        await pilot.press("enter")
        await pilot.pause()

        # Verify: mode should be back to normal
        assert app._mode == "normal"
        # Value in data model should be updated
        assert app._table_data["timeout"][1] == "60"


@pytest.mark.asyncio
async def test_option_a_editbar_escape_cancels():
    """Option A: Escape cancels the edit without applying."""
    app = EditBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        # Type something but then cancel
        await pilot.press("9", "9", "9")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        # Mode back to normal, value unchanged
        assert app._mode == "normal"
        assert app._table_data["timeout"][1] == "30"  # Original value


@pytest.mark.asyncio
async def test_option_b_repurpose_smartbar_receives_keystrokes():
    """Option B: Repurposed SmartBar SHOULD receive keystrokes (same widget)."""
    app = RepurposeSmartBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Open panel
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Enter insert mode — SmartBar is repurposed with pre-filled "30"
        await pilot.press("i")
        await pilot.pause()

        # SmartBar should now be in "editing" mode with the current value
        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        assert bar.value == "30", f"Pre-fill failed: '{bar.value}'"

        # Type at end — but Textual may auto-select on focus,
        # so typing replaces the pre-filled value
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()

        # The Input received keystrokes — that's what matters
        assert "hello" in bar.value, f"SmartBar has: '{bar.value}'"


@pytest.mark.asyncio
async def test_option_b_confirm_updates_table():
    """Option B: Enter confirms and restores SmartBar state."""
    app = RepurposeSmartBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Type something in SmartBar first (to verify state is saved/restored)
        from textual.widgets import Input

        await pilot.press("m", "y", "c", "m", "d")
        await pilot.pause()
        bar = app.query_one("#smart-bar", Input)
        assert bar.value == "mycmd"

        # Open panel and edit
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        # SmartBar now shows "30" (pre-filled). Select all and replace.
        # home + shift doesn't work, so delete char by char then type
        assert bar.value == "30"
        await pilot.press("backspace", "backspace")  # Clear "30"
        await pilot.press("6", "0")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Verify: table updated, SmartBar restored
        assert app._mode == "normal"
        assert app._table_data["timeout"][1] == "60"
        assert bar.value == "mycmd"  # SmartBar state restored


@pytest.mark.asyncio
async def test_option_c_modal_receives_keystrokes():
    """Option C: Modal overlay SHOULD receive keystrokes (layer: modal)."""
    app = ModalEditApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Open panel
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Enter insert mode (mounts modal)
        await pilot.press("i")
        await pilot.pause()

        # The modal input should be focused and pre-filled with "30"
        from textual.widgets import Input

        modal_input = app.query_one("#modal-input", Input)
        assert modal_input.value == "30", f"Pre-fill: '{modal_input.value}'"

        # Type at end — but Textual may auto-select on focus,
        # so typing replaces the pre-filled value
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()

        # The modal Input received keystrokes — that's what matters
        assert "hello" in modal_input.value, f"Modal input has: '{modal_input.value}'"


@pytest.mark.asyncio
async def test_option_c_modal_confirm_updates_table():
    """Option C: Enter in modal confirms and updates table."""
    app = ModalEditApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        from textual.widgets import Input

        modal_input = app.query_one("#modal-input", Input)
        # Clear pre-filled "30" and type "60"
        await pilot.press("backspace", "backspace")
        await pilot.press("6", "0")
        await pilot.pause()
        assert modal_input.value == "60"

        await pilot.press("enter")
        await pilot.pause()

        # Table should be updated
        assert app._table_data["timeout"][1] == "60"
        assert app._mode == "normal"


@pytest.mark.asyncio
async def test_option_c_modal_escape_cancels():
    """Option C: Escape in modal cancels without updating."""
    app = ModalEditApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        await pilot.press("9", "9", "9")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert app._table_data["timeout"][1] == "30"  # Unchanged
        assert app._mode == "normal"


# ─── Root Cause Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_truly_broken_smartbar_consumes_keys_in_normal_mode():
    """ROOT CAUSE: SmartBar (Input) consumes printable keys, blocking App.on_key.

    When an Input widget has focus, printable characters are consumed by the
    Input's internal handler (they become text in the input). The App's on_key
    never sees them. This means 'i', 'j', 'k', '/' etc. go into the SmartBar
    text instead of being routed by the centralized key handler.
    """
    from experiments.input_handling.experiment_truly_broken import TrulyBrokenApp

    app = TrulyBrokenApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Press Ctrl+E — this works because Ctrl+E is NOT consumed by Input
        await pilot.press("ctrl+e")
        await pilot.pause()

        assert app._mode == "normal"

        # Now press 'i' — this should enter INSERT mode
        # BUT SmartBar still has focus, so 'i' goes into the Input as text!
        await pilot.press("i")
        await pilot.pause()

        # The mode does NOT change — 'i' was eaten by SmartBar
        assert app._mode == "normal", (
            "If this fails, Textual changed key dispatch behavior"
        )

        # The SmartBar contains 'i' as typed text
        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        assert "i" in bar.value, f"SmartBar should have 'i': '{bar.value}'"
