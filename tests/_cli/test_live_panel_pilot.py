"""``live.panel(...)`` → interactive PanelHost panel (convergence, item 3).

``PanelLiveZone.panel`` no longer degrades to a passive render: the construct
is wrapped in a ``LivePanelWidget``, joins the general panel ring
(auto-surfacing it), takes focus, and speaks the converged interaction
contract. The handle returns synchronously from the job's worker thread and
all widget work is marshaled; ``close()`` unmounts and the ring collapses
back to the SmartBar when nothing else is showing.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Static

from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize._cli.tui.live_panel_widget import LivePanelWidget
from functualize._cli.tui.panel_live_zone import PanelLiveZone
from tests._cli._tui_fixtures import tui_app

__all__ = ["tui_app"]


class _TreeConstruct:
    """Minimal LiveConstruct: __rich__ + optional interaction hooks."""

    name = "tree"

    def __init__(self) -> None:
        self.drilled = 0

    def __rich__(self) -> str:
        return "execution tree"

    def drill_down(self) -> None:
        self.drilled += 1

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        return [("Enter", "expand")]


def _make_zone(tui_app) -> PanelLiveZone:
    return PanelLiveZone(tui_app, tui_app.query_one("#live-zone", Static))


async def test_live_panel_mounts_interactive_panel(tui_app) -> None:
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        zone = _make_zone(tui_app)
        construct = _TreeConstruct()

        zone.panel(construct)
        await pilot.pause()

        assert tui_app._panel_host.is_active, "live.panel must auto-surface the ring"
        current = tui_app._panel_host.current_panel_widget
        assert isinstance(current, LivePanelWidget)
        assert current.construct is construct
        assert tui_app._focus_state.mode is FocusMode.NORMAL
        assert tui_app._focus_state.zone is FocusZone.PANEL
        assert tui_app.active_panel is current

        # Construct-provided footer hints win over the scroll defaults.
        assert current.get_available_actions(True) == [("Enter", "expand")]

        # Enter routes to the panel widget → the construct's drill hook.
        await pilot.press("enter")
        await pilot.pause()
        assert construct.drilled == 1

        # The passive #live-zone Static must NOT also render the construct.
        assert construct not in zone._constructs

        zone.close()
        await pilot.pause()
        assert not tui_app._panel_host.is_active
        assert tui_app._focus_state.mode is FocusMode.COMMAND


async def test_live_panel_from_worker_thread(tui_app) -> None:
    """The job-thread path: panel() marshals, handle returns immediately."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        zone = _make_zone(tui_app)
        construct = _TreeConstruct()

        handle = await asyncio.to_thread(zone.panel, construct)
        await pilot.pause()

        assert handle.construct is construct
        assert isinstance(tui_app._panel_host.current_panel_widget, LivePanelWidget)

        await asyncio.to_thread(handle.remove)
        await pilot.pause()
        assert not tui_app._panel_host.is_active, (
            "removing the only live panel must collapse the ring"
        )


async def test_live_panel_degrades_without_mount_support() -> None:
    """A bare app without mount_live_panel gets the passive fallback."""

    class _BareApp:
        pass

    zone = PanelLiveZone(_BareApp(), _FakeStatic())
    construct = _TreeConstruct()
    zone.panel(construct)

    assert construct in zone._constructs, "must degrade to a passive add()"
    assert not zone._panel_constructs


class _FakeStatic:
    def update(self, *_args: object) -> None:
        pass

    def set_class(self, *_args: object) -> None:
        pass
