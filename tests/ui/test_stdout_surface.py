"""StdoutSurface — one Rich surface, one writer.

Uses a non-terminal Rich Console over a StringIO so output is capturable and
the live zone degrades (Rich's own fallback) rather than animating.
"""

from __future__ import annotations

import io

import pytest

from functualize._engine.capabilities.live import Live
from functualize._types.interactivity import (
    PromptCollector,
    PromptIntent,
    PromptRequest,
    Surface,
)

pytest.importorskip("rich")

from rich.console import Console  # noqa: E402
from rich.text import Text  # noqa: E402

from functualize.ui import StdoutSurface  # noqa: E402


class _FakeEvent:
    def __init__(self, name: str, resource: str = "") -> None:
        self.event_name = name
        self.resource = resource
        self.payload: dict = {}


class _Construct:
    """A minimal LiveConstruct (Rich renderable via __rich__)."""

    def __init__(self) -> None:
        self.n = 0

    def __rich__(self) -> Text:
        return Text(f"count={self.n}")


class _EventConstruct(_Construct):
    """A construct that also consumes events (like a flow tree)."""

    def handle_event(self, event: object) -> None:
        self.n += 1


def _surface() -> tuple[StdoutSurface, io.StringIO]:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=80)
    return StdoutSurface(console=console), buf


def test_stdout_surface_conformance() -> None:
    surface, _ = _surface()
    assert isinstance(surface, Surface)
    assert isinstance(surface, PromptCollector)


def test_handle_event_writes_scrollback() -> None:
    surface, buf = _surface()
    surface.handle_event(_FakeEvent("upload.progress", "s3"))
    out = buf.getvalue()
    assert "upload.progress" in out
    assert "s3" in out


def test_event_forwarded_to_hosted_construct() -> None:
    surface, _ = _surface()
    construct = _EventConstruct()
    surface.add(construct)
    surface.handle_event(_FakeEvent("step.done"))
    surface.handle_event(_FakeEvent("step.done"))
    assert construct.n == 2


def test_add_returns_handle_and_update_is_safe() -> None:
    surface, _ = _surface()
    handle = surface.add(_Construct())
    handle.update()  # non-terminal: must not raise
    handle.remove()


def test_collect_returns_default_when_not_a_terminal() -> None:
    surface, _ = _surface()
    resp = surface.collect(
        PromptRequest(question="?", intent=PromptIntent.TEXT_INPUT, default="d")
    )
    assert resp.value == "d"
    assert resp.source == "default"


def test_live_capability_binds_to_stdout_zone() -> None:
    surface, _ = _surface()
    live = Live(_zone=surface)
    construct = _Construct()
    handle = live.add(construct)
    # The construct is hosted by the surface's live zone.
    assert construct in surface._constructs
    handle.update()


def test_stdout_live_session_pushes_and_pops() -> None:
    from types import SimpleNamespace

    from functualize.ui import StdoutSurface, stdout_live_session

    stack: list = []
    app = SimpleNamespace(
        _surfaces=[],
        _surface_stack=stack,
        push_surface=lambda s: stack.append(s),
        pop_surface=lambda s=None: stack.pop(),
    )

    with stdout_live_session(app) as surface:
        assert isinstance(surface, StdoutSurface)
        assert surface in stack  # active during the session
    assert stack == []  # popped in finally
