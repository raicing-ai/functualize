"""Tests for experiment B extended: autocomplete + validation.

Run:
    uv run pytest experiments/input_handling/test_b_autocomplete.py -v --tb=short
"""

from __future__ import annotations

import pytest

from tests.experiments.input_handling.experiment_b_with_autocomplete import (
    SmartBarAutoCompleteApp,
)


# ─── Validation Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_rejects_invalid_int():
    """Entering a non-integer for 'timeout' shows an error and stays in INSERT."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Navigate to 'timeout' (row index 1)
        await pilot.press("j")
        await pilot.pause()

        # Enter insert mode
        await pilot.press("i")
        await pilot.pause()
        assert app._mode == "insert"

        # Type an invalid value
        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        await pilot.press("backspace", "backspace")  # Clear "30"
        await pilot.press("a", "b", "c")
        await pilot.pause()

        # Try to confirm — should fail validation
        await pilot.press("enter")
        await pilot.pause()

        # Still in INSERT mode (validation rejected)
        assert app._mode == "insert"
        # Bar should have "invalid" class
        assert bar.has_class("invalid")
        # Original value unchanged
        assert app._fields["timeout"].value == "30"


@pytest.mark.asyncio
async def test_validation_accepts_valid_int():
    """Entering a valid integer for 'timeout' applies and returns to NORMAL."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Navigate to 'timeout' (row 1)
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        # Clear and type valid value
        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        await pilot.press("backspace", "backspace")
        await pilot.press("6", "0")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        # Should be back in NORMAL mode
        assert app._mode == "normal"
        # Value updated
        assert app._fields["timeout"].value == "60"


@pytest.mark.asyncio
async def test_validation_error_clears_on_typing():
    """After a validation error, typing again clears the error state."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("j")  # timeout
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        from textual.widgets import Input, Static

        bar = app.query_one("#smart-bar", Input)

        # Type invalid and try to confirm
        await pilot.press("backspace", "backspace")
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Error shown
        assert bar.has_class("invalid")
        msg = app.query_one("#validation-msg", Static)
        assert msg.has_class("visible")

        # Type again — error should clear
        await pilot.press("backspace")
        await pilot.press("5")
        await pilot.pause()

        # Error cleared
        assert not bar.has_class("invalid")
        assert not msg.has_class("visible")


@pytest.mark.asyncio
async def test_validation_negative_int_rejected():
    """Negative integers are rejected by the validator."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("j")  # timeout
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        # Clear and type negative
        await pilot.press("backspace", "backspace")
        # Note: '-' is a printable character that goes to the Input
        await pilot.press("-", "5")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Should stay in INSERT (negative rejected)
        assert app._mode == "insert"
        assert bar.has_class("invalid")


# ─── Enum/Choices Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enum_field_shows_editing_mode():
    """Editing an enum field (log_level) enters INSERT with correct placeholder."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        # log_level is row 0 (first field)
        await pilot.press("i")
        await pilot.pause()

        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        assert app._mode == "insert"
        assert bar.value == "info"  # Pre-filled with current value
        # Placeholder should mention the field
        assert "log_level" in bar.placeholder


@pytest.mark.asyncio
async def test_enum_value_accepted():
    """Typing a valid enum value and confirming updates the field."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")  # Edit log_level
        await pilot.pause()

        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        # Clear "info" and type "debug"
        await pilot.press("backspace", "backspace", "backspace", "backspace")
        await pilot.press("d", "e", "b", "u", "g")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert app._mode == "normal"
        assert app._fields["log_level"].value == "debug"


@pytest.mark.asyncio
async def test_completer_switches_to_edit_mode():
    """When entering INSERT, the completer switches to field_edit mode."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Initially in command mode
        assert app._completer.mode == "command"

        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")  # Edit log_level (has choices)
        await pilot.pause()

        # Completer should now be in field_edit mode
        assert app._completer.mode == "field_edit"
        assert app._completer._choices == [
            "debug", "info", "warning", "error", "critical"
        ]


@pytest.mark.asyncio
async def test_completer_returns_to_command_mode_on_cancel():
    """Pressing Escape restores completer to command mode.

    Note: If autocomplete dropdown is visible, first Escape dismisses it,
    second Escape cancels the edit. This test presses Escape twice to be safe.
    """
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert app._completer.mode == "field_edit"

        # Press escape twice — first may dismiss autocomplete dropdown,
        # second cancels the edit
        await pilot.press("escape")
        await pilot.pause()
        if app._mode == "insert":
            # First escape was consumed by autocomplete, press again
            await pilot.press("escape")
            await pilot.pause()

        assert app._completer.mode == "command"


@pytest.mark.asyncio
async def test_completer_returns_to_command_mode_on_confirm():
    """After confirming edit, completer returns to command mode."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("i")  # log_level
        await pilot.pause()
        assert app._completer.mode == "field_edit"

        # Just confirm the pre-filled value
        await pilot.press("enter")
        await pilot.pause()

        assert app._completer.mode == "command"


# ─── Path Field Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_path_field_sets_completer_path_mode():
    """Editing output_dir (path field) sets is_path on the completer."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        # Navigate to output_dir (row 3)
        await pilot.press("j", "j", "j")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        assert app._completer.mode == "field_edit"
        assert app._completer._is_path is True
        assert app._completer._field_name == "output_dir"


@pytest.mark.asyncio
async def test_path_field_accepts_any_string():
    """Path fields have no validator — any string is accepted."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("j", "j", "j")  # output_dir
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()

        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)
        # Clear "/tmp" and type a non-existent path (avoids autocomplete interference)
        await pilot.press("backspace", "backspace", "backspace", "backspace")
        await pilot.press("/", "n", "o", "n", "e")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert app._mode == "normal"
        # Value should contain what we typed (autocomplete may or may not apply)
        assert "none" in app._fields["output_dir"].value or app._fields["output_dir"].value == "/none"


# ─── Multi-edit cycle test ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_edits_in_sequence():
    """Can edit multiple fields in sequence without issues."""
    app = SmartBarAutoCompleteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+e")
        await pilot.pause()

        from textual.widgets import Input

        bar = app.query_one("#smart-bar", Input)

        # Edit log_level (row 0)
        await pilot.press("i")
        await pilot.pause()
        await pilot.press("backspace", "backspace", "backspace", "backspace")
        await pilot.press("e", "r", "r", "o", "r")
        await pilot.press("enter")
        await pilot.pause()
        assert app._fields["log_level"].value == "error"
        assert app._mode == "normal"

        # Move down and edit timeout (row 1)
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        await pilot.press("backspace", "backspace")
        await pilot.press("9", "0")
        await pilot.press("enter")
        await pilot.pause()
        assert app._fields["timeout"].value == "90"
        assert app._mode == "normal"

        # Move down and edit verbose (row 2)
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        # "false" → clear → "true"
        for _ in range(5):
            await pilot.press("backspace")
        await pilot.press("t", "r", "u", "e")
        await pilot.press("enter")
        await pilot.pause()
        assert app._fields["verbose"].value == "true"
        assert app._mode == "normal"
