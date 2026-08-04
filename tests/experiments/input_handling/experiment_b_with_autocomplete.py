"""Experiment B Extended: Repurpose SmartBar with Autocomplete & Validation.

Demonstrates how the SmartBar-repurpose approach works with:
1. Enum autocomplete — field with fixed choices (e.g., log_level: debug|info|warning|error)
2. Path autocomplete — field that suggests filesystem paths
3. Validation — reject invalid values on Enter, show error, stay in INSERT mode

The key insight: the SmartBar already has textual-autocomplete attached. When we
repurpose it for editing, we swap the completer's candidate source to return
field-specific choices instead of command completions. The dropdown widget stays
the same — only the data source changes.

Architecture:
    SmartBar (Input) ← always the same widget
    AutoComplete overlay ← already attached, shows dropdown
    EditCompleter (swappable) ← provides candidates based on mode
        mode="command" → job names, flags, etc.
        mode="field_edit" → enum choices, path suggestions for current field

Run:
    uv run python -m experiments.input_handling.experiment_b_with_autocomplete
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Input, Static

# Try to import textual-autocomplete (optional)
try:
    from textual_autocomplete import AutoComplete, DropdownItem
    from textual_autocomplete._autocomplete import TargetState

    HAS_AUTOCOMPLETE = True
except ImportError:
    HAS_AUTOCOMPLETE = False


# ─── Field Metadata ──────────────────────────────────────────────────────────


@dataclass
class FieldMeta:
    """Metadata about a config field — used for autocomplete and validation."""

    name: str
    value: str
    source: str
    # Autocomplete
    choices: list[str] | None = None  # Enum choices
    is_path: bool = False  # Show path suggestions
    # Validation
    validator: Any = None  # Callable[[str], str | None] → error message or None


def _validate_int(value: str) -> str | None:
    """Validate that value is a positive integer."""
    try:
        n = int(value)
        if n <= 0:
            return "Must be a positive integer"
        return None
    except ValueError:
        return f"'{value}' is not a valid integer"


def _validate_bool(value: str) -> str | None:
    """Validate boolean-like values."""
    if value.lower() in ("true", "false", "yes", "no", "1", "0"):
        return None
    return f"'{value}' is not a boolean (use true/false)"


# ─── Swappable Completer ─────────────────────────────────────────────────────


class EditCompleter:
    """Swappable autocomplete completer.

    When mode="command": returns command-like suggestions (simulated).
    When mode="field_edit": returns choices for the field being edited.
    """

    def __init__(self) -> None:
        self._mode: str = "command"
        self._choices: list[str] = []
        self._field_name: str = ""
        self._is_path: bool = False

    def set_command_mode(self) -> None:
        """Switch to command autocomplete mode."""
        self._mode = "command"
        self._choices = []
        self._field_name = ""
        self._is_path = False

    def set_edit_mode(
        self,
        field_name: str,
        choices: list[str] | None = None,
        is_path: bool = False,
    ) -> None:
        """Switch to field-edit autocomplete mode."""
        self._mode = "field_edit"
        self._field_name = field_name
        self._choices = choices or []
        self._is_path = is_path

    @property
    def mode(self) -> str:
        return self._mode

    def get_items(self, value: str) -> list[DropdownItem] | list[dict]:
        """Return candidates based on current mode and input value."""
        if self._mode == "command":
            return self._command_candidates(value)
        elif self._mode == "field_edit":
            return self._edit_candidates(value)
        return []

    def _command_candidates(self, value: str) -> list[Any]:
        """Simulated command candidates."""
        commands = ["deploy", "test", "build", "lint", "format", "migrate"]
        partial = value.lower()
        matches = [c for c in commands if partial in c] if partial else commands
        if not HAS_AUTOCOMPLETE:
            return [{"main": m} for m in matches[:10]]
        return [DropdownItem(main=m) for m in matches[:10]]

    def _edit_candidates(self, value: str) -> list[Any]:
        """Candidates for field editing: enum choices or path suggestions."""
        candidates: list[Any] = []
        partial = value.lower()

        # Enum choices
        if self._choices:
            for choice in self._choices:
                if partial and partial not in choice.lower():
                    continue
                if HAS_AUTOCOMPLETE:
                    candidates.append(DropdownItem(main=choice))
                else:
                    candidates.append({"main": choice})

        # Path suggestions
        if self._is_path:
            candidates.extend(self._path_candidates(value))

        return candidates[:20]

    def _path_candidates(self, partial: str) -> list[Any]:
        """Scan filesystem for path suggestions."""
        candidates: list[Any] = []
        try:
            base = Path(partial) if partial else Path(".")
            if not base.exists():
                base = base.parent
            if base.is_dir():
                for entry in sorted(base.iterdir())[:15]:
                    name = str(entry)
                    if partial and not name.startswith(partial):
                        continue
                    suffix = "/" if entry.is_dir() else ""
                    display = f"{name}{suffix}"
                    if HAS_AUTOCOMPLETE:
                        candidates.append(DropdownItem(main=display))
                    else:
                        candidates.append({"main": display})
        except (PermissionError, OSError):
            pass
        return candidates


# ─── Custom AutoComplete widget that uses the swappable completer ─────────────

if HAS_AUTOCOMPLETE:

    class SwappableAutoComplete(AutoComplete):
        """AutoComplete that delegates to EditCompleter for candidates."""

        def __init__(self, target: Input, completer: EditCompleter, **kwargs) -> None:
            super().__init__(target, candidates=None, **kwargs)
            self._completer = completer

        def get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
            return self._completer.get_items(target_state.text)

        def get_search_string(self, target_state: TargetState) -> str:
            return target_state.text

        def should_show_dropdown(self, search_string: str) -> bool:
            """Show dropdown when there are candidates and in edit mode."""
            if self._completer.mode == "field_edit":
                return self.option_list.option_count > 0
            # In command mode, show only when user has typed something
            return bool(search_string.strip()) and self.option_list.option_count > 0


# ─── Main App ────────────────────────────────────────────────────────────────


class SmartBarAutoCompleteApp(App[None]):
    """Extended Option B: SmartBar + AutoComplete + Validation."""

    CSS = """
    Screen { height: auto; }
    #header { height: 1; background: $primary; color: $text; padding: 0 1; }
    #smart-bar { width: 100%; }
    #smart-bar.editing { border: tall green; }
    #smart-bar.invalid { border: tall red; }
    #validation-msg { height: 1; display: none; color: red; padding: 0 1; }
    #validation-msg.visible { display: block; }
    #panel-container { display: none; height: auto; min-height: 3; max-height: 10; }
    #panel-container.active { display: block; }
    #status { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    AutoComplete {
        background: $surface-lighten-1;
        padding: 0 1;
        margin: 0 1 0 1;
    }
    AutoComplete > .autocomplete--highlight-match {
        color: $accent;
        text-style: bold;
    }
    AutoComplete > OptionList {
        background: $surface-lighten-1;
        border: round $secondary;
        padding: 0 1;
    }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._mode = "command"  # command | normal | insert
        self._edit_row_key: str | None = None
        self._edit_field: FieldMeta | None = None
        # Saved SmartBar state
        self._saved_bar_text: str = ""
        self._saved_bar_cursor: int = 0
        self._saved_bar_placeholder: str = ""
        # Completer (shared between command mode and edit mode)
        self._completer = EditCompleter()
        # Table data with rich metadata
        self._fields: dict[str, FieldMeta] = {
            "log_level": FieldMeta(
                name="log_level",
                value="info",
                source="config.toml",
                choices=["debug", "info", "warning", "error", "critical"],
            ),
            "timeout": FieldMeta(
                name="timeout",
                value="30",
                source="default",
                validator=_validate_int,
            ),
            "verbose": FieldMeta(
                name="verbose",
                value="false",
                source="env",
                choices=["true", "false"],
                validator=_validate_bool,
            ),
            "output_dir": FieldMeta(
                name="output_dir",
                value="/tmp",
                source="cli",
                is_path=True,
            ),
            "format": FieldMeta(
                name="format",
                value="json",
                source="default",
                choices=["json", "yaml", "toml", "csv", "table"],
            ),
        }

    def compose(self) -> ComposeResult:
        yield Static(
            " Option B + AutoComplete + Validation", id="header"
        )
        smart_bar = Input(
            placeholder="SmartBar (type commands)...", id="smart-bar"
        )
        yield smart_bar

        # Attach autocomplete if available
        if HAS_AUTOCOMPLETE:
            yield SwappableAutoComplete(
                smart_bar,
                self._completer,
                prevent_default_enter=False,
                prevent_default_tab=False,
            )

        yield Static("", id="validation-msg")
        with Vertical(id="panel-container"):
            yield DataTable(id="panel-table", cursor_type="row")
        yield Static("", id="status", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()

        table = self.query_one("#panel-table", DataTable)
        table.can_focus = False
        table.add_column("Setting", key="setting")
        table.add_column("Value", key="value")
        table.add_column("Source", key="source")
        table.add_column("Type", key="type")
        for key, meta in self._fields.items():
            type_info = ""
            if meta.choices:
                type_info = f"enum({len(meta.choices)})"
            elif meta.is_path:
                type_info = "path"
            elif meta.validator:
                type_info = "validated"
            table.add_row(meta.name, meta.value, meta.source, type_info, key=key)

        self._update_status()

    def on_key(self, event) -> None:
        """Centralized key handler."""
        if self._mode == "command":
            if event.key == "ctrl+e":
                event.prevent_default()
                event.stop()
                self._enter_normal()

        elif self._mode == "normal":
            if event.key == "j":
                event.prevent_default()
                event.stop()
                table = self.query_one("#panel-table", DataTable)
                if table.cursor_row < table.row_count - 1:
                    table.move_cursor(row=table.cursor_row + 1)
            elif event.key == "k":
                event.prevent_default()
                event.stop()
                table = self.query_one("#panel-table", DataTable)
                if table.cursor_row > 0:
                    table.move_cursor(row=table.cursor_row - 1)
            elif event.key == "i":
                event.prevent_default()
                event.stop()
                self._enter_insert()
            elif event.key == "escape":
                event.prevent_default()
                event.stop()
                self._exit_to_command()
            else:
                if len(event.key) == 1 and event.key.isprintable():
                    event.prevent_default()
                    event.stop()

        elif self._mode == "insert":
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._cancel_edit()
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._confirm_edit()
            elif event.key == "tab":
                # Tab accepts the autocomplete selection
                event.prevent_default()
                event.stop()
                self._accept_autocomplete()
            # All other keys pass through to SmartBar (it has focus)

    # ─── Mode transitions ─────────────────────────────────────────────────

    def _enter_normal(self) -> None:
        """Command → Normal."""
        self._mode = "normal"
        self.query_one("#panel-container").add_class("active")
        self.set_focus(None)
        self._completer.set_command_mode()
        self._update_status()

    def _enter_insert(self) -> None:
        """Normal → Insert: save state, repurpose SmartBar, switch completer."""
        table = self.query_one("#panel-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0:
            return

        keys = list(self._fields.keys())
        if row_idx >= len(keys):
            return

        row_key = keys[row_idx]
        field_meta = self._fields[row_key]
        self._edit_row_key = row_key
        self._edit_field = field_meta

        # Save SmartBar state
        bar = self.query_one("#smart-bar", Input)
        self._saved_bar_text = bar.value
        self._saved_bar_cursor = bar.cursor_position
        self._saved_bar_placeholder = bar.placeholder

        # Repurpose SmartBar
        bar.value = field_meta.value
        bar.cursor_position = len(field_meta.value)
        bar.add_class("editing")
        bar.remove_class("invalid")

        # Build placeholder with type hint
        hint = ""
        if field_meta.choices:
            hint = f" [{', '.join(field_meta.choices)}]"
        elif field_meta.is_path:
            hint = " [path — Tab to complete]"
        elif field_meta.validator:
            hint = " [integer > 0]"
        bar.placeholder = f"Edit: {field_meta.name}{hint}"

        # Switch completer to field-edit mode
        self._completer.set_edit_mode(
            field_name=field_meta.name,
            choices=field_meta.choices,
            is_path=field_meta.is_path,
        )

        # Clear any previous validation error
        self._hide_validation_error()

        # Focus SmartBar
        self.set_focus(bar)
        self._mode = "insert"
        self._update_status()

    def _confirm_edit(self) -> None:
        """Insert → Normal: validate, then apply or show error."""
        bar = self.query_one("#smart-bar", Input)
        new_value = bar.value.strip()

        if not new_value:
            # Empty value — just cancel
            self._cancel_edit()
            return

        # Validate if field has a validator
        if self._edit_field and self._edit_field.validator:
            error = self._edit_field.validator(new_value)
            if error:
                # Show validation error, stay in INSERT mode
                self._show_validation_error(error)
                bar.add_class("invalid")
                bar.remove_class("editing")
                return

        # Valid — apply
        if self._edit_row_key and self._edit_field:
            self._edit_field.value = new_value
            table = self.query_one("#panel-table", DataTable)
            table.update_cell(self._edit_row_key, "value", new_value)
            table.update_cell(self._edit_row_key, "source", "session")
            self.notify(f"✓ {self._edit_field.name} = {new_value!r}")

        self._restore_smartbar()

    def _cancel_edit(self) -> None:
        """Insert → Normal: discard changes."""
        self._restore_smartbar()

    def _restore_smartbar(self) -> None:
        """Restore SmartBar to command mode state."""
        self._mode = "normal"
        bar = self.query_one("#smart-bar", Input)
        bar.value = self._saved_bar_text
        bar.placeholder = self._saved_bar_placeholder
        bar.cursor_position = self._saved_bar_cursor
        bar.remove_class("editing")
        bar.remove_class("invalid")
        self._edit_row_key = None
        self._edit_field = None
        self._hide_validation_error()
        # Switch completer back to command mode
        self._completer.set_command_mode()
        # Blur for NORMAL mode
        self.set_focus(None)
        self._update_status()

    def _exit_to_command(self) -> None:
        """Normal → Command."""
        self._mode = "command"
        self.query_one("#panel-container").remove_class("active")
        self._completer.set_command_mode()
        self.query_one("#smart-bar", Input).focus()
        self._update_status()

    # ─── Autocomplete helpers ─────────────────────────────────────────────

    def _accept_autocomplete(self) -> None:
        """Tab: accept the highlighted autocomplete suggestion."""
        if not HAS_AUTOCOMPLETE:
            return
        try:
            for ac in self.query(SwappableAutoComplete):
                if ac.display and ac.option_list.option_count > 0:
                    highlighted = ac.option_list.highlighted or 0
                    option = ac.option_list.get_option_at_index(highlighted)
                    # Get the plain text value from the option
                    from rich.text import Text

                    value = (
                        option.prompt.plain
                        if isinstance(option.prompt, Text)
                        else str(option.prompt)
                    )
                    bar = self.query_one("#smart-bar", Input)
                    bar.value = value
                    bar.cursor_position = len(value)
                    # Clear validation on new input
                    bar.remove_class("invalid")
                    self._hide_validation_error()
                    return
        except Exception:
            pass

    # ─── Validation display ───────────────────────────────────────────────

    def _show_validation_error(self, message: str) -> None:
        """Show validation error below the SmartBar."""
        msg = self.query_one("#validation-msg", Static)
        msg.update(f" ✗ {message}")
        msg.add_class("visible")

    def _hide_validation_error(self) -> None:
        """Hide the validation message."""
        msg = self.query_one("#validation-msg", Static)
        msg.remove_class("visible")
        msg.update("")

    # ─── Input change handler (clear validation on new typing) ────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Clear validation error when user resumes typing."""
        if self._mode == "insert" and event.input.id == "smart-bar":
            bar = self.query_one("#smart-bar", Input)
            if bar.has_class("invalid"):
                bar.remove_class("invalid")
                bar.add_class("editing")
                self._hide_validation_error()

    # ─── Status bar ───────────────────────────────────────────────────────

    def _update_status(self) -> None:
        mode_display = {
            "command": "[dim]COMMAND[/dim] — type commands, Ctrl+E opens panel",
            "normal": "[bold cyan]NORMAL[/bold cyan] — j/k navigate, i edit, Esc back",
            "insert": "[bold green]INSERT[/bold green] — type value, Tab complete, Enter confirm, Esc cancel",
        }
        extra = ""
        if self._mode == "insert" and self._edit_field:
            if self._edit_field.choices:
                extra = f"  [dim](choices: {', '.join(self._edit_field.choices[:3])}...)[/dim]"
            elif self._edit_field.is_path:
                extra = "  [dim](Tab for path suggestions)[/dim]"
        self.query_one("#status", Static).update(
            f" {mode_display[self._mode]}{extra}"
        )


if __name__ == "__main__":
    app = SmartBarAutoCompleteApp()
    app.run(inline=True, inline_no_clear=True)
