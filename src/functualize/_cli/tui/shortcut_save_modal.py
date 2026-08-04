"""Shortcut save modal for persisting current command as a reusable shortcut file.

Shown as a floating modal overlay when the user presses Ctrl+S
from the smart bar or the argument form modal. Allows choosing
a shortcut name and output file (Python-only), with a live preview
of the generated content.

This module is in the ``_cli/`` layer — it imports ONLY from public API.
Textual imports are guarded behind try/except ImportError.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import ComposeResult

try:
    from textual.containers import Vertical, VerticalScroll  # noqa: TC002
    from textual.css.query import NoMatches
    from textual.message import Message  # noqa: TC002
    from textual.screen import ModalScreen  # noqa: TC002
    from textual.widgets import Input, Static, TextArea  # noqa: TC002
except ImportError as _exc:
    raise ImportError(
        "ShortcutSaveModal requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.data.shortcut_generator import (
    ShortcutSpec,
    _validate_shortcut_name,
    append_or_write_python_shortcut,
    generate_shortcut_content,
)


def _sanitize_name_for_python(name: str) -> str:
    """Convert a job name to a valid Python identifier default.

    Replaces hyphens and dots with underscores.
    """
    return re.sub(r"[-.]", "_", name)


class ShortcutSaveModal(ModalScreen[str | None]):
    """Save-as-shortcut dialog triggered by Ctrl+S.

    A proper ``ModalScreen`` (pushed via ``push_screen(..., callback)``
    from ``FunctualizeInlineTUI.action_save_shortcut``), so it captures
    all key input while open — no leaking Escape/Ctrl+Enter through to the
    app underneath.

    Displays inputs for shortcut name and output file, with a live preview
    of the generated shortcut content.
    On confirm (``ctrl+j``), validates the name, writes the file, posts
    ``ShortcutSaved``, and dismisses with the saved path. On validation or
    write error, shows the error message inline and stays open (no
    dismiss). Escape posts ``ShortcutCancelled`` and dismisses with
    ``None``.
    """

    DEFAULT_CSS = """
    ShortcutSaveModal {
        align: center middle;
    }
    ShortcutSaveModal #ssm-dialog {
        width: 60%;
        max-height: 80%;
        border: thick $success;
        background: $surface;
    }
    ShortcutSaveModal .ssm-description {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    ShortcutSaveModal .ssm-label {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    ShortcutSaveModal .ssm-input {
        width: 1fr;
        margin: 0 1;
    }
    ShortcutSaveModal .ssm-preview {
        height: auto;
        min-height: 6;
        max-height: 14;
        margin: 0 1;
        border: round $primary;
    }
    ShortcutSaveModal .ssm-error {
        height: auto;
        color: $error;
        padding: 0 1;
    }
    ShortcutSaveModal .ssm-footer {
        height: 1;
        color: $text-muted;
        padding: 0 1;
        dock: bottom;
    }
    """

    class ShortcutSaved(Message):
        """Shortcut file was written successfully."""

        def __init__(self, path: str) -> None:
            self.path = path
            super().__init__()

    class ShortcutCancelled(Message):
        """User cancelled the save dialog."""

    def __init__(
        self,
        job_name: str,
        kwargs: dict[str, str],
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._job_name = job_name
        self._kwargs = kwargs
        # Requirement 3 (edit-detachment): once the user types directly
        # into the preview TextArea, auto-regeneration from the name/
        # output-file inputs stops touching the preview content.
        self._preview_detached = False

    def compose(self) -> ComposeResult:
        """Render shortcut save form with name, output file, preview, and error area.

        Content is wrapped in an inner ``#ssm-dialog`` container that
        receives the box-model CSS (width/max-height/border) — a
        ``ModalScreen`` fills the viewport by default, so those constraints
        must target an inner container rather than the Screen itself.

        Modal convention (see ``on_mount``): the dialog's name lives in the
        Textual border title (``#ssm-dialog.border_title``), not a Static
        row — the border already frames the dialog, so a redundant title
        line wastes a row. A one-line description of what the modal does
        goes at the top of the body instead, immediately below the border.
        Any future ``ModalScreen`` in this codebase should follow the same
        pattern: ``border_title`` for the name, a description Static for
        the "why am I seeing this" context.
        """
        with Vertical(id="ssm-dialog"):
            yield Static(
                "Save the current command as a reusable shortcut job.",
                classes="ssm-description",
            )
            with VerticalScroll():
                yield Static(
                    "[dim]Shortcut name:[/dim]",
                    classes="ssm-label",
                    markup=True,
                )
                yield Input(
                    value=_sanitize_name_for_python(self._job_name),
                    placeholder="shortcut_name",
                    id="ssm-input-name",
                    classes="ssm-input",
                )
                yield Static(
                    "[dim]Output file:[/dim]",
                    classes="ssm-label",
                    markup=True,
                )
                yield Input(
                    value="./shortcuts.py",
                    placeholder="./shortcuts.py",
                    id="ssm-input-file",
                    classes="ssm-input",
                )
                yield Static(
                    "[dim]Preview:[/dim]",
                    id="ssm-preview-label",
                    classes="ssm-label",
                    markup=True,
                )
                yield TextArea.code_editor(
                    "",
                    language="python",
                    id="ssm-preview",
                    classes="ssm-preview",
                )
                yield Static(
                    "",
                    id="ssm-error",
                    classes="ssm-error",
                    markup=True,
                )
            yield Static(
                "[dim]Ctrl+Enter[/dim] save  "
                "[dim]Tab[/dim] navigate  "
                "[dim]Esc[/dim] cancel",
                classes="ssm-footer",
                markup=True,
            )

    def on_mount(self) -> None:
        """Set the border title and generate the initial preview.

        ``border_title`` is a runtime widget attribute, not composable via
        ``yield`` — it must be set after the widget exists (Textual's
        Border titles convention: displayed in the top border, only
        visible on a bordered widget; ``#ssm-dialog`` has ``border: thick``
        in ``DEFAULT_CSS``).
        """
        self.query_one("#ssm-dialog").border_title = "Save Shortcut"
        self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update preview when any input changes."""
        self._update_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Confirm on Enter inside any field — terminal-independent path.

        ``ctrl+enter`` requires the Kitty keyboard protocol (not universally
        supported); this handler makes plain Enter inside a focused Input
        confirm the dialog on every terminal, matching normal dialog UX.
        """
        event.stop()
        self._confirm()

    def _update_preview(self) -> None:
        """Regenerate the preview content from current input values.

        No-op once the preview has detached (Requirement 3): after the
        user types directly into the TextArea, further name/output-file
        edits must not overwrite their manual changes.
        """
        if self._preview_detached:
            return

        try:
            preview_area = self.query_one("#ssm-preview", TextArea)
        except NoMatches:
            return

        name = self._get_input_value("ssm-input-name")
        output_file = self._get_input_value("ssm-input-file")

        try:
            spec = ShortcutSpec(
                shortcut_name=name,
                job_name=self._job_name,
                kwargs=self._kwargs,
                output_file=Path(output_file),
            )
            content = generate_shortcut_content(spec)
        except ValueError:
            # Name validation failed — show placeholder
            content = "(enter a valid shortcut name to see preview)"

        preview_area.language = "python"
        preview_area.load_text(content)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Detach the preview from auto-regeneration on real user edits.

        Only a genuine keystroke gives the ``TextArea`` focus at the time
        this message fires — the programmatic ``load_text()`` calls made by
        ``_update_preview()`` never focus the widget — so checking
        ``has_focus`` reliably distinguishes user typing from auto-regen.
        """
        if event.text_area.id != "ssm-preview":
            return
        if event.text_area.has_focus and not self._preview_detached:
            self._preview_detached = True
            self._update_preview_label()

    def _update_preview_label(self) -> None:
        """Refresh the ``Preview:`` label to show the detached indicator."""
        try:
            label = self.query_one("#ssm-preview-label", Static)
        except NoMatches:
            return
        if self._preview_detached:
            label.update("[dim]Preview: (edited)[/dim]")
        else:
            label.update("[dim]Preview:[/dim]")

    def on_key(self, event: object) -> None:
        """Handle Ctrl+Enter (confirm), Escape (cancel).

        ``ctrl+enter`` is the key Textual actually delivers on terminals
        supporting the Kitty keyboard protocol. ``ctrl+j`` is kept as a
        legacy fallback (some terminals map Ctrl+Enter to LF/0x0A), but the
        primary, terminal-independent confirm path is ``on_input_submitted``
        below (plain Enter inside a focused Input).
        """
        key: str = getattr(event, "key", "")

        if key in ("ctrl+enter", "ctrl+j"):
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
            self.post_message(self.ShortcutCancelled())
            self.dismiss(None)

    def _confirm(self) -> None:
        """Validate, generate, write file, and post ShortcutSaved."""
        name = self._get_input_value("ssm-input-name")
        output_file = self._get_input_value("ssm-input-file")

        # Validate output file extension
        if not output_file.endswith(".py"):
            self._show_error("Output file must end in .py")
            return

        # Validate name
        try:
            _validate_shortcut_name(name)
        except ValueError as exc:
            self._show_error(str(exc))
            return

        spec = ShortcutSpec(
            shortcut_name=name,
            job_name=self._job_name,
            kwargs=self._kwargs,
            output_file=Path(output_file),
        )

        # Save the TextArea's CURRENT text (respecting manual edits), not a
        # fresh regeneration — falls back to generate_shortcut_content when
        # the preview widget isn't mounted (e.g. unit tests that construct
        # the modal without compose()/mount()).
        try:
            preview_area = self.query_one("#ssm-preview", TextArea)
            content = preview_area.text
        except NoMatches:
            content = generate_shortcut_content(spec)

        # Write to file — appends to an existing file rather than
        # overwriting it (Requirement 2), deduping the import line and the
        # JOB_GROUP declaration.
        try:
            append_or_write_python_shortcut(spec, content)
        except OSError as exc:
            self._show_error(f"Write failed: {exc}")
            return

        # Success — post message and dismiss with the saved path
        self.post_message(self.ShortcutSaved(path=str(spec.output_file)))
        self.dismiss(str(spec.output_file))

    def _show_error(self, message: str) -> None:
        """Display an error message in the error Static widget."""
        try:
            error_widget = self.query_one("#ssm-error", Static)
            error_widget.update(f"[bold red]{message}[/bold red]")
        except NoMatches:
            pass

    def _get_input_value(self, input_id: str) -> str:
        """Get the current value of an Input widget by ID."""
        try:
            input_widget = self.query_one(f"#{input_id}", Input)
            return input_widget.value
        except NoMatches:
            return ""
