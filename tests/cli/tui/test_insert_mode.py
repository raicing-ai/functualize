"""Unit tests for tui/insert_mode.py — INSERT mode SmartBar repurposing flow.

Tests the InsertModeController lifecycle: entering INSERT mode (save bar,
set edit value, add "editing" class, focus bar), confirming edits with
validation gate, cancelling edits, and clearing INVALID state on input.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6, 13.1, 13.2, 13.3, 13.4, 13.5**
"""

from __future__ import annotations

from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.insert_mode import EditOrigin, FieldDef, InsertModeController

# =============================================================================
# Helpers — Mock SmartBar
# =============================================================================


class MockSmartBar:
    """Minimal SmartBar mock for testing InsertModeController logic."""

    def __init__(self) -> None:
        self.value: str = "deploy --region us-east-1"
        self.cursor_position: int = 10
        self.placeholder: str = "Type a command"
        self._readiness: BarReadiness = BarReadiness.READY
        self._saved: bool = False
        self._classes: set[str] = set()
        self._focused: bool = False
        self._validity_reason: str = ""

    @property
    def readiness(self) -> BarReadiness:
        return self._readiness

    def save_state(self) -> None:
        self._saved = True
        self._saved_value = self.value
        self._saved_cursor = self.cursor_position
        self._saved_placeholder = self.placeholder
        self._saved_readiness = self._readiness

    def restore_state(self) -> None:
        if not self._saved:
            raise RuntimeError("restore_state() called without prior save_state()")
        self.value = self._saved_value
        self.cursor_position = self._saved_cursor
        self.placeholder = self._saved_placeholder
        self._readiness = self._saved_readiness
        self._saved = False
        self._classes.discard("editing")
        self._classes.discard("invalid")

    def enter_edit_mode(self, field_name: str, value: str, hint: str) -> None:
        self.value = value
        self.placeholder = f"Edit: {field_name}"
        self._validity_reason = hint
        self._readiness = BarReadiness.EDITING

    def enter_invalid(self, error_msg: str) -> None:
        self._validity_reason = error_msg
        self._classes.discard("editing")
        self._readiness = BarReadiness.INVALID

    def focus(self) -> None:
        self._focused = True

    def add_class(self, cls: str) -> None:
        self._classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self._classes.discard(cls)


# =============================================================================
# Tests: enter_insert
# =============================================================================


class TestEnterInsert:
    """Tests for InsertModeController.enter_insert."""

    def _make_controller(self) -> tuple[InsertModeController, FocusState, MockSmartBar]:
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        return ctrl, fs, bar

    def test_enter_insert_from_normal_succeeds(self) -> None:
        """Req 4.1, 4.2: Enter INSERT mode saves bar, sets edit value, focuses."""
        ctrl, fs, bar = self._make_controller()
        # Must be in NORMAL mode to enter INSERT
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="region", value="us-west-2", source="")
        result = ctrl.enter_insert(field)

        assert result is True
        assert fs.mode == FocusMode.INSERT
        assert bar._saved is True  # state was saved
        assert bar.value == "us-west-2"  # field value populated
        assert bar.placeholder == "Edit: region"
        assert bar._readiness == BarReadiness.EDITING
        assert "editing" in bar._classes
        assert bar._focused is True

    def test_enter_insert_from_command_fails(self) -> None:
        """Cannot enter INSERT directly from COMMAND mode."""
        ctrl, fs, bar = self._make_controller()
        # Default state is COMMAND
        assert fs.mode == FocusMode.COMMAND

        field = FieldDef(name="region", value="us-west-2", source="")
        result = ctrl.enter_insert(field)

        assert result is False
        assert fs.mode == FocusMode.COMMAND  # unchanged
        assert ctrl.is_active is False

    def test_enter_insert_records_return_zone(self) -> None:
        """Return zone is recorded for exit transition."""
        ctrl, fs, bar = self._make_controller()
        fs.force(FocusMode.NORMAL, FocusZone.DISPLAY)

        field = FieldDef(name="port", value="8080", source="")
        ctrl.enter_insert(field, return_zone=FocusZone.DISPLAY)

        assert ctrl._return_zone == FocusZone.DISPLAY

    def test_is_active_reflects_editing_state(self) -> None:
        """is_active property reflects whether INSERT mode is active."""
        ctrl, fs, bar = self._make_controller()
        assert ctrl.is_active is False

        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        field = FieldDef(name="x", value="1", source="")
        ctrl.enter_insert(field)

        assert ctrl.is_active is True


# =============================================================================
# Tests: confirm_edit
# =============================================================================


class TestConfirmEdit:
    """Tests for InsertModeController.confirm_edit."""

    def _setup_insert(
        self,
        validator=None,
        initial_value: str = "old",
    ) -> tuple[InsertModeController, FocusState, MockSmartBar, FieldDef]:
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(
            name="region", value=initial_value, validator=validator, source=""
        )
        ctrl.enter_insert(field)
        return ctrl, fs, bar, field

    def test_confirm_valid_value_no_validator(self) -> None:
        """Req 13.1: No validator → accept any non-empty value."""
        ctrl, fs, bar, field = self._setup_insert()
        # Simulate user typing a new value
        bar.value = "eu-west-1"

        success, error = ctrl.confirm_edit()

        assert success is True
        assert error is None
        # Field should be updated (fallback logic)
        assert field.value == "eu-west-1"
        assert field.source == "unsaved"
        assert field.edit_origin == EditOrigin.VALUE
        # Bar should be restored
        assert fs.mode == FocusMode.NORMAL
        assert ctrl.is_active is False

    def test_confirm_empty_value_no_validator_fails(self) -> None:
        """Req 13.1: No validator, but empty value is rejected."""
        ctrl, fs, bar, field = self._setup_insert()
        bar.value = "   "

        success, error = ctrl.confirm_edit()

        assert success is False
        assert error == "Value cannot be empty"
        assert bar._readiness == BarReadiness.INVALID
        # Still in INSERT mode
        assert fs.mode == FocusMode.INSERT
        assert ctrl.is_active is True

    def test_confirm_valid_value_with_validator(self) -> None:
        """Req 13.1, 13.4: Validator passes → apply and exit."""

        def int_validator(v: str) -> tuple[bool, str]:
            try:
                int(v)
                return (True, "")
            except ValueError:
                return (False, f"'{v}' is not a valid integer")

        ctrl, fs, bar, field = self._setup_insert(validator=int_validator)
        bar.value = "42"

        success, error = ctrl.confirm_edit()

        assert success is True
        assert error is None
        assert field.value == "42"
        assert fs.mode == FocusMode.NORMAL

    def test_confirm_invalid_value_with_validator(self) -> None:
        """Req 4.6, 13.2: Validator rejects → INVALID, keep INSERT."""

        def int_validator(v: str) -> tuple[bool, str]:
            try:
                int(v)
                return (True, "")
            except ValueError:
                return (False, f"'{v}' is not a valid integer")

        ctrl, fs, bar, field = self._setup_insert(validator=int_validator)
        bar.value = "not-a-number"

        success, error = ctrl.confirm_edit()

        assert success is False
        assert error == "'not-a-number' is not a valid integer"
        assert bar._readiness == BarReadiness.INVALID
        assert fs.mode == FocusMode.INSERT
        # Field unchanged
        assert field.value == "old"

    def test_confirm_with_apply_callback(self) -> None:
        """Apply callback is invoked instead of fallback logic."""
        applied: list[tuple[FieldDef, str]] = []

        def on_apply(f: FieldDef, val: str) -> None:
            applied.append((f, val))
            f.value = val
            f.source = "cli"

        ctrl, fs, bar, field = self._setup_insert()
        ctrl.set_apply_callback(on_apply)
        bar.value = "new-value"

        success, error = ctrl.confirm_edit()

        assert success is True
        assert len(applied) == 1
        assert applied[0] == (field, "new-value")

    def test_confirm_no_active_field_returns_false(self) -> None:
        """Confirm when not in INSERT mode is a no-op."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)

        success, error = ctrl.confirm_edit()

        assert success is False
        assert error == "No field being edited"


# =============================================================================
# Tests: exit_insert
# =============================================================================


class TestExitInsert:
    """Tests for InsertModeController.exit_insert (Escape)."""

    def _setup_insert(
        self,
    ) -> tuple[InsertModeController, FocusState, MockSmartBar, FieldDef]:
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="timeout", value="30", source="")
        ctrl.enter_insert(field)
        return ctrl, fs, bar, field

    def test_exit_restores_bar_without_applying(self) -> None:
        """Req 4.4: Escape restores bar without applying changes."""
        ctrl, fs, bar, field = self._setup_insert()
        original_value = "deploy --region us-east-1"  # MockSmartBar initial value

        # Simulate user typing something different
        bar.value = "totally-different"

        ctrl.exit_insert()

        # Bar should be restored to original
        assert bar.value == original_value
        assert fs.mode == FocusMode.NORMAL
        assert fs.zone == FocusZone.PANEL
        assert ctrl.is_active is False

    def test_exit_removes_editing_class(self) -> None:
        """Req 4.4: "editing" class is removed on exit."""
        ctrl, fs, bar, field = self._setup_insert()
        assert "editing" in bar._classes

        ctrl.exit_insert()

        assert "editing" not in bar._classes

    def test_exit_returns_to_correct_zone(self) -> None:
        """Req 4.4, 13.5: Focus returns to the zone that was active before INSERT."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.DISPLAY)

        field = FieldDef(name="x", value="1", source="")
        ctrl.enter_insert(field, return_zone=FocusZone.DISPLAY)
        ctrl.exit_insert()

        assert fs.zone == FocusZone.DISPLAY

    def test_exit_during_invalid_state(self) -> None:
        """Req 13.5: Escape during INVALID cancels edit, returns to NORMAL/PANEL."""
        ctrl, fs, bar, field = self._setup_insert()

        # Trigger validation failure
        bar.value = ""
        ctrl.confirm_edit()
        assert bar._readiness == BarReadiness.INVALID
        assert fs.mode == FocusMode.INSERT

        # Now press Escape
        ctrl.exit_insert()

        assert fs.mode == FocusMode.NORMAL
        assert fs.zone == FocusZone.PANEL
        assert ctrl.is_active is False

    def test_exit_when_not_active_is_noop(self) -> None:
        """Exit when not in INSERT mode does nothing."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)

        # Should not raise
        ctrl.exit_insert()
        assert ctrl.is_active is False


# =============================================================================
# Tests: on_bar_changed (clear INVALID on input)
# =============================================================================


class TestOnBarChanged:
    """Tests for InsertModeController.on_bar_changed."""

    def _setup_invalid(
        self,
    ) -> tuple[InsertModeController, FocusState, MockSmartBar, FieldDef]:
        """Set up controller in INVALID state after a failed validation."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="port", value="8080", source="")
        ctrl.enter_insert(field)

        # Force INVALID state
        bar.value = "   "
        ctrl.confirm_edit()
        assert bar._readiness == BarReadiness.INVALID

        return ctrl, fs, bar, field

    def test_clears_invalid_on_input(self) -> None:
        """Req 13.3: Further input after INVALID clears error, returns to EDITING."""
        ctrl, fs, bar, field = self._setup_invalid()

        # Simulate user typing
        bar.value = "90"
        ctrl.on_bar_changed()

        assert bar._readiness == BarReadiness.EDITING
        assert bar.placeholder == "Edit: port"

    def test_no_effect_when_editing(self) -> None:
        """on_bar_changed is a no-op when already in EDITING state."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="x", value="1", source="")
        ctrl.enter_insert(field)
        assert bar._readiness == BarReadiness.EDITING

        bar.value = "something"
        ctrl.on_bar_changed()

        # Still EDITING — no state change
        assert bar._readiness == BarReadiness.EDITING

    def test_no_effect_when_not_active(self) -> None:
        """on_bar_changed is a no-op when not in INSERT mode."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)

        # Should not raise
        ctrl.on_bar_changed()


# =============================================================================
# Tests: Full flow integration
# =============================================================================


class TestInsertModeFullFlow:
    """Integration tests verifying the complete INSERT mode lifecycle."""

    def test_enter_fail_correct_succeed(self) -> None:
        """Req 13.4: Enter → invalid → correct → valid → exit normally."""

        def even_validator(v: str) -> tuple[bool, str]:
            try:
                n = int(v)
                if n % 2 == 0:
                    return (True, "")
                return (False, f"{n} is not even")
            except ValueError:
                return (False, f"'{v}' is not a number")

        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="count", value="4", validator=even_validator, source="")
        ctrl.enter_insert(field)
        assert fs.mode == FocusMode.INSERT

        # First attempt: invalid
        bar.value = "7"
        success, error = ctrl.confirm_edit()
        assert success is False
        assert "not even" in error
        assert bar._readiness == BarReadiness.INVALID
        assert fs.mode == FocusMode.INSERT

        # User types correction → clears error
        bar.value = "8"
        ctrl.on_bar_changed()
        assert bar._readiness == BarReadiness.EDITING

        # Second attempt: valid
        success, error = ctrl.confirm_edit()
        assert success is True
        assert error is None
        assert field.value == "8"
        assert fs.mode == FocusMode.NORMAL

    def test_enter_fail_escape(self) -> None:
        """Req 13.5: Enter → invalid → Escape cancels without applying."""

        def never_valid(v: str) -> tuple[bool, str]:
            return (False, "always fails")

        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="x", value="original", validator=never_valid, source="")
        ctrl.enter_insert(field)

        bar.value = "attempt"
        ctrl.confirm_edit()
        assert bar._readiness == BarReadiness.INVALID

        ctrl.exit_insert()
        assert fs.mode == FocusMode.NORMAL
        assert field.value == "original"  # unchanged
