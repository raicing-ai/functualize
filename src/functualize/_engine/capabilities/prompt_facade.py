"""Asking the person on the other end — `rc.prompts`.

Extracted from :class:`~functualize._engine.capabilities.runcontext.RunContext`
(engine-sealed-construction/T8), and the largest single group at 147 lines: four
methods plus the routing that decides *who* answers.

**The `prompt_` prefix is gone with the move.** It existed to disambiguate four
methods on a flat object — `rc.prompts.confirm` beside `rc.log` and `rc.invoke` —
and on a facade named `prompts` it says the same word twice. `rc.prompts.confirm(...)`,
`.choice(...)`, `.text(...)`, and `.ask(request)` for the general form.

What did **not** change is the rule underneath: a prompt is routed to the
surface that owns the terminal, and a job that asks where nothing can answer
gets `InputNotAvailable` rather than a default. Silently defaulting is how a
non-interactive run appears to have been confirmed.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, cast

from functualize._types.interactivity import (
    InputNotAvailable,
    PromptChoice,
    PromptIntent,
    PromptRequest,
    PromptResponse,
)

if TYPE_CHECKING:
    from functualize._engine.capabilities.runcontext import RunContext

__all__ = ["PromptFacade"]


class PromptFacade:
    """`rc.prompts` — ask the person on the other end, or be told there is none."""

    __slots__ = ("_rc",)

    def __init__(self, rc: RunContext) -> None:
        self._rc = rc

    def _get_input_provider(self) -> Any | None:
        """Return the collector that should answer this job's prompts.

        Only surfaces that actually implement ``collect`` are eligible — a
        render-only surface (flow-viz) must never be handed a prompt it
        cannot answer.

        Stack-scoped: top-of-stack wins, so the phase that owns the terminal
        collects; see ``_engine/surface_routing.active_collector`` and
        contributor/adr/001-surface-architecture-collapse.md.
        """
        if self._rc._execution_engine is None:
            return None
        host = self._rc._execution_engine.host
        if host is None:
            return None

        # Stack-scoped resolution: the topmost pushed surface that can collect
        # (the phase that owns the terminal), else the first registered
        # collector, else the kernel's TTY-gated stdin fallback (None off a
        # terminal — preserving default / InputNotAvailable behavior there).
        return host.collector()

    def ask(self, request: PromptRequest) -> PromptResponse:
        from functualize._types.interactivity import PromptResponse as _PromptResponse

        filled = dataclasses.replace(request, source_job=self._rc._name)
        provider = self._get_input_provider()
        if provider is None:
            if filled.required and filled.default is None:
                raise InputNotAvailable(
                    f"No InputProvider registered and prompt requires input "
                    f"(job='{self._rc._name}', question='{filled.question}')"
                )
            return _PromptResponse(value=filled.default, source="default")
        return cast("PromptResponse", provider.collect(filled))

    def confirm(
        self,
        question: str,
        *,
        destructive: bool = False,
        default: bool | None = None,
        context_message: str | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> bool:
        from functualize._types.interactivity import (
            PromptRequest as _PromptRequest,
        )
        from functualize._types.interactivity import (
            severity_for_intent,
        )

        intent = (
            PromptIntent.CONFIRM_DESTRUCTIVE
            if destructive
            else PromptIntent.CONFIRM_NEUTRAL
        )
        # Derived, not hand-mapped — one source of truth for the styling.
        severity = severity_for_intent(intent)
        response = self.ask(
            _PromptRequest(
                question=question,
                intent=intent,
                severity=severity,
                default=default,
                context_message=context_message,
                context_data=context_data,
                required=default is None,
            )
        )
        if response.was_cancelled:
            return False
        value = response.value
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("yes", "y", "true", "1")
        return bool(value) if value is not None else False

    def choice(
        self,
        question: str,
        choices: list[str] | list[PromptChoice],
        *,
        default: str | None = None,
        context_message: str | None = None,
    ) -> str:
        from functualize._types.interactivity import (
            PromptChoice as _PromptChoice,
        )
        from functualize._types.interactivity import (
            PromptRequest as _PromptRequest,
        )

        normalized = [
            _PromptChoice(value=c) if isinstance(c, str) else c for c in choices
        ]
        response = self.ask(
            _PromptRequest(
                question=question,
                intent=PromptIntent.SELECT,
                choices=normalized,
                default=default,
                context_message=context_message,
                required=default is None,
            )
        )
        return str(response.value) if response.value is not None else ""

    def text(
        self,
        question: str,
        *,
        default: str | None = None,
        secret: bool = False,
        placeholder: str | None = None,
        validator: str | Any | None = None,
        context_message: str | None = None,
    ) -> str:
        from functualize._types.interactivity import (
            PromptRequest as _PromptRequest,
        )

        intent = PromptIntent.SECRET_INPUT if secret else PromptIntent.TEXT_INPUT
        response = self.ask(
            _PromptRequest(
                question=question,
                intent=intent,
                default=default,
                placeholder=placeholder,
                validator=validator,
                context_message=context_message,
                required=default is None,
            )
        )
        return str(response.value) if response.value is not None else ""
