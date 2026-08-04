"""Tests for the PANEL binding of the ``Live`` capability (item 2).

A ``live: Live`` job run in the func TUI panel used to degrade silently:
``active_live_zone`` found no live-capable surface, so ``live.add()`` no-op'd.
These tests prove the zone is resolved, rendered into, and unwound.

Jobs are registered on the ``FunctualizeApp`` **before** the TUI is
constructed — the TUI snapshots the job registry at construction, so a job
registered afterwards is not recognized by the smart bar.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from textual.widgets import Static

from functualize._cli.tui.app import FunctualizeInlineTUI

# Runtime imports (not TYPE_CHECKING): capability injection resolves the job
# signatures' string annotations via get_type_hints, which needs these names
# in the module globals — moving them out silently un-injects the jobs.
from functualize._engine.capabilities.live import Live  # noqa: TC001
from functualize._engine.capabilities.runcontext import RunContext  # noqa: TC001
from functualize._engine.surface_routing import active_live_zone
from functualize.app.core import FunctualizeApp


class _Table:
    """A minimal LiveConstruct: renders text, counts events."""

    def __init__(self) -> None:
        self.rows: list[str] = []
        self.events = 0

    def __rich__(self) -> str:
        return "\n".join(self.rows) or "(empty)"

    def handle_event(self, event: object) -> None:
        self.events += 1


@pytest.fixture()
def make_tui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str, Callable[..., None]], FunctualizeInlineTUI]:
    """Build a TUI over an app with one job already registered."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    def _make(job_name: str, fn: Callable[..., None]) -> FunctualizeInlineTUI:
        func_app = FunctualizeApp(name="liveapp")
        func_app.register_dynamic_job(job_name, fn)
        return FunctualizeInlineTUI(func_app)

    return _make


def _live_zone_text(tui: FunctualizeInlineTUI) -> str:
    """Render the live-zone widget's current content to plain text.

    ``Static.render()`` returns a visual wrapper, not the text, so the content
    is re-rendered through a Rich console to assert on what a user would see.
    """
    from rich.console import Console

    widget = tui.query_one("#live-zone", Static)
    content: object = None
    for attr in ("content", "renderable", "_renderable", "_content"):
        value = getattr(widget, attr, None)
        if value is not None:
            content = value
            break
    if content is None:
        return ""
    console = Console(file=io.StringIO(), width=80, force_terminal=False)
    console.print(content)
    return console.file.getvalue()  # type: ignore[union-attr]


async def _run_job(tui: FunctualizeInlineTUI, job_name: str) -> str:
    """Run ``job_name`` through the real TUI; return the live zone's text."""
    async with tui.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui._smart_bar.value = job_name
        await pilot.pause()
        tui.action_execute()
        await pilot.pause()
        await tui.workers.wait_for_complete()
        await pilot.pause()
        return _live_zone_text(tui)


async def test_live_zone_is_resolved_and_rendered_during_panel_run(
    make_tui: Callable[[str, Callable[..., None]], FunctualizeInlineTUI],
) -> None:
    """A `live: Live` job binds to the panel zone and its construct renders."""
    seen: dict[str, object] = {}

    def live_job(live: Live) -> None:
        # Runs on the job worker thread — exactly where the marshaling matters.
        seen["zone"] = active_live_zone(tui._func_app)
        table = _Table()
        handle = live.add(table)
        table.rows.append("alpha")
        handle.update()

    tui = make_tui("livejob", live_job)
    rendered = await _run_job(tui, "livejob")

    assert seen.get("zone") is not None, (
        "active_live_zone must resolve the PANEL zone during a panel run — "
        "`live.add()` is degrading to a no-op again"
    )
    assert "alpha" in rendered, (
        f"the construct's content should render into #live-zone, got {rendered!r}"
    )


async def test_live_zone_is_popped_after_the_run(
    make_tui: Callable[[str, Callable[..., None]], FunctualizeInlineTUI],
) -> None:
    """The zone is scoped to the run — including when the job raises."""

    def boom(live: Live) -> None:
        live.add(_Table())
        raise RuntimeError("job failed")

    tui = make_tui("boom", boom)
    await _run_job(tui, "boom")

    assert active_live_zone(tui._func_app) is None, (
        "the panel live zone must be popped in `finally` even when the job "
        "raises, or it leaks into the next run"
    )


async def test_events_forward_to_hosted_constructs(
    make_tui: Callable[[str, Callable[..., None]], FunctualizeInlineTUI],
) -> None:
    """A construct exposing handle_event is fed the job's event stream."""

    captured: dict[str, _Table] = {}

    def emitting_job(live: Live, rc: RunContext) -> None:
        table = _Table()
        live.add(table)
        captured["table"] = table
        rc.emit("custom.thing", resource="widget")

    tui = make_tui("emitter", emitting_job)
    await _run_job(tui, "emitter")

    table = captured.get("table")
    assert table is not None, "the job body did not run"
    assert table.events >= 1, (
        "the zone should forward structured events to hosted constructs that "
        "expose handle_event"
    )
