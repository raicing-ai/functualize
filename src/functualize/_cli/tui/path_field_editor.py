"""Path field inline editor with filesystem suggestions.

Provides a compose helper for Config Table inline editing of path-typed fields.
Integrates the PathSuggestionScanner with an inline Input widget, showing
real-time filesystem suggestions below the input.

Supports:
- Relative (./ or bare word), absolute (/), and home-relative (~/) modes
- Tab inserts highlighted suggestion into Input
- "/" triggers directory descent rescan
- path_mode from json_schema_extra ("relative" or "absolute" pre-fill/conversion)
- FilePath: show files and dirs but only accept files
- DirectoryPath: show only directories

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._cli.data.path_suggestion import PathSuggestion

try:
    from textual.app import ComposeResult  # noqa: TC002
    from textual.css.query import NoMatches
    from textual.message import Message  # noqa: TC002
    from textual.widget import Widget  # noqa: TC002
    from textual.widgets import Input, Static  # noqa: TC002
except ImportError as _exc:
    raise ImportError(
        "PathFieldEditor requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.tui.path_suggestion_scanner import PathSuggestionScanner

_MAX_VISIBLE_SUGGESTIONS = 10


class PathFieldEditor(Widget):
    """Inline editor for path-typed fields with filesystem suggestions.

    Shows an Input pre-filled with the current value and a suggestion
    list below it that updates on each keystroke. Tab inserts highlighted
    suggestion, "/" triggers directory descent rescan, Enter confirms,
    Esc dismisses.

    Args:
        current_value: The current effective value of the field.
        cwd: Current working directory for relative path resolution.
        path_mode: "relative", "absolute", or None for auto-detect.
        file_filter: "file" for FilePath, "directory" for DirectoryPath, None for both.
        field_name: The name of the field being edited (for messages).
    """

    can_focus = False  # The Input child handles focus

    DEFAULT_CSS = """
    PathFieldEditor {
        height: auto;
        max-height: 14;
    }
    PathFieldEditor #pfe-input {
        height: 1;
    }
    PathFieldEditor #pfe-suggestions {
        height: auto;
        max-height: 12;
        color: $text-muted;
        padding: 0 1;
    }
    PathFieldEditor .pfe-suggestion-selected {
        background: $accent;
        color: $text;
    }
    """

    class Confirmed(Message):
        """User confirmed the path value with Enter."""

        def __init__(self, field_name: str, value: str) -> None:
            self.field_name = field_name
            self.value = value
            super().__init__()

    class Dismissed(Message):
        """User dismissed the editor with Esc."""

        def __init__(self, field_name: str) -> None:
            self.field_name = field_name
            super().__init__()

    def __init__(
        self,
        current_value: str,
        cwd: Path,
        path_mode: str | None = None,
        file_filter: str | None = None,
        field_name: str = "",
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._cwd = cwd
        self._path_mode = path_mode
        self._file_filter = file_filter
        self._field_name = field_name
        self._scanner = PathSuggestionScanner()
        self._suggestions: list[PathSuggestion] = []
        self._selected_suggestion_index: int = 0
        self._initial_value = self._compute_initial_value(current_value)

    def _compute_initial_value(self, current_value: str) -> str:
        """Compute the initial input value based on path_mode.

        - "relative": pre-fill with "./" prefix if not already relative
        - "absolute": pre-fill with absolute path
        - None: use current_value as-is (auto-detect mode)
        """
        if not current_value:
            if self._path_mode == "relative":
                return "./"
            elif self._path_mode == "absolute":
                return str(self._cwd) + "/"
            return ""

        if self._path_mode == "relative":
            # If value is absolute but within CWD, convert to relative
            if current_value.startswith("/"):
                try:
                    rel = Path(current_value).relative_to(self._cwd)
                    return "./" + str(rel)
                except ValueError:
                    return current_value
            # Already relative or starts with ./
            if not current_value.startswith("./") and not current_value.startswith(
                "~/"
            ):
                return "./" + current_value
            return current_value
        elif self._path_mode == "absolute":
            # If value is relative, resolve to absolute
            if not current_value.startswith("/") and not current_value.startswith("~/"):
                resolved = self._cwd / current_value.lstrip("./")
                return str(resolved)
            return current_value

        return current_value

    def compose(self) -> ComposeResult:
        """Compose the Input and suggestions list."""
        yield Input(
            value=self._initial_value,
            placeholder="Type a path...",
            id="pfe-input",
        )
        yield Static("", id="pfe-suggestions", markup=True)

    def on_mount(self) -> None:
        """Focus the input and trigger initial scan on mount."""
        input_widget = self.query_one("#pfe-input", Input)
        input_widget.focus()
        self._rescan(self._initial_value)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input text changes — rescan suggestions."""
        if event.input.id != "pfe-input":
            return
        value = event.value
        # Check if "/" was typed at end — triggers directory descent
        self._rescan(value)

    def on_key(self, event: object) -> None:
        """Handle key events for the path field editor.

        Intercepts Tab, Enter, Esc, and arrow keys for suggestion navigation.
        """
        key: str = getattr(event, "key", "")

        if key == "tab":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self._insert_suggestion()
        elif key == "enter":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self._confirm()
        elif key == "escape":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self._dismiss()
        elif key == "down":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self._move_suggestion_down()
        elif key == "up":
            if hasattr(event, "prevent_default"):
                event.prevent_default()
            if hasattr(event, "stop"):
                event.stop()
            self._move_suggestion_up()

    def _rescan(self, partial: str) -> None:
        """Scan filesystem and update suggestion list."""
        self._suggestions = self._scanner.scan(
            partial,
            self._cwd,
            path_mode=self._path_mode,
            file_filter=self._file_filter,
        )
        self._selected_suggestion_index = 0
        self._render_suggestions()

    def _render_suggestions(self) -> None:
        """Render the suggestion list with highlighting."""
        try:
            suggestions_widget = self.query_one("#pfe-suggestions", Static)
        except NoMatches:
            return

        if not self._suggestions:
            suggestions_widget.update("[dim]No suggestions[/dim]")
            return

        lines: list[str] = []
        visible = self._suggestions[:_MAX_VISIBLE_SUGGESTIONS]
        for i, suggestion in enumerate(visible):
            icon = "📁 " if suggestion.is_directory else "📄 "
            display = suggestion.display
            if i == self._selected_suggestion_index:
                line = f"[reverse]{icon}{display}[/reverse]"
            else:
                if suggestion.is_directory:
                    line = f"[dim]{icon}{display}[/dim]"
                else:
                    line = f"{icon}{display}"
            lines.append(line)

        remaining = len(self._suggestions) - _MAX_VISIBLE_SUGGESTIONS
        if remaining > 0:
            lines.append(f"[dim]  ... and {remaining} more[/dim]")

        suggestions_widget.update("\n".join(lines))

    def _move_suggestion_down(self) -> None:
        """Move the highlighted suggestion down."""
        max_idx = min(len(self._suggestions), _MAX_VISIBLE_SUGGESTIONS) - 1
        if self._selected_suggestion_index < max_idx:
            self._selected_suggestion_index += 1
            self._render_suggestions()

    def _move_suggestion_up(self) -> None:
        """Move the highlighted suggestion up."""
        if self._selected_suggestion_index > 0:
            self._selected_suggestion_index -= 1
            self._render_suggestions()

    def _insert_suggestion(self) -> None:
        """Insert the highlighted suggestion into the Input.

        Tab inserts the suggestion's display path. If the suggestion is
        a directory, appends "/" and triggers a rescan for directory descent.
        """
        if not self._suggestions:
            return

        idx = self._selected_suggestion_index
        if idx >= len(self._suggestions):
            return

        suggestion = self._suggestions[idx]
        insert_value = suggestion.display

        # For directories, ensure trailing "/"
        if suggestion.is_directory and not insert_value.endswith("/"):
            insert_value += "/"

        try:
            input_widget = self.query_one("#pfe-input", Input)
            input_widget.value = insert_value
            input_widget.cursor_position = len(insert_value)
        except NoMatches:
            return

        # If it's a directory, trigger a rescan for descent
        if suggestion.is_directory:
            self._rescan(insert_value)

    def _confirm(self) -> None:
        """Confirm the current value.

        Validates based on file_filter:
        - FilePath ("file"): only accept files, not directories.
          If user confirms a directory, treat it as directory descent.
        - DirectoryPath ("directory"): directories only (scanner already filters).

        Applies path_mode conversion:
        - "relative": convert result to relative path
        - "absolute": resolve to absolute path
        """
        try:
            input_widget = self.query_one("#pfe-input", Input)
        except NoMatches:
            return

        value = input_widget.value.strip()
        if not value:
            self._dismiss()
            return

        # Resolve the path for validation
        resolved = self._resolve_path(value)

        # FilePath validation: if user confirms a directory, treat as descent
        if self._file_filter == "file" and resolved.is_dir():
            # Append "/" and rescan — don't accept directories
            if not value.endswith("/"):
                value += "/"
            input_widget.value = value
            input_widget.cursor_position = len(value)
            self._rescan(value)
            return

        # Apply path_mode conversion on the final value
        final_value = self._apply_path_mode_conversion(value, resolved)

        self.post_message(self.Confirmed(self._field_name, final_value))

    def _dismiss(self) -> None:
        """Dismiss without applying."""
        self.post_message(self.Dismissed(self._field_name))

    def _resolve_path(self, value: str) -> Path:
        """Resolve a typed value to a Path for validation."""
        if value.startswith("~/"):
            return Path.home() / value[2:]
        elif value.startswith("/"):
            return Path(value)
        elif value.startswith("./"):
            return self._cwd / value[2:]
        else:
            return self._cwd / value

    def _apply_path_mode_conversion(self, value: str, resolved: Path) -> str:
        """Apply path_mode conversion to the final value.

        - "relative": convert to relative path (relative to CWD)
        - "absolute": ensure absolute path
        - None: return as-is
        """
        if self._path_mode == "relative":
            try:
                rel = resolved.relative_to(self._cwd)
                return "./" + str(rel)
            except ValueError:
                # Path not within CWD subtree — keep as-is
                return value
        elif self._path_mode == "absolute":
            return str(resolved)
        return value

    @property
    def selected_suggestion(self) -> PathSuggestion | None:
        """Return the currently highlighted suggestion, or None if empty."""
        if self._suggestions and 0 <= self._selected_suggestion_index < len(
            self._suggestions
        ):
            return self._suggestions[self._selected_suggestion_index]
        return None

    @property
    def current_input_value(self) -> str:
        """Return the current text in the Input widget."""
        try:
            input_widget = self.query_one("#pfe-input", Input)
            return input_widget.value
        except NoMatches:
            return self._initial_value
