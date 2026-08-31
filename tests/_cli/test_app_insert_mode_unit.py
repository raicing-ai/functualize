"""Unit tests for INSERT mode lifecycle from the app's perspective.

Tests how app.py's action methods interact with InsertModeController:
- enter_insert saves SmartBar state and sets editing mode
- confirm_edit applies value, restores state, transitions to NORMAL
- exit_insert restores state without applying, transitions to NORMAL

**Validates: Requirements 16.1, 16.2, 16.3, 16.4**
"""

from __future__ import annotations

from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.insert_mode import FieldDef, InsertModeController

# =============================================================================
# Mock SmartBar — mimics the SmartBarProtocol for testing
# =============================================================================


class MockSmartBar:
    """Minimal SmartBar mock implementing SmartBarProtocol."""

    def __init__(self) -> None:
        self.value: str = "deploy --region us-east-1"
        self.placeholder: str = "Type a command"
        self._readiness: BarReadiness = BarReadiness.READY
        self._saved: bool = False
        self._saved_value: str = ""
        self._saved_placeholder: str = ""
        self._saved_readiness: BarReadiness = BarReadiness.READY
        self._classes: set[str] = set()
        self._focused: bool = False

    @property
    def readiness(self) -> BarReadiness:
        return self._readiness

    def save_state(self) -> None:
        self._saved = True
        self._saved_value = self.value
        self._saved_placeholder = self.placeholder
        self._saved_readiness = self._readiness

    def restore_state(self) -> None:
        if not self._saved:
            raise RuntimeError("restore_state() called without prior save_state()")
        self.value = self._saved_value
        self.placeholder = self._saved_placeholder
        self._readiness = self._saved_readiness
        self._saved = False
        self._classes.discard("editing")
        self._classes.discard("invalid")

    def enter_edit_mode(
        self, field_name: str, value: str, hint: str, *, secret: bool = False
    ) -> None:
        # `secret` mirrors the real SmartBar: a secret field masks the bar
        # while it is edited. Recorded so a test can assert on it; the
        # keyword must exist here or the mock silently stops matching the
        # collaborator it stands in for.
        self.secret = secret
        self.value = value
        self.placeholder = f"Edit: {field_name}"
        self._readiness = BarReadiness.EDITING

    def enter_invalid(self, error_msg: str) -> None:
        self._readiness = BarReadiness.INVALID

    def focus(self) -> None:
        self._focused = True

    def add_class(self, cls: str) -> None:
        self._classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self._classes.discard(cls)


# =============================================================================
# Test 1: enter_insert saves SmartBar state and sets editing mode
# =============================================================================


class TestActionEnterInsertSavesBarState:
    """Req 16.1: enter_insert saves SmartBar state and sets editing mode."""

    def _make_controller(self) -> tuple[InsertModeController, FocusState, MockSmartBar]:
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        return ctrl, fs, bar

    def test_action_enter_insert_saves_bar_state(self) -> None:
        """Enter INSERT: save_state() called, enter_edit_mode() called, FocusState → INSERT."""
        ctrl, fs, bar = self._make_controller()
        # Must be in NORMAL mode (as the app would be after panel toggle)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        original_value = bar.value  # "deploy --region us-east-1"
        field = FieldDef(name="region", value="us-west-2", source="")

        result = ctrl.enter_insert(field, return_zone=FocusZone.PANEL)

        # Verify successful entry
        assert result is True
        # SmartBar.save_state() was called
        assert bar._saved is True
        assert bar._saved_value == original_value
        # SmartBar.enter_edit_mode() was called — bar now shows field value
        assert bar.value == "us-west-2"
        assert bar.placeholder == "Edit: region"
        assert bar._readiness == BarReadiness.EDITING
        # "editing" class added
        assert "editing" in bar._classes
        # SmartBar focused
        assert bar._focused is True
        # FocusState transitions to INSERT
        assert fs.mode == FocusMode.INSERT


# =============================================================================
# Test 2: confirm_edit applies value, restores state, transitions to NORMAL
# =============================================================================


class TestActionConfirmEditAppliesAndRestores:
    """Req 16.2: confirm_edit applies value, restores state, transitions to NORMAL."""

    def _setup_insert(
        self,
    ) -> tuple[InsertModeController, FocusState, MockSmartBar, FieldDef]:
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        field = FieldDef(name="region", value="us-east-1", source="")
        ctrl.enter_insert(field)
        return ctrl, fs, bar, field

    def test_action_confirm_edit_applies_and_restores(self) -> None:
        """Confirm edit: value applied, restore_state() called, FocusState → NORMAL."""
        ctrl, fs, bar, field = self._setup_insert()
        original_bar_value = bar._saved_value  # Saved before entering INSERT

        # Simulate user editing
        bar.value = "eu-west-1"

        success, error = ctrl.confirm_edit()

        # Edit applied successfully
        assert success is True
        assert error is None
        # Value applied to field (fallback logic)
        assert field.value == "eu-west-1"
        assert field.source == "unsaved"
        # SmartBar.restore_state() was called — bar restored to original
        assert bar.value == original_bar_value
        assert bar._saved is False  # restore clears saved flag
        # "editing" class removed
        assert "editing" not in bar._classes
        # FocusState transitions back to NORMAL
        assert fs.mode == FocusMode.NORMAL
        assert fs.zone == FocusZone.PANEL

    def test_action_confirm_edit_with_callback(self) -> None:
        """Confirm edit uses apply callback when set (matching app pattern)."""
        ctrl, fs, bar, field = self._setup_insert()
        applied: list[tuple[FieldDef, str]] = []

        def on_apply(f: FieldDef, val: str) -> None:
            applied.append((f, val))
            f.value = val
            f.source = "cli"

        ctrl.set_apply_callback(on_apply)
        bar.value = "ap-southeast-1"

        success, _ = ctrl.confirm_edit()

        assert success is True
        assert len(applied) == 1
        assert applied[0] == (field, "ap-southeast-1")
        assert fs.mode == FocusMode.NORMAL


# =============================================================================
# Test 3: exit_insert restores state without applying, transitions to NORMAL
# =============================================================================


class TestActionExitInsertRestoresWithoutApplying:
    """Req 16.3: exit_insert restores state without applying, transitions to NORMAL."""

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

    def test_action_exit_insert_restores_without_applying(self) -> None:
        """Exit INSERT: restore_state() called, field value unchanged, FocusState → NORMAL."""
        ctrl, fs, bar, field = self._setup_insert()
        original_bar_value = bar._saved_value  # "deploy --region us-east-1"

        # Simulate user typing something (not yet confirmed)
        bar.value = "999"

        ctrl.exit_insert()

        # SmartBar.restore_state() was called — bar is back to original
        assert bar.value == original_bar_value
        assert bar._saved is False
        # "editing" class removed
        assert "editing" not in bar._classes
        # Field value unchanged — edit was NOT applied
        assert field.value == "30"
        assert field.source == ""  # unchanged from initial
        # FocusState transitions to NORMAL
        assert fs.mode == FocusMode.NORMAL
        assert fs.zone == FocusZone.PANEL
        # Controller no longer active
        assert ctrl.is_active is False


# =============================================================================
# Test 4: enter_insert requires NORMAL mode
# =============================================================================


class TestEnterInsertRequiresNormalMode:
    """Req 16.4: enter_insert requires FocusState in NORMAL mode to succeed."""

    def test_enter_insert_requires_normal_mode(self) -> None:
        """Attempt enter_insert from COMMAND mode → should fail (return False)."""
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        # Default FocusState is COMMAND mode
        assert fs.mode == FocusMode.COMMAND

        field = FieldDef(name="region", value="us-east-1", source="")
        result = ctrl.enter_insert(field)

        # Should fail — COMMAND → INSERT is not a valid transition
        assert result is False
        assert fs.mode == FocusMode.COMMAND  # unchanged
        assert ctrl.is_active is False
        # SmartBar state should not have been modified
        assert bar._saved is False
        assert bar._focused is False
        assert "editing" not in bar._classes


# =============================================================================
# Test 5: confirm_edit validation failure stays in INSERT
# =============================================================================


class TestConfirmEditValidationFailureStaysInsert:
    """Req 16.2 (validation gate): validation failure keeps INSERT mode active."""

    def test_confirm_edit_validation_failure_stays_insert(self) -> None:
        """Validator rejects value → (False, error_msg), FocusState stays INSERT."""

        def port_validator(v: str) -> tuple[bool, str]:
            try:
                port = int(v)
                if 1 <= port <= 65535:
                    return (True, "")
                return (False, f"Port {port} out of range (1-65535)")
            except ValueError:
                return (False, f"'{v}' is not a valid port number")

        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        field = FieldDef(name="port", value="8080", source="", validator=port_validator)
        ctrl.enter_insert(field)
        assert fs.mode == FocusMode.INSERT

        # Type an invalid value
        bar.value = "not-a-port"

        success, error = ctrl.confirm_edit()

        # Validation failed
        assert success is False
        assert error == "'not-a-port' is not a valid port number"
        # Bar transitions to INVALID readiness
        assert bar._readiness == BarReadiness.INVALID
        # FocusState stays INSERT — user can correct
        assert fs.mode == FocusMode.INSERT
        # Controller still active
        assert ctrl.is_active is True
        # Field value unchanged
        assert field.value == "8080"
