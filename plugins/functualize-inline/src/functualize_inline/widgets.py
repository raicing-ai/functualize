"""Custom Textual widgets for inline prompt rendering.

Each widget corresponds to a PromptIntent and handles user interaction,
returning the result via a message posted to the parent app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import on
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult


class PromptResult(Message):
    """Message posted when a widget produces a result."""

    def __init__(self, value: object, source: str = "user") -> None:
        super().__init__()
        self.value = value
        self.source = source


class ConfirmDestructiveWidget(Widget):
    """Red-bordered widget requiring the user to type 'yes' to confirm."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmDestructiveWidget {
        border: heavy red;
        padding: 1 2;
        height: auto;
        width: 100%;
    }
    ConfirmDestructiveWidget Label {
        margin-bottom: 1;
    }
    ConfirmDestructiveWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        question: str,
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._context_message = context_message

    def compose(self) -> ComposeResult:
        yield Label(f"[bold red]⚠ {self._question}[/]")
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        yield Label('[dim]Type "yes" to confirm, anything else to cancel[/]')
        yield Input(placeholder="yes")

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        confirmed = event.value.strip().lower() == "yes"
        self.post_message(PromptResult(value=confirmed, source="user"))

    def action_cancel(self) -> None:
        self.post_message(PromptResult(value=None, source="cancelled"))


class ConfirmNeutralWidget(Widget):
    """Standard Y/n confirmation widget."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("y", "confirm_yes", "Yes", show=False),
        Binding("n", "confirm_no", "No", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmNeutralWidget {
        border: solid $accent;
        padding: 1 2;
        height: auto;
        width: 100%;
    }
    ConfirmNeutralWidget Label {
        margin-bottom: 1;
    }
    ConfirmNeutralWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        question: str,
        default: object = None,
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._default = default
        self._context_message = context_message

    def compose(self) -> ComposeResult:
        default_hint = "[Y/n]" if self._default is True else "[y/N]"
        yield Label(f"{self._question} {default_hint}")
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        yield Input(placeholder="y/n")

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        val = event.value.strip().lower()
        if val == "":
            result = self._default if self._default is not None else True
        elif val in ("y", "yes"):
            result = True
        else:
            result = False
        self.post_message(PromptResult(value=result, source="user"))

    def action_cancel(self) -> None:
        self.post_message(PromptResult(value=None, source="cancelled"))

    def action_confirm_yes(self) -> None:
        self.post_message(PromptResult(value=True, source="user"))

    def action_confirm_no(self) -> None:
        self.post_message(PromptResult(value=False, source="user"))


class SelectWidget(Widget):
    """OptionList widget for SELECT intent with max 12 visible items."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    SelectWidget {
        border: solid $accent;
        padding: 1 2;
        height: auto;
        max-height: 18;
        width: 100%;
    }
    SelectWidget Label {
        margin-bottom: 1;
    }
    SelectWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    SelectWidget OptionList {
        max-height: 12;
    }
    """

    def __init__(
        self,
        question: str,
        choices: list[object],
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._choices = choices
        self._context_message = context_message

    def compose(self) -> ComposeResult:
        yield Label(self._question)
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        option_list = OptionList()
        for choice in self._choices:
            label = choice.label or choice.value  # type: ignore[union-attr]
            prompt = label
            if choice.description:  # type: ignore[union-attr]
                prompt = f"{label} — {choice.description}"  # type: ignore[union-attr]
            option_list.add_option(
                Option(prompt, id=choice.value, disabled=choice.disabled)  # type: ignore[union-attr]
            )
        yield option_list

    @on(OptionList.OptionSelected)
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is not None:
            self.post_message(PromptResult(value=event.option.id, source="user"))

    def action_cancel(self) -> None:
        self.post_message(PromptResult(value=None, source="cancelled"))


class MultiSelectWidget(Widget):
    """Checkbox list for MULTI_SELECT intent."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "submit", "Submit", show=False),
    ]

    DEFAULT_CSS = """
    MultiSelectWidget {
        border: solid $accent;
        padding: 1 2;
        height: auto;
        max-height: 20;
        width: 100%;
    }
    MultiSelectWidget Label {
        margin-bottom: 1;
    }
    MultiSelectWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    MultiSelectWidget OptionList {
        max-height: 12;
    }
    """

    def __init__(
        self,
        question: str,
        choices: list[object],
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._choices = choices
        self._context_message = context_message
        self._selected: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Label(f"{self._question} [dim](Space to toggle, Enter to confirm)[/]")
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        option_list = OptionList()
        for choice in self._choices:
            label = choice.label or choice.value  # type: ignore[union-attr]
            prompt = f"☐ {label}"
            if choice.description:  # type: ignore[union-attr]
                prompt = f"☐ {label} — {choice.description}"  # type: ignore[union-attr]
            option_list.add_option(
                Option(prompt, id=choice.value, disabled=choice.disabled)  # type: ignore[union-attr]
            )
        yield option_list

    @on(OptionList.OptionSelected)
    def _on_toggle(self, event: OptionList.OptionSelected) -> None:
        """Toggle selection on the chosen option."""
        if event.option.id is None:
            return
        opt_id = event.option.id
        if opt_id in self._selected:
            self._selected.discard(opt_id)
        else:
            self._selected.add(opt_id)
        # Update display to reflect selection state
        option_list = self.query_one(OptionList)
        idx = event.option_index
        choice = self._choices[idx]
        label = choice.label or choice.value  # type: ignore[union-attr]
        check = "☑" if opt_id in self._selected else "☐"
        desc = f" — {choice.description}" if choice.description else ""  # type: ignore[union-attr]
        option_list.replace_option_prompt(idx, f"{check} {label}{desc}")

    def action_submit(self) -> None:
        self.post_message(PromptResult(value=list(self._selected), source="user"))

    def action_cancel(self) -> None:
        self.post_message(PromptResult(value=None, source="cancelled"))


class TextInputWidget(Widget):
    """Text input widget for TEXT_INPUT intent."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    TextInputWidget {
        border: solid $accent;
        padding: 1 2;
        height: auto;
        width: 100%;
    }
    TextInputWidget Label {
        margin-bottom: 1;
    }
    TextInputWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        question: str,
        placeholder: str | None = None,
        default: object = None,
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._placeholder = placeholder or ""
        self._default = default
        self._context_message = context_message

    def compose(self) -> ComposeResult:
        yield Label(self._question)
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        default_str = str(self._default) if self._default is not None else ""
        yield Input(placeholder=self._placeholder, value=default_str)

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        value = event.value
        if not value and self._default is not None:
            value = str(self._default)
        self.post_message(PromptResult(value=value, source="user"))

    def action_cancel(self) -> None:
        self.post_message(PromptResult(value=None, source="cancelled"))


class SecretInputWidget(Widget):
    """Masked input widget for SECRET_INPUT intent."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    SecretInputWidget {
        border: solid $accent;
        padding: 1 2;
        height: auto;
        width: 100%;
    }
    SecretInputWidget Label {
        margin-bottom: 1;
    }
    SecretInputWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        question: str,
        placeholder: str | None = None,
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._placeholder = placeholder or ""
        self._context_message = context_message

    def compose(self) -> ComposeResult:
        yield Label(self._question)
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        yield Input(placeholder=self._placeholder, password=True)

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        self.post_message(PromptResult(value=event.value, source="user"))

    def action_cancel(self) -> None:
        self.post_message(PromptResult(value=None, source="cancelled"))


class AcknowledgeWidget(Widget):
    """Any-key dismiss widget for ACKNOWLEDGE intent."""

    BINDINGS = [
        Binding("escape", "dismiss", "Dismiss", show=False),
    ]

    DEFAULT_CSS = """
    AcknowledgeWidget {
        border: solid $success;
        padding: 1 2;
        height: auto;
        width: 100%;
    }
    AcknowledgeWidget Label {
        margin-bottom: 1;
    }
    AcknowledgeWidget .context-msg {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        question: str,
        context_message: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._context_message = context_message

    def compose(self) -> ComposeResult:
        yield Label(self._question)
        if self._context_message:
            yield Static(self._context_message, classes="context-msg")
        yield Label("[dim]Press any key to continue...[/]")

    def on_key(self, event: object) -> None:
        self.post_message(PromptResult(value=True, source="user"))

    def action_dismiss(self) -> None:
        self.post_message(PromptResult(value=True, source="user"))
