"""Functualize Inline Plugin — a PromptCollector using Textual inline mode.

Implements ``collect`` to render rich inline terminal widgets for each
PromptIntent. Falls back to plain CLI input() when Textual inline mode is
unavailable (non-TTY, import failure, or lacking terminal support).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from functualize._types.interactivity import (
    PromptIntent,
    PromptRequest,
    PromptResponse,
)

__all__ = ["InlinePlugin"]

logger = logging.getLogger(__name__)


def _is_inline_available() -> bool:
    """Check if Textual inline mode is available.

    Returns False if:
    - stdin/stdout is not a TTY
    - Textual cannot be imported
    - Terminal lacks inline support
    """
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return False
        # Verify Textual can be imported and inline mode is supported
        from textual.app import App  # noqa: F401

        return True
    except (ImportError, AttributeError, OSError):
        return False


class InlinePlugin:
    """Textual inline PromptCollector for functualize prompts.

    Dispatches PromptRequest objects to appropriate Textual inline widgets
    based on PromptIntent. Falls back to plain CLI when Textual inline is
    unavailable.
    """

    name: str = "inline"
    version: str = "0.1.0"
    description: str = "Textual inline terminal prompts"

    def __call__(self, app: Any) -> None:
        """Register this plugin as a PromptCollector with the application."""
        try:
            app.register_surface(self)
            logger.debug("InlinePlugin registered as PromptCollector")
        except Exception as e:
            logger.warning("InlinePlugin: Failed to register: %s", e)

    # ─── PromptCollector Protocol ────────────────────────────────────

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Collect user input for the given prompt request.

        Dispatches to Textual inline widgets when available, otherwise
        falls back to plain CLI input().

        Args:
            request: The structured prompt request with intent, choices, etc.

        Returns:
            PromptResponse with the user's value and source metadata.
        """
        if _is_inline_available():
            return self._prompt_inline(request)
        return self._prompt_cli_fallback(request)

    # ─── Textual Inline Path ─────────────────────────────────────────

    def _prompt_inline(self, request: PromptRequest) -> PromptResponse:
        """Render a Textual inline widget based on prompt intent."""
        from functualize_inline.apps import InlinePromptApp
        from functualize_inline.widgets import (
            AcknowledgeWidget,
            ConfirmDestructiveWidget,
            ConfirmNeutralWidget,
            MultiSelectWidget,
            SecretInputWidget,
            SelectWidget,
            TextInputWidget,
        )

        intent = request.intent
        widget_class: type
        widget_kwargs: dict[str, Any] = {}

        if intent == PromptIntent.CONFIRM_DESTRUCTIVE:
            widget_class = ConfirmDestructiveWidget
            widget_kwargs = {
                "question": request.question,
                "context_message": request.context_message,
            }
        elif intent in (PromptIntent.CONFIRM_NEUTRAL, PromptIntent.CONFIRM_PROCEED):
            widget_class = ConfirmNeutralWidget
            widget_kwargs = {
                "question": request.question,
                "default": request.default,
                "context_message": request.context_message,
            }
        elif intent == PromptIntent.SELECT:
            widget_class = SelectWidget
            widget_kwargs = {
                "question": request.question,
                "choices": request.choices or [],
                "context_message": request.context_message,
            }
        elif intent == PromptIntent.MULTI_SELECT:
            widget_class = MultiSelectWidget
            widget_kwargs = {
                "question": request.question,
                "choices": request.choices or [],
                "context_message": request.context_message,
            }
        elif intent == PromptIntent.SECRET_INPUT:
            widget_class = SecretInputWidget
            widget_kwargs = {
                "question": request.question,
                "placeholder": request.placeholder,
                "context_message": request.context_message,
            }
        elif intent == PromptIntent.ACKNOWLEDGE:
            widget_class = AcknowledgeWidget
            widget_kwargs = {
                "question": request.question,
                "context_message": request.context_message,
            }
        else:
            # TEXT_INPUT or any unknown intent
            widget_class = TextInputWidget
            widget_kwargs = {
                "question": request.question,
                "placeholder": request.placeholder,
                "default": request.default,
                "context_message": request.context_message,
            }

        try:
            app = InlinePromptApp(
                widget_class=widget_class,
                widget_kwargs=widget_kwargs,
                timeout=request.timeout,
            )
            result = app.run()

            if result is None:
                # App exited without returning a result (shouldn't happen normally)
                return PromptResponse(value=None, source="cancelled")

            value, source = result

            # For timeout, use the default value
            if source == "timeout":
                return PromptResponse(value=request.default, source="timeout")

            return PromptResponse(value=value, source=source)

        except Exception as e:
            logger.warning(
                "InlinePlugin: Textual inline failed (%s), falling back to CLI", e
            )
            return self._prompt_cli_fallback(request)

    # ─── Plain CLI Fallback ──────────────────────────────────────────

    def _prompt_cli_fallback(self, request: PromptRequest) -> PromptResponse:
        """Plain CLI fallback using standard input/print.

        Used when Textual inline mode is unavailable.
        """
        intent = request.intent

        try:
            if intent == PromptIntent.CONFIRM_DESTRUCTIVE:
                return self._cli_confirm_destructive(request)
            elif intent in (PromptIntent.CONFIRM_NEUTRAL, PromptIntent.CONFIRM_PROCEED):
                return self._cli_confirm_neutral(request)
            elif intent == PromptIntent.SELECT:
                return self._cli_select(request)
            elif intent == PromptIntent.MULTI_SELECT:
                return self._cli_multi_select(request)
            elif intent == PromptIntent.SECRET_INPUT:
                return self._cli_secret_input(request)
            elif intent == PromptIntent.ACKNOWLEDGE:
                return self._cli_acknowledge(request)
            else:
                return self._cli_text_input(request)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")

    def _cli_confirm_destructive(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for CONFIRM_DESTRUCTIVE: requires typing 'yes'."""
        if request.context_message:
            print(f"  {request.context_message}")
        prompt_text = f"⚠ {request.question} (type 'yes' to confirm): "
        try:
            response = input(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")
        confirmed = response.strip().lower() == "yes"
        return PromptResponse(value=confirmed, source="user")

    def _cli_confirm_neutral(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for CONFIRM_NEUTRAL: Y/n prompt."""
        if request.context_message:
            print(f"  {request.context_message}")
        default_hint = "[Y/n]" if request.default is True else "[y/N]"
        prompt_text = f"{request.question} {default_hint}: "
        try:
            response = input(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")
        val = response.strip().lower()
        if val == "":
            result = request.default if request.default is not None else True
        elif val in ("y", "yes"):
            result = True
        else:
            result = False
        return PromptResponse(value=result, source="user")

    def _cli_select(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for SELECT: numbered list."""
        if request.context_message:
            print(f"  {request.context_message}")
        print(f"{request.question}")
        choices = request.choices or []
        for i, choice in enumerate(choices, 1):
            label = choice.label or choice.value
            disabled = " [disabled]" if choice.disabled else ""
            desc = f" — {choice.description}" if choice.description else ""
            print(f"  {i}. {label}{desc}{disabled}")

        prompt_text = "Select (number): "
        try:
            response = input(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")

        try:
            idx = int(response.strip()) - 1
            if 0 <= idx < len(choices):
                selected = choices[idx]
                if selected.disabled:
                    print("  That option is disabled.")
                    return PromptResponse(value=request.default, source="user")
                return PromptResponse(value=selected.value, source="user")
        except (ValueError, IndexError):
            pass

        # Invalid selection — return default if available
        if request.default is not None:
            return PromptResponse(value=request.default, source="default")
        return PromptResponse(value=None, source="cancelled")

    def _cli_multi_select(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for MULTI_SELECT: numbered list with comma-separated input."""
        if request.context_message:
            print(f"  {request.context_message}")
        print(f"{request.question}")
        choices = request.choices or []
        for i, choice in enumerate(choices, 1):
            label = choice.label or choice.value
            disabled = " [disabled]" if choice.disabled else ""
            desc = f" — {choice.description}" if choice.description else ""
            print(f"  {i}. {label}{desc}{disabled}")

        prompt_text = "Select (comma-separated numbers): "
        try:
            response = input(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")

        selected: list[str] = []
        for part in response.split(","):
            part = part.strip()
            try:
                idx = int(part) - 1
                if 0 <= idx < len(choices) and not choices[idx].disabled:
                    selected.append(choices[idx].value)
            except (ValueError, IndexError):
                continue

        return PromptResponse(value=selected, source="user")

    def _cli_secret_input(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for SECRET_INPUT: uses getpass for masked input."""
        import getpass

        if request.context_message:
            print(f"  {request.context_message}")
        prompt_text = f"{request.question}: "
        try:
            value = getpass.getpass(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")
        return PromptResponse(value=value, source="user")

    def _cli_acknowledge(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for ACKNOWLEDGE: press Enter to continue."""
        if request.context_message:
            print(f"  {request.context_message}")
        prompt_text = f"{request.question} [Press Enter to continue]: "
        try:
            input(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")
        return PromptResponse(value=True, source="user")

    def _cli_text_input(self, request: PromptRequest) -> PromptResponse:
        """CLI fallback for TEXT_INPUT: plain input()."""
        if request.context_message:
            print(f"  {request.context_message}")
        default_hint = f" [{request.default}]" if request.default is not None else ""
        prompt_text = f"{request.question}{default_hint}: "
        try:
            value = input(prompt_text)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")
        if not value and request.default is not None:
            return PromptResponse(value=request.default, source="default")
        return PromptResponse(value=value, source="user")
