"""StdinCollector — the kernel's minimal, zone-less prompt collector.

The bottom of the resolution chain: with nothing else registered,
``rc.prompt_*()`` still works at an interactive terminal, backed by nothing
but :func:`input` and :func:`getpass.getpass`. This is the collector an
*embedder* gets — someone using ``FunctualizeApp`` with no CLI at all.

It is deliberately dumb. It has **no live zone**, so it is the one collector
that can never fight another writer for the cursor. The rich terminal
experience — a scrollback section plus an updateable bottom zone that also
hosts prompts — is the CLI's ``StdoutSurface`` (``functualize.ui``), which
registers itself and supersedes this fallback via normal registration order.
See ``contributor/adr/001-surface-architecture-collapse.md`` §2b.

Deliberately TTY-gated. When stdin/stdout is not a terminal — piped input,
CI, background jobs, MCP — :meth:`StdinCollector.is_available` returns False
and :func:`get_stdin_collector` returns None, so the caller keeps its
``default`` / ``InputNotAvailable`` behavior instead of blocking forever on a
read that will never come.

It is a :class:`PromptCollector` only, not a :class:`Surface`: it asks
questions and renders nothing.
"""

from __future__ import annotations

import getpass
import sys

from functualize._types.interactivity import (
    PromptIntent,
    PromptRequest,
    PromptResponse,
)

__all__ = ["StdinCollector", "get_stdin_collector"]


class StdinCollector:
    """Minimal kernel PromptCollector using ``input()`` / ``getpass``.

    Only usable at an interactive terminal (see :meth:`is_available`). Callers
    must check :meth:`is_available` before dispatching to :meth:`collect`;
    ``collect`` itself does not re-check the TTY, keeping the guard testable in
    isolation.
    """

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` only when both stdin and stdout are TTYs.

        Mirrors the ``_cli/stdin_reader`` TTY idiom. Any failure probing the
        streams is treated as "not available".
        """
        try:
            return bool(sys.stdin.isatty() and sys.stdout.isatty())
        except (AttributeError, OSError, ValueError):
            return False

    # ─── PromptCollector protocol ────────────────────────────────────
    # This class has no handle_event: it is a collector, not a Surface.

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Collect input for ``request`` by dispatching on its intent.

        Args:
            request: The structured prompt request.

        Returns:
            A :class:`PromptResponse`. On ``KeyboardInterrupt``/``EOFError``
            (Ctrl-C, Ctrl-D, or a stream that closes mid-read) returns a
            ``cancelled`` response rather than raising.
        """
        intent = request.intent
        try:
            if intent == PromptIntent.CONFIRM_DESTRUCTIVE:
                return self._confirm_destructive(request)
            if intent in (PromptIntent.CONFIRM_NEUTRAL, PromptIntent.CONFIRM_PROCEED):
                return self._confirm_neutral(request)
            if intent == PromptIntent.SELECT:
                return self._select(request)
            if intent == PromptIntent.MULTI_SELECT:
                return self._multi_select(request)
            if intent == PromptIntent.SECRET_INPUT:
                return self._secret_input(request)
            if intent == PromptIntent.ACKNOWLEDGE:
                return self._acknowledge(request)
            return self._text_input(request)
        except (KeyboardInterrupt, EOFError):
            return PromptResponse(value=None, source="cancelled")

    # ─── Per-intent handlers ─────────────────────────────────────────

    def _confirm_destructive(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        response = input(f"⚠ {request.question} (type 'yes' to confirm): ")
        return PromptResponse(value=response.strip().lower() == "yes", source="user")

    def _confirm_neutral(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        default_hint = "[Y/n]" if request.default is True else "[y/N]"
        val = input(f"{request.question} {default_hint}: ").strip().lower()
        if val == "":
            result = request.default if request.default is not None else True
        elif val in ("y", "yes"):
            result = True
        else:
            result = False
        return PromptResponse(value=result, source="user")

    def _select(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        print(request.question)
        choices = request.choices or []
        for i, choice in enumerate(choices, 1):
            label = choice.label or choice.value
            disabled = " [disabled]" if choice.disabled else ""
            desc = f" — {choice.description}" if choice.description else ""
            print(f"  {i}. {label}{desc}{disabled}")
        response = input("Select (number): ")
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
        if request.default is not None:
            return PromptResponse(value=request.default, source="default")
        return PromptResponse(value=None, source="cancelled")

    def _multi_select(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        print(request.question)
        choices = request.choices or []
        for i, choice in enumerate(choices, 1):
            label = choice.label or choice.value
            disabled = " [disabled]" if choice.disabled else ""
            desc = f" — {choice.description}" if choice.description else ""
            print(f"  {i}. {label}{desc}{disabled}")
        response = input("Select (comma-separated numbers): ")
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

    def _secret_input(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        value = getpass.getpass(f"{request.question}: ")
        return PromptResponse(value=value, source="user")

    def _acknowledge(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        input(f"{request.question} [Press Enter to continue]: ")
        return PromptResponse(value=True, source="user")

    def _text_input(self, request: PromptRequest) -> PromptResponse:
        if request.context_message:
            print(f"  {request.context_message}")
        default_hint = f" [{request.default}]" if request.default is not None else ""
        value = input(f"{request.question}{default_hint}: ")
        if not value and request.default is not None:
            return PromptResponse(value=request.default, source="default")
        return PromptResponse(value=value, source="user")


_STDIN_COLLECTOR: StdinCollector | None = None


def get_stdin_collector() -> StdinCollector | None:
    """Return a process-wide cached :class:`StdinCollector`, or ``None``.

    Returns the singleton only when :meth:`StdinCollector.is_available`
    reports an interactive terminal; otherwise returns ``None`` so callers
    preserve their non-TTY behavior. The instance is cached at module scope
    (not on any per-invocation object) so repeated prompts reuse it.
    """
    if not StdinCollector.is_available():
        return None
    global _STDIN_COLLECTOR
    if _STDIN_COLLECTOR is None:
        _STDIN_COLLECTOR = StdinCollector()
    return _STDIN_COLLECTOR
