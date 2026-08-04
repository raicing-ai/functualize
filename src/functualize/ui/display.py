"""``Display`` — optional base class for ambient TUI display panels.

A display is the above-header panel that shows ambient situational awareness
(git status, running containers, the current cluster) while the shell is idle.
Subclassing is **optional**: discovery duck-types on ``display_id``,
``display_title``, ``display_priority``, ``should_show`` and
``compose_display``, so a plain class still works. What the base buys you is
sane defaults for every optional hook, so a minimal display cannot trip the
refresh timer or the affinity matcher::

    from functualize.ui import Display
    from textual.widgets import Static

    class GitDisplay(Display):
        display_id = "git"
        display_title = "Git"
        refresh_interval = 5.0

        def should_show(self, cwd, app) -> bool:
            return any((p / ".git").exists() for p in [cwd, *cwd.parents])

        def compose_display(self):
            yield Static(self._summary)

        def refresh(self) -> None:
            self._summary = _git_status()   # runs on a thread worker

``refresh()`` is called on a **thread worker**, never the event loop, so it may
do I/O freely. It is bounded by ``refresh_timeout`` seconds; exceeding that
abandons the cycle with a warning rather than freezing the TUI. ``should_show``
runs on the loop thread for every provider on every CWD change — keep it cheap.

Mirrors the ``Surface`` / ``TextualApp`` pattern: a protocol you may satisfy
structurally, plus a base class that fills in the boring parts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import ComposeResult
    from textual.widget import Widget

    from functualize.app.core import FunctualizeApp

__all__ = ["Display"]


class Display:
    """Base class for a ``DisplayProvider`` with defaults for every optional hook.

    Subclasses must set :attr:`display_id` and implement :meth:`should_show`
    and :meth:`compose_display`. Everything else has a working default.
    """

    class DrillDown(Message):
        """Ask the display slot to push ``widget`` as a drill-down sub-view.

        Posted by a display's interactive widget (typically from its
        ``action_drill_down``, reached via Enter in the DISPLAY zone)::

            self.post_message(Display.DrillDown(DetailView(item), item.name))

        The app handles it by mounting the widget in the display slot,
        focusing it, and adding a breadcrumb sub-level; Esc pops back.
        Same idiom as the PanelHost drill-down messages.
        """

        def __init__(self, widget: Widget, title: str) -> None:
            self.widget = widget
            self.title = title
            super().__init__()

    #: Stable identifier, unique across displays. Lowercase, ``[a-z0-9_-]``.
    display_id: str = ""

    #: Human-readable title shown in the display breadcrumb.
    display_title: str = ""

    #: Ring ordering — lower sorts first. Ties break on registration order.
    display_priority: int = 100

    #: Seconds between refreshes, or None to never auto-refresh. Values below
    #: 0.5s are clamped up; the first refresh runs immediately on registration.
    refresh_interval: float | None = None

    #: Seconds to allow :meth:`refresh` before abandoning the cycle.
    refresh_timeout: float = 10.0

    #: Job names this display relates to (drives auto-switch / the indicator).
    linked_jobs: list[str] | None = None

    #: Job groups this display relates to, including ancestor groups.
    linked_groups: list[str] | None = None

    def should_show(self, cwd: Path, app: FunctualizeApp) -> bool:
        """Whether this display is relevant to ``cwd``.

        Runs on the event-loop thread for every provider on every CWD change —
        keep it to cheap filesystem checks, never network or subprocess calls.
        Defaults to always visible.
        """
        return True

    def compose_display(self) -> ComposeResult:
        """Yield the widget tree for this display's body."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement compose_display()"
        )

    def refresh(self) -> None:
        """Update the display's state. Runs on a thread worker; I/O is fine.

        Defaults to a no-op, for displays whose content is static or derived
        entirely in :meth:`compose_display`.
        """
        return None

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        """``(key, label)`` pairs for the dynamic footer. Defaults to none."""
        return []
