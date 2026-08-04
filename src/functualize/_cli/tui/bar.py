"""SmartBar widget — command input with readiness state machine.

Extends Textual's Input widget with a BarReadiness FSM that drives
border color CSS classes and posts ReadinessChanged messages on
state transitions. Supports INSERT mode repurposing via save/restore.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from textual.message import Message
from textual.widgets import Input

__all__ = ["BarReadiness", "SavedBarState", "SmartBar"]


class BarReadiness(Enum):
    """State machine for the SmartBar's visual readiness indicator."""

    GREY = "grey"  # No recognized command
    PENDING = "pending"  # Command recognized, missing required args
    READY = "ready"  # All args satisfied, executable
    EDITING = "editing"  # INSERT mode active (SmartBar repurposed)
    INVALID = "invalid"  # Validation failed in INSERT mode


@dataclass(frozen=True)
class SavedBarState:
    """Snapshot of SmartBar state before entering INSERT mode."""

    value: str
    cursor_position: int
    placeholder: str
    readiness: BarReadiness


# CSS class names for each readiness state
_READINESS_CLASSES = tuple(r.value for r in BarReadiness)


class SmartBar(Input):
    """Command composition input with readiness state machine.

    Posts ReadinessChanged when the readiness enum value changes.
    Manages border CSS classes corresponding to readiness states.
    """

    # --- Messages ---

    class RequestExecute(Message):
        """Posted when the user requests execution (Enter in READY state)."""

    class ReadinessChanged(Message):
        """Posted when readiness transitions to a new value."""

        def __init__(self, state: BarReadiness) -> None:
            super().__init__()
            self.state = state

    # --- Initialization ---

    def __init__(
        self,
        *,
        placeholder: str = "Type a command",
        id: str | None = None,  # noqa: A002
    ) -> None:
        super().__init__(placeholder=placeholder, id=id)
        self.select_on_focus = False  # Don't select-all when gaining focus
        self._readiness: BarReadiness = BarReadiness.GREY
        self._saved_state: SavedBarState | None = None
        self._validity_reason: str = ""

    # --- Properties ---

    @property
    def readiness(self) -> BarReadiness:
        """Current readiness state."""
        return self._readiness

    @property
    def validity_reason(self) -> str:
        """Human-readable reason for current readiness (for display)."""
        return self._validity_reason

    # --- Readiness management ---

    def _set_readiness(self, new: BarReadiness) -> None:
        """Update readiness, manage CSS classes, post message if changed."""
        if new == self._readiness:
            return

        # Remove all readiness classes, add the new one
        for cls in _READINESS_CLASSES:
            self.remove_class(cls)
        self.add_class(new.value)

        self._readiness = new
        self.post_message(self.ReadinessChanged(new))

    # --- Evaluation ---

    def evaluate(
        self,
        tokens: list[str],
        job_names: list[str],
        get_required_fields: Callable[[str], list[str]],
        get_fields: Callable[[str], list[Any]] | None = None,
    ) -> BarReadiness:
        """Evaluate command tokens and update readiness state.

        Args:
            tokens: Split command text from the bar.
            job_names: Known job names for matching.
            get_required_fields: Returns required field names for a job.
            get_fields: Optional callback returning FieldDescriptor-like objects
                with .name, .positional, .short_flag attributes. Enables detection
                of positional args and short flags as "provided".

        Returns:
            The new BarReadiness value.
        """
        if not tokens:
            self._validity_reason = "Type a command"
            self.placeholder = "Type a command"
            self._set_readiness(BarReadiness.GREY)
            return BarReadiness.GREY

        command = tokens[0]

        if command not in job_names:
            self._validity_reason = f"Unknown: {command}"
            self.placeholder = f"Unknown: {command}"
            self._set_readiness(BarReadiness.GREY)
            return BarReadiness.GREY

        # Command recognized — check required fields
        required = get_required_fields(command)

        # Build field metadata for positional/short-flag detection
        fields = get_fields(command) if get_fields else []
        positional_names: list[str] = [
            f.name for f in fields if getattr(f, "positional", False)
        ]
        short_to_name: dict[str, str] = {}
        for f in fields:
            short = getattr(f, "short_flag", None)
            if short:
                short_to_name[short.lstrip("-")] = f.name

        # Extract provided field names from tokens
        provided_names: set[str] = set()
        positional_idx = 0
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok.startswith("--") and len(tok) > 2:
                provided_names.add(tok[2:].replace("-", "_"))
                # Skip the value token if present
                i += 2
            elif tok.startswith("-") and len(tok) >= 2 and not tok[1:].isdigit():
                # Short flag: -g value
                flag_char = tok.lstrip("-")
                field_name = short_to_name.get(flag_char)
                if field_name:
                    provided_names.add(field_name)
                    # Skip the value token
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
            else:
                # Bare token → assign to next positional field
                if positional_idx < len(positional_names):
                    provided_names.add(positional_names[positional_idx])
                    positional_idx += 1
                i += 1

        missing = [f for f in required if f not in provided_names]

        if missing:
            # Show up to 3 missing field names
            display_missing = missing[:3]
            suffix = f" (+{len(missing) - 3})" if len(missing) > 3 else ""
            reason = f"Missing: {', '.join(display_missing)}{suffix}"
            self._validity_reason = reason
            self.placeholder = reason
            self._set_readiness(BarReadiness.PENDING)
            return BarReadiness.PENDING

        self._validity_reason = "Ready to run"
        self.placeholder = "Ready to run"
        self._set_readiness(BarReadiness.READY)
        return BarReadiness.READY

    # --- State save/restore (INSERT mode) ---

    def save_state(self) -> None:
        """Save current value, cursor position, placeholder, and readiness.

        Called before entering INSERT mode so the bar can be restored later.
        """
        self._saved_state = SavedBarState(
            value=self.value,
            cursor_position=self.cursor_position,
            placeholder=str(self.placeholder),
            readiness=self._readiness,
        )

    def restore_state(self) -> None:
        """Restore previously saved state after INSERT mode ends.

        Raises:
            RuntimeError: If no state was saved via save_state().
        """
        if self._saved_state is None:
            msg = "restore_state() called without prior save_state()"
            raise RuntimeError(msg)

        saved = self._saved_state
        self.value = saved.value
        self.cursor_position = saved.cursor_position
        self.placeholder = saved.placeholder
        self._saved_state = None

        # Remove editing/invalid classes and restore readiness
        self.remove_class("editing")
        self.remove_class("invalid")
        self._set_readiness(saved.readiness)

    # --- INSERT mode operations ---

    def enter_edit_mode(self, field_name: str, value: str, hint: str) -> None:
        """Repurpose the bar for field editing (INSERT mode).

        Args:
            field_name: Name of the field being edited.
            value: Current field value to populate the bar with.
            hint: Tooltip/display text for context.
        """
        self.value = value
        self.placeholder = f"Edit: {field_name}"
        self._validity_reason = hint
        self._set_readiness(BarReadiness.EDITING)

    def enter_invalid(self, error_msg: str) -> None:
        """Mark bar as invalid (validation failed in INSERT mode).

        Args:
            error_msg: Error message describing the validation failure.
        """
        self._validity_reason = error_msg
        self.remove_class("editing")
        self._set_readiness(BarReadiness.INVALID)
