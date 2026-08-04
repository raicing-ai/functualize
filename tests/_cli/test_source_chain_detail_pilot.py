"""End-to-end Pilot tests for the shared Source-Chain Detail view.

These press *real keys* against a *real, running* TUI. That matters: the
defect this feature fixes was invisible to the previous tests precisely
because they called ``action_*`` methods directly, which works fine even when
no key is bound to them and even when the view can never re-render. Every test
here goes through ``pilot.press()`` → ``App.on_key`` → ``KeyDispatcher`` →
``KEYMAPS`` → ``active_panel``, so a missing keymap entry or a mis-routed
target fails the test.

Uses **discovered** jobs (a real job module on disk), not
``register_dynamic_job`` — dynamic jobs yield no field descriptors, so the
panels would have no fields to show and the whole flow would be vacuous.

Config files must be named ``config.<env>.toml``: the kernel's default
discovery regex is ``^config\\.(\\w+)\\.(\\w+)$`` and the file reader requires the
same ``<slot>`` segment, so a plain ``config.toml`` is neither found nor read.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize._cli.tui.focus import FocusMode, FocusZone
from functualize._cli.tui.panels.config_files import ConfigFilesPanel
from functualize._cli.tui.settings_panel import SettingsPanel
from functualize._cli.tui.source_chain_detail import (
    FILE_FLAVOR,
    KEY_FLAVOR,
    SourceChainDetailView,
)
from functualize.app.core import FunctualizeApp, JobSources

# The job takes a Pydantic config class, which is what makes its parameters
# CONFIG rather than PLAIN. Plain function params resolve from CLI/default only
# and never participate in file resolution, so a file's Detail view correctly
# shows nothing for them (R5-AC5) — a plain-function job would make these tests
# vacuous.
_JOB_MODULE = '''
from pydantic import BaseModel, Field


class ServeConfig(BaseModel):
    """Config for the serve job."""

    port: int = Field(default=3000, description="Port to bind")
    host: str = Field(default="localhost", description="Host to bind")
    debug: bool = Field(default=False, description="Enable debug mode")


def serve(config: ServeConfig) -> None:
    """Serve the app."""
'''


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp project with a discovered `serve` job and two config files."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "serve_job.py").write_text(_JOB_MODULE)

    # dev is discovered first, so it outranks prod.
    (tmp_path / "config.dev.toml").write_text("[serve]\nport = 8080\ndebug = true\n")
    (tmp_path / "config.prod.toml").write_text("[serve]\nport = 9999\nhost = 'prod'\n")
    return tmp_path


def _make_tui(project: Path) -> FunctualizeInlineTUI:
    func_app = FunctualizeApp(
        name="detailapp", job_sources=JobSources(directories=[str(project / "jobs")])
    )
    return FunctualizeInlineTUI(func_app)


async def _retype(pilot, text: str) -> None:
    """Replace the INSERT-mode value with `text`.

    INSERT pre-fills the SmartBar with the field's current value (so the user
    can amend it), and the cursor sits at the end — typing alone would append,
    turning an edit of `8080` into `80809091`.
    """
    for _ in range(32):
        await pilot.press("backspace")
    await pilot.press(*text)


async def _open_config_files_detail(pilot, tui: FunctualizeInlineTUI):
    """Drive the real key sequence into the file Detail view."""
    await pilot.press(*"serve")
    await pilot.pause()
    await pilot.press("ctrl+r")  # open the Command ring
    await pilot.pause()

    # Ring-navigate to the Config Files panel.
    for _ in range(len(tui._panel_host._panels)):
        if isinstance(tui._panel_host.current_panel_widget, ConfigFilesPanel):
            break
        await pilot.press("ctrl+j")
        await pilot.pause()

    assert isinstance(tui._panel_host.current_panel_widget, ConfigFilesPanel)

    tui.set_focus(None)
    tui._focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)
    await pilot.press("enter")  # drill down
    await pilot.pause()
    return tui._panel_host.current_panel_widget


class TestFileDetailKeysActuallyWork:
    """The reported bug: 'no key press does anything except Esc'."""

    async def test_enter_opens_an_interactive_detail_view(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)

            assert isinstance(view, SourceChainDetailView)
            assert view.flavor == FILE_FLAVOR
            # It is the active panel, so keys route to it.
            assert tui.active_panel is view
            assert tui._panel_host.view_depth == 1
            assert tui._panel_host.breadcrumb_depth == 1

    async def test_detail_view_shows_this_files_contribution_and_status(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)

            rows = {r.key_name: r for r in view.rows}
            assert "port" in rows
            # Whichever file we drilled into, its own value is shown — not the
            # merged one. That per-file provenance is the point of the screen.
            assert rows["port"].value in ("8080", "9999")
            assert rows["port"].status.startswith(("★", "●"))

    async def test_j_and_k_move_the_detail_cursor(self, project: Path) -> None:
        """j/k used to move the *hidden file list's* cursor instead."""
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)
            assert len(view.rows) > 1
            assert view.cursor_row == 0

            await pilot.press("j")
            await pilot.pause()
            assert view.cursor_row == 1

            await pilot.press("k")
            await pilot.pause()
            assert view.cursor_row == 0

            # Wraps backwards from the top.
            await pilot.press("k")
            await pilot.pause()
            assert view.cursor_row == len(view.rows) - 1

    async def test_i_enters_insert_mode_for_the_row(self, project: Path) -> None:
        """`i` used to post a message no handler consumed."""
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await _open_config_files_detail(pilot, tui)

            await pilot.press("i")
            await pilot.pause()

            assert tui._focus_state.mode is FocusMode.INSERT

    async def test_i_then_confirm_stages_an_edit_and_shows_it(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)
            row = view.rows[view.cursor_row]

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "9091")
            await pilot.press("enter")
            await pilot.pause()

            staged = view.staged_edits
            assert (row.source_id, row.key_name) in staged
            assert view.is_dirty
            # Staged, not written.
            assert "9091" not in (project / "config.dev.toml").read_text()

    async def test_d_toggles_a_staged_removal(self, project: Path) -> None:
        """`d` had no KEYMAPS entry at all — it did literally nothing."""
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)

            # Land on a row this file actually sets, so removal is meaningful.
            for index, row in enumerate(view.rows):
                if row.is_set and row.writable:
                    view._cursor_row = index
                    break
            row = view.rows[view.cursor_row]

            await pilot.press("d")
            await pilot.pause()
            assert (row.source_id, row.key_name) in view.staged_removals

            await pilot.press("d")
            await pilot.pause()
            assert (row.source_id, row.key_name) not in view.staged_removals

    async def test_esc_discards_staged_changes_and_pops_the_view(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "7777")
            await pilot.press("enter")
            await pilot.pause()
            assert view.is_dirty

            await pilot.press("escape")
            await pilot.pause()

            assert tui._panel_host.view_depth == 0
            assert tui._panel_host.breadcrumb_depth == 0
            assert isinstance(tui.active_panel, ConfigFilesPanel)
            assert not view.is_dirty  # discarded


class TestFileDetailSave:
    """Ctrl+S had no NORMAL-mode binding, so the writer was unreachable."""

    async def test_ctrl_s_writes_the_edit_to_the_real_file(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)

            # Edit `port` specifically, so we can assert on a known key.
            for index, row in enumerate(view.rows):
                if row.key_name == "port":
                    view._cursor_row = index
                    break
            target_path = Path(view.rows[view.cursor_row].source_id[len("file:") :])

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "9091")
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("ctrl+s")
            await pilot.pause()

            written = tomllib.loads(target_path.read_text())["serve"]
            # Typed, not stringified — port is an int parameter.
            assert written["port"] == 9091

    async def test_save_pops_the_view_and_clears_staging(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)
            for index, row in enumerate(view.rows):
                if row.key_name == "port":
                    view._cursor_row = index
                    break

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "9091")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert not view.is_dirty
            assert tui._panel_host.view_depth == 0
            assert isinstance(tui.active_panel, ConfigFilesPanel)

    async def test_save_preserves_other_keys_in_the_file(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            view = await _open_config_files_detail(pilot, tui)
            for index, row in enumerate(view.rows):
                if row.key_name == "port":
                    view._cursor_row = index
                    break
            target_path = Path(view.rows[view.cursor_row].source_id[len("file:") :])
            before = tomllib.loads(target_path.read_text())["serve"]

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "9091")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            after = tomllib.loads(target_path.read_text())["serve"]
            for key, value in before.items():
                if key != "port":
                    assert after[key] == value

    async def test_ctrl_s_with_nothing_staged_does_not_touch_the_file(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await _open_config_files_detail(pilot, tui)
            path = project / "config.dev.toml"
            before = path.read_text()

            await pilot.press("ctrl+s")
            await pilot.pause()

            assert path.read_text() == before


class TestSettingsDetail:
    """The Settings panel was display-only; Enter did nothing at all."""

    async def _open_settings(self, pilot, tui: FunctualizeInlineTUI, setting=None):
        """Focus the Settings panel, optionally landing on a named setting."""
        await pilot.press("ctrl+e")  # General ring
        await pilot.pause()
        for _ in range(len(tui._panel_host._panels)):
            if isinstance(tui._panel_host.current_panel_widget, SettingsPanel):
                break
            await pilot.press("ctrl+j")
            await pilot.pause()
        panel = tui._panel_host.current_panel_widget
        assert isinstance(panel, SettingsPanel)
        tui.set_focus(None)
        tui._focus_state.force(FocusMode.NORMAL, FocusZone.PANEL)

        if setting is not None:
            # Walk with the real `j` key rather than poking the cursor.
            for _ in range(len(panel._fields) + 1):
                if panel.selected_setting == setting:
                    break
                await pilot.press("j")
                await pilot.pause()
            assert panel.selected_setting == setting
        return panel

    async def test_settings_panel_shows_real_sources_not_just_default(
        self, project: Path
    ) -> None:
        """The Source column used to read 'default' unconditionally."""
        cfg = project / "config" / "functualize"
        cfg.mkdir(parents=True)
        (cfg / "config.toml").write_text('[tui]\ntheme = "dark"\n')

        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            panel = await self._open_settings(pilot, tui)
            tui._reload_settings_panel()
            await pilot.pause()

            field = next(f for f in panel._fields if f.name == "tui.theme")
            assert field.value == "dark"
            assert field.source == "global config"

    async def test_enter_opens_the_key_detail_chain(self, project: Path) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await self._open_settings(pilot, tui)

            await pilot.press("enter")
            await pilot.pause()

            view = tui._panel_host.current_panel_widget
            assert isinstance(view, SourceChainDetailView)
            assert view.flavor == KEY_FLAVOR
            assert tui.active_panel is view
            # Rows are sources, highest precedence first.
            labels = [r.label for r in view.rows]
            assert labels[0].startswith("FUNCTUALIZE_TUI_")
            assert "default" in labels

    async def test_env_row_is_read_only_and_rejects_edits(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await self._open_settings(pilot, tui)
            await pilot.press("enter")
            await pilot.pause()
            view = tui._panel_host.current_panel_widget

            # Row 0 is the env var — highest precedence, never writable.
            assert view.rows[0].writable is False

            await pilot.press("i")
            await pilot.pause()

            # Stayed in NORMAL: no INSERT for a source we cannot write.
            assert tui._focus_state.mode is FocusMode.NORMAL
            assert not view.is_dirty

    async def test_edit_and_save_writes_the_user_settings_file(
        self, project: Path
    ) -> None:
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await self._open_settings(pilot, tui, setting="tui.theme")
            await pilot.press("enter")
            await pilot.pause()
            view = tui._panel_host.current_panel_widget

            # Land on the writable user-file row.
            for index, row in enumerate(view.rows):
                if row.writable:
                    view._cursor_row = index
                    break
            assert view.rows[view.cursor_row].writable

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "dark")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            settings_file = tui._settings_store.global_path
            assert settings_file.exists()
            assert tomllib.loads(settings_file.read_text())["tui"]["theme"] == "dark"

    async def test_invalid_value_is_rejected_at_save_and_keeps_staging(
        self, project: Path
    ) -> None:
        """A bad value must not reach the file, and must not be lost silently.

        Staging is unvalidated (the view is domain-agnostic); the store is the
        thing that knows `default_surface` is an enum, so it rejects at write
        time. The staged edit survives so the user can correct it.
        """
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await self._open_settings(pilot, tui, setting="tui.default_surface")
            await pilot.press("enter")
            await pilot.pause()
            view = tui._panel_host.current_panel_widget
            for index, row in enumerate(view.rows):
                if row.writable:
                    view._cursor_row = index
                    break

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "banana")  # not one of panel|stdout
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert not tui._settings_store.global_path.exists()
            assert view.is_dirty  # kept, so the user can fix it
            assert tui._panel_host.view_depth == 1  # view stays open

    async def test_saved_setting_is_applied_live(self, project: Path) -> None:
        """A saved theme must take effect, or saving looks like a no-op."""
        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await self._open_settings(pilot, tui, setting="tui.theme")
            assert tui._theme_manager.active_theme_id == "transparent"

            await pilot.press("enter")
            await pilot.pause()
            view = tui._panel_host.current_panel_widget
            for index, row in enumerate(view.rows):
                if row.writable:
                    view._cursor_row = index
                    break

            await pilot.press("i")
            await pilot.pause()
            await _retype(pilot, "dark")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

            assert tui._theme_manager.active_theme_id == "dark"


class TestSettingsStartupLoad:
    async def test_env_var_wins_at_startup(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = project / "config" / "functualize"
        cfg.mkdir(parents=True)
        (cfg / "config.toml").write_text('[tui]\ntheme = "dark"\n')
        monkeypatch.setenv("FUNCTUALIZE_TUI_THEME", "minimal")

        tui = _make_tui(project)
        async with tui.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Applied at mount, env beating the user file.
            assert tui._theme_manager.active_theme_id == "minimal"
