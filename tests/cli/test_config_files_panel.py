"""Tests for ConfigFilesPanel widget — basic rendering, navigation, and filtering."""

from __future__ import annotations

from pathlib import Path

from functualize._cli.tui.panels.config_files import (
    ConfigFileEntry,
    ConfigFilesPanel,
)
from functualize._cli.tui.panels.config_table import FieldDef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entries() -> list[ConfigFileEntry]:
    """Create a small set of test ConfigFileEntry objects."""
    return [
        ConfigFileEntry(
            path=Path("/project/.functualize.toml"),
            section="deploy",
            display_name=".functualize.toml",
            status="exists",
            fields_from_file=["host", "port"],
        ),
        ConfigFileEntry(
            path=Path("/project/pyproject.toml"),
            section="tool.functualize.deploy",
            display_name="pyproject.toml",
            status="not_found",
            fields_from_file=[],
        ),
        ConfigFileEntry(
            path=Path("/etc/functualize/config.toml"),
            section="deploy",
            display_name="/etc/functualize/config.toml",
            status="read_only",
            fields_from_file=["timeout"],
        ),
    ]


# ---------------------------------------------------------------------------
# Construction and set_files
# ---------------------------------------------------------------------------


class TestConfigFilesPanelConstruction:
    """Test basic construction and initial state."""

    def test_initial_state(self) -> None:
        panel = ConfigFilesPanel()
        assert panel._files == []
        assert panel._filtered_files == []
        assert panel._cursor_row == 0
        assert panel._row_count == 0
        assert panel._populated is False

    def test_set_files_stores_entries(self) -> None:
        panel = ConfigFilesPanel()
        entries = _make_entries()
        panel.set_files(entries)

        assert panel._files == entries
        assert panel._filtered_files == entries
        assert panel._row_count == 3
        assert panel._cursor_row == 0
        # _populated remains False because _table is None (not yet composed)
        assert panel._populated is False

    def test_set_files_resets_cursor(self) -> None:
        panel = ConfigFilesPanel()
        entries = _make_entries()
        panel.set_files(entries)
        panel._cursor_row = 2  # Simulate cursor movement

        # Setting new files resets cursor
        panel.set_files(entries[:1])
        assert panel._cursor_row == 0
        assert panel._row_count == 1


# ---------------------------------------------------------------------------
# Navigation (wrapping)
# ---------------------------------------------------------------------------


class TestConfigFilesPanelNavigation:
    """Test j/k row navigation with wrapping."""

    def test_cursor_down_wraps(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())

        # Move down through all rows
        panel.action_cursor_down()
        assert panel._cursor_row == 1
        panel.action_cursor_down()
        assert panel._cursor_row == 2
        # Wrap to first
        panel.action_cursor_down()
        assert panel._cursor_row == 0

    def test_cursor_up_wraps(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())

        # Move up from row 0 wraps to last
        panel.action_cursor_up()
        assert panel._cursor_row == 2
        panel.action_cursor_up()
        assert panel._cursor_row == 1
        panel.action_cursor_up()
        assert panel._cursor_row == 0

    def test_cursor_noop_when_empty(self) -> None:
        panel = ConfigFilesPanel()
        # No files loaded — navigation is no-op
        panel.action_cursor_down()
        assert panel._cursor_row == 0
        panel.action_cursor_up()
        assert panel._cursor_row == 0

    def test_single_row_wraps_to_self(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries()[:1])

        panel.action_cursor_down()
        assert panel._cursor_row == 0
        panel.action_cursor_up()
        assert panel._cursor_row == 0


# ---------------------------------------------------------------------------
# Status formatting
# ---------------------------------------------------------------------------


class TestStatusFormatting:
    """Test that status values map to correct display strings."""

    def test_active_status(self) -> None:
        from functualize._cli.tui.panels.config_files import _format_status

        assert _format_status("active") == "★ active"

    def test_not_found_status(self) -> None:
        from functualize._cli.tui.panels.config_files import _format_status

        assert _format_status("not_found") == "○ not found"

    def test_inactive_status(self) -> None:
        """A file that exists but belongs to another environment."""
        from functualize._cli.tui.panels.config_files import _format_status

        assert _format_status("inactive") == "○ inactive"

    def test_read_only_is_a_suffix_not_a_status(self) -> None:
        """Writability is a separate axis from contribution.

        Folding them together made it impossible to say that a writable file
        is being ignored — the thing users actually need to know.
        """
        from functualize._cli.tui.panels.config_files import _format_status

        assert _format_status("active", writable=False) == "★ active 🔒"
        assert _format_status("inactive", writable=False) == "○ inactive 🔒"

    def test_unknown_status_passthrough(self) -> None:
        from functualize._cli.tui.panels.config_files import _format_status

        assert _format_status("custom") == "custom"


# ---------------------------------------------------------------------------
# get_available_actions
# ---------------------------------------------------------------------------


class TestGetAvailableActions:
    """Test context-sensitive action hints."""

    def test_unfocused_shows_focus_and_cycle(self) -> None:
        panel = ConfigFilesPanel()
        actions = panel.get_available_actions(focused=False)
        assert actions == [("Ctrl+R", "focus"), ("Shift+Tab", "cycle")]

    def test_focused_empty_shows_basic_hints(self) -> None:
        panel = ConfigFilesPanel()
        actions = panel.get_available_actions(focused=True)
        # No files → no Enter hint
        assert ("j/k", "navigate") in actions
        assert ("/", "filter") in actions
        assert ("Enter", "open file") not in actions

    def test_focused_with_files_shows_enter_hint(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())
        actions = panel.get_available_actions(focused=True)
        assert ("j/k", "navigate") in actions
        assert ("/", "filter") in actions
        assert ("Enter", "open file") in actions

    def test_focused_shows_new_file_hint(self) -> None:
        """`n` is bound on this panel, so the footer must advertise it.

        The action shipped without the hint — the key worked but nothing
        told the user it existed.
        """
        panel = ConfigFilesPanel()
        # With files (the common case: adding an overlay next to a base)...
        panel.set_files(_make_entries())
        assert ("n", "new file") in panel.get_available_actions(focused=True)
        # ...and without any.
        empty = ConfigFilesPanel()
        assert ("n", "new file") in empty.get_available_actions(focused=True)
        # Not when unfocused — the key doesn't route there.
        assert ("n", "new file") not in empty.get_available_actions(focused=False)


# ---------------------------------------------------------------------------
# Filterable protocol
# ---------------------------------------------------------------------------


class TestFilterableProtocol:
    """Test apply_filter for Filterable protocol compatibility."""

    def test_filter_narrows_rows(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())

        panel.apply_filter("pyproject")
        assert panel._row_count == 1
        assert panel._filtered_files[0].display_name == "pyproject.toml"
        assert panel.active_filter == "pyproject"

    def test_filter_case_insensitive(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())

        panel.apply_filter("FUNCTUALIZE")
        # Matches ".functualize.toml" and "/etc/functualize/config.toml"
        assert panel._row_count == 2

    def test_empty_filter_resets(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())

        panel.apply_filter("pyproject")
        assert panel._row_count == 1

        panel.apply_filter("")
        assert panel._row_count == 3
        assert panel.active_filter == ""

    def test_filter_resets_cursor(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())
        panel._cursor_row = 2

        panel.apply_filter("pyproject")
        assert panel._cursor_row == 0

    def test_filter_no_match(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())

        panel.apply_filter("nonexistent")
        assert panel._row_count == 0
        assert panel._filtered_files == []


# ---------------------------------------------------------------------------
# get_cursor_file
# ---------------------------------------------------------------------------


class TestGetCursorFile:
    """Test get_cursor_file helper."""

    def test_returns_none_when_empty(self) -> None:
        panel = ConfigFilesPanel()
        assert panel.get_cursor_file() is None

    def test_returns_entry_at_cursor(self) -> None:
        panel = ConfigFilesPanel()
        entries = _make_entries()
        panel.set_files(entries)

        assert panel.get_cursor_file() == entries[0]
        panel.action_cursor_down()
        assert panel.get_cursor_file() == entries[1]


# ---------------------------------------------------------------------------
# Filterable protocol compliance check
# ---------------------------------------------------------------------------


class TestFilterableCompliance:
    """Verify ConfigFilesPanel is recognized by the Filterable protocol."""

    def test_is_filterable(self) -> None:
        from functualize._cli.tui.panels import Filterable

        panel = ConfigFilesPanel()
        assert isinstance(panel, Filterable)


# ---------------------------------------------------------------------------
# Drill-down — the panel only announces it; the app owns the detail view
# ---------------------------------------------------------------------------
#
# The previous tests here exercised a panel-owned detail implementation
# (_in_detail, _detail_fields, render_detail_text, stage_edit,
# action_toggle_removal, action_save, action_detail_cursor_*). They all passed
# while the feature was completely unusable, because they called the action
# methods directly — no key was bound to most of them, and the view they drove
# was a write-once RichLog that never re-rendered. That code is gone; detail
# state lives in SourceChainDetailView, and the flow is covered by real
# keypresses in tests/_cli/test_source_chain_detail_pilot.py.


def _make_file_entries() -> list[ConfigFileEntry]:
    return [
        ConfigFileEntry(
            path=Path("/proj/config.dev.toml"),
            section="serve",
            display_name="config.dev.toml",
            status="exists",
            fields_from_file=["port"],
        ),
    ]


class TestDrillDown:
    """Enter posts DrillDownRequested and nothing else."""

    def test_drill_down_posts_the_selected_file(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_file_entries())
        posted: list = []
        panel.post_message = posted.append  # type: ignore[assignment]

        panel.action_drill_down()

        assert len(posted) == 1
        assert isinstance(posted[0], ConfigFilesPanel.DrillDownRequested)
        assert posted[0].file_entry.display_name == "config.dev.toml"

    def test_drill_down_noop_when_empty(self) -> None:
        panel = ConfigFilesPanel()
        posted: list = []
        panel.post_message = posted.append  # type: ignore[assignment]

        panel.action_drill_down()

        assert posted == []

    def test_drill_down_is_repeatable(self) -> None:
        """No _in_detail latch: the panel holds no detail state to get stuck in."""
        panel = ConfigFilesPanel()
        panel.set_files(_make_file_entries())
        posted: list = []
        panel.post_message = posted.append  # type: ignore[assignment]

        panel.action_drill_down()
        panel.action_drill_down()

        assert len(posted) == 2

    def test_panel_owns_no_detail_state(self) -> None:
        """Guards the regression: detail state on the list panel is what
        made j/k move the hidden file cursor instead of the detail cursor."""
        panel = ConfigFilesPanel()
        for attr in (
            "_in_detail",
            "_detail_fields",
            "_detail_file",
            "_staged_edits",
            "_staged_removals",
            "render_detail_text",
            "action_save",
            "action_toggle_removal",
        ):
            assert not hasattr(panel, attr), f"{attr} should live in the detail view"

    def test_public_accessors_expose_state_without_reach_in(self) -> None:
        panel = ConfigFilesPanel()
        entries = _make_file_entries()
        panel.set_files(entries)
        fields = [FieldDef(name="port", value="8080", source="File")]
        panel.set_fields(fields)

        assert [f.display_name for f in panel.files] == ["config.dev.toml"]
        assert [f.name for f in panel.job_fields] == ["port"]


# ---------------------------------------------------------------------------
# Preset awareness (gap 6: env_only/twelve_factor have no FileSource)
# ---------------------------------------------------------------------------


class TestPresetNotice:
    """set_preset_notice shows an explanation instead of an empty list."""

    def test_notice_replaces_file_list(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_files(_make_entries())
        panel.set_preset_notice("File resolution disabled by preset")

        assert panel.preset_notice == "File resolution disabled by preset"
        assert panel.files == []
        assert panel.get_cursor_file() is None

    def test_drill_down_noop_under_notice(self) -> None:
        panel = ConfigFilesPanel()
        panel.set_preset_notice("File resolution disabled by preset")
        posted: list[object] = []
        panel.post_message = lambda msg: posted.append(msg)  # type: ignore[method-assign]

        panel.action_drill_down()

        assert posted == []

    def test_default_panel_has_no_notice(self) -> None:
        panel = ConfigFilesPanel()
        assert panel.preset_notice is None


class TestFileResolutionDisabled:
    """Chain inspection helper for preset awareness."""

    def test_env_only_app_reports_disabled(self) -> None:
        from functualize._cli.tui.chain_resolution import file_resolution_disabled
        from functualize.app.config import JobSources, PluginSources
        from functualize.app.core import FunctualizeApp
        from functualize.app.presets import env_only

        app = FunctualizeApp(
            name="preset-test",
            job_sources=JobSources(functions=[lambda: None]),
            config_sources=env_only(dotenv=False),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )

        assert file_resolution_disabled(app) is True

    def test_classic_app_reports_enabled(self, tmp_path, monkeypatch) -> None:
        from functualize._cli.tui.chain_resolution import file_resolution_disabled
        from functualize.app.config import ConfigSources, JobSources
        from functualize.app.core import FunctualizeApp

        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        app = FunctualizeApp(
            name="classic-test",
            job_sources=JobSources(directories=[str(jobs_dir)]),
            config_sources=ConfigSources(dotenv=False),
        )

        assert file_resolution_disabled(app) is False
