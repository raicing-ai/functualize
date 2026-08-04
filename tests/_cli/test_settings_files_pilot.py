"""End-to-end Pilot tests for the Settings Table + Settings Files panels.

These press *real keys* against a *real, running* TUI (per the tui-panels
steering: action_* calls pass even when no key routes to them).

What they pin down:
- The General ring (Ctrl+E) carries Jobs, Settings, and Settings Files.
- The Settings table shows the full catalog resolved from the *real* func
  config files — not the retired parallel `functualize.toml`/`settings.toml`
  pair, and not a hardcoded defaults dict.
- Enter on a settings file pushes the shared Detail view; staging an edit
  and Ctrl+S writes it into the real file, typed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize._cli.tui.panels.settings_files import SettingsFilesPanel
from functualize._cli.tui.settings_panel import SettingsPanel
from functualize._cli.tui.source_chain_detail import SourceChainDetailView
from functualize.app.core import FunctualizeApp, JobSources


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp project with a real .functualize.toml and isolated global dir."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    for var in ("FUNCTUALIZE_TUI_THEME", "FUNCTUALIZE_CLI_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    (project / ".functualize.toml").write_text('[cli]\noutput = "plain"\n')
    return project


def _make_tui(project: Path) -> FunctualizeInlineTUI:
    func_app = FunctualizeApp(
        name="settingsapp", job_sources=JobSources(directories=[])
    )
    return FunctualizeInlineTUI(func_app)


async def _open_general_ring_panel(pilot, tui: FunctualizeInlineTUI, panel_type):
    """Ctrl+E, then ring-navigate until `panel_type` is the active panel."""
    await pilot.press("ctrl+e")
    await pilot.pause()
    for _ in range(len(tui._panel_host._panels)):
        if isinstance(tui._panel_host.current_panel_widget, panel_type):
            break
        await pilot.press("ctrl+j")
        await pilot.pause()
    assert isinstance(tui._panel_host.current_panel_widget, panel_type)
    tui.set_focus(None)
    tui._focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)
    return tui._panel_host.current_panel_widget


class TestGeneralRingComposition:
    @pytest.mark.asyncio
    async def test_ring_has_settings_files_panel(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await pilot.press("ctrl+e")
            await pilot.pause()

            titles = [title for title, _ in tui._general_panels]
            assert "Settings" in titles
            assert "Settings Files" in titles


class TestSettingsTableIsReal:
    @pytest.mark.asyncio
    async def test_values_come_from_the_real_config_file(self, project: Path) -> None:
        """cli.output = "plain" in .functualize.toml must show, with source."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_general_ring_panel(pilot, tui, SettingsPanel)

            assert panel._values["cli.output"] == "plain"
            assert ".functualize.toml" in panel._sources["cli.output"]

    @pytest.mark.asyncio
    async def test_unset_settings_fall_back_to_default(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_general_ring_panel(pilot, tui, SettingsPanel)

            assert panel._values["tui.theme"] == "transparent"
            assert panel._sources["tui.theme"] == "default"


class TestSettingsFilesPanel:
    @pytest.mark.asyncio
    async def test_lists_project_and_global_files(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_general_ring_panel(pilot, tui, SettingsFilesPanel)

            names = {entry.path.name for entry in panel.files}
            assert ".functualize.toml" in names
            assert "config.toml" in names  # global — listed even when missing

    @pytest.mark.asyncio
    async def test_missing_global_file_reads_not_found(self, project: Path) -> None:
        """The canonical global location is discoverable, not hidden."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_general_ring_panel(pilot, tui, SettingsFilesPanel)

            global_entry = next(
                entry for entry in panel.files if entry.path.name == "config.toml"
            )
            assert global_entry.status == "not_found"
            assert global_entry.writable is True

    @pytest.mark.asyncio
    async def test_enter_pushes_the_detail_view(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            await _open_general_ring_panel(pilot, tui, SettingsFilesPanel)

            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(
                tui._panel_host.current_panel_widget, SourceChainDetailView
            )

    @pytest.mark.asyncio
    async def test_edit_and_save_writes_the_real_file(self, project: Path) -> None:
        """Stage `cli.output = json` in the project file, Ctrl+S, verify TOML."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_general_ring_panel(pilot, tui, SettingsFilesPanel)

            # Cursor onto the project .functualize.toml row.
            for _ in range(len(panel.files)):
                entry = panel.get_cursor_file()
                if entry is not None and entry.path.name == ".functualize.toml":
                    break
                await pilot.press("j")
                await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()
            view = tui._panel_host.current_panel_widget
            assert isinstance(view, SourceChainDetailView)

            # Navigate the detail rows to cli.output.
            for _ in range(64):
                if view.rows[view.cursor_row].key_name == "cli.output":
                    break
                await pilot.press("j")
                await pilot.pause()
            assert view.rows[view.cursor_row].key_name == "cli.output"

            await pilot.press("i")
            await pilot.pause()
            for _ in range(16):
                await pilot.press("backspace")
            await pilot.press(*"json")
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

            data = tomllib.loads((project / ".functualize.toml").read_text())
            assert data["cli"]["output"] == "json"

    @pytest.mark.asyncio
    async def test_saving_into_the_missing_global_file_creates_it(
        self, project: Path
    ) -> None:
        """Drill into the not-yet-existing global config, save, file appears."""
        tui = _make_tui(project)
        async with tui.run_test() as pilot:
            panel = await _open_general_ring_panel(pilot, tui, SettingsFilesPanel)

            for _ in range(len(panel.files)):
                entry = panel.get_cursor_file()
                if entry is not None and entry.path.name == "config.toml":
                    global_path = entry.path
                    break
                await pilot.press("j")
                await pilot.pause()
            else:
                pytest.fail("global config.toml row not found")

            await pilot.press("enter")
            await pilot.pause()
            view = tui._panel_host.current_panel_widget
            assert isinstance(view, SourceChainDetailView)

            for _ in range(64):
                if view.rows[view.cursor_row].key_name == "tui.theme":
                    break
                await pilot.press("j")
                await pilot.pause()

            await pilot.press("i")
            await pilot.pause()
            for _ in range(24):
                await pilot.press("backspace")
            await pilot.press(*"transparent")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert global_path.exists()
            data = tomllib.loads(global_path.read_text())
            assert data["tui"]["theme"] == "transparent"
