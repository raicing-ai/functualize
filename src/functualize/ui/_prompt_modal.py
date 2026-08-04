"""Shared prompt modal for job-owned Textual apps.

A ``PromptRequest`` rendered as a severity-styled ``ModalScreen`` that dismisses
with a ``{"value", "source"}`` result dict. Used by ``TextualApp.collect`` so
any job-owned Textual app answers ``rc.prompt_*()`` through the same modal — the
job never knows a modal is involved.

Lives in ``functualize.ui`` (the ``[cli]`` extra); imports Textual at module
load, so this module is only importable when that extra is installed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from textual import on
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult

__all__ = ["MODAL_CSS", "PromptModal"]

# ─── Severity Styling ─────────────────────────────────────────────────

SEVERITY_BORDER_COLORS: dict[str, str] = {
    "info": "blue",
    "warning": "yellow",
    "danger": "red",
    "success": "green",
}

SEVERITY_ICONS: dict[str, str] = {
    "info": "ℹ",
    "warning": "⚠",
    "danger": "🚨",
    "success": "✓",
}


class PromptModal(ModalScreen[dict[str, Any]]):
    """Modal dialog for mid-job prompts, styled by PromptSeverity.

    Overlays the app, collects user input based on PromptIntent, and dismisses
    with a result dict containing 'value' and 'source'.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        question: str,
        intent: str = "text_input",
        severity: str = "info",
        choices: list[Any] | None = None,
        default: Any = None,
        context_message: str | None = None,
        context_data: dict[str, Any] | None = None,
        placeholder: str | None = None,
        help_text: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._intent = intent
        self._severity = severity
        self._choices = choices or []
        self._default = default
        self._context_message = context_message
        self._context_data = context_data
        self._placeholder = placeholder or ""
        self._help_text = help_text

    @property
    def _icon(self) -> str:
        return SEVERITY_ICONS.get(self._severity, "ℹ")

    @property
    def _css_class(self) -> str:
        return f"severity-{self._severity}"

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container", classes=self._css_class):
            yield Label(
                f"[bold]{self._icon} {self._question}[/bold]",
                id="modal-question",
            )
            if self._context_message:
                yield Static(
                    f"[dim]{self._context_message}[/dim]",
                    id="modal-context-message",
                )
            if self._context_data:
                yield Static(
                    _format_context_data(self._context_data),
                    id="modal-context-data",
                )
            if self._help_text:
                yield Static(
                    f"[italic dim]{self._help_text}[/italic dim]",
                    id="modal-help",
                )
            yield from self._compose_input()

    def _compose_input(self) -> ComposeResult:
        """Compose the appropriate input widget for the prompt intent."""
        intent = self._intent

        if intent in ("confirm_destructive", "confirm_neutral", "confirm_proceed"):
            if intent == "confirm_destructive":
                yield Static(
                    '[dim]Type "yes" to confirm, anything else to cancel[/dim]'
                )
                yield Input(placeholder="yes", id="modal-input")
            else:
                default_hint = "[Y/n]" if self._default is True else "[y/N]"
                yield Static(f"[dim]{default_hint}[/dim]")
                yield Input(placeholder="y/n", id="modal-input")

        elif intent == "select":
            option_list = OptionList(id="modal-options")
            for choice in self._choices:
                label = getattr(choice, "label", None) or getattr(
                    choice, "value", str(choice)
                )
                desc = getattr(choice, "description", None)
                disabled = getattr(choice, "disabled", False)
                value = getattr(choice, "value", str(choice))
                prompt = f"{label}" if not desc else f"{label} — {desc}"
                option_list.add_option(Option(prompt, id=value, disabled=disabled))
            yield option_list

        elif intent == "multi_select":
            option_list = OptionList(id="modal-options")
            for choice in self._choices:
                label = getattr(choice, "label", None) or getattr(
                    choice, "value", str(choice)
                )
                desc = getattr(choice, "description", None)
                disabled = getattr(choice, "disabled", False)
                value = getattr(choice, "value", str(choice))
                prompt = f"☐ {label}" if not desc else f"☐ {label} — {desc}"
                option_list.add_option(Option(prompt, id=value, disabled=disabled))
            yield option_list
            yield Static("[dim]Space to toggle, Enter to confirm[/dim]")
            yield Button("Confirm Selection", id="modal-confirm-btn", variant="primary")

        elif intent == "secret_input":
            yield Input(placeholder=self._placeholder, password=True, id="modal-input")

        elif intent == "acknowledge":
            yield Static("[dim]Press any key or click OK to continue[/dim]")
            yield Button("OK", id="modal-ok-btn", variant="primary")

        else:
            # TEXT_INPUT and fallback
            default_str = str(self._default) if self._default is not None else ""
            yield Input(
                placeholder=self._placeholder, value=default_str, id="modal-input"
            )

    @on(Input.Submitted, "#modal-input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle text input submission."""
        intent = self._intent
        value = event.value

        if intent == "confirm_destructive":
            confirmed = value.strip().lower() == "yes"
            self.dismiss({"value": confirmed, "source": "user"})
        elif intent in ("confirm_neutral", "confirm_proceed"):
            val = value.strip().lower()
            if val == "":
                result = self._default if self._default is not None else True
            elif val in ("y", "yes"):
                result = True
            else:
                result = False
            self.dismiss({"value": result, "source": "user"})
        elif intent == "secret_input":
            self.dismiss({"value": value, "source": "user"})
        else:
            # TEXT_INPUT
            if not value and self._default is not None:
                value = str(self._default)
            self.dismiss({"value": value, "source": "user"})

    @on(OptionList.OptionSelected, "#modal-options")
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection for SELECT intent."""
        if self._intent == "select":
            if event.option.id is not None:
                self.dismiss({"value": event.option.id, "source": "user"})
        elif self._intent == "multi_select":
            self._toggle_multi_select(event)

    def _toggle_multi_select(self, event: OptionList.OptionSelected) -> None:
        """Toggle a multi-select option."""
        if not hasattr(self, "_multi_selected"):
            self._multi_selected: set[str] = set()

        opt_id = event.option.id
        if opt_id is None:
            return

        if opt_id in self._multi_selected:
            self._multi_selected.discard(opt_id)
        else:
            self._multi_selected.add(opt_id)

        option_list = self.query_one("#modal-options", OptionList)
        idx = event.option_index
        choice = self._choices[idx]
        label = getattr(choice, "label", None) or getattr(choice, "value", str(choice))
        desc = getattr(choice, "description", None)
        check = "☑" if opt_id in self._multi_selected else "☐"
        desc_suffix = f" — {desc}" if desc else ""
        option_list.replace_option_prompt_at_index(idx, f"{check} {label}{desc_suffix}")

    @on(Button.Pressed, "#modal-confirm-btn")
    def _on_confirm_multi(self, event: Button.Pressed) -> None:
        """Confirm multi-select choices."""
        selected = list(getattr(self, "_multi_selected", set()))
        self.dismiss({"value": selected, "source": "user"})

    @on(Button.Pressed, "#modal-ok-btn")
    def _on_ok(self, event: Button.Pressed) -> None:
        """Handle acknowledge OK button."""
        self.dismiss({"value": True, "source": "user"})

    def on_key(self, event: Any) -> None:
        """Handle key press for acknowledge intent."""
        if self._intent == "acknowledge":
            self.dismiss({"value": True, "source": "user"})

    def action_cancel(self) -> None:
        """Cancel the prompt."""
        self.dismiss({"value": None, "source": "cancelled"})


def _format_context_data(data: dict[str, Any]) -> str:
    """Format context data dict as a readable panel display."""
    lines: list[str] = ["[bold]Context Data:[/bold]"]
    for key, value in data.items():
        if isinstance(value, dict):
            formatted = json.dumps(value, indent=2, default=str)
            lines.append(f"  [cyan]{key}[/cyan]: {formatted}")
        elif isinstance(value, list):
            formatted = json.dumps(value, default=str)
            lines.append(f"  [cyan]{key}[/cyan]: {formatted}")
        else:
            lines.append(f"  [cyan]{key}[/cyan]: {value}")
    return "\n".join(lines)


MODAL_CSS = """
PromptModal {
    align: center middle;
}

#modal-container {
    width: 60%;
    max-width: 80;
    min-width: 40;
    height: auto;
    max-height: 80%;
    padding: 1 2;
    border: heavy $accent;
    background: $surface;
}

#modal-container.severity-info { border: heavy blue; }
#modal-container.severity-warning { border: heavy yellow; }
#modal-container.severity-danger { border: heavy red; }
#modal-container.severity-success { border: heavy green; }

#modal-question { margin-bottom: 1; }
#modal-context-message { margin-bottom: 1; }
#modal-context-data {
    margin-bottom: 1;
    padding: 1;
    border: solid $accent-lighten-2;
    background: $panel;
}
#modal-help { margin-bottom: 1; }
#modal-options { max-height: 12; margin-bottom: 1; }
#modal-input { margin-top: 1; }
"""
