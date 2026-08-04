"""FullscreenTuiApp — the shipped TextualApp subclass (fullscreen shell).

Migrated from the dissolved functualize-fullscreen-tui plugin; the bespoke
collect/event-marshaling it used to carry now comes from the TextualApp base
and is covered by test_textual_app.py.
"""

from __future__ import annotations

import pytest

from functualize._types.interactivity import PromptCollector, Surface

pytest.importorskip("textual")

from functualize.ui.fullscreen import FullscreenTuiApp  # noqa: E402


class _FakeEvent:
    def __init__(self, name: str) -> None:
        self.event_name = name
        self.resource = "svc"


def test_fullscreen_app_is_surface_and_collector() -> None:
    app = FullscreenTuiApp()
    assert isinstance(app, Surface)
    assert isinstance(app, PromptCollector)


async def test_fullscreen_app_mounts_main_screen() -> None:
    app = FullscreenTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.main_screen is not None
        # The split-pane widgets are reachable.
        assert app.main_screen.log_panel is not None
        assert app.main_screen.flow_tree is not None


async def test_fullscreen_app_renders_event_into_log() -> None:
    app = FullscreenTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Should not raise; the event is marshaled onto the loop and written.
        app.handle_event(_FakeEvent("upload.progress"))
        await pilot.pause()
