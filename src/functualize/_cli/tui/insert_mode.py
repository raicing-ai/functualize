"""INSERT mode controller — manages SmartBar repurposing for field editing.

Coordinates the lifecycle of INSERT mode: entering (save bar state, set
edit value, add "editing" class, focus bar), confirming (validate, apply
linked edit, restore bar, exit INSERT), and cancelling (restore bar
without applying, exit INSERT).

Implements the validation gate: invalid values transition to INVALID
readiness, keeping INSERT mode for correction. Further input clears the
error and returns to EDITING readiness.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6, 13.1, 13.2, 13.3, 13.4, 13.5**
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.panels.config_table import EditOrigin, FieldDef

__all__ = [
    "FieldDef",
    "InsertModeController",
    "ValidatorFn",
]


# Type alias for field validators: takes a value, returns (valid, error_msg)
ValidatorFn = Callable[[str], tuple[bool, str]]


class SmartBarProtocol(Protocol):
    """Protocol defining the SmartBar interface needed by InsertModeController."""

    @property
    def value(self) -> str: ...

    @value.setter
    def value(self, v: str) -> None: ...

    @property
    def readiness(self) -> Any: ...

    def save_state(self) -> None: ...
    def restore_state(self) -> None: ...
    def enter_edit_mode(self, field_name: str, value: str, hint: str) -> None: ...
    def enter_invalid(self, error_msg: str) -> None: ...
    # These three mirror `textual.widget.Widget`, which SmartBar inherits:
    # variadic class names, an `update` keyword, and a `Self` return. Declaring
    # the narrower `(cls: str) -> None` shape the call sites happen to use made
    # the real widget fail to satisfy this protocol. Return `Any` because the
    # callers discard it.
    def focus(self, scroll_visible: bool = ...) -> Any: ...
    def add_class(self, *class_names: str, update: bool = ...) -> Any: ...
    def remove_class(self, *class_names: str, update: bool = ...) -> Any: ...


class InsertModeController:
    """Manages the INSERT mode lifecycle for SmartBar field editing.

    Coordinates between the FocusState FSM, the SmartBar widget, and
    field metadata to implement the full INSERT mode flow:

    1. enter_insert: save bar → set edit value → add "editing" class → focus bar
    2. confirm_edit: validate → apply linked edit → restore bar → exit INSERT
    3. exit_insert: restore bar without applying → exit INSERT
    4. on_bar_changed: clear INVALID state on further input
    """

    def __init__(self, focus_state: FocusState, bar: SmartBarProtocol) -> None:
        self._focus_state = focus_state
        self._bar = bar
        self._editing_field: FieldDef | None = None
        self._return_zone: FocusZone = FocusZone.PANEL
        self._apply_callback: Callable[[FieldDef, str], None] | None = None

    @property
    def editing_field(self) -> FieldDef | None:
        """The field currently being edited, or None if not in INSERT mode."""
        return self._editing_field

    @property
    def is_active(self) -> bool:
        """True if the controller is managing an active INSERT mode session."""
        return self._editing_field is not None

    def set_apply_callback(self, cb: Callable[[FieldDef, str], None]) -> None:
        """Set the callback invoked when an edit is confirmed and valid.

        The callback receives (field, new_value) and should apply the linked
        edit (e.g., set field.value, field.source = "unsaved", etc.).
        """
        self._apply_callback = cb

    def enter_insert(
        self,
        field: FieldDef,
        return_zone: FocusZone = FocusZone.PANEL,
    ) -> bool:
        """Enter INSERT mode for the given field.

        Saves bar state, populates with field value, adds "editing" class,
        sets EDITING readiness, focuses bar, and transitions FSM to INSERT.

        Args:
            field: The FieldDef to edit.
            return_zone: Zone to return focus to on exit (default: PANEL).

        Returns:
            True if INSERT mode was entered successfully, False if the
            FSM transition was rejected (e.g., not in NORMAL mode).
        """
        # Attempt FSM transition: NORMAL → INSERT
        if not self._focus_state.enter_insert():
            return False

        self._editing_field = field
        self._return_zone = return_zone

        # Save current bar state (Req 4.1)
        self._bar.save_state()

        # Repurpose bar for editing (Req 4.2)
        hint = f"Editing {field.name}"
        self._bar.enter_edit_mode(field.name, field.value, hint)

        # Add "editing" class and focus (Req 4.2)
        self._bar.add_class("editing")
        self._bar.focus()

        return True

    def confirm_edit(self) -> tuple[bool, str | None]:
        """Confirm the edit: validate, apply, restore, exit INSERT.

        Returns:
            A tuple (success, error_msg_or_None).
            - (True, None) if the value was valid and applied.
            - (False, error_msg) if validation failed — bar transitions
              to INVALID, INSERT mode remains active for correction.
        """
        if self._editing_field is None:
            return (False, "No field being edited")

        field = self._editing_field
        value = self._bar.value

        # Validation gate (Req 13.1)
        valid, error_msg = self._validate(field, value)

        if not valid:
            # Validation failed → INVALID readiness, keep INSERT (Req 4.6, 13.2)
            self._bar.enter_invalid(error_msg)
            return (False, error_msg)

        # Valid value — apply linked edit (Req 4.3, 13.4)
        if self._apply_callback is not None:
            self._apply_callback(field, value)
        else:
            # Fallback: directly update field. — use "unsaved"
            # for terminology consistency (this branch is currently unreachable
            # since app.py always registers an apply_callback).
            field.value = value
            field.source = "unsaved"
            field.edit_origin = EditOrigin.VALUE

        # Restore bar and exit INSERT (Req 4.3)
        self._restore_and_exit()
        return (True, None)

    def exit_insert(self) -> None:
        """Cancel and exit INSERT mode without applying any changes.

        Restores bar state and transitions back to NORMAL mode with
        the return zone (Req 4.4, 13.5).
        """
        if self._editing_field is None:
            return

        self._restore_and_exit()

    def on_bar_changed(self) -> None:
        """Called when bar input changes — clears INVALID state.

        If the bar is in INVALID readiness (after a failed validation),
        typing further input clears the error and returns to EDITING
        readiness (Req 13.3).
        """
        if self._editing_field is None:
            return

        # Import here to avoid circular dependency issues at module level
        from functualize._cli.tui.bar import BarReadiness

        if self._bar.readiness == BarReadiness.INVALID:
            # Clear error, return to EDITING (Req 13.3)
            self._bar.enter_edit_mode(
                self._editing_field.name,
                self._bar.value,
                f"Editing {self._editing_field.name}",
            )

    # --- Private helpers ---

    def _validate(self, field: FieldDef, value: str) -> tuple[bool, str]:
        """Validate a value against the field's validator.

        If no validator is defined, accepts any non-empty value (Req 13.1).

        Returns:
            (is_valid, error_message). error_message is empty if valid.
        """
        # No validator → accept any non-empty value
        if field.validator is None:
            if not value.strip():
                return (False, "Value cannot be empty")
            return (True, "")

        # Use the field's validator function. config_table.FieldDef declares
        # `validator` as `str | None` for forward-compat with named/serialized
        # validators, but the only runtime producers (this module's callers,
        # see tests/_cli/test_app_insert_mode_unit.py) always pass a callable
        # matching ValidatorFn. Cast to reconcile the declared type with the
        # actual runtime contract used here.
        return cast("ValidatorFn", field.validator)(value)

    def _restore_and_exit(self) -> None:
        """Restore bar state, remove editing class, exit INSERT mode."""
        # Remove "editing" class (Req 4.3, 4.4)
        self._bar.remove_class("editing")

        # Restore saved bar state
        self._bar.restore_state()

        # Clear editing field
        self._editing_field = None

        # Transition FSM: INSERT → NORMAL with return zone (Req 4.3, 4.4, 13.5)
        self._focus_state.transition(FocusMode.NORMAL, self._return_zone)
