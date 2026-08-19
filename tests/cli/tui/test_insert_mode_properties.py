# Feature: tui-v3-integration, Property 14: Validation gates edit application
"""Property-based tests for INSERT mode validation gate.

Tests InsertModeController from functualize._cli.tui.insert_mode:
- Property 14: Validation gates edit application

Generate fields with validators + valid/invalid values; verify:
- invalid → INVALID readiness + field.value unchanged + FocusMode stays INSERT
- valid → field.value applied + linked edit callback invoked + FocusMode back to NORMAL

**Validates: Requirements 13.1, 13.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.bar import BarReadiness
from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.insert_mode import FieldDef, InsertModeController, ValidatorFn

# =============================================================================
# Helpers — Mock SmartBar (same pattern as test_insert_mode.py)
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
        # Match real bar behavior: remove all readiness classes, add "editing"
        for cls in ("grey", "pending", "ready", "editing", "invalid"):
            self._classes.discard(cls)
        self._classes.add("editing")
        self._readiness = BarReadiness.EDITING

    def enter_invalid(self, error_msg: str) -> None:
        self._validity_reason = error_msg
        # Match real bar behavior: remove all readiness classes, add "invalid"
        for cls in ("grey", "pending", "ready", "editing", "invalid"):
            self._classes.discard(cls)
        self._classes.add("invalid")
        self._readiness = BarReadiness.INVALID

    def focus(self) -> None:
        self._focused = True

    def add_class(self, cls: str) -> None:
        self._classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self._classes.discard(cls)


# =============================================================================
# Validators used in property generation
# =============================================================================


def _always_valid(v: str) -> tuple[bool, str]:
    """Validator that always passes."""
    return (True, "")


def _always_invalid(v: str) -> tuple[bool, str]:
    """Validator that always fails."""
    return (False, "always fails")


def _numeric_only(v: str) -> tuple[bool, str]:
    """Validator that accepts only numeric strings."""
    try:
        int(v)
        return (True, "")
    except ValueError:
        return (False, f"'{v}' is not a number")


def _max_length_10(v: str) -> tuple[bool, str]:
    """Validator that accepts strings with length <= 10."""
    if len(v) <= 10:
        return (True, "")
    return (False, f"value too long ({len(v)} > 10)")


# =============================================================================
# Strategies
# =============================================================================

# Strategy for generating non-empty strings (valid when no validator is set)
_nonempty_text = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
)

# Strategy for whitespace-only strings (invalid when no validator)
_whitespace_only = st.from_regex(r"^\s+$", fullmatch=True)

# Numeric strings
_numeric_str = st.integers(min_value=-9999, max_value=9999).map(str)

# Non-numeric strings (guaranteed non-empty, no digits only)
_non_numeric_str = st.text(
    alphabet=st.characters(categories=("L", "P", "S")),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "" and not _is_numeric(s))

# Short strings (length <= 10)
_short_str = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=10,
)

# Long strings (length > 10)
_long_str = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=11,
    max_size=30,
)

# Field names
_field_name = st.text(
    alphabet=st.characters(categories=("L",), min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=15,
)

# Original field values (any non-empty string)
_original_value = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=20,
)


def _is_numeric(s: str) -> bool:
    """Check if string is parseable as int."""
    try:
        int(s)
        return True
    except ValueError:
        return False


@st.composite
def _field_with_invalid_input(draw: st.DrawFn) -> tuple[FieldDef, str]:
    """Generate a FieldDef with a validator and a value that will FAIL validation.

    Returns (field, invalid_value) tuple.
    """
    name = draw(_field_name)
    original = draw(_original_value)

    validator_choice = draw(
        st.sampled_from(["always_invalid", "numeric", "max_length", "no_validator"])
    )

    if validator_choice == "always_invalid":
        validator: ValidatorFn | None = _always_invalid
        # Any non-empty value fails
        value = draw(_nonempty_text)
    elif validator_choice == "numeric":
        validator = _numeric_only
        # Non-numeric strings fail
        value = draw(_non_numeric_str)
    elif validator_choice == "max_length":
        validator = _max_length_10
        # Long strings fail
        value = draw(_long_str)
    else:
        # No validator → whitespace-only values are invalid
        validator = None
        value = draw(_whitespace_only)

    field = FieldDef(name=name, value=original, source="default", validator=validator)
    return (field, value)


@st.composite
def _field_with_valid_input(draw: st.DrawFn) -> tuple[FieldDef, str]:
    """Generate a FieldDef with a validator and a value that will PASS validation.

    Returns (field, valid_value) tuple.
    """
    name = draw(_field_name)
    original = draw(_original_value)

    validator_choice = draw(
        st.sampled_from(["always_valid", "numeric", "max_length", "no_validator"])
    )

    if validator_choice == "always_valid":
        validator: ValidatorFn | None = _always_valid
        # Any value passes
        value = draw(_nonempty_text)
    elif validator_choice == "numeric":
        validator = _numeric_only
        # Numeric strings pass
        value = draw(_numeric_str)
    elif validator_choice == "max_length":
        validator = _max_length_10
        # Short strings pass
        value = draw(_short_str)
    else:
        # No validator → any non-empty, non-whitespace value is valid
        validator = None
        value = draw(_nonempty_text)

    field = FieldDef(name=name, value=original, source="default", validator=validator)
    return (field, value)


# =============================================================================
# Property 14: Validation gates edit application
# =============================================================================


@pytest.mark.slow
class TestValidationGatesEditApplication:
    """Property 14: Validation gates edit application.

    For fields with validators + valid/invalid values:
    - invalid → INVALID readiness + field.value unchanged + FocusMode stays INSERT
    - valid → field.value applied + FocusMode back to NORMAL

    **Validates: Requirements 13.1, 13.2**
    """

    @given(data=_field_with_invalid_input())
    def test_invalid_value_rejected(self, data: tuple[FieldDef, str]) -> None:
        """Invalid values → INVALID readiness, field unchanged, mode stays INSERT."""
        field, invalid_value = data
        original_value = field.value

        # Set up controller in INSERT mode
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        ctrl.enter_insert(field)

        # Simulate user typing the invalid value
        bar.value = invalid_value

        # Confirm the edit
        success, error_msg = ctrl.confirm_edit()

        # Assertions: Req 13.2 — validation fails
        assert success is False, (
            f"Expected confirm_edit to fail for invalid value '{invalid_value}'"
        )
        assert error_msg is not None and len(error_msg) > 0, (
            "Expected non-empty error message on validation failure"
        )
        # Bar should be in INVALID readiness
        assert bar.readiness == BarReadiness.INVALID, (
            f"Expected INVALID readiness, got {bar.readiness.name}"
        )
        # FocusMode remains INSERT
        assert fs.mode == FocusMode.INSERT, (
            f"Expected mode to stay INSERT, got {fs.mode.name}"
        )
        # Field value is unchanged
        assert field.value == original_value, (
            f"Expected field.value unchanged at '{original_value}', got '{field.value}'"
        )
        # Controller is still active
        assert ctrl.is_active is True

    @given(data=_field_with_valid_input())
    def test_valid_value_applied(self, data: tuple[FieldDef, str]) -> None:
        """Valid values → applied, FocusMode back to NORMAL."""
        field, valid_value = data

        # Set up controller in INSERT mode
        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)

        # Track apply callback invocations
        applied: list[tuple[FieldDef, str]] = []

        def on_apply(f: FieldDef, val: str) -> None:
            applied.append((f, val))
            f.value = val
            f.source = "cli"
            f.edit_origin = "value"

        ctrl.set_apply_callback(on_apply)
        ctrl.enter_insert(field)

        # Simulate user typing the valid value
        bar.value = valid_value

        # Confirm the edit
        success, error_msg = ctrl.confirm_edit()

        # Assertions: Req 13.1 — validation passes
        assert success is True, (
            f"Expected confirm_edit to succeed for valid value '{valid_value}', "
            f"but got error: {error_msg}"
        )
        assert error_msg is None, (
            f"Expected no error message on success, got '{error_msg}'"
        )
        # FocusMode is NORMAL (exited INSERT)
        assert fs.mode == FocusMode.NORMAL, (
            f"Expected mode back to NORMAL, got {fs.mode.name}"
        )
        # Apply callback was invoked with the correct value
        assert len(applied) == 1, (
            f"Expected apply callback called once, got {len(applied)} calls"
        )
        assert applied[0] == (field, valid_value), (
            f"Expected apply callback with (field, '{valid_value}'), "
            f"got (field, '{applied[0][1]}')"
        )
        # Field value should be updated (by the callback)
        assert field.value == valid_value, (
            f"Expected field.value='{valid_value}', got '{field.value}'"
        )
        # Controller is no longer active
        assert ctrl.is_active is False

    @given(data=_field_with_valid_input())
    def test_valid_value_restores_bar(self, data: tuple[FieldDef, str]) -> None:
        """Valid values → bar state is restored after edit application."""
        field, valid_value = data

        fs = FocusState()
        bar = MockSmartBar()
        # Capture original bar state
        original_bar_value = bar.value
        original_bar_placeholder = bar.placeholder

        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        ctrl.enter_insert(field)

        # Simulate user typing the valid value
        bar.value = valid_value
        ctrl.confirm_edit()

        # Bar should be restored to its original state
        assert bar.value == original_bar_value, (
            f"Expected bar.value restored to '{original_bar_value}', got '{bar.value}'"
        )
        assert bar.placeholder == original_bar_placeholder, (
            f"Expected bar.placeholder restored to '{original_bar_placeholder}', "
            f"got '{bar.placeholder}'"
        )
        # "editing" class should be removed
        assert "editing" not in bar._classes

    @given(data=_field_with_invalid_input())
    def test_invalid_value_keeps_bar_editable(self, data: tuple[FieldDef, str]) -> None:
        """Invalid values → bar stays in INSERT with INVALID readiness, user can retry."""
        field, invalid_value = data

        fs = FocusState()
        bar = MockSmartBar()
        ctrl = InsertModeController(fs, bar)
        fs.force(FocusMode.NORMAL, FocusZone.PANEL)
        ctrl.enter_insert(field)

        bar.value = invalid_value
        ctrl.confirm_edit()

        # "invalid" class is present (visual feedback for validation failure)
        assert "invalid" in bar._classes, (
            "Expected 'invalid' class after validation failure"
        )
        # "editing" class is removed (replaced by "invalid" readiness class)
        assert "editing" not in bar._classes, (
            "Expected 'editing' class removed — replaced by 'invalid'"
        )
        # Bar readiness is INVALID
        assert bar.readiness == BarReadiness.INVALID
        # User can still type (FocusMode is INSERT)
        assert fs.mode == FocusMode.INSERT
