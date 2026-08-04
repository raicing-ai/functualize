"""The status bar must show which environment is loaded.

The environment selects which ``config.<env>.*`` overlay merges, so a user
looking at a config file that "isn't working" needs to see it without
running a command. Crucially, "defaulted to DEV" and "explicitly chose DEV"
must look different — the former is the usual cause of the confusion.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.app.core import FunctualizeApp, JobSources


def _make_tui(tmp_path: Path) -> FunctualizeInlineTUI:
    app = FunctualizeApp(name="envapp", job_sources=JobSources(directories=[]))
    return FunctualizeInlineTUI(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    for var in ("FUNCTUALIZE_ENV", "ENVIRONMENT", "ENV"):
        monkeypatch.delenv(var, raising=False)


def _status_text(tui: FunctualizeInlineTUI) -> str:
    return str(tui.query_one("#status-bar", Static).content)


class TestEnvironmentIndicator:
    @pytest.mark.asyncio
    async def test_shows_explicit_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "prod")
        tui = _make_tui(tmp_path)
        async with tui.run_test() as pilot:
            await pilot.pause()
            assert "ENV:prod" in _status_text(tui)

    @pytest.mark.asyncio
    async def test_shows_default_environment(self, tmp_path: Path) -> None:
        tui = _make_tui(tmp_path)
        async with tui.run_test() as pilot:
            await pilot.pause()
            assert "ENV:DEV" in _status_text(tui)

    @pytest.mark.asyncio
    async def test_functualize_env_wins_over_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("FUNCTUALIZE_ENV", "staging")
        tui = _make_tui(tmp_path)
        async with tui.run_test() as pilot:
            await pilot.pause()
            assert "ENV:staging" in _status_text(tui)

    def test_defaulted_and_explicit_are_visually_distinct(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same name, different provenance — must not render identically."""
        defaulted = _make_tui(tmp_path)._environment_indicator()

        monkeypatch.setenv("ENVIRONMENT", "DEV")
        explicit = _make_tui(tmp_path)._environment_indicator()

        assert "DEV" in defaulted
        assert "DEV" in explicit
        assert defaulted != explicit
