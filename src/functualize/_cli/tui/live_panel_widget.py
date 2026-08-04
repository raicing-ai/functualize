"""LivePanelWidget — a job-scoped LiveConstruct hosted as a PanelHost panel.

``live.panel(construct)`` in PANEL mode mounts the construct here instead of
the passive ``#live-zone`` Static: the widget joins the general panel ring,
takes focus, and speaks the converged interaction contract
(``InteractiveContent``) — ``action_*`` methods reached via
``KEYMAPS → KeyDispatcher._resolve_target`` and ``get_available_actions`` for
the footer. No ``BINDINGS``: KEYMAPS stays the sole key router.

The construct remains the source of truth: ``__rich__()`` renders it,
``handle_event`` (via the owning ``PanelLiveZone``) updates it, and this
widget just repaints. Optional construct hooks make it interactive beyond
scrolling:

- ``get_available_actions(focused)`` — footer hints
- ``action_drill_down()`` (or ``drill_down()``) — Enter

Threading: jobs run on a worker thread, so every mutation of this widget is
marshaled by the caller (``PanelLiveZone``); the widget itself only ever runs
on the loop thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from textual.containers import VerticalScroll
    from textual.css.query import NoMatches
    from textual.widget import Widget
    from textual.widgets import Static
except ImportError as _exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "LivePanelWidget requires the [cli] extras group. "
        "Install with: pip install functualize[cli]"
    ) from _exc

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from functualize._types.interactivity import LiveConstruct

__all__ = ["LivePanelWidget"]

_SCROLL_STEP = 1


class LivePanelWidget(Widget):
    """Interactive PanelHost panel wrapping a job's ``LiveConstruct``."""

    can_focus = True

    DEFAULT_CSS = """
    LivePanelWidget {
        height: auto;
        min-height: 3;
        max-height: 16;
    }
    LivePanelWidget VerticalScroll {
        height: auto;
        min-height: 2;
        max-height: 14;
    }
    """

    def __init__(self, construct: LiveConstruct, title: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._construct = construct
        self._title = title
        self._body = Static("")

    @property
    def construct(self) -> LiveConstruct:
        """The hosted construct (source of truth for rendering)."""
        return self._construct

    @property
    def title(self) -> str:
        """Ring title this panel was mounted under."""
        return self._title

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield self._body

    def on_mount(self) -> None:
        self.refresh_from_construct()

    def refresh_from_construct(self) -> None:
        """Repaint the body from the construct. Loop thread only."""
        try:
            self._body.update(self._construct)  # renders via __rich__()
        except Exception as exc:
            self.log.warning(
                f"LivePanelWidget: construct {type(self._construct).__name__} "
                f"failed to render ({type(exc).__name__}): {exc}"
            )

    # ─── Converged interaction contract (KEYMAPS → _resolve_target) ─────

    def action_cursor_down(self) -> None:
        """j / down — scroll the construct body."""
        self._scroll(_SCROLL_STEP)

    def action_cursor_up(self) -> None:
        """k / up — scroll the construct body."""
        self._scroll(-_SCROLL_STEP)

    def action_drill_down(self) -> None:
        """Enter — delegate to the construct's optional hook; inert otherwise."""
        hook = getattr(self._construct, "action_drill_down", None) or getattr(
            self._construct, "drill_down", None
        )
        if not callable(hook):
            return
        try:
            hook()
        except Exception as exc:
            self.log.warning(
                f"LivePanelWidget: construct drill_down raised "
                f"({type(exc).__name__}): {exc}"
            )
            return
        self.refresh_from_construct()

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """Footer hints — the construct's own, else scroll/back defaults."""
        getter: Any = getattr(self._construct, "get_available_actions", None)
        if callable(getter):
            try:
                raw_actions: Any = getter(focused)
                return list(raw_actions)
            except Exception as exc:
                self.log.warning(
                    f"LivePanelWidget: construct get_available_actions raised "
                    f"({type(exc).__name__}): {exc}"
                )
        return [("j/k", "scroll"), ("Esc", "back")]

    def _scroll(self, delta: int) -> None:
        try:
            scroller = self.query_one(VerticalScroll)
        except NoMatches:
            # Not composed yet (action before mount completes) — nothing to
            # scroll.
            return
        scroller.scroll_relative(y=delta, animate=False)
