"""TextualApp base class: Surface/PromptCollector conformance + threading.

Uses Textual's ``run_test`` pilot. asyncio_mode=auto (pyproject) means the
async tests need no decorator.
"""

from __future__ import annotations

import threading

import pytest

from functualize._types.interactivity import (
    PromptCollector,
    PromptIntent,
    PromptRequest,
    Surface,
)

pytest.importorskip("textual")

from functualize.ui import FuncEvent, TextualApp  # noqa: E402


class _FakeEvent:
    """Minimal StructuredEvent stand-in (handle_event only reads event_name)."""

    def __init__(self, name: str) -> None:
        self.event_name = name
        self.resource = ""


class _RecordingApp(TextualApp[None]):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[str] = []

    def on_func_event(self, message: FuncEvent) -> None:
        self.received.append(message.event.event_name)


def test_textualapp_satisfies_both_protocols() -> None:
    app = _RecordingApp()
    assert isinstance(app, Surface)
    assert isinstance(app, PromptCollector)


async def test_pre_mount_events_buffer_and_flush() -> None:
    app = _RecordingApp()
    # Events arriving before mount must not be lost.
    app.handle_event(_FakeEvent("first"))
    app.handle_event(_FakeEvent("second"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.received == ["first", "second"]


async def test_post_mount_event_delivered_to_on_func_event() -> None:
    app = _RecordingApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_event(_FakeEvent("live"))
        await pilot.pause()
        assert "live" in app.received


def test_collect_returns_default_when_not_mounted() -> None:
    app = _RecordingApp()
    resp = app.collect(
        PromptRequest(question="?", intent=PromptIntent.TEXT_INPUT, default="d")
    )
    assert resp.value == "d"
    assert resp.source == "default"


async def test_collect_answers_via_modal() -> None:
    app = _RecordingApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        captured: dict[str, object] = {}

        def worker() -> None:
            captured["resp"] = app.collect(
                PromptRequest(
                    question="Name?",
                    intent=PromptIntent.TEXT_INPUT,
                    default="x",
                    timeout=5.0,
                )
            )

        t = threading.Thread(target=worker)
        t.start()

        # Let the worker schedule the modal onto the loop, then answer it.
        await pilot.pause(0.2)
        await pilot.press("h", "i")
        await pilot.press("enter")

        t.join(timeout=5.0)
        assert not t.is_alive()
        resp = captured["resp"]
        assert resp.value == "hi"  # type: ignore[attr-defined]
        assert resp.source == "user"  # type: ignore[attr-defined]
