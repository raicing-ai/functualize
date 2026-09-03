"""SmartBar widget — command input with readiness state machine.

Extends Textual's Input widget with a BarReadiness FSM that drives
border color CSS classes and posts ReadinessChanged messages on
state transitions. Supports INSERT mode repurposing via save/restore.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from textual.message import Message
from textual.widgets import Input

if TYPE_CHECKING:
    from functualize._cli.tui.cli_arg_parser import TuiCommandResolution

__all__ = ["BarReadiness", "SavedBarState", "SmartBar"]


def _is_negative_number(token: str) -> bool:
    """True for a `-`-prefixed token that is a number, not a flag.

    `-5` and `-1.5` are values a positional can legitimately take. Without
    this the flag check greys out a perfectly good line.
    """
    try:
        float(token)
    except ValueError:
        return False
    return True


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
        self._suppress_autocomplete: bool = False
        """Set while editing a secret — see :meth:`enter_edit_mode`."""

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
        resolution: TuiCommandResolution | None = None,
        is_non_job_command: Callable[[str], bool] | None = None,
    ) -> BarReadiness:
        """Evaluate command tokens and update readiness state.

        Args:
            tokens: Split command text from the bar.
            job_names: Known job names for matching.
            get_required_fields: Returns required field names for a job.
            get_fields: Optional callback returning FieldDescriptor-like objects
                with .name, .positional, .short_flag attributes. Enables detection
                of positional args and short flags as "provided".
            resolution: The walk of ``tokens``, from ``resolve_tui_command``.
                Required for a correct answer under groups: ``job_names``
                contains top-level **group** nodes as well as jobs, so matching
                on the bar's first token makes `deploy` a recognized command
                whose required-field list is empty — and the bar reports READY
                no matter what the real job is still missing. When omitted the
                first token is used, which is right for an ungrouped project.
            is_non_job_command: Returns True for a top-level command that is
                not a job — a builtin. The group trie holds **jobs only**, so
                the walk cannot resolve `builtin env` and returns ``None``;
                without this predicate every builtin greys out the moment a
                project declares a single ``GroupOptions`` subclass, and
                ``action_execute`` (gated on READY) turns Enter into a silent
                no-op. That is the exact failure ``_get_command_names``'s
                docstring exists to prevent.

        Returns:
            The new BarReadiness value.
        """
        if not tokens:
            self._validity_reason = "Type a command"
            self.placeholder = "Type a command"
            self._set_readiness(BarReadiness.GREY)
            return BarReadiness.GREY

        if resolution is None:
            # One owner of "no trie -> flat", rather than a second copy of the
            # rule here: the resolver's own trie-less path takes the first
            # token as the job and the rest as its arguments.
            from functualize._cli.tui.cli_arg_parser import resolve_tui_command

            resolution = resolve_tui_command(None, tokens)

        command = resolution.job_name
        args = resolution.args

        if command is None and is_non_job_command is not None:
            # A builtin is not in the trie and never will be — the CLI's own
            # walk does not know about them either. Rather than teach the
            # resolver a second command model, recognise the one shape the
            # walk cannot reach and fall back to the flat reading, which is
            # what a builtin has always been.
            head = tokens[0]
            if is_non_job_command(head):
                command = head
                args = list(tokens[1:])

        if command is None:
            # The walk did not reach a runnable job. Distinguish a path still
            # being typed from a name that means nothing: `deploy` is a real
            # group and deserves an invitation, `nonsense` deserves a refusal.
            # The head is for the message only — nothing is resolved from it.
            head, *_rest = tokens
            reason = (
                f"Incomplete: {' '.join(tokens)}…"
                if head in job_names
                else f"Unknown: {head}"
            )
            self._validity_reason = reason
            self.placeholder = reason
            self._set_readiness(BarReadiness.GREY)
            return BarReadiness.GREY

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

        # Extract provided field names from the job's own arguments. Walking
        # the whole line instead would count path segments as positionals —
        # `web` filling `image` — and mid-path group flags as job flags.
        provided_names: set[str] = set()
        positional_idx = 0
        i = 0
        while i < len(args):
            tok = args[i]
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
                    if i + 1 < len(args) and not args[i + 1].startswith("-"):
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

        # A flag the job does not declare is not a missing field — it is a
        # command that will not run. This is where a group's flag written
        # *after* the job surfaces: position is what separates a group flag
        # from the job's own, so `deploy web run --env prod` is a job flag
        # called `env`, and there is no such thing. Reporting READY there sent
        # the user to a click error they had no warning of.
        # The set is built from the same rules the click param builder applies
        # (`app/adapters/click_params.py`), field by field, rather than from
        # field *names*: what click accepts as `--x` is not "every field named
        # x". Two of its rules bite.
        #
        #   * A **positional** field becomes a `click.Argument`, which has no
        #     flag spelling at all — `deploy web run --image v1.2` is refused
        #     by click even though `image` is a real field.
        #   * A boolean's negative half is decided by `negative_flag_for`, the
        #     same rule the click builders render from. It used to be allowed
        #     only for a bool *without* a short flag, mirroring a builder that
        #     dropped the pair in that case; both now emit it, and a sibling
        #     literally named `no_x` still suppresses it.
        from functualize.app.utils import negative_flag_for

        known: set[str] = set()
        known_short: set[str] = set()
        field_names = {f.name for f in fields}
        for f in fields:
            if getattr(f, "positional", False):
                # Argument, not Option: given by being typed, never by name.
                continue
            stdin_flag = getattr(f, "stdin_flag", None)
            if getattr(f, "is_stdin", False) and stdin_flag:
                known.add(stdin_flag.lstrip("-").replace("-", "_"))
                continue
            known.add(f.name)
            short = getattr(f, "short_flag", None)
            if short:
                known_short.add(short.lstrip("-"))
            if (getattr(f, "type_annotation", "") or "") == "bool":
                negative = negative_flag_for(f.name, field_names)
                if negative:
                    known.add(negative[2:].replace("-", "_"))

        # `fields` empty means "nothing known about this command" (a builtin,
        # or a get_fields callback that was not supplied) — not "no flag is
        # valid". Skip rather than grey out everything.
        if fields:
            for tok in args:
                if tok.startswith("--"):
                    if len(tok) <= 2:
                        continue
                    spelled = tok[2:].split("=", 1)[0]
                    if spelled.replace("-", "_") in known:
                        continue
                elif tok.startswith("-") and len(tok) >= 2:
                    if _is_negative_number(tok):
                        continue
                    spelled = tok[1:].split("=", 1)[0]
                    if spelled in known_short:
                        continue
                else:
                    continue
                reason = f"Unknown flag: {tok.split('=', 1)[0]}"
                self._validity_reason = reason
                self.placeholder = reason
                self._set_readiness(BarReadiness.GREY)
                return BarReadiness.GREY

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
        # Unmask first, before anything that can raise. COMMAND mode is never
        # masked, and a bar left in `password` would silently hide every
        # subsequent command the user types — so unmasking must not be
        # conditional on the restore succeeding.
        self.password = False
        self._suppress_autocomplete = False

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

    def enter_edit_mode(
        self, field_name: str, value: str, hint: str, *, secret: bool = False
    ) -> None:
        """Repurpose the bar for field editing (INSERT mode).

        When ``secret`` is set the bar masks its own display (Textual ``Input``
        renders bullets for ``password``), so a credential is not echoed onto a
        screen the user may be sharing. Autocomplete is suppressed with it:
        a dropdown offering completions for a masked value would re-render that
        value one row below the mask, which defeats the whole point.

        Args:
            field_name: Name of the field being edited.
            value: Current field value to populate the bar with.
            hint: Tooltip/display text for context.
            secret: Mask the input as it is typed.
        """
        self.value = value
        self.placeholder = f"Edit: {field_name}"
        self.password = secret
        self._suppress_autocomplete = secret
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
