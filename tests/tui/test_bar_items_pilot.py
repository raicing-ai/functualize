"""Pilot test: plugin-provided bar items reach the header and status bar."""

from __future__ import annotations

import pytest

try:
    import textual  # noqa: F401

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

pytestmark = [
    pytest.mark.skipif(not HAS_TEXTUAL, reason="textual not available"),
]


class _BarItemsPlugin:
    """Plugin providing one header item and one status bar item."""

    name = "bar-items-test"
    version = "1.0.0"
    description = "Test plugin for bar items"

    item_id = "test-item"
    item_priority = 10

    def render_item(self, app, state=None) -> str:
        return "PLUGIN-BAR-TEXT"


@pytest.fixture()
def tui_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)

    from functualize.app.core import FunctualizeApp

    func_app = FunctualizeApp(name="testapp")
    func_app.plugin_loader._loaded_instances.append(_BarItemsPlugin())

    from functualize._cli.tui.app import FunctualizeInlineTUI

    return FunctualizeInlineTUI(func_app)


async def test_plugin_items_render_in_bars(tui_app) -> None:
    from textual.widgets import Static

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

        header = tui_app.query_one("#header", Static)
        assert "PLUGIN-BAR-TEXT" in str(header.content)

        # Force a status bar refresh through the single update path
        tui_app._update_status_bar(tui_app._focus_state.mode, tui_app._focus_state.zone)
        await pilot.pause()
        status_bar = tui_app.query_one("#status-bar", Static)
        assert "PLUGIN-BAR-TEXT" in str(status_bar.content)
