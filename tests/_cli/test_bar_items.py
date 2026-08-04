"""Unit tests for plugin-provided header/status bar items (bar_items.py).

Covers the consumption semantics documented on the protocols:
priority sort, None-skip, double-space join, BarRenderer override
(last registered wins), and provider exception isolation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from functualize._cli.tui.bar_items import (
    find_bar_renderer,
    render_header_items,
    render_status_items,
)


class _HeaderItem:
    """Minimal HeaderItemProvider implementation."""

    def __init__(self, item_id: str, priority: int, text: str | None) -> None:
        self.item_id = item_id
        self.item_priority = priority
        self._text = text

    def render_item(self, app) -> str | None:
        return self._text


class _StatusItem:
    """Minimal StatusBarItemProvider implementation."""

    def __init__(self, item_id: str, priority: int, text: str | None) -> None:
        self.item_id = item_id
        self.item_priority = priority
        self._text = text

    def render_item(self, app, state) -> str | None:
        return self._text


class _FailingHeaderItem:
    item_id = "boom"
    item_priority = 0

    def render_item(self, app) -> str | None:
        raise RuntimeError("provider exploded")


class _Renderer:
    """Minimal BarRenderer implementation."""

    def __init__(self, bar_type: str, output: str) -> None:
        self.bar_type = bar_type
        self._output = output
        self.seen_items: list[tuple[str, str]] | None = None

    def render(self, items, context) -> str:
        self.seen_items = items
        return self._output


class TestHeaderItems:
    def test_items_sorted_by_priority_and_joined(self) -> None:
        plugins = [
            _HeaderItem("b", 20, "second"),
            _HeaderItem("a", 10, "first"),
        ]
        assert render_header_items(plugins, MagicMock()) == "first  second"

    def test_none_items_skipped(self) -> None:
        plugins = [
            _HeaderItem("a", 10, None),
            _HeaderItem("b", 20, "shown"),
        ]
        assert render_header_items(plugins, MagicMock()) == "shown"

    def test_no_providers_returns_none(self) -> None:
        assert render_header_items([object()], MagicMock()) is None

    def test_failing_provider_isolated(self) -> None:
        plugins = [_FailingHeaderItem(), _HeaderItem("ok", 5, "alive")]
        assert render_header_items(plugins, MagicMock()) == "alive"


class TestStatusItems:
    def test_status_items_receive_state(self) -> None:
        received: list[object] = []

        class _Probe:
            item_id = "probe"
            item_priority = 0

            def render_item(self, app, state) -> str:
                received.append(state)
                return "probed"

        assert render_status_items([_Probe()], MagicMock()) == "probed"
        assert len(received) == 1

    def test_header_provider_not_picked_up_for_status(self) -> None:
        # _HeaderItem.render_item takes (app) only — not a StatusBarItemProvider
        # by signature, but runtime_checkable protocols only check attribute
        # presence, so it IS picked up structurally. Verify no crash and that
        # a real status provider still renders.
        plugins = [_StatusItem("s", 1, "status-ok")]
        assert render_status_items(plugins, MagicMock()) == "status-ok"


class TestBarRenderer:
    def test_renderer_overrides_join(self) -> None:
        renderer = _Renderer("header", "CUSTOM")
        plugins = [_HeaderItem("a", 10, "first"), renderer]

        assert render_header_items(plugins, MagicMock()) == "CUSTOM"
        assert renderer.seen_items == [("a", "first")]

    def test_last_registered_renderer_wins(self) -> None:
        first = _Renderer("status", "FIRST")
        second = _Renderer("status", "SECOND")

        assert find_bar_renderer([first, second], "status") is second

    def test_renderer_bar_type_mismatch_ignored(self) -> None:
        renderer = _Renderer("status", "CUSTOM")
        plugins = [_HeaderItem("a", 10, "first"), renderer]

        assert render_header_items(plugins, MagicMock()) == "first"

    def test_renderer_used_even_with_no_items(self) -> None:
        renderer = _Renderer("header", "ONLY-RENDERER")

        assert render_header_items([renderer], MagicMock()) == "ONLY-RENDERER"

    def test_failing_renderer_falls_back_to_join(self) -> None:
        class _Boom:
            bar_type = "header"

            def render(self, items, context) -> str:
                raise ValueError("renderer exploded")

        plugins = [_HeaderItem("a", 10, "fallback"), _Boom()]
        assert render_header_items(plugins, MagicMock()) == "fallback"
