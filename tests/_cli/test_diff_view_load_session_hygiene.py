"""Targeted regression tests for ``on_diff_view_widget_load_session_requested``.

The tautological ``except (AttributeError, Exception)`` catch
inside ``on_diff_view_widget_load_session_requested`` was collapsed to its
narrowest meaningful exception type (a single logged ``except Exception``,
since the guarded code — a snapshot-store lookup and a panel method call —
is not a ``query_one``/``query`` lookup, so ``NoMatches`` narrowing does not
apply per the TUI audit rules).

This module proves the handler degrades gracefully (does not crash) in both
of the scenarios the original tautological catch was written to guard:

1. The active panel is not a ``DiffViewWidget`` (the ``isinstance`` guard
   short-circuits before the try/except is even entered).
2. The active panel *is* a ``DiffViewWidget`` but the panel-refresh call
   inside the try raises — the collapsed ``except Exception`` must still
   catch it, log it, and let the handler return normally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.data.config_snapshot_store import ConfigSnapshot
from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.diff_view_widget import DiffViewWidget
from functualize.app.core import FunctualizeApp


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    """A real FunctualizeInlineTUI over a minimal app, isolated from $HOME/cwd."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="loadsessionhygieneapp")

    def greet(name: str = "world") -> None:  # pragma: no cover - never run
        pass

    func_app.register_dynamic_job("greet", greet)

    return FunctualizeInlineTUI(func_app)


def _snapshot(values: dict[str, str]) -> ConfigSnapshot:
    return ConfigSnapshot(
        job_name="greet", timestamp=0.0, values=values, outcome="success"
    )


class _FakeEvent:
    """Stand-in for DiffViewWidget.LoadSessionRequested."""

    def __init__(self, snapshot: ConfigSnapshot) -> None:
        self.snapshot = snapshot


async def test_degrades_gracefully_when_active_panel_is_not_diff_view(
    tui_app: FunctualizeInlineTUI,
) -> None:
    """handler does not crash when the active panel isn't a
    DiffViewWidget — the isinstance guard short-circuits before the
    (now-collapsed) except block would ever be reached."""
    async with tui_app.run_test(size=(100, 30)):
        tui_app._pending = tui_app._build_pending_execution("greet")

        # Active panel is None (no panel host activated) — not a DiffViewWidget.
        assert tui_app.active_panel is None

        event = _FakeEvent(_snapshot({"name": "bob"}))
        # Should not raise.
        tui_app.on_diff_view_widget_load_session_requested(event)  # type: ignore[arg-type]

        assert tui_app._pending.overrides["name"] == "bob"


async def test_degrades_gracefully_when_panel_refresh_raises(
    tui_app: FunctualizeInlineTUI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """when the active panel IS a DiffViewWidget but
    ``refresh_diff_only`` raises, the collapsed ``except Exception`` catch
    still swallows it (logging via ``self.log.warning``) instead of
    crashing the handler."""
    async with tui_app.run_test(size=(100, 30)):
        tui_app._pending = tui_app._build_pending_execution("greet")

        panel = DiffViewWidget()

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated refresh failure")

        panel.refresh_diff_only = _boom  # type: ignore[method-assign]

        # active_panel is a read-only property delegating to the panel
        # host; patch it on the class for this unit-level test (restored
        # automatically by monkeypatch on teardown).
        monkeypatch.setattr(type(tui_app), "active_panel", property(lambda self: panel))

        event = _FakeEvent(_snapshot({"name": "bob"}))
        # Should not raise, despite refresh_diff_only blowing up.
        tui_app.on_diff_view_widget_load_session_requested(event)  # type: ignore[arg-type]

        assert tui_app._pending.overrides["name"] == "bob"
