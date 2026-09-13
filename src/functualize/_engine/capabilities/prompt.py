"""Asking the person on the other end — `rc.prompts` and `prompt: Prompt`.

**One class, two doors** (ADR-021). Until `capability-duality`/T11 these were
two classes: `Prompt` for the DI parameter and `PromptFacade` for `rc.prompts`.
They were not merely separate objects — the DI one was *inert*. Its registry
factory was ``lambda ctx: Prompt()``, so every injected `Prompt` carried
``_provider=None`` and raised `InputNotAvailable` on every call, while
`rc.prompts` resolved the live collector and answered. A job written
``def j(p: Prompt)`` could not prompt at all.

That is the same shape as the `Perf` stub (`capability-duality`/T5): a factory
that returns the *unwired* form of a capability whose real wiring lives
somewhere else. The fix is the same — resolve through the shared map, and let
one implementation hold the logic.

The rule underneath did not change: a prompt is routed to the surface that owns
the terminal, and a job that asks where nothing can answer gets
`InputNotAvailable` rather than a silent default. Silently defaulting is how a
non-interactive run appears to have been confirmed.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, cast

from functualize._engine.capabilities.spec import CapabilitySpec
from functualize._types.interactivity import (
    InputNotAvailable,
    PromptChoice,
    PromptIntent,
    PromptRequest,
    PromptResponse,
    severity_for_intent,
)

if TYPE_CHECKING:
    from functualize._types.interactivity import PromptCollector

__all__ = ["Prompt"]


class Prompt:
    """Ask the person on the other end, or be told there is none.

    Reached two ways, and it is the **same object** either way (ADR-021):
    ``rc.prompts.confirm(...)`` and a ``prompt: Prompt`` parameter.

    Args:
        _provider: A collector bound at construction. The kernel's own callers
            (`Shell.sudo`, missing-value prompting) resolve a collector first
            and pass it here, so those paths do not depend on a RunContext.
        _caps: The run's capability map, from which the RunContext — and
            through it the live surface stack — is found **at call time**.
            Lazy on purpose: DI resolution runs before the RunContext exists,
            so capturing it eagerly captures ``None`` (the defect
            `capability-duality`/T1 fixed for `Invoke`).
    """

    __slots__ = ("_caps", "_explicit_rc", "_provider")

    def __init__(
        self,
        *,
        _provider: PromptCollector | None = None,
        _rc: Any | None = None,
        _caps: dict[type, Any] | None = None,
    ) -> None:
        self._provider = _provider
        self._explicit_rc = _rc
        self._caps = _caps

    @property
    def _rc(self) -> Any | None:
        """The RunContext for this execution, or None outside a job."""
        if self._explicit_rc is not None:
            return self._explicit_rc
        if self._caps is None:
            return None
        from functualize._engine.capabilities.runcontext import RunContext

        return self._caps.get(RunContext)

    @property
    def _job_name(self) -> str | None:
        """The job asking, stamped onto the request so a surface can say who."""
        rc = self._rc
        return None if rc is None else rc._name

    def _get_input_provider(self) -> PromptCollector | None:
        """Return the collector that should answer this job's prompts.

        Only surfaces that actually implement ``collect`` are eligible — a
        render-only surface (flow-viz) must never be handed a prompt it
        cannot answer.

        **Resolved per call, not per construction.** A surface pushed after
        this object was built — the common case, since DI resolves before the
        orchestrator pushes anything — must still be the one that answers.
        Stack-scoped: top-of-stack wins, so the phase that owns the terminal
        collects; see ``_engine/surface_routing.active_collector`` and
        contributor/adr/001-surface-architecture-collapse.md.
        """
        if self._provider is not None:
            return self._provider
        rc = self._rc
        if rc is None or rc._execution_engine is None:
            return None
        host = rc._execution_engine.host
        if host is None:
            return None
        return cast("PromptCollector | None", host.collector())

    def ask(self, request: PromptRequest) -> PromptResponse:
        """Send a fully-constructed request to the surface that can answer it.

        The low-level form every convenience method routes through. Use it when
        you need control over the `PromptRequest` fields.

        Raises:
            InputNotAvailable: Nothing can collect and the request is required
                with no default — the case where returning a default would
                fabricate an answer nobody gave.
        """
        filled = dataclasses.replace(request, source_job=self._job_name)
        provider = self._get_input_provider()
        if provider is None:
            if filled.required and filled.default is None:
                raise InputNotAvailable(
                    f"No InputProvider registered and prompt requires input "
                    f"(job={self._job_name!r}, question={filled.question!r}). "
                    f"Prompts need either an interactive terminal or a "
                    f"registered surface (see docs/guides/interactivity.md)."
                )
            return PromptResponse(value=filled.default, source="default")
        return provider.collect(filled)

    def confirm(
        self,
        question: str,
        *,
        destructive: bool = False,
        default: bool | None = None,
        context_message: str | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> bool:
        """Ask a yes/no question.

        With no ``default`` the question is *required*: off a terminal it
        raises rather than assuming an answer. Pass ``default`` to make the
        non-interactive answer explicit.
        """
        intent = (
            PromptIntent.CONFIRM_DESTRUCTIVE
            if destructive
            else PromptIntent.CONFIRM_NEUTRAL
        )
        # Derived, not hand-mapped — one source of truth for the styling.
        response = self.ask(
            PromptRequest(
                question=question,
                intent=intent,
                severity=severity_for_intent(intent),
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
        """Present options and return the selected value."""
        normalized = [
            PromptChoice(value=c) if isinstance(c, str) else c for c in choices
        ]
        response = self.ask(
            PromptRequest(
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
        """Ask for free-form text. ``secret=True`` asks without echoing."""
        intent = PromptIntent.SECRET_INPUT if secret else PromptIntent.TEXT_INPUT
        response = self.ask(
            PromptRequest(
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


# ── Registry entry (ADR-014) ───────────────────────────────────────────────

CAPABILITY = CapabilitySpec(
    name="Prompt",
    rc_accessor="prompts",
    type=Prompt,
    # `caps`, not a collector. The collector is resolved per call because the
    # surface that owns the terminal changes during a run; binding one here is
    # what made the injected `Prompt` permanently inert.
    factory=lambda ctx: Prompt(_caps=ctx.caps),
)
