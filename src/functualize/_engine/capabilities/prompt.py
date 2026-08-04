"""Prompt capability class — interactive input collection (1:1 dispatch).

The Prompt class provides convenient methods (confirm, choice, text) that
build a PromptRequest and delegate to a single active Surface. If no surface
is available, all methods raise InputNotAvailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize._types.interactivity import (
    InputNotAvailable,
    PromptChoice,
    PromptIntent,
    PromptRequest,
    PromptResponse,
)

if TYPE_CHECKING:
    from functualize._types.interactivity import PromptCollector

__all__ = ["Prompt"]


class Prompt:
    """Interactive input collection capability (1:1 dispatch to a Surface).

    Provides typed convenience methods that construct a PromptRequest and
    delegate to exactly one active Surface. Raises InputNotAvailable if none
    is available.

    Args:
        _provider: The Surface to collect through, or None if none is
                   available.
    """

    def __init__(self, *, _provider: PromptCollector | None = None) -> None:
        self._provider = _provider

    def _ensure_provider(self) -> PromptCollector:
        """Return the active collector or raise InputNotAvailable."""
        if self._provider is None:
            raise InputNotAvailable(
                "No Surface is available to collect input. Prompts need "
                "either an interactive terminal or a registered surface "
                "(see docs/guides/interactivity.md)."
            )
        return self._provider

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """Ask a yes/no confirmation question.

        Args:
            message: The confirmation question to display.
            default: Default boolean value if user provides no input.

        Returns:
            True if confirmed, False otherwise.

        Raises:
            InputNotAvailable: If no Surface is available.
        """
        provider = self._ensure_provider()
        request = PromptRequest(
            question=message,
            intent=PromptIntent.CONFIRM_NEUTRAL,
            default=default,
        )
        response = provider.collect(request)
        # Coerce value to bool
        value = response.value
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "y", "1")
        return bool(value)

    def choice(
        self, message: str, options: list[PromptChoice], **kwargs: object
    ) -> str:
        """Present choices and return the selected value.

        Args:
            message: The selection question to display.
            options: List of PromptChoice objects representing available options.
            **kwargs: Additional keyword arguments passed to PromptRequest
                      (e.g., default, severity, help_text).

        Returns:
            The selected choice value as a string.

        Raises:
            InputNotAvailable: If no Surface is available.
        """
        provider = self._ensure_provider()
        request = PromptRequest(
            question=message,
            intent=PromptIntent.SELECT,
            choices=options,
            **kwargs,  # type: ignore[arg-type]
        )
        response = provider.collect(request)
        return str(response.value) if response.value is not None else ""

    def text(self, message: str, *, default: str = "", **kwargs: object) -> str:
        """Ask for free-form text input.

        Args:
            message: The input question to display.
            default: Default string value if user provides no input.
            **kwargs: Additional keyword arguments passed to PromptRequest
                      (e.g., placeholder, help_text, validator).

        Returns:
            The user's text response as a string.

        Raises:
            InputNotAvailable: If no Surface is available.
        """
        provider = self._ensure_provider()
        request = PromptRequest(
            question=message,
            intent=PromptIntent.TEXT_INPUT,
            default=default,
            **kwargs,  # type: ignore[arg-type]
        )
        response = provider.collect(request)
        return str(response.value) if response.value is not None else ""

    def ask(self, request: PromptRequest) -> PromptResponse:
        """Send a fully-constructed PromptRequest to the active Surface.

        This is the low-level method that all other convenience methods
        ultimately delegate to. Use this when you need full control over
        the PromptRequest fields.

        Args:
            request: A structured PromptRequest describing the input needed.

        Returns:
            A PromptResponse from the Surface.

        Raises:
            InputNotAvailable: If no Surface is available.
        """
        provider = self._ensure_provider()
        return provider.collect(request)
