"""StdoutSurface — one Rich surface, one writer (scrollback + live zone + prompt).

The rich stdout rendering path is a single object that owns the cursor. It
satisfies both ``Surface`` (events append to scrollback) and ``PromptCollector``
(``collect`` pauses the live zone, asks, resumes), and it hosts ``LiveConstruct``
objects in a ``rich.live.Live`` region — so the ``Live`` capability's STDOUT
binding is this surface's live zone.

This replaces the collision class that shipped before: flow-viz used to run its
own daemon thread writing ANSI cursor moves while a blocked ``input()`` sat on
the same terminal — two writers, one cursor. Here one object owns both the live
refresh and the prompt, so it pauses the refresh while asking. The "raw" fallback
is Rich's own degradation: off a TTY, ``rich.live.Live`` prints final state only
and ``Console`` drops colour — no second renderer.

Lives in ``functualize.ui`` (the ``[cli]`` extra); imports Rich at load.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from rich.console import Console, Group
from rich.live import Live

if TYPE_CHECKING:
    from functualize._events.bus import StructuredEvent
    from functualize._types.interactivity import (
        LiveConstruct,
        PromptRequest,
        PromptResponse,
    )

__all__ = ["StdoutLiveHandle", "StdoutSurface", "stdout_live_session"]


@contextlib.contextmanager
def stdout_live_session(app: Any, descriptor: Any = None) -> Iterator[StdoutSurface]:
    """Push a ``StdoutSurface`` as the active surface for a job's duration.

    Pushed onto the surface stack (not merely registered) so it becomes the
    active terminal surface: the ``Live`` capability binds to its live zone,
    events fan out to it, and — because it is an exclusive terminal surface —
    other terminal surfaces (a stray self-rendering flow-viz) are skipped for
    the window, so there is exactly one writer. Popped and closed in ``finally``.

    Args:
        app: The application whose surface stack to push onto.
        descriptor: The job about to run, used to decide which ambient
            constructs to pre-mount. None mounts none.
    """
    surface = StdoutSurface()
    surface.adopt_ambient(app, descriptor)
    app.push_surface(surface)
    try:
        yield surface
    finally:
        app.pop_surface(surface)
        surface.close()


class StdoutLiveHandle:
    """Handle to a construct mounted in the StdoutSurface live zone.

    Returned by ``StdoutSurface.add`` / ``.panel`` and used as the ``_bound``
    of a ``LiveHandle`` — ``update`` re-renders the live region, ``remove``
    drops the construct.
    """

    def __init__(self, surface: StdoutSurface, construct: LiveConstruct) -> None:
        self._surface = surface
        self._construct = construct

    def update(self) -> None:
        self._surface._refresh_live()

    def remove(self) -> None:
        self._surface._remove_construct(self._construct)


class StdoutSurface:
    """One Rich surface: scrollback + a live zone of constructs + prompts.

    Satisfies ``Surface`` and ``PromptCollector`` and provides the ``Live``
    capability's STDOUT binding (``add`` / ``panel``). ``needs_terminal`` is
    True — it is suspended while a job owns the screen.
    """

    name: str = "stdout"
    needs_terminal: bool = True

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._constructs: list[LiveConstruct] = []
        self._live: Live | None = None
        # Names of ambient constructs mounted here, so an imperative
        # ``live.suppress(name)`` can find and drop them mid-run.
        self._ambient_names: dict[int, str] = {}

    # ─── Ambient constructs ─────────────────────────────────────────────

    def adopt_ambient(self, app: Any, descriptor: Any = None) -> None:
        """Pre-mount the ambient constructs eligible for this job."""
        from functualize._engine.ambient import resolve_ambient_constructs

        for construct in resolve_ambient_constructs(app, descriptor):
            name = getattr(construct, "name", type(construct).__name__)
            self._ambient_names[id(construct)] = str(name)
            self._constructs.append(construct)

    def suppress_ambient(self, name: str) -> None:
        """Drop a mounted ambient construct by name (``live.suppress``)."""
        for construct in list(self._constructs):
            if self._ambient_names.get(id(construct)) == name:
                self._remove_construct(construct)
                self._ambient_names.pop(id(construct), None)

    def suppress_all_ambient(self) -> None:
        """Drop every mounted ambient construct (``live.suppress_all``)."""
        for construct in list(self._constructs):
            if id(construct) in self._ambient_names:
                self._remove_construct(construct)
                self._ambient_names.pop(id(construct), None)

    # ─── Live zone (the Live capability's STDOUT binding) ───────────────

    def _renderable(self) -> Group:
        return Group(*[c for c in self._constructs])

    def _ensure_live(self) -> None:
        if self._live is None:
            self._live = Live(
                self._renderable(),
                console=self._console,
                auto_refresh=False,
                transient=False,
            )
            self._live.start()

    def _refresh_live(self) -> None:
        if not self._constructs:
            return
        self._ensure_live()
        assert self._live is not None
        self._live.update(self._renderable(), refresh=True)

    def _remove_construct(self, construct: LiveConstruct) -> None:
        try:
            self._constructs.remove(construct)
        except ValueError:
            return
        if self._live is not None:
            self._live.update(self._renderable(), refresh=True)

    def add(self, construct: LiveConstruct) -> StdoutLiveHandle:
        """Mount a passive construct (a Rich renderable) in the live zone."""
        self._constructs.append(construct)
        self._refresh_live()
        return StdoutLiveHandle(self, construct)

    def panel(self, construct: LiveConstruct) -> StdoutLiveHandle:
        """Mount an interactive construct. STDOUT has no event loop, so it
        degrades to a passive render (identical to :meth:`add`); interactivity
        needs PANEL or EXCLUSIVE."""
        return self.add(construct)

    # ─── Surface ────────────────────────────────────────────────────────

    def handle_event(self, event: StructuredEvent) -> None:
        """Append an event line to scrollback, above the live zone.

        A hosted construct that also consumes events (e.g. a flow tree built
        from the stream) is forwarded to and the live zone re-rendered.
        """
        forwarded = False
        for construct in self._constructs:
            handler = getattr(construct, "handle_event", None)
            if callable(handler):
                handler(event)
                forwarded = True
        if forwarded:
            self._refresh_live()
            return

        # Otherwise, print a one-line summary into scrollback. rich.live.Live
        # prints above the live region when active.
        line = f"[dim]⚡ {event.event_name}[/dim]"
        resource = getattr(event, "resource", "")
        if resource:
            line += f" [dim]({resource})[/dim]"
        self._print(line)

    def write(self, text: str) -> None:
        """Write a scrollback line (used by log rendering)."""
        self._print(text)

    def _print(self, renderable: Any) -> None:
        if self._live is not None:
            self._live.console.print(renderable)
        else:
            self._console.print(renderable)

    # ─── PromptCollector ────────────────────────────────────────────────

    def collect(self, request: PromptRequest) -> PromptResponse:
        """Ask the user, pausing the live refresh while the prompt is up."""

        was_live = self._live is not None
        if was_live:
            assert self._live is not None
            self._live.stop()
        try:
            answer = self._ask(request)
        finally:
            if was_live and self._constructs:
                # Resume the live zone for whatever follows.
                self._live = None
                self._refresh_live()
        return answer

    def _ask(self, request: PromptRequest) -> PromptResponse:
        from functualize._types.interactivity import PromptResponse

        if not self._console.is_terminal:
            # Non-interactive (piped/CI): honour the default, never block.
            return PromptResponse(value=request.default, source="default")

        prompt = request.question
        if request.choices:
            labels = ", ".join(getattr(c, "value", str(c)) for c in request.choices)
            prompt = f"{prompt} [{labels}]"
        try:
            raw = self._console.input(f"{prompt}: ")
        except (EOFError, KeyboardInterrupt):
            return PromptResponse(value=request.default, source="cancelled")
        if raw == "" and request.default is not None:
            return PromptResponse(value=request.default, source="default")
        return PromptResponse(value=raw, source="user")

    def close(self) -> None:
        """Stop the live zone (idempotent)."""
        if self._live is not None:
            self._live.stop()
            self._live = None
