"""snapshot baseline for stable TUI states.

Covers, at minimum, the four states called out in
``contributor/guides/steering_textual_tui.md`` §4.4 ("Snapshot stable
states only: default empty state, READY bar, panel ring open, modal
open"):

1. Empty/default state — bar GREY, no job typed.
2. READY bar state — a valid job + args typed, bar green.
3. Panel ring open (Ctrl+E), NORMAL mode.
4. Modal open (Ctrl+S with a valid command) — ``ShortcutSaveModal``
   visible.

All fixture data is deterministic (a fixed dynamic ``greet(name="world")``
job, fixed SmartBar text, no real filesystem scanning, no timestamps) and
``terminal_size`` is fixed for every test, per §4.4's flakiness rules.

Deviation from the literal "launcher module referenced by path" pattern
shown in §4.4: ``pytest_textual_snapshot.snap_compare`` accepts either a
file path *or* a live ``App`` instance
(``pytest_textual_snapshot.py::compare``, ``app: str | PurePath |
App[Any]``). Building the app from a static launcher file would require
that file to independently reproduce the ``XDG_DATA_HOME``/``chdir``
isolation and dynamic-job registration that live in the shared
``tests/_cli/_tui_fixtures.py`` factory (``make_tui_app``) — duplicating
exactly the isolation boilerplate exists to eliminate. Passing
a constructed ``FunctualizeInlineTUI`` instance directly keeps a single
source of truth for app construction while remaining fully within the
plugin's supported API and this repo's fixture conventions (§4.2).

Workflow (per §4.4): first run fails (no baseline SVG exists yet) — that
is expected. Run with ``--snapshot-update`` to generate/commit the
baseline SVGs under ``tests/_cli/__snapshots__/test_snapshot_baseline/``,
then re-run normally to confirm they pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from functualize._cli.tui.shortcut_save_modal import ShortcutSaveModal
from tests._cli._tui_fixtures import make_tui_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from textual.pilot import Pilot

    from functualize._cli.tui.app import FunctualizeInlineTUI

_TERMINAL_SIZE = (120, 40)


def _build_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    return make_tui_app(tmp_path, monkeypatch, app_name="snapshotapp")


def _as_tui(pilot: Pilot[FunctualizeInlineTUI]) -> FunctualizeInlineTUI:
    """Narrow ``pilot.app`` from ``App[T]`` to ``FunctualizeInlineTUI``.

    ``Pilot[T]`` parameterizes the App's ``run()`` return type, not the App
    subclass itself, so ``pilot.app`` is statically typed as the base
    ``App[T]`` regardless of ``T`` — this cast documents (and localizes)
    that the app under test is always our concrete
    ``FunctualizeInlineTUI`` here.
    """
    return cast("FunctualizeInlineTUI", pilot.app)


async def _ready_bar(pilot: Pilot[FunctualizeInlineTUI]) -> None:
    app = _as_tui(pilot)
    app._smart_bar.value = "greet --name bob"


async def _panel_ring_open(pilot: Pilot[FunctualizeInlineTUI]) -> None:
    app = _as_tui(pilot)
    app.set_focus(None)


async def _modal_open(pilot: Pilot[FunctualizeInlineTUI]) -> None:
    app = _as_tui(pilot)
    app._smart_bar.value = "greet"
    await pilot.pause()
    assert app._smart_bar.readiness.name == "READY"
    app.set_focus(None)


def test_snapshot_empty_state(
    snap_compare: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default empty state: no job typed, bar GREY, no panels open."""
    app = _build_app(tmp_path, monkeypatch)
    assert snap_compare(app, terminal_size=_TERMINAL_SIZE)


def test_snapshot_ready_bar(
    snap_compare: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """READY bar state: a valid job + args typed, bar renders green."""
    app = _build_app(tmp_path, monkeypatch)
    assert snap_compare(app, run_before=_ready_bar, terminal_size=_TERMINAL_SIZE)


def test_snapshot_panel_ring_open(
    snap_compare: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Panel ring open (Ctrl+E), NORMAL mode."""
    app = _build_app(tmp_path, monkeypatch)
    assert snap_compare(
        app,
        run_before=_panel_ring_open,
        press=["ctrl+e"],
        terminal_size=_TERMINAL_SIZE,
    )


def test_snapshot_modal_open(
    snap_compare: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modal open (Ctrl+S with a valid command): ShortcutSaveModal visible."""
    app = _build_app(tmp_path, monkeypatch)

    async def _open_modal(pilot: Pilot[FunctualizeInlineTUI]) -> None:
        await _modal_open(pilot)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert any(isinstance(s, ShortcutSaveModal) for s in pilot.app.screen_stack), (
            "modal should be pushed onto the screen stack before the screenshot"
        )

    assert snap_compare(app, run_before=_open_modal, terminal_size=_TERMINAL_SIZE)
