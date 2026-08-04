"""PanelLiveZone — the ``Live`` capability's binding for PANEL execution.

A ``live: Live`` job run from the func TUI used to degrade silently: the
surface stack held no live-capable surface, so ``active_live_zone`` returned
None and every ``live.add()`` no-op'd. This is the missing surface. Pushed for
the duration of a PANEL run, it makes ``Live`` bind here instead, so the same
job body that renders a table on STDOUT renders it in the output panel.

Rendering differs from ``StdoutSurface`` only in the mechanics: STDOUT owns a
``rich.live.Live`` region and manages the cursor; here a Textual ``Static``
is handed the composed Rich renderable and Textual handles the repaint.

Threading contract (steering_textual_tui.md §2.5): jobs execute on a thread
worker, so ``live.add()`` / ``handle.update()`` arrive **off the loop thread**.
Every widget mutation therefore goes through ``marshal``. Writing to the widget
directly from the job thread is the original freeze/corruption bug in a new
costume.

``needs_terminal`` is False: this surface draws inside the TUI, not onto the
raw terminal, so the exclusive-window fan-out filter must not skip it.

This module is in the ``_cli/`` layer — it imports Textual at runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

try:
    from rich.console import Group
except ImportError as _exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "PanelLiveZone requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

from functualize._cli.tui.thread_marshal import marshal

if TYPE_CHECKING:
    from textual.widgets import Static

    from functualize._events.bus import StructuredEvent
    from functualize._types.interactivity import LiveConstruct

logger = logging.getLogger(__name__)

__all__ = ["PanelLiveHandle", "PanelLiveZone"]


class PanelLiveHandle:
    """Handle to a construct mounted in the panel live zone.

    Used as the ``_bound`` of the capability's ``LiveHandle``: ``update()``
    repaints, ``remove()`` drops the construct.
    """

    def __init__(self, zone: PanelLiveZone, construct: LiveConstruct) -> None:
        self._zone = zone
        self._construct = construct

    @property
    def construct(self) -> LiveConstruct:
        return self._construct

    def update(self) -> None:
        self._zone.refresh_live()

    def push(self) -> None:
        self.update()

    def remove(self) -> None:
        self._zone.remove_construct(self._construct)


class PanelLiveZone:
    """A live zone backed by a Textual ``Static`` in the TUI output area.

    Satisfies the live-zone duck type ``active_live_zone`` looks for (``add``
    and ``panel``) plus ``Surface`` (``handle_event``), so hosted constructs
    that consume events are fed the same way ``StdoutSurface`` feeds them.
    """

    name: str = "panel-live"
    # Draws inside the TUI, not on the raw terminal — must keep receiving
    # events even while a terminal-owning surface is active.
    needs_terminal: bool = False

    def __init__(self, textual_app: Any, widget: Static) -> None:
        self._app = textual_app
        self._widget = widget
        self._constructs: list[LiveConstruct] = []
        # Names of ambient constructs mounted here, so an imperative
        # ``live.suppress(name)`` can find and drop them mid-run.
        self._ambient_names: dict[int, str] = {}
        # ``live.panel(...)`` constructs, hosted as interactive PanelHost
        # panels rather than in the passive zone widget. Kept out of
        # ``_constructs`` so the zone Static never double-renders them.
        self._panel_constructs: list[LiveConstruct] = []
        self._panel_widgets: dict[int, Any] = {}

    # ─── Ambient constructs ─────────────────────────────────────────────

    def adopt_ambient(self, func_app: Any, descriptor: Any = None) -> None:
        """Pre-mount the ambient constructs eligible for this job.

        Goes through the app facade rather than ``_engine`` directly (the
        "_cli uses public API only" import contract), but lands on the same
        resolution helper ``StdoutSurface`` uses — so predicates and
        suppression cannot drift between the two surfaces.
        """
        resolver = getattr(func_app, "resolve_ambient_constructs", None)
        if not callable(resolver):
            return
        constructs = resolver(descriptor)
        if not constructs:
            return
        for construct in constructs:
            name = getattr(construct, "name", type(construct).__name__)
            self._ambient_names[id(construct)] = str(name)
            self._constructs.append(construct)
        self._show()
        self.refresh_live()

    def suppress_ambient(self, name: str) -> None:
        """Drop a mounted ambient construct by name (``live.suppress``)."""
        for construct in list(self._constructs):
            if self._ambient_names.get(id(construct)) == name:
                self._ambient_names.pop(id(construct), None)
                self.remove_construct(construct)

    def suppress_all_ambient(self) -> None:
        """Drop every mounted ambient construct (``live.suppress_all``)."""
        for construct in list(self._constructs):
            if id(construct) in self._ambient_names:
                self._ambient_names.pop(id(construct), None)
                self.remove_construct(construct)

    # ─── Live zone (the Live capability's PANEL binding) ────────────────

    def add(self, construct: LiveConstruct) -> PanelLiveHandle:
        """Mount a passive construct (a Rich renderable) in the live zone."""
        self._constructs.append(construct)
        self._show()
        self.refresh_live()
        return PanelLiveHandle(self, construct)

    def panel(self, construct: LiveConstruct) -> PanelLiveHandle:
        """Mount an interactive construct as a PanelHost panel.

        The construct joins the general panel ring wrapped in a
        ``LivePanelWidget`` (focusable; j/k scroll, Enter drill-down, footer
        hints — the converged interaction contract), auto-surfacing the ring.
        Called from the job's worker thread: the handle returns immediately
        and every widget mutation is marshaled onto the loop thread. Degrades
        to a passive ``add()``-style render when the app exposes no
        ``mount_live_panel`` (bare zones in unit tests).
        """
        handle = PanelLiveHandle(self, construct)
        self._panel_constructs.append(construct)
        marshal(self._app, self._mount_panel_widget, construct)
        return handle

    def _mount_panel_widget(self, construct: LiveConstruct) -> None:
        """Build + mount the panel widget. Loop thread only (via marshal)."""
        if construct not in self._panel_constructs:
            # Removed (or the run ended) before the marshaled mount ran.
            return
        mounter = getattr(self._app, "mount_live_panel", None)
        if not callable(mounter):
            # No PanelHost to join — passive degradation, same as add().
            self._panel_constructs.remove(construct)
            self._constructs.append(construct)
            self._show()
            self.refresh_live()
            return
        try:
            from functualize._cli.tui.live_panel_widget import LivePanelWidget

            title = getattr(construct, "title", None) or getattr(
                construct, "name", None
            )
            title = str(title) if title else type(construct).__name__
            widget = LivePanelWidget(construct, title)
            mounter(widget, title)
            self._panel_widgets[id(construct)] = widget
        except Exception:
            logger.warning(
                "PanelLiveZone: failed to mount live panel for %r; "
                "falling back to passive render",
                type(construct).__name__,
                exc_info=True,
            )
            if construct in self._panel_constructs:
                self._panel_constructs.remove(construct)
                self._constructs.append(construct)
                self._show()
                self.refresh_live()

    def _unmount_panel_widget(self, widget: Any) -> None:
        """Remove a mounted panel widget. Loop thread only (via marshal)."""
        remover = getattr(self._app, "remove_live_panel", None)
        if callable(remover):
            try:
                remover(widget)
            except Exception:
                logger.warning(
                    "PanelLiveZone: failed to remove live panel", exc_info=True
                )

    def remove_construct(self, construct: LiveConstruct) -> None:
        removed = False
        try:
            self._constructs.remove(construct)
            removed = True
        except ValueError:
            pass
        if construct in self._panel_constructs:
            self._panel_constructs.remove(construct)
            removed = True
            widget = self._panel_widgets.pop(id(construct), None)
            if widget is not None:
                marshal(self._app, self._unmount_panel_widget, widget)
        if removed:
            self.refresh_live()

    def refresh_live(self) -> None:
        """Repaint the zone from the current constructs (thread-safe)."""
        marshal(self._app, self._render)

    def _render(self) -> None:
        """Update the widget(s). Loop thread only — always reached via marshal."""
        try:
            self._widget.update(Group(*self._constructs))
        except Exception:
            logger.warning("PanelLiveZone: failed to render constructs", exc_info=True)
        for widget in self._panel_widgets.values():
            refresher = getattr(widget, "refresh_from_construct", None)
            if callable(refresher):
                refresher()

    def _show(self) -> None:
        marshal(self._app, self._set_visible, True)

    def _set_visible(self, visible: bool) -> None:
        """Toggle the zone's visibility. Loop thread only."""
        try:
            self._widget.set_class(visible, "visible")
        except Exception:
            logger.warning("PanelLiveZone: failed to toggle visibility", exc_info=True)

    # ─── Surface ────────────────────────────────────────────────────────

    def handle_event(self, event: StructuredEvent) -> None:
        """Forward events to hosted constructs that consume them.

        Mirrors ``StdoutSurface.handle_event``'s forwarding, minus the
        scrollback fallback: log lines already reach the output panel through
        the TUI's logging handler, so echoing events here would double up.
        """
        forwarded = False
        for construct in [*self._constructs, *self._panel_constructs]:
            handler = getattr(construct, "handle_event", None)
            if not callable(handler):
                continue
            try:
                handler(event)
                forwarded = True
            except Exception:
                logger.warning(
                    "PanelLiveZone: construct %r raised in handle_event",
                    type(construct).__name__,
                    exc_info=True,
                )
        if forwarded:
            self.refresh_live()

    # ─── Lifecycle ──────────────────────────────────────────────────────

    def close(self) -> None:
        """Drop all constructs, unmount live panels, hide the zone (idempotent)."""
        self._constructs.clear()
        self._panel_constructs.clear()
        for widget in list(self._panel_widgets.values()):
            marshal(self._app, self._unmount_panel_widget, widget)
        self._panel_widgets.clear()
        marshal(self._app, self._set_visible, False)
