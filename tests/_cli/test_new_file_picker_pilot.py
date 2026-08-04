"""End-to-end Pilot tests for the new-file picker (`n` on a Files panel).

Real keys against a real TUI, per the tui-panels steering (HARD rule: a new
KEYMAPS entry ships with a pilot test that presses the actual key).

The picker exists because a user who doesn't know the file conventions
cannot type the right filename into a prompt: `n` lists the conventional
locations, Enter continues into the shared Detail view scoped to the chosen
(possibly not-yet-existing) path, and Ctrl+S there writes the file into
being. Nothing is created before that save.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize._cli.tui.new_file_picker import NewFilePickerView
from functualize._cli.tui.panels.config_files import ConfigFilesPanel
from functualize._cli.tui.panels.settings_files import SettingsFilesPanel
from functualize._cli.tui.source_chain_detail import SourceChainDetailView
from functualize.app.core import FunctualizeApp, JobSources

_JOB_MODULE = '''
from pydantic import BaseModel, Field


class ServeConfig(BaseModel):
    """Config for the serve job."""

    port: int = Field(default=3000, description="Port to bind")


def serve(config: ServeConfig) -> None:
    """Serve the app."""
'''


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("ENVIRONMENT", "dev")
    project = tmp_path / "project"
    jobs = project / "jobs"
    jobs.mkdir(parents=True)
    monkeypatch.chdir(project)
    (jobs / "serve_job.py").write_text(_JOB_MODULE)
    (project / "config.base.toml").write_text("[serve]\nport = 80\n")
    return project


def _make_tui(project: Path) -> FunctualizeInlineTUI:
    func_app = FunctualizeApp(
        name="pickerapp", job_sources=JobSources(directories=[str(project / "jobs")])
    )
    return FunctualizeInlineTUI(func_app)


async def _focus_panel(pilot, tui: FunctualizeInlineTUI, panel_type):
    for _ in range(len(tui._panel_host._panels)):
        if isinstance(tui._panel_host.current_panel_widget, panel_type):
            break
        await pilot.press("ctrl+j")
        await pilot.pause()
    assert isinstance(tui._panel_host.current_panel_widget, panel_type)
    tui.set_focus(None)
    tui._focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)
    return tui._panel_host.current_panel_widget


async def _open_settings_files(pilot, tui: FunctualizeInlineTUI):
    await pilot.press("ctrl+e")
    await pilot.pause()
    return await _focus_panel(pilot, tui, SettingsFilesPanel)


async def _open_config_files(pilot, tui: FunctualizeInlineTUI):
    await pilot.press(*"serve")
    await pilot.pause()
    await pilot.press("ctrl+r")
    await pilot.pause()
    return await _focus_panel(pilot, tui, ConfigFilesPanel)


async def _pick(pilot, tui: FunctualizeInlineTUI, filename: str):
    """In an open picker, walk to `filename` and press Enter."""
    picker = tui._panel_host.current_panel_widget
    assert isinstance(picker, NewFilePickerView)
    for _ in range(len(picker.candidates) + 1):
        candidate = picker.cursor_candidate
        if candidate is not None and candidate.path.name == filename:
            break
        await pilot.press("j")
        await pilot.pause()
    assert picker.cursor_candidate.path.name == filename
    await pilot.press("enter")
    await pilot.pause()


class TestFooterAdvertisesNewFile:
    """The rendered footer must show the `n` hint — a bound key nobody can
    discover is indistinguishable from a missing feature."""

    @staticmethod
    def _footer_text(tui: FunctualizeInlineTUI) -> str:
        from functualize._cli.tui.dynamic_footer_widget import DynamicFooterWidget

        footer = tui._panel_host.query_one(".panel-host-footer", DynamicFooterWidget)
        return str(footer.content)

    @pytest.mark.asyncio
    async def test_config_files_footer_shows_n(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_config_files(pilot, tui)
            tui._panel_host.update_chrome_with_focus(focused=True)
            await pilot.pause()

            assert "n new file" in self._footer_text(tui)

    @pytest.mark.asyncio
    async def test_settings_files_footer_shows_n(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_settings_files(pilot, tui)
            tui._panel_host.update_chrome_with_focus(focused=True)
            await pilot.pause()

            assert "n new file" in self._footer_text(tui)

    @pytest.mark.asyncio
    async def test_settings_files_unfocused_hint_names_the_general_ring(
        self, project: Path
    ) -> None:
        """Inherited hints said Ctrl+R (Command ring); this panel is on Ctrl+E."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_settings_files(pilot, tui)

            actions = panel.get_available_actions(focused=False)
            assert ("Ctrl+E", "focus") in actions
            assert ("Ctrl+R", "focus") not in actions


class TestPickerOpens:
    @pytest.mark.asyncio
    async def test_n_on_settings_files_opens_the_picker(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_settings_files(pilot, tui)

            await pilot.press("n")
            await pilot.pause()

            picker = tui._panel_host.current_panel_widget
            assert isinstance(picker, NewFilePickerView)
            names = {c.path.name for c in picker.candidates}
            # The conventional locations, discoverable instead of guessed.
            assert ".functualize.toml" in names
            assert "pyproject.toml" in names
            assert "config.toml" in names  # global

    @pytest.mark.asyncio
    async def test_n_on_config_files_offers_base_and_active_overlay(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_config_files(pilot, tui)

            await pilot.press("n")
            await pilot.pause()

            picker = tui._panel_host.current_panel_widget
            assert isinstance(picker, NewFilePickerView)
            names = [c.path.name for c in picker.candidates]
            assert "config.base.toml" in names
            assert "config.dev.toml" in names  # the active environment
            existing = next(
                c for c in picker.candidates if c.path.name == "config.base.toml"
            )
            assert existing.exists is True

    @pytest.mark.asyncio
    async def test_n_is_inert_on_non_file_panels(self, project: Path) -> None:
        """`n` resolves to the Files panels only — dead elsewhere by design."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press("ctrl+e")
            await pilot.pause()
            # Jobs panel is first in the general ring.
            tui.set_focus(None)
            tui._focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)

            await pilot.press("n")
            await pilot.pause()

            assert not isinstance(
                tui._panel_host.current_panel_widget, NewFilePickerView
            )

    @pytest.mark.asyncio
    async def test_escape_closes_the_picker_without_creating(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_settings_files(pilot, tui)
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(tui._panel_host.current_panel_widget, NewFilePickerView)

            await pilot.press("escape")
            await pilot.pause()

            assert isinstance(tui._panel_host.current_panel_widget, SettingsFilesPanel)
            assert not (project / ".functualize.toml").exists()


class TestCreateFlow:
    @pytest.mark.asyncio
    async def test_create_a_project_settings_file(self, project: Path) -> None:
        """n → pick .functualize.toml → stage a value → Ctrl+S creates it."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_settings_files(pilot, tui)
            await pilot.press("n")
            await pilot.pause()
            await _pick(pilot, tui, ".functualize.toml")

            view = tui._panel_host.current_panel_widget
            assert isinstance(view, SourceChainDetailView)
            # Nothing exists yet — selection alone must not create the file.
            assert not (project / ".functualize.toml").exists()

            for _ in range(64):
                if view.rows[view.cursor_row].key_name == "cli.output":
                    break
                await pilot.press("j")
                await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            for _ in range(16):
                await pilot.press("backspace")
            await pilot.press(*"json")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            created = project / ".functualize.toml"
            assert created.exists()
            assert tomllib.loads(created.read_text())["cli"]["output"] == "json"

    @pytest.mark.asyncio
    async def test_create_the_active_environment_overlay(self, project: Path) -> None:
        """n on Config Files → pick config.dev.toml → save → overlay exists."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_config_files(pilot, tui)
            await pilot.press("n")
            await pilot.pause()
            await _pick(pilot, tui, "config.dev.toml")

            view = tui._panel_host.current_panel_widget
            assert isinstance(view, SourceChainDetailView)
            assert not (project / "config.dev.toml").exists()

            for _ in range(64):
                if view.rows[view.cursor_row].key_name == "port":
                    break
                await pilot.press("j")
                await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            for _ in range(16):
                await pilot.press("backspace")
            await pilot.press(*"8080")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            created = project / "config.dev.toml"
            assert created.exists()
            assert tomllib.loads(created.read_text())["serve"]["port"] == 8080
