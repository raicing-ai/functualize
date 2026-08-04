"""Live capability — a per-surface live-display channel.

A job that wants a live-updating view declares ``live: Live`` and pushes a
construct::

    @job
    def sync(cfg: SyncConfig, live: Live) -> None:
        table = live.add(SyncTable())      # a LiveConstruct (Rich renderable)
        for row in stream(cfg):
            table.update()                 # the SURFACE owns the cursor/mount

``Live`` is **always injected and degrading** (unlike ``TTY``, which grants an
irreducible resource and can be absent). It grants a *channel* that always has
a fallback — a ``rich.live.Live`` zone in STDOUT, a PanelHost region in the func
TUI panel, event-emission in MCP, and a no-op in the kernel. So ``live: Live``
runs on every surface and the job never needs a None check.

The kernel provides this bare, zone-less version (no live surface → the handles
are no-ops that never raise). The real surface-side bindings are supplied by the
delivery layer (``functualize.ui`` ``StdoutSurface`` live zone / TUI PanelHost),
Phase 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._types.interactivity import LiveConstruct

__all__ = ["Live", "LiveHandle"]


class LiveHandle:
    """A construct mounted in the active surface's live zone.

    Returned by :meth:`Live.add` / :meth:`Live.panel`. ``update()`` asks the
    surface to repaint the construct; the surface owns the cursor/mount, so the
    job never moves a cursor or marshals threads. In a degraded context (the
    kernel default, MCP, headless) the bound surface handle is None and every
    method is a no-op that never raises — job code is identical everywhere.
    """

    def __init__(self, construct: LiveConstruct, *, _bound: Any | None = None) -> None:
        self._construct = construct
        self._bound = _bound

    @property
    def construct(self) -> LiveConstruct:
        """The construct this handle renders."""
        return self._construct

    def update(self) -> None:
        """Ask the surface to repaint the construct's current state."""
        if self._bound is not None:
            self._bound.update()

    def push(self) -> None:
        """Alias for :meth:`update` (reads naturally for append-style constructs)."""
        self.update()

    def remove(self) -> None:
        """Remove the construct from the live zone."""
        if self._bound is not None:
            self._bound.remove()


class Live:
    """Per-invocation live-display channel, bound to the active rendering surface.

    Args:
        _zone: The surface-side live zone that actually mounts constructs, or
            None for the degraded/kernel case (handles become no-ops).
    """

    def __init__(self, *, _zone: Any | None = None) -> None:
        self._zone = _zone

    def suppress(self, name: str) -> None:
        """Hide an ambient construct for this invocation.

        Ambient constructs are the ones a plugin registered to render by
        default (a flow-viz tree, say). A job that wants a quiet output for
        one run drops it here::

            def simple(live: Live) -> None:
                live.suppress("flow-viz")

        The declarative equivalent is ``@job(suppress_live=["flow-viz"])``;
        project-wide, it is ``[live] suppress``. No-op in a degraded context.
        """
        if self._zone is not None:
            suppressor = getattr(self._zone, "suppress_ambient", None)
            if callable(suppressor):
                suppressor(name)

    def suppress_all(self) -> None:
        """Hide every ambient construct for this invocation."""
        if self._zone is not None:
            suppressor = getattr(self._zone, "suppress_all_ambient", None)
            if callable(suppressor):
                suppressor()

    def add(self, construct: LiveConstruct) -> LiveHandle:
        """Mount a passive construct (a Rich renderable) in the live zone."""
        if self._zone is not None:
            return self._zone.add(construct)  # type: ignore[no-any-return]
        return LiveHandle(construct)

    def panel(self, construct: LiveConstruct) -> LiveHandle:
        """Mount an interactive construct as a PanelHost panel (j/k/Enter).

        Requires an event loop; where none exists (STDOUT) it degrades to a
        passive render, and in MCP to event-emission — the same handle, honest
        degradation. In the kernel it is a no-op.
        """
        if self._zone is not None:
            return self._zone.panel(construct)  # type: ignore[no-any-return]
        return LiveHandle(construct)
