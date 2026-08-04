"""TextualApp — the batteries-included Surface + PromptCollector base class.

``Surface`` is the contract; ``TextualApp`` is the one correct Textual
implementation of it. Subclass it for a job-owned UI (a ``tty: TTY`` job) and
the two hard parts are solved for you:

- **Engine events are marshaled onto the loop thread.** ``handle_event`` is
  called from the job's worker thread; it posts a :class:`FuncEvent` onto the
  Textual message pump (thread-safe) rather than touching widgets directly.
  Override :meth:`on_func_event` to render — it runs on the loop thread, so no
  marshaling of your own. Events that arrive before mount are buffered and
  flushed on mount (skip this and the first log lines silently vanish).
- **Prompts are answered by a modal.** ``collect`` (PromptCollector) pushes a
  :class:`~functualize.ui._prompt_modal.PromptModal` and blocks the worker
  thread on a ``threading.Event`` until the user answers — so ``rc.prompt_*()``
  Just Works, and the job never knows a modal was involved.

Lives in ``functualize.ui`` (the ``[cli]`` extra); imports Textual at load.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from textual import events, on
from textual.app import App
from textual.message import Message

from functualize.ui._prompt_modal import MODAL_CSS, PromptModal

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent
    from functualize._types.interactivity import PromptRequest, PromptResponse

__all__ = ["FuncEvent", "TextualApp"]

ReturnT = TypeVar("ReturnT")


class FuncEvent(Message):
    """A functualize ``StructuredEvent`` delivered onto the Textual message pump.

    ``handle_event`` posts one of these from the worker thread; the loop thread
    dispatches it to :meth:`TextualApp.on_func_event`.
    """

    def __init__(self, event: StructuredEvent) -> None:
        self.event = event
        super().__init__()


class TextualApp(App[ReturnT], Generic[ReturnT]):
    """Textual ``App`` that satisfies both ``Surface`` and ``PromptCollector``.

    See the module docstring for the threading and buffering contract.
    Subclasses that define their own ``CSS`` must include ``MODAL_CSS`` (or set
    ``CSS_PATH``) so the prompt modal is styled — this base sets it by default.
    """

    CSS = MODAL_CSS

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._funcapp_mounted = False
        self._funcapp_pre_mount: list[StructuredEvent] = []
        self._funcapp_prompt_event = threading.Event()
        self._funcapp_prompt_result: dict[str, Any] | None = None

    # ─── Mount hook (via @on so it never clashes with a subclass on_mount) ──

    @on(events.Mount)
    def _funcapp_on_mount(self) -> None:
        self._funcapp_mounted = True
        buffered, self._funcapp_pre_mount = self._funcapp_pre_mount, []
        for event in buffered:
            self.post_message(FuncEvent(event))

    # ─── Surface ────────────────────────────────────────────────────────

    def handle_event(self, event: StructuredEvent) -> None:
        """Deliver an engine event onto the loop thread (buffered pre-mount).

        Called from the job's worker thread. Never touch widgets here — render
        in :meth:`on_func_event` instead.
        """
        if not self._funcapp_mounted:
            self._funcapp_pre_mount.append(event)
            return
        self.post_message(FuncEvent(event))

    def on_func_event(self, message: FuncEvent) -> None:  # noqa: B027 — intentional no-op hook
        """Render one engine event. Override point; runs on the loop thread."""

    # ─── PromptCollector ────────────────────────────────────────────────

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Answer a prompt with a modal, blocking the worker thread until done."""
        from functualize._types.interactivity import PromptResponse

        if not self._funcapp_mounted:
            return PromptResponse(value=request.default, source="default")

        self._funcapp_prompt_event.clear()
        self._funcapp_prompt_result = None

        severity = getattr(request.severity, "value", "info")
        intent = getattr(request.intent, "value", "text_input")

        self.call_from_thread(self._funcapp_show_modal, request, severity, intent)

        responded = self._funcapp_prompt_event.wait(timeout=request.timeout)
        if not responded:
            self.call_from_thread(self._funcapp_dismiss_modal)
            return PromptResponse(value=request.default, source="timeout")

        result = self._funcapp_prompt_result
        if result is None:
            return PromptResponse(value=None, source="cancelled")
        return PromptResponse(
            value=result.get("value"), source=result.get("source", "user")
        )

    # ─── Modal helpers (run on the loop thread via call_from_thread) ─────

    def _funcapp_show_modal(
        self, request: PromptRequest, severity: str, intent: str
    ) -> None:
        modal = PromptModal(
            question=request.question,
            intent=intent,
            severity=severity,
            choices=request.choices,
            default=request.default,
            context_message=request.context_message,
            context_data=request.context_data,
            placeholder=request.placeholder,
            help_text=request.help_text,
        )

        def _on_dismiss(result: dict[str, Any] | None) -> None:
            self._funcapp_prompt_result = result
            self._funcapp_prompt_event.set()

        self.push_screen(modal, callback=_on_dismiss)

    def _funcapp_dismiss_modal(self) -> None:
        if len(self.screen_stack) > 1 and isinstance(self.screen, PromptModal):
            self.pop_screen()
