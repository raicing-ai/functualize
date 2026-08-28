"""V3 TUI composition root — thin orchestrator delegating to v3 modules.

Replaces the monolithic inline_tui.py (~1900 lines) with a slim composition
root that instantiates and wires all v3 state machines and widgets.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Input, RichLog, Static

from functualize._cli.data.config_snapshot_store import ConfigSnapshotStore
from functualize._cli.data.func_settings import FuncSettingsStore
from functualize._cli.tui.bar import BarReadiness, SmartBar  # noqa: F401
from functualize._cli.tui.bar_items import render_header_items, render_status_items
from functualize._cli.tui.chain_resolution import (
    _build_group_field_defs,
    build_command_panels,
    build_pending_execution,
    compute_chain_detail_rows,
)
from functualize._cli.tui.cli_arg_parser import (
    build_group_option_trie,
    group_option_specs_on_path,
    parse_cli_args_to_kwargs,
    resolve_tui_command,
)
from functualize._cli.tui.descriptor_fields import get_descriptor_fields
from functualize._cli.tui.diff_view_widget import DiffViewWidget
from functualize._cli.tui.display_chrome import update_display_chrome
from functualize._cli.tui.display_provider_discovery import register_display_providers
from functualize._cli.tui.display_slot import DisplaySlot
from functualize._cli.tui.dynamic_input_bar import DynamicInputBar
from functualize._cli.tui.focus import FocusMode, FocusState, FocusZone
from functualize._cli.tui.functualize_autocomplete import FunctualizeAutoComplete
from functualize._cli.tui.insert_mode import InsertModeController
from functualize._cli.tui.integration import (
    action_zone_cycle,  # noqa: F401
    enter_normal_mode,  # noqa: F401
    exit_to_command_mode,  # noqa: F401
)
from functualize._cli.tui.job_execution import (
    execute_job_async,
    extract_effective_values,
    run_job,
)
from functualize._cli.tui.job_listing import build_general_panels, count_jobs_in_cwd
from functualize._cli.tui.key_handler import KeyDispatcher

# Imported at runtime (not just for typing) because the drill-down and
# settings-reload paths isinstance-check them, matching how ConfigTablePanel
# is already used here.
from functualize._cli.tui.new_file_picker import NewFileCandidate, NewFilePickerView
from functualize._cli.tui.panel_host import PanelHost
from functualize._cli.tui.panels.config_files import (
    ConfigFilesPanel,
    _make_display_name,
)
from functualize._cli.tui.panels.config_table import ConfigTablePanel
from functualize._cli.tui.preflight_summary import build_preflight_lines
from functualize._cli.tui.settings_panel import SettingsPanel
from functualize._cli.tui.shell_mode import register_shell_mode
from functualize._cli.tui.shortcut_save_modal import ShortcutSaveModal
from functualize._cli.tui.source_chain_detail import (
    FILE_FLAVOR,
    KEY_FLAVOR,
    SourceChainDetailView,
)
from functualize._cli.tui.source_chain_providers import (
    FileScope,
    FuncSettingsChainProvider,
    JobConfigChainProvider,
    file_source_id,
)
from functualize._cli.tui.sync import (
    build_command_line,
    sync_bar_to_overrides,
    sync_overrides_to_bar,
    sync_pending_overrides_to_bar,
)
from functualize._cli.tui.theme_manager import ThemeManager
from functualize.types import EnvironmentSource

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.widget import Widget

    from functualize._cli.data.pending_execution import PendingExecution
    from functualize._cli.tui.panels.config_table import FieldDef
    from functualize._cli.tui.panels.job_browser import JobBrowserPanel
    from functualize._cli.tui.panels.settings_files import SettingsFilesPanel
    from functualize.app.core import FunctualizeApp
    from functualize.ui import Display

__all__ = ["FunctualizeInlineTUI"]

# Mode indicator mapping for status bar display (R8-AC4).
_MODE_STYLES: dict[FocusMode, str] = {
    FocusMode.COMMAND: "[dim]COMMAND[/dim]",
    FocusMode.NORMAL: "[bold cyan]NORMAL[/bold cyan]",
    FocusMode.INSERT: "[bold green]INSERT[/bold green]",
    FocusMode.FILTER: "[bold yellow]FILTER[/bold yellow]",
}

# Zone display names for status bar (R8-AC5).
_ZONE_NAMES: dict[FocusZone, str] = {
    FocusZone.SMARTBAR: "SmartBar",
    FocusZone.DISPLAY: "Display",
    FocusZone.PANEL: "Panel",
}


class FunctualizeInlineTUI(App[int]):
    """V3 TUI composition root — thin orchestrator delegating to v3 modules."""

    DEFAULT_CSS = """
    Screen {
        height: auto;
    }
    #display-section {
        display: none;
        height: auto;
        max-height: 12;
    }
    #display-section.visible {
        display: block;
    }
    #display-section:focus {
        background: $primary-darken-3;
    }
    #display-bc {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    #display-footer {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #header {
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    #input-bar {
        height: auto;
        min-height: 3;
        max-height: 3;
    }
    #smart-bar {
        margin: 0;
    }
    #smart-bar.ready { border: tall green; }
    #smart-bar.pending { border: tall yellow; }
    #smart-bar.editing { border: tall $accent; }
    #smart-bar.invalid { border: tall red; }
    AutoComplete {
        height: auto;
        max-height: 8;
    }
    AutoComplete > OptionList {
        background: $surface-lighten-1;
        border: round $secondary;
        padding: 0 1;
        height: auto;
        max-height: 6;
    }
    AutoComplete > .autocomplete--highlight-match {
        color: $accent;
        text-style: bold;
    }
    #preflight-summary {
        display: none;
        height: auto;
        max-height: 12;
        padding: 0 1;
    }
    #output-log {
        display: none;
        height: auto;
        max-height: 10;
    }
    #output-log.visible {
        display: block;
    }
    #live-zone {
        display: none;
        height: auto;
        max-height: 16;
        overflow-y: auto;
    }
    #live-zone.visible {
        display: block;
    }
    #status-bar {
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
    }
    #chain-detail-view {
        height: auto;
        overflow: hidden;
        scrollbar-size: 0 0;
    }
    #file-detail-view {
        height: auto;
        overflow: hidden;
        scrollbar-size: 0 0;
    }
    """

    def __init__(self, func_app: FunctualizeApp) -> None:
        """Accept the booted FunctualizeApp for job discovery and execution."""
        super().__init__()
        self._func_app = func_app

        # Orchestrator handoff: when a job that owns the terminal (tty: TTY) is
        # selected, the shell records it here and exits so the orchestrator can
        # run it on the main thread after the terminal is released, then
        # relaunch the shell. None = normal exit (no handoff).
        self._handoff_tokens: list[str] | None = None

        # --- State machines ---
        self._focus_state = FocusState()
        self._key_dispatcher = KeyDispatcher(self._focus_state, self)

        # --- Widgets (created once, yielded in compose) ---
        self._smart_bar = SmartBar(placeholder="Type a command", id="smart-bar")
        self._insert_mode = InsertModeController(self._focus_state, self._smart_bar)
        self._insert_mode.set_apply_callback(self._on_insert_edit_applied)
        self._panel_host = PanelHost(
            type_prefix="R", id="panel-host", focus_state=self._focus_state
        )
        # Mounted inside #display-section by compose(). The app is still
        # handed in explicitly: registration (and the refresh workers it
        # starts) can run before mounting completes, when `self.app` would
        # raise NoActiveAppError.
        self._display_slot = DisplaySlot(
            func_app, Path.cwd(), id="display-slot", textual_app=self
        )

        # --- Autocomplete ---
        self._completer = self._create_completer()

        # --- Input row host ---
        # Shares the completer's mode registry rather than owning a second one:
        # the mode that decides which widget is mounted must be the same object
        # that decides which candidates are offered, or the bar could complete
        # for a mode it is not displaying.
        self._input_bar = DynamicInputBar(
            self._completer.input_modes, self._smart_bar, id="input-bar"
        )
        # `!` runs a shell command. Registered here rather than inside the
        # completer because the mode needs the app to suspend it and to reach
        # the output log — the completer only knows about candidates.
        register_shell_mode(self, self._completer.input_modes)

        # --- Ring tracking ---
        self._active_ring: str | None = None
        self._command_panels: list[tuple[str, Any]] = []
        self._command_panels_stale: bool = False
        self._general_panels: list[tuple[str, Any]] = []
        self._panel_id_seq: int = 0
        # True while the general ring is only open because a live.panel
        # construct auto-surfaced it — removal of the last live panel then
        # collapses the ring instead of stranding the user in it.
        self._live_panel_autoactivated: bool = False

        # --- PendingExecution lifecycle ---
        self._pending: PendingExecution | None = None
        self._snapshot_store: ConfigSnapshotStore = ConfigSnapshotStore.load()

        # --- Input tracking ---
        self._last_recognized_job: str | None = None

        # --- func settings (defaults < global < project file(s) < env) ---
        self._settings_store: FuncSettingsStore = FuncSettingsStore.discover()
        self._theme_manager: ThemeManager = ThemeManager()
        self._settings_view_seq: int = 0
        # Set when a new-file picker is pushed: called with the chosen path.
        self._new_file_open: Callable[[Path], None] | None = None

    # ------------------------------------------------------------------
    # Orchestrator handoff
    # ------------------------------------------------------------------

    @property
    def handoff_tokens(self) -> list[str] | None:
        """The command the orchestrator should run after the shell exits.

        None for a normal exit. Set by :meth:`request_handoff`.
        """
        return self._handoff_tokens

    def request_handoff(self, tokens: list[str]) -> None:
        """Exit the shell so the orchestrator runs ``tokens`` on the main thread.

        Used for a job that owns the terminal (``tty: TTY``): it cannot run on
        the TUI's worker thread (Textual needs the main thread), so the shell
        steps aside, the job runs after the terminal is released, and the shell
        relaunches. See ``_cli/inline_tui.launch_inline_tui``.
        """
        self._handoff_tokens = list(tokens)
        self.exit()

    # ------------------------------------------------------------------
    # Textual lifecycle
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Yield the vertical layout for the TUI."""
        # Row 1: Display section (hidden by default, auto-shows on provider
        # registration). The DisplaySlot mounts the active display's real
        # widget tree between the breadcrumb and the footer, so display
        # widgets can hold focus and receive keys like PanelHost panels.
        with Vertical(id="display-section"):
            yield Static("", id="display-bc")
            yield self._display_slot
            yield Static("", id="display-footer")

        # Row 2: Header with app name and job counts
        yield Static(f" func — {self._func_app.name}", id="header", markup=True)

        # Row 3: the input row. `DynamicInputBar` replaces a bare `Vertical`
        # and mounts the active mode's widget; for the default command mode
        # that is the same `SmartBar` instance, under the same `#input-bar`
        # parent, so the single-line path is structurally unchanged.
        yield self._input_bar

        # Row 4: Pre-flight summary (hidden by default, shown when readiness is PENDING/READY)
        _summary = RichLog(id="preflight-summary", wrap=True, markup=True)
        _summary.can_focus = False
        yield _summary

        # Row 5: Autocomplete overlay
        yield FunctualizeAutoComplete(self._smart_bar, completer=self._completer)

        # Row 6: PanelHost (hidden by default, shows on Ctrl+R/E)
        yield self._panel_host

        # Row 7: Output log (hidden by default, shows on execution)
        # The PANEL binding for the `Live` capability. Hidden until a
        # `live: Live` job mounts a construct into it; sits above the log so
        # a live table stays put while log lines scroll beneath it.
        yield Static("", id="live-zone")
        yield RichLog(id="output-log", wrap=True, highlight=True, markup=True)

        # Row 8: Status bar (mode indicator + readiness hints)
        yield Static("", id="status-bar", markup=True)

    def on_mount(self) -> None:
        """Wire observers and set initial focus."""
        # Subscribe to FocusState changes
        self._focus_state.subscribe(self._on_focus_changed)

        # Watch DisplaySlot visibility to toggle CSS class
        self.watch(
            self._display_slot, "is_visible_slot", self._on_display_slot_visibility
        )

        # Register display providers from the app's plugin system
        self._register_display_providers()

        # The display zone must hold real Textual focus for Shift+Tab
        # zone-cycling to land on it. An interactive display's widget takes
        # focus directly; the `#display-section` container is the fallback
        # target for legacy non-interactive displays — make it focusable.
        with contextlib.suppress(NoMatches):
            self.query_one("#display-section").can_focus = True

        # Registration may have added several displays; the visibility watcher
        # only fires on the first (0→1) transition, so refresh the chrome once
        # more so the breadcrumb count reflects every registered display.
        if self._display_slot.has_visible_displays:
            self._update_display_chrome()

        # Resolve TUI settings and apply them to the running app
        self._load_settings()

        # Update header with job discovery counts
        self._update_header()

        # Paint the status bar once at startup. It is otherwise only written
        # from _on_focus_changed, so it stayed blank until the user changed
        # mode — and the environment indicator on it has to be visible from
        # the first frame.
        self._update_status_bar(self._focus_state.mode, self._focus_state.zone)

        # Initial focus: SmartBar in COMMAND mode
        self._smart_bar.focus()

    def on_key(self, event: Any) -> None:
        """Sole key handling: delegate to KeyDispatcher."""
        self._key_dispatcher.dispatch(event)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle SmartBar input changes — tokenize and evaluate readiness.

        In COMMAND mode: tokenizes the input and calls SmartBar.evaluate()
        with known job names and a required-fields resolver.
        In INSERT mode: delegates to InsertModeController.on_bar_changed()
        to clear INVALID readiness on further input.
        In FILTER mode: no-op (let user type freely without side effects).
        """
        if event.input.id != "smart-bar":
            return

        # Keep the input row's active mode in step with what is typed, so the
        # mode offering candidates is always the mode being displayed. Cheap on
        # the common path — same sigil as the last keystroke returns immediately.
        self._input_bar.sync(event.value)

        # FILTER mode: user is typing a filter query — no evaluation needed
        if self._focus_state.mode is FocusMode.FILTER:
            return

        # INSERT mode: delegate to controller for INVALID→EDITING clearance
        if self._focus_state.mode is FocusMode.INSERT:
            self._insert_mode.on_bar_changed()
            return

        text = event.value

        # A sigil mode owns its own readiness rule (`InputMode.is_ready`), so
        # the command-mode evaluation below must not run for it: `!ls` is not a
        # job name, and evaluating it as one paints the bar INVALID red while
        # the command is in fact perfectly runnable.
        if text and text[0] in self._completer.input_modes:
            self._smart_bar._set_readiness(
                BarReadiness.READY if self._mode_is_ready(text) else BarReadiness.GREY
            )
            return

        # COMMAND mode: tokenize, walk to the job, evaluate readiness. The walk
        # comes first because readiness depends on it: the command-name list
        # contains group nodes as well as jobs, so a bar evaluated on its first
        # token reports a group READY and never asks the real job what it is
        # still missing.
        tokens = text.split() if text.strip() else []
        _resolution = self.resolve_command(tokens)
        self._smart_bar.evaluate(
            tokens,
            self._get_command_names(),
            self._get_required_fields,
            get_fields=self._get_job_fields,
            resolution=_resolution,
        )

        # Invalidate command panels cache when job changes. The job is resolved
        # by walking the space-separated path (S6b) — `deploy web run` — so a
        # grouped job is recognized as the user types its segments, not only
        # when a dotted name is typed whole.
        new_job = _resolution.job_name if tokens else None
        old_job = self._last_recognized_job
        if new_job != old_job:
            self._command_panels = []
            self._last_recognized_job = new_job
            # Build PendingExecution when a job is recognized (GREY→PENDING/READY).
            # Builtins are recognized names but not jobs — they have no
            # descriptor and no config fields, so there is nothing to pend.
            if (
                new_job
                and self._find_job_descriptor(new_job) is not None
                and self._smart_bar.readiness != BarReadiness.GREY
            ):
                self._pending = self._build_pending_execution(new_job)
            else:
                self._pending = None

        # Update PendingExecution overrides from the job's own argument tokens
        # (S6b): the walk already consumed any mid-path group flag, so what
        # remains is the job's, and a group flag can no longer be mistaken for
        # a job override.
        if self._pending is not None and tokens:
            # The group's own values, kept apart from the job's. They are not
            # this job's arguments — they belong to an ancestor and are spelled
            # beside that ancestor's segment — and anything that rebuilds the
            # bar has to write them back there or the user's `--env prod`
            # vanishes the first time they touch a field.
            self._pending.group_option_values = dict(_resolution.group_values)
            self._pending.group_option_paths = self._group_option_paths(
                self._pending.job_name
            )

            provided = self.job_kwargs_for(self._pending.job_name, _resolution.args)
            # Sync: add/update overrides for provided tokens, remove stale ones
            current_override_keys = set(self._pending.overrides.keys())
            for key, val in provided.items():
                if key in self._pending.resolved_values:
                    self._pending.overrides[key] = val
            # Clear overrides that are no longer in CLI tokens
            for key in current_override_keys - set(provided.keys()):
                self._pending.overrides.pop(key, None)

        # Sync config table from SmartBar args if command ring is active
        self._sync_config_table_from_smartbar()

        # Auto-update pre-flight summary on field value changes
        self._update_preflight_summary()

    def on_smart_bar_readiness_changed(self, event: SmartBar.ReadinessChanged) -> None:
        """Handle ReadinessChanged message — update status bar with new readiness."""
        try:
            # Refresh the status bar to reflect new readiness state
            mode = self._focus_state.mode
            zone = self._focus_state.zone
            self._update_status_bar(mode, zone)
        except Exception as exc:
            # _update_status_bar() already guards its own query_one lookup
            # internally; this outer catch protects against future changes
            # to that contract, so log rather than swallow silently.
            self.log.warning(
                f"on_smart_bar_readiness_changed: status bar refresh failed "
                f"({type(exc).__name__}): {exc}"
            )
        self._update_preflight_summary()

    def on_job_browser_panel_job_selected(
        self, event: JobBrowserPanel.JobSelected
    ) -> None:
        """Handle job selection from the browser — populate SmartBar and collapse."""
        autocomplete = self.query_one(FunctualizeAutoComplete)
        autocomplete.suppress()
        self._smart_bar.value = event.job_name
        self._panel_host.collapse()
        self._active_ring = None
        exit_to_command_mode(self, self._focus_state, self._smart_bar)
        self._update_preflight_summary()
        self.call_after_refresh(autocomplete.unsuppress)

    def on_config_table_panel_insert_requested(
        self, event: ConfigTablePanel.InsertRequested
    ) -> None:
        """Handle INSERT request from ConfigTablePanel — enter INSERT mode."""
        field_def = event.field_def
        if field_def is not None:
            self._insert_mode.enter_insert(field_def, return_zone=FocusZone.PANEL)
            # Switch autocomplete to field-specific choices (empty list = suppress normal completions)
            choices = getattr(field_def, "choices", None) or []
            try:
                ac = self.query_one(FunctualizeAutoComplete)
                ac.enter_insert_mode(choices)
            except NoMatches:
                pass

    def on_config_table_panel_override_reset(
        self, event: ConfigTablePanel.OverrideReset
    ) -> None:
        """Handle OverrideReset message from ConfigTablePanel.

        When the panel resets a field override via the 'r' key, clear
        the corresponding PendingExecution override and refresh all views.

        R1-AC5: clear_override() + notify all panels to refresh.
        """
        field_def = getattr(event, "field_def", None)
        if field_def is None:
            return
        field_name = getattr(field_def, "name", None)
        if self._pending is not None and field_name:
            self._pending.clear_override(field_name)
        self._refresh_all_views()

    def on_config_table_panel_drill_down_requested(
        self, event: ConfigTablePanel.DrillDownRequested
    ) -> None:
        """Handle drill-down request from ConfigTablePanel — show resolution chain.

        R5-AC2: Push breadcrumb with "Detail: <field_name>" and render chain sub-view.
        R5-AC3: Display sources with ★ for winning, ● for non-winning.
        R5-AC4: Show value or "(not set)" for each source.
        R5-AC5: Show field metadata (type, required, choices, description).
        R5-AC6: Show "[Edited]" banner if the field was manually edited in this view.
        """
        field_def = event.field_def
        if field_def is None:
            return

        # Push breadcrumb for drill-down sub-view
        self._panel_host.push_breadcrumb(f"Detail: {field_def.name}")

        # Render the chain detail into a RichLog mounted in the panel
        self._render_chain_detail(field_def)

    def _render_chain_detail(self, field_def: FieldDef) -> None:
        """Render the resolution chain detail view for a field.

        Shows field metadata, resolution chain with winning source marked,
        and a "[Edited]" banner if the field was manually edited in this view.

        Kind-aware rendering (R5-AC2, R5-AC3, R5-AC4):
        - CONFIG params: show all 5 sources (CLI, Env, File, Remote, Default)
        - PLAIN params: show only 2 sources (CLI, Default) with banner
        """
        panel = self.active_panel
        if panel is None:
            return

        # Hide the DataTable and show a detail view via RichLog
        # We'll use the panel's table to render into (replace rows with detail text)
        # Instead, use a RichLog overlay approach within the panel host content
        try:
            from textual.widgets import RichLog as _RichLog

            # Create or reuse a drill-down RichLog
            content_area = self._panel_host.query_one(".panel-host-content")
            detail_id = "chain-detail-view"

            # Remove any previous detail view
            for child in content_area.query(f"#{detail_id}"):
                child.remove()

            detail_log = _RichLog(id=detail_id, wrap=True, markup=True)
            detail_log.add_class("panel-visible")
            content_area.mount(detail_log)

            # Hide the config table panel while drill-down is active
            if panel is not None:
                panel.remove_class("panel-visible")

            for line in compute_chain_detail_rows(field_def):
                detail_log.write(line)

        except Exception as exc:
            # Guards a multi-step overlay build (query_one + mount + a
            # compute/render loop), not a single lookup — log so a bug in
            # any of those steps is visible.
            self.log.warning(
                f"_render_chain_detail: failed to render detail view "
                f"({type(exc).__name__}): {exc}"
            )

    def on_display_drill_down(self, event: Display.DrillDown) -> None:
        """Push a display drill-down sub-view (Enter on an interactive display).

        Posted by a display widget's ``action_drill_down`` via
        ``Display.DrillDown``; mirrors the PanelHost drill-down handlers —
        the slot's ``push_view`` mounts and focuses the sub-view, making it
        the key target through ``active_panel``.
        """
        self._display_slot.push_view(event.widget, event.title)
        self._update_display_chrome()

    def on_diff_view_widget_load_session_requested(
        self, event: DiffViewWidget.LoadSessionRequested
    ) -> None:
        """Apply all snapshot values as session overrides (R3-AC3).

        When the user selects a previous session in the DiffView, apply all
        its values by writing directly into PendingExecution.overrides and
        refresh all panels and the SmartBar.
        """
        if self._pending is None:
            return
        snapshot = getattr(event, "snapshot", None)
        if snapshot is None:
            return
        for field_name, value in snapshot.values.items():
            self._pending.overrides[field_name] = value
        self._refresh_all_views()
        # Refresh only the diff entries section (preserve DataTable cursor/scroll)
        try:
            panel = self.active_panel
            if isinstance(panel, DiffViewWidget) and self._pending is not None:
                previous = self._snapshot_store.get_last_snapshot(
                    self._pending.job_name
                )
                panel.refresh_diff_only(self._pending, previous)
        except Exception as exc:
            # was a tautological except (AttributeError,
            # Exception) — collapsed to a single logged Exception catch.
            # Guards a snapshot-store lookup and a panel refresh call, not
            # a query_one lookup, so NoMatches narrowing does not apply.
            self.log.warning(
                f"on_diff_view_widget_load_session_requested: diff refresh "
                f"failed ({type(exc).__name__}): {exc}"
            )
        # Mark command panels stale so they rebuild on next ring switch.
        # This ensures Config Table picks up new override values.
        self._command_panels_stale = True

    def on_diff_view_widget_back_requested(
        self, event: DiffViewWidget.BackRequested
    ) -> None:
        """Collapse panel host and return to COMMAND mode (R3-AC4)."""
        exit_to_command_mode(self, self._focus_state, self._smart_bar)
        self._panel_host.collapse()
        self._active_ring = None
        self._update_preflight_summary()

    def on_config_files_panel_file_saved(
        self, event: ConfigFilesPanel.FileSaved
    ) -> None:
        """Handle FileSaved → pop breadcrumb, rebuild PendingExecution, refresh.

        R2-AC14: Pop breadcrumb and trigger full refresh via re-resolution.
        """
        self._panel_host.pop_breadcrumb()
        # Rebuild PendingExecution with re-resolved values
        if self._pending is not None:
            self._pending = self._build_pending_execution(self._pending.job_name)
        self._refresh_all_views()

    def on_config_files_panel_drill_down_requested(
        self, event: ConfigFilesPanel.DrillDownRequested
    ) -> None:
        """Enter on a config file → push the interactive file Detail view.

        Rows are the job's keys, showing what this file contributes and
        whether it wins. This replaces a write-once RichLog that could never
        re-render, which is why every key but Esc used to be dead here.
        """
        file_entry = event.file_entry
        if file_entry is None:
            return

        panel = self.active_panel
        if not isinstance(panel, ConfigFilesPanel):
            return

        display_name = getattr(file_entry, "display_name", "") or str(
            getattr(file_entry, "path", "file")
        )
        provider = self._build_job_config_provider(panel)
        if provider is None:
            return

        self._settings_view_seq += 1
        view = SourceChainDetailView(
            provider,
            flavor=FILE_FLAVOR,
            scope=file_source_id(file_entry.path),
            id=f"source-chain-detail-{self._settings_view_seq}",
        )
        self._panel_host.push_view(view, f"File: {display_name}")

    def _build_job_config_provider(
        self, panel: ConfigFilesPanel
    ) -> JobConfigChainProvider | None:
        """Build a provider over the config files the panel is showing."""
        files = [
            FileScope(entry.path, entry.section, entry.display_name)
            for entry in panel.files
        ]
        if not files:
            return None
        return JobConfigChainProvider(panel.job_fields, files)

    def on_settings_files_panel_drill_down_requested(
        self, event: SettingsFilesPanel.DrillDownRequested
    ) -> None:
        """Enter on a settings file → push the file Detail view.

        Rows are the settings catalog, showing what this file contributes
        and whether it wins. Drilling into the not-yet-existing global file
        is the create flow: stage values, Ctrl+S writes the file into being.
        """
        file_entry = event.file_entry
        if file_entry is None:
            return

        display_name = getattr(file_entry, "display_name", "") or str(
            getattr(file_entry, "path", "file")
        )
        self._settings_view_seq += 1
        view = SourceChainDetailView(
            self._build_settings_provider(),
            flavor=FILE_FLAVOR,
            scope=file_source_id(file_entry.path),
            id=f"source-chain-detail-{self._settings_view_seq}",
        )
        self._panel_host.push_view(view, f"File: {display_name}")

    # ------------------------------------------------------------------
    # New-file picker (`n` on a Files panel)
    # ------------------------------------------------------------------

    def on_config_files_panel_new_file_requested(
        self, event: ConfigFilesPanel.NewFileRequested
    ) -> None:
        """`n` on Config Files → pick a conventional location for a new file."""
        self._push_new_file_picker(
            self._job_config_file_candidates(), self._open_new_job_config_detail
        )

    def on_settings_files_panel_new_file_requested(
        self, event: SettingsFilesPanel.NewFileRequested
    ) -> None:
        """`n` on Settings Files → pick a conventional location for a new file."""
        self._push_new_file_picker(
            self._settings_file_candidates(), self._open_new_settings_detail
        )

    def on_new_file_picker_view_selected(
        self, event: NewFilePickerView.Selected
    ) -> None:
        """A location was chosen — replace the picker with the Detail view.

        Nothing is created yet: the Detail view stages values and Ctrl+S is
        what writes the file into being.
        """
        open_detail = self._new_file_open
        self._panel_host.pop_view()
        if open_detail is not None:
            open_detail(event.candidate.path)

    def _push_new_file_picker(
        self,
        candidates: list[NewFileCandidate],
        open_detail: Callable[[Path], None],
    ) -> None:
        if not candidates:
            return
        self._new_file_open = open_detail
        self._settings_view_seq += 1
        view = NewFilePickerView(
            candidates, id=f"new-file-picker-{self._settings_view_seq}"
        )
        self._panel_host.push_view(view, "New file")

    def _job_config_file_candidates(self) -> list[NewFileCandidate]:
        """Conventional locations for a job-config file.

        The kernel's config directories (where files were already found),
        falling back to the cwd — each offering a base file and the active
        environment's overlay.
        """
        try:
            environment = self._func_app.active_environment().lower()
        except AttributeError:
            environment = "dev"

        directories: list[Path] = []
        panel = self.active_panel
        if isinstance(panel, ConfigFilesPanel):
            for entry in panel.files:
                parent = entry.path.parent
                if parent not in directories:
                    directories.append(parent)
        if Path.cwd() not in directories:
            directories.insert(0, Path.cwd())

        candidates: list[NewFileCandidate] = []
        cwd = Path.cwd()
        for directory in directories:
            for slot, note in (
                ("base", "base — always loaded"),
                (environment, f"{environment} overlay (active environment)"),
            ):
                path = directory / f"config.{slot}.toml"
                if any(c.path == path for c in candidates):
                    continue
                candidates.append(
                    NewFileCandidate(
                        path=path,
                        label=_make_display_name(path, cwd),
                        note=note,
                        exists=path.exists(),
                    )
                )
        return candidates

    def _settings_file_candidates(self) -> list[NewFileCandidate]:
        """Conventional locations for a `func` settings file."""
        cwd = Path.cwd()
        raw: list[tuple[Path, str]] = [
            (cwd / ".functualize.toml", "project settings"),
            (cwd / "pyproject.toml", "project settings under [tool.functualize]"),
            (
                cwd / ".functualize" / ".functualize.toml",
                "project settings (convention directory)",
            ),
            (self._settings_store.global_path, "global — every project"),
        ]
        return [
            NewFileCandidate(
                path=path,
                label=_make_display_name(path, cwd),
                note=note,
                exists=path.exists(),
            )
            for path, note in raw
        ]

    def _open_new_settings_detail(self, path: Path) -> None:
        """Push a Detail view over a (possibly not-yet-existing) settings file."""
        self._settings_store.ensure_layer(path)
        self._settings_view_seq += 1
        view = SourceChainDetailView(
            self._build_settings_provider(),
            flavor=FILE_FLAVOR,
            scope=file_source_id(path),
            id=f"source-chain-detail-{self._settings_view_seq}",
        )
        self._panel_host.push_view(view, f"New: {_make_display_name(path, Path.cwd())}")

    def _open_new_job_config_detail(self, path: Path) -> None:
        """Push a Detail view over a (possibly not-yet-existing) config file."""
        panel = self.active_panel
        if not isinstance(panel, ConfigFilesPanel):
            return
        job_name = self._last_recognized_job
        section = ""
        try:
            if job_name:
                section = self._func_app.get_job_config_section(job_name)
        except Exception as exc:
            self.log.warning(
                f"_open_new_job_config_detail: get_job_config_section failed "
                f"({type(exc).__name__}): {exc}"
            )
        if not section and panel.files:
            section = panel.files[0].section
        if not section:
            return

        display = _make_display_name(path, Path.cwd())
        # The prospective file goes first: a file created here is the nearest,
        # and FileScope treats a missing file with a writable parent as
        # writable — which is exactly the create flow.
        scopes = [FileScope(path, section, display)]
        scopes.extend(
            FileScope(entry.path, entry.section, entry.display_name)
            for entry in panel.files
            if entry.path != path
        )
        provider = JobConfigChainProvider(panel.job_fields, scopes)

        self._settings_view_seq += 1
        view = SourceChainDetailView(
            provider,
            flavor=FILE_FLAVOR,
            scope=file_source_id(path),
            id=f"source-chain-detail-{self._settings_view_seq}",
        )
        self._panel_host.push_view(view, f"New: {display}")

    def on_settings_panel_drill_down_requested(
        self, event: SettingsPanel.DrillDownRequested
    ) -> None:
        """Enter on a setting → push the interactive key Detail view.

        Rows are the setting's sources in precedence order, so the user can
        see which layer wins and edit any writable one.
        """
        self._settings_view_seq += 1
        view = SourceChainDetailView(
            self._build_settings_provider(),
            flavor=KEY_FLAVOR,
            scope=event.setting_name,
            id=f"source-chain-detail-{self._settings_view_seq}",
        )
        self._panel_host.push_view(view, event.setting_name)

    def _build_settings_provider(self) -> FuncSettingsChainProvider:
        """A settings provider whose saves take effect immediately."""
        return FuncSettingsChainProvider(
            self._settings_store, apply_hook=self._apply_settings
        )

    def _apply_settings(self, values: dict[str, str]) -> None:
        """Push setting values into the running app.

        Only the settings that have a live consumer today are wired here:
        ``display_auto_switch`` (DisplaySlot changes behaviour immediately)
        and ``theme`` (ThemeManager tracks + resolves the active CSS). The
        rest — ``default_surface``, ``history_retention``,
        ``signature_enabled``, ``show_session_stamp``,
        ``default_override_target`` — are resolved and displayed truthfully
        but have no consumer reading them yet; wiring each is its own change,
        not something to fake here.

        ``sensitive_keywords`` used to sit in that list and was removed
        outright: it promised masking, had no consumer, and secret detection is
        now model-driven (``is_secret_field``), so there is no name-list left
        for it to mean anything against. A setting a user can set, see echoed
        back, and derive false confidence from is worse than no setting.
        """
        # No suppression here: a wrong method name or a bad value must fail
        # loudly. A blanket `suppress(Exception)` previously swallowed an
        # AttributeError from a misspelled setter, so this setting silently
        # never applied while appearing wired.
        # Keys are dotted catalog names (`tui.theme`), matching what
        # FuncSettingsStore resolves and what a Detail-view save passes.
        if "tui.display_auto_switch" in values:
            self._display_slot.set_auto_switch_setting(
                values["tui.display_auto_switch"]
            )

        if "tui.theme" in values:
            self._theme_manager.activate_theme(values["tui.theme"])

    def _load_settings(self) -> None:
        """Resolve settings at startup and apply them."""
        try:
            self._apply_settings(self._settings_store.effective_values())
        except OSError as exc:
            # A broken/unreadable settings file must not stop the TUI booting.
            self.log.warning(f"_load_settings: failed to apply settings: {exc}")

    def _reload_settings_panel(self) -> None:
        """Re-resolve settings and push them into the Settings panel, if built."""
        panel = self._find_settings_panel()
        if panel is None:
            return
        with contextlib.suppress(Exception):
            # The store parses at construction; a save (or an external edit)
            # since then would otherwise show stale values here.
            self._settings_store.refresh()
            panel.load_from_store(
                self._settings_store.effective_values(),
                self._settings_store.source_labels(),
            )

    def _find_settings_panel(self) -> SettingsPanel | None:
        """The SettingsPanel in the General ring, if one was built."""
        for _title, widget in self._general_panels:
            if isinstance(widget, SettingsPanel):
                return widget
        return None

    def on_settings_panel_insert_requested(
        self, event: SettingsPanel.InsertRequested
    ) -> None:
        """Handle INSERT request from SettingsPanel — enter INSERT mode."""
        self._enter_insert_for(event.field_def)

    def on_source_chain_detail_view_insert_requested(
        self, event: SourceChainDetailView.InsertRequested
    ) -> None:
        """Handle INSERT request from a Detail view — enter INSERT mode.

        The same handler shape as the SettingsPanel's, because both now post
        a FieldDef-shaped payload. ``ConfigFilesPanel.InsertRequested`` used
        to post ``(field_name, current_value)`` instead — a signature nothing
        in the INSERT flow could consume, and which had no handler anyway.
        """
        self._enter_insert_for(event.field_def)

    def _enter_insert_for(self, field_def: Any) -> None:
        """Start SmartBar INSERT editing for a field, with its choices."""
        if field_def is None:
            return
        self._insert_mode.enter_insert(field_def, return_zone=FocusZone.PANEL)
        choices = getattr(field_def, "choices", None)
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.enter_insert_mode(choices)
        except NoMatches:
            pass

    def on_source_chain_detail_view_saved(
        self, event: SourceChainDetailView.Saved
    ) -> None:
        """Staged changes were written → pop the view and re-resolve.

        The kernel parsed config files at boot and will not re-read them, so
        the Config Table is rebuilt from a fresh PendingExecution rather than
        trusting the kernel's cached view.
        """
        self._panel_host.pop_view()
        if self._pending is not None:
            self._pending = self._build_pending_execution(self._pending.job_name)
        self._command_panels_stale = True
        self._refresh_all_views()
        self._reload_settings_panel()
        self._panel_host.update_chrome_with_focus(focused=True)

    def on_source_chain_detail_view_save_failed(
        self, event: SourceChainDetailView.SaveFailed
    ) -> None:
        """A write failed — tell the user rather than silently doing nothing."""
        self.log.warning(f"source chain detail save failed: {event.error}")
        self._smart_bar.enter_invalid(f"Save failed: {event.error}")

    def on_source_chain_detail_view_read_only_rejected(
        self, event: SourceChainDetailView.ReadOnlyRejected
    ) -> None:
        """User tried to edit a source they cannot write."""
        self._smart_bar.enter_invalid(f"{event.label} is read-only")

    def on_settings_panel_setting_changed(
        self, event: SettingsPanel.SettingChanged
    ) -> None:
        """A quick edit in the Settings table → apply it to the running app.

        This is the handler whose absence made the whole panel display-only:
        the message was posted and nothing consumed it, so a confirmed edit
        changed neither behaviour nor any file. The quick-edit path stays
        in-memory ("unsaved"); persistence is the Enter/Detail flow, which
        can say *which* source to write to.
        """
        self._apply_settings({event.setting_name: event.value})

    # ------------------------------------------------------------------
    # State query (used by KeyDispatcher)
    # ------------------------------------------------------------------

    def is_autocomplete_visible(self) -> bool:
        """Check if autocomplete dropdown is currently visible."""
        try:
            ac_widget = self.query_one(FunctualizeAutoComplete)
            return (
                ac_widget.display
                and hasattr(ac_widget, "option_list")
                and ac_widget.option_list.option_count > 0
            )
        except NoMatches:
            return False

    def _mode_is_ready(self, text: str) -> bool:
        """Whether the sigil mode owning ``text`` considers it submittable."""
        mode = self._completer.input_modes.get(text[0]) if text else None
        return bool(mode is not None and mode.is_ready(mode.strip_sigil(text)))

    def is_execute_ready(self) -> bool:
        """Check whether plain Enter should execute, used by ``KeyDispatcher``.

        Each input mode carries its own readiness rule, so a sigil mode is
        asked its own question. Gating everything on `SmartBar.readiness` would
        consult the *command* mode's rule — "is this a runnable job with its
        required fields filled" — which `!ls` can never satisfy, so Enter would
        silently do nothing in shell mode.
        """
        text = self._smart_bar.value
        if text and text[0] in self._completer.input_modes:
            return self._mode_is_ready(text)
        return self._smart_bar.readiness == BarReadiness.READY

    def resolved_default_surface(self) -> str:
        """The effective ``tui.default_surface`` value (default < file < env).

        Consulted by the surface-resolution ladder (``run_job``) to decide
        whether a job renders in the panel (``"panel"``) or hands off to a
        real-stdout run (``"stdout"``). Read live so a
        ``FUNCTUALIZE_TUI_DEFAULT_SURFACE`` override or a settings save takes
        effect on the next run.
        """
        return self._settings_store.effective_values().get(
            "tui.default_surface", "panel"
        )

    @property
    def active_panel(self) -> Widget | None:
        """Active widget for KeyDispatcher target resolution — zone-aware.

        With the DISPLAY zone focused in NORMAL mode, the display's
        interactive widget owns the keys (the convergence contract: display
        widgets are routed exactly like PanelHost panels, through this one
        property — never a second routing mechanism). Everywhere else, the
        PanelHost's current widget, as before.
        """
        if (
            self._focus_state.zone is FocusZone.DISPLAY
            and self._focus_state.mode is FocusMode.NORMAL
        ):
            return self._display_slot.current_interactive_widget
        return self._panel_host.current_panel_widget

    def display_zone_engaged(self) -> bool:
        """Whether the user is interacting with the display zone right now.

        Consulted by ``DisplaySlot`` to skip content remounts that would
        steal focus/cursor state mid-interaction.
        """
        return (
            self._focus_state.zone is FocusZone.DISPLAY
            and self._focus_state.mode is FocusMode.NORMAL
        )

    # ------------------------------------------------------------------
    # COMMAND mode actions
    # ------------------------------------------------------------------

    def action_autocomplete_toggle(self) -> None:
        """Toggle autocomplete dropdown visibility.

        If the dropdown is currently visible with options, hide it.
        Otherwise, trigger a rebuild/show by refreshing the target state.
        """
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            if ac.display and ac.option_list.option_count > 0:
                ac.action_hide()
            else:
                # Trigger a rebuild and show
                ac.refresh_dropdown()
        except NoMatches:
            pass

    def action_panel_command_toggle(self) -> None:
        """Toggle the command panel ring (Ctrl+R).

        If already active and showing the command ring, collapse and return
        to COMMAND mode. Otherwise, build the command panels from the
        current job's field definitions, set them, activate the host, and
        enter NORMAL mode with zone PANEL.
        """
        # An explicit toggle takes ownership of the ring from live.panel.
        self._live_panel_autoactivated = False
        if self._panel_host.is_active and self._active_ring == "command":
            self._panel_host.collapse()
            self._active_ring = None
            exit_to_command_mode(self, self._focus_state, self._smart_bar)
        else:
            # Command panels require a recognized job (PENDING or READY)
            if self._smart_bar.readiness == BarReadiness.GREY:
                return
            # Always rebuild command panels to avoid duplicate ID errors
            # when switching between panel rings (async removal timing)
            self._command_panels = self._build_command_panels()
            if not self._command_panels:
                return  # No fields for this job
            self._panel_host.set_type_prefix("R")
            self._panel_host.set_panels(self._command_panels)
            self._panel_host.activate()
            self._active_ring = "command"
            enter_normal_mode(self, self._focus_state, FocusZone.PANEL)
        self._update_preflight_summary()

    def action_panel_general_toggle(self) -> None:
        """Toggle the general panel ring (Ctrl+E).

        If already active and showing the general ring, collapse and return
        to COMMAND mode. Otherwise, set the general panels, activate the
        host, and enter NORMAL mode with zone PANEL.
        """
        # An explicit toggle takes ownership of the ring from live.panel.
        self._live_panel_autoactivated = False
        if self._panel_host.is_active and self._active_ring == "general":
            self._panel_host.collapse()
            self._active_ring = None
            exit_to_command_mode(self, self._focus_state, self._smart_bar)
        else:
            # Always rebuild general panels (widgets are invalidated on ring switch)
            self._general_panels = self._build_general_panels()
            self._panel_host.set_type_prefix("E")
            self._panel_host.set_panels(self._general_panels)
            self._panel_host.activate()
            self._active_ring = "general"
            enter_normal_mode(self, self._focus_state, FocusZone.PANEL)
            # A freshly built Settings panel shows catalog defaults until the
            # store's resolution is pushed into it.
            self._reload_settings_panel()
        self._update_preflight_summary()

    def mount_live_panel(self, widget: Widget, title: str) -> None:
        """Mount a job's ``live.panel(...)`` construct as a general-ring panel.

        Auto-surfaces: if the general ring is not active, it is (re)built and
        activated — surfacing the panel is the point of ``live.panel``. The
        new panel joins the end of the ring and takes focus. Loop thread only
        (``PanelLiveZone`` marshals its way here).
        """
        entry = (title, widget)
        if self._panel_host.is_active and self._active_ring == "general":
            # New list object: set_panels skips when handed the same list.
            self._general_panels = [*self._general_panels, entry]
            self._panel_host.set_panels(self._general_panels)
        else:
            self._general_panels = [*self._build_general_panels(), entry]
            self._panel_host.set_type_prefix("E")
            self._panel_host.set_panels(self._general_panels)
            self._panel_host.activate()
            self._active_ring = "general"
            self._live_panel_autoactivated = True
            enter_normal_mode(self, self._focus_state, FocusZone.PANEL)
        self._panel_host.navigate_last()
        self._update_preflight_summary()

    def remove_live_panel(self, widget: Widget) -> None:
        """Unmount a ``live.panel`` construct's panel (job ended).

        Drops it from the general ring; if it was the last panel showing,
        the host collapses and focus returns to the SmartBar. Loop thread
        only.
        """
        from functualize._cli.tui.live_panel_widget import LivePanelWidget

        was_current = (
            self._panel_host.is_active
            and self._panel_host.current_panel_widget is widget
        )
        self._general_panels = [
            (title, panel)
            for title, panel in self._general_panels
            if panel is not widget
        ]
        with contextlib.suppress(Exception):
            widget.remove()
        if not (self._panel_host.is_active and self._active_ring == "general"):
            return
        live_remaining = any(
            isinstance(panel, LivePanelWidget) for _title, panel in self._general_panels
        )
        collapse = not self._general_panels or (
            self._live_panel_autoactivated and not live_remaining
        )
        if not collapse:
            self._panel_host.set_panels(self._general_panels)
            if was_current:
                self._panel_host.navigate_first()
            self._panel_host.update_chrome_with_focus(
                focused=self._focus_state.zone is FocusZone.PANEL
            )
        else:
            # The ring existed only to host live panels — leave with them.
            self._panel_host.collapse()
            self._active_ring = None
            self._live_panel_autoactivated = False
            if self._focus_state.mode is FocusMode.NORMAL:
                exit_to_command_mode(self, self._focus_state, self._smart_bar)
        self._update_preflight_summary()

    def action_execute(self) -> None:
        """Execute the current command if bar is READY, show preflight if PENDING."""
        # A sigil mode owns its own submit — `!ls` is not a job name and must
        # never reach the job path. Checked before readiness because readiness
        # is the *command* mode's rule; each mode carries its own `is_ready`.
        # The membership test is inline, not inside the helper: it is the whole
        # dispatch rule ("is the first character a registered sigil"), and
        # keeping it here means the ordinary command path never calls into mode
        # machinery at all.
        _text = self._smart_bar.value
        if _text and _text[0] in self._completer.input_modes:
            self._submit_via_mode(_text)
            return

        if self._smart_bar.readiness == BarReadiness.READY:
            text = self._smart_bar.value
            tokens = text.split() if text.strip() else []
            if not tokens:
                return
            self._run_job(tokens)
        elif self._smart_bar.readiness == BarReadiness.PENDING:
            # Missing required fields — open the command panel to show what
            # needs filling. When execute is triggered from *within* an already
            # open command panel (NORMAL mode Ctrl+Enter), leave it open rather
            # than toggling it closed — the user is there to fill those fields.
            if not (self._panel_host.is_active and self._active_ring == "command"):
                self.action_panel_command_toggle()

    def _submit_via_mode(self, text: str) -> None:
        """Run ``text`` through the sigil mode that owns it.

        The caller has already established that ``text[0]`` is a registered
        sigil. Only sigil modes come here: the default command mode's submit is
        the existing job path, and moving that too would be a much larger
        change than C1b.3 needs. The sigil check is what keeps `!ls` from being
        looked up as a job name.
        """
        mode = self._completer.input_modes.get(text[0])
        if mode is None:  # pragma: no cover — the caller checked membership
            return

        body = mode.strip_sigil(text)
        if not mode.is_ready(body):
            # A bare `!` is not runnable — do nothing rather than fall through
            # to the job path, which would try to resolve `!` as a job name.
            return

        mode.submit(body)
        self._smart_bar.value = ""

    def _run_job(self, tokens: list[str]) -> None:
        """Execute a job from parsed tokens and display output in the RichLog.

        Args:
            tokens: Split command tokens, first element is the job name.
        """
        run_job(self, tokens)

    async def _execute_job_async(self, job_name: str, kwargs: dict[str, str]) -> int:
        """Run a job in-process through the FunctualizeApp execution API.

        Captures output via a logging handler attached to the job logger
        and writes results to the RichLog widget.
        """
        return await execute_job_async(self, job_name, kwargs)

    def _extract_effective_values(
        self, job_name: str, kwargs: dict[str, str]
    ) -> dict[str, Any]:
        """Extract effective config values for snapshot recording.

        Uses PendingExecution.all_effective() if pending exists for this job,
        otherwise falls back to the kwargs dict.
        """
        return extract_effective_values(self._pending, job_name, kwargs)

    async def action_quit(self) -> None:
        """Quit the application.

        ``async`` to match ``textual.app.App.action_quit``; Textual awaits an
        action's result when it is awaitable, so dispatch is unchanged.
        """
        self.exit(0)

    def action_smartbar_clear(self) -> None:
        """Clear the SmartBar value."""
        self._smart_bar.value = ""

    def action_ring_next(self) -> None:
        """Navigate to next panel in the active ring."""
        if self._panel_host.is_active and self._panel_host.breadcrumb_depth == 0:
            self._rebuild_if_stale()
            self._panel_host.navigate_next()
            self._refresh_diff_view_if_active()

    def action_ring_prev(self) -> None:
        """Navigate to previous panel in the active ring."""
        if self._panel_host.is_active and self._panel_host.breadcrumb_depth == 0:
            self._rebuild_if_stale()
            self._panel_host.navigate_prev()
            self._refresh_diff_view_if_active()

    def action_ring_first(self) -> None:
        """Navigate to first panel in the active ring."""
        if self._panel_host.is_active and self._panel_host.breadcrumb_depth == 0:
            self._rebuild_if_stale()
            self._panel_host.navigate_first()
            self._refresh_diff_view_if_active()

    def action_ring_last(self) -> None:
        """Navigate to last panel in the active ring."""
        if self._panel_host.is_active and self._panel_host.breadcrumb_depth == 0:
            self._rebuild_if_stale()
            self._panel_host.navigate_last()
            self._refresh_diff_view_if_active()

    def action_display_prev(self) -> None:
        """Navigate to the previous display provider."""
        self._display_slot.navigate_prev()
        self._update_display_chrome()

    def action_display_next(self) -> None:
        """Navigate to the next display provider."""
        self._display_slot.navigate_next()
        self._update_display_chrome()

    def action_zone_cycle(self) -> None:
        """Cycle focus between visible zones (Shift+Tab)."""
        action_zone_cycle(
            self,
            self._focus_state,
            get_visible_zones=self._get_visible_zones,
            get_zone_widget=self._get_zone_widget,
        )
        self._sync_mode_to_zone()

    def _sync_mode_to_zone(self) -> None:
        """Align FocusMode with the zone Shift+Tab just landed on.

        Landing on DISPLAY with an interactive display enters NORMAL so
        j/k/Enter dispatch to the display widget; landing back on SMARTBAR
        from NORMAL returns to COMMAND with the SmartBar focused. Other
        zones keep their existing behavior.
        """
        zone = self._focus_state.zone
        mode = self._focus_state.mode
        if zone is FocusZone.DISPLAY:
            widget = self._display_slot.current_interactive_widget
            if widget is not None:
                if mode is not FocusMode.NORMAL:
                    self._focus_state.transition(FocusMode.NORMAL, FocusZone.DISPLAY)
                widget.focus()
            self._update_display_footer(FocusZone.DISPLAY)
        elif zone is FocusZone.SMARTBAR and mode is FocusMode.NORMAL:
            exit_to_command_mode(self, self._focus_state, self._smart_bar)

    def action_save_shortcut(self) -> None:
        """Save current command as a shortcut (Ctrl+S).

        A shortcut is a generated file calling ``invoke("<name>", **kwargs)``,
        so the name has to be the *job's*. The bar's first token is the outermost
        group for anything grouped, and a group is not invocable — the file
        would be written happily and fail the first time it ran. The walk also
        keeps the group's own flags out of the job's kwargs, where they would
        arrive as arguments the job never declared.
        """
        text = self._smart_bar.value
        tokens = text.split() if text.strip() else []
        if not tokens:
            return
        resolution = self.resolve_command(tokens)
        job_name = resolution.job_name
        if job_name is None:
            return
        kwargs = parse_cli_args_to_kwargs(resolution.args)
        modal = ShortcutSaveModal(job_name=job_name, kwargs=kwargs)
        self.push_screen(modal, callback=self._on_shortcut_save_dismissed)

    def _on_shortcut_save_dismissed(self, result: str | None) -> None:
        """Handle shortcut-save ModalScreen dismissal.

        ``result`` is the saved file path on success, or ``None`` on
        cancel. Side effects (file write, ``ShortcutSaved``/
        ``ShortcutCancelled`` messages) already happened inside the modal;
        this callback exists to satisfy ``push_screen``'s contract and is
        currently a no-op observation point.
        """

    # ------------------------------------------------------------------
    # NORMAL mode actions (routed to panel if it defines them)
    # ------------------------------------------------------------------

    def action_exit_panel(self) -> None:
        """Exit panel / NORMAL mode back to COMMAND mode (Escape in NORMAL).

        If breadcrumb depth > 0, pops one breadcrumb level and restores the
        previous view (e.g., from chain detail back to table). Otherwise
        collapses the panel host, clears the active ring, and transitions
        back to COMMAND mode with SmartBar focused.

        R5-AC7: Esc in drill-down → pop breadcrumb, restore Config Table view.
        """
        # DISPLAY zone owns Esc while focused: pop its drill-down sub-view if
        # one is pushed, else leave the zone back to COMMAND/SmartBar — the
        # display stays visible (it is ambient; Esc leaves, it doesn't hide).
        if self._focus_state.zone is FocusZone.DISPLAY:
            if self._display_slot.pop_view():
                widget = self._display_slot.current_interactive_widget
                if widget is not None:
                    widget.focus()
                self._update_display_chrome()
                return
            exit_to_command_mode(self, self._focus_state, self._smart_bar)
            self._update_display_chrome()
            return

        # A pushed Detail view owns Esc first: discard its staged changes and
        # pop it. Staging is what makes discarding safe enough to need no
        # confirmation prompt (R2-AC15).
        if self._panel_host.view_depth > 0:
            view = self._panel_host.current_panel_widget
            if isinstance(view, SourceChainDetailView):
                view.discard()
            self._panel_host.pop_view()
            self._panel_host.update_chrome_with_focus(focused=True)
            return

        if self._panel_host.breadcrumb_depth > 0:
            # Pop breadcrumb and restore the panel view
            self._panel_host.pop_breadcrumb()
            self._restore_from_drill_down()
            # Update footer after drill-down state is cleared
            self._panel_host.update_chrome_with_focus(focused=True)
            return

        exit_to_command_mode(self, self._focus_state, self._smart_bar)
        self._panel_host.collapse()
        self._active_ring = None
        self._update_preflight_summary()

    def _restore_from_drill_down(self) -> None:
        """Restore the panel view after exiting a drill-down sub-view.

        Removes the chain detail or file detail RichLog, shows the panel again,
        and clears the drill-down state on the panel.
        """
        try:
            content_area = self._panel_host.query_one(".panel-host-content")

            # Remove any detail views (chain or file)
            for child in content_area.query("#chain-detail-view"):
                child.remove()
            for child in content_area.query("#file-detail-view"):
                child.remove()

            # Show the config table panel again
            panel = self.active_panel
            if panel is None:
                # Panel was hidden — re-show the current panel
                current_widget = self._panel_host.current_panel_widget
                if current_widget is not None:
                    current_widget.add_class("panel-visible")
                    panel = current_widget

            if panel is not None:
                panel.add_class("panel-visible")
                # Clear drill-down state (PanelActions.clear_drill_down)
                clear_drill_down = getattr(panel, "clear_drill_down", None)
                if clear_drill_down is not None:
                    clear_drill_down()
                # Clear file detail state — ConfigFilesPanel
                # (PanelActions.exit_detail_view)
                exit_detail_view = getattr(panel, "exit_detail_view", None)
                if exit_detail_view is not None:
                    exit_detail_view()
        except NoMatches:
            # The panel-host content area may not be mounted during
            # teardown/mode-transition timing windows.
            pass

    def action_enter_insert(self) -> None:
        """Enter INSERT mode for the focused field.

        Gets the cursor field from ConfigTablePanel and delegates to
        InsertModeController.enter_insert(). The controller handles
        saving SmartBar state, setting edit value, and FSM transition.
        """
        panel = self.active_panel
        if panel is None:
            return
        # Panel must expose get_cursor_field() to provide the field to edit
        get_field = getattr(panel, "get_cursor_field", None)
        if get_field is None:
            return
        field = get_field()
        if field is None:
            return
        self._insert_mode.enter_insert(field, return_zone=FocusZone.PANEL)

    def action_enter_persist(self) -> None:
        """Enter persist-mode override application."""
        panel = self.active_panel
        # PanelActions.action_enter_persist
        action_enter_persist = getattr(panel, "action_enter_persist", None)
        if panel is not None and action_enter_persist is not None:
            action_enter_persist()

    def action_reset_override(self) -> None:
        """Reset the current field override.

        Delegates to the panel to reset its visual state, then clears the
        override in PendingExecution and refreshes all views.

        R1-AC5: clear_override() + notify all panels to refresh.
        """
        panel = self.active_panel
        # PanelActions.action_reset_override
        action_reset_override = getattr(panel, "action_reset_override", None)
        if panel is not None and action_reset_override is not None:
            # Get the field name before the panel resets it
            field_name = None
            get_cursor_field = getattr(panel, "get_cursor_field", None)
            if get_cursor_field is not None:
                cursor_field = get_cursor_field()
                if cursor_field is not None:
                    field_name = getattr(cursor_field, "name", None)

            action_reset_override()

            # Clear override in PendingExecution
            if self._pending is not None and field_name:
                self._pending.clear_override(field_name)

            # Refresh all views to propagate the change
            self._refresh_all_views()

    def action_enter_filter(self) -> None:
        """Enter FILTER mode — repurpose SmartBar for panel filtering.

        Only enters filter mode if the active panel implements the Filterable
        protocol. Saves the current SmartBar state, clears it with a filter
        placeholder, suppresses autocomplete entirely, and transitions to
        FILTER mode.
        """
        from functualize._cli.tui.panels import Filterable

        panel = self.active_panel
        if panel is None or not isinstance(panel, Filterable):
            return  # Panel doesn't support filtering — no-op
        self._focus_state.transition(FocusMode.FILTER)
        # Save bar state so we can restore on exit
        self._smart_bar.save_state()
        # Pre-fill with existing filter if re-entering
        self._smart_bar.value = panel.active_filter
        self._smart_bar.placeholder = "Filter..."
        self._smart_bar.focus()
        # Suppress autocomplete entirely while filtering
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.suppress()
        except NoMatches:
            pass

    def action_drill_down(self) -> None:
        """Drill down into nested config."""
        panel = self.active_panel
        # PanelActions.action_drill_down
        action_drill_down = getattr(panel, "action_drill_down", None)
        if panel is not None and action_drill_down is not None:
            action_drill_down()

    # ------------------------------------------------------------------
    # INSERT mode actions
    # ------------------------------------------------------------------

    def action_confirm_edit(self) -> None:
        """Confirm the current edit in INSERT mode."""
        self._insert_mode.confirm_edit()
        # Restore autocomplete to command mode
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.exit_insert_mode()
        except NoMatches:
            pass
        # After confirm, sync the SmartBar with updated field values
        self._sync_smartbar_from_fields()

    def action_exit_insert(self) -> None:
        """Exit INSERT mode without applying changes."""
        self._insert_mode.exit_insert()
        # Restore autocomplete to command mode
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.exit_insert_mode()
        except NoMatches:
            pass

    def _on_insert_edit_applied(self, field: Any, new_value: str) -> None:
        """Callback from InsertModeController when an edit is confirmed.

        Updates the ConfigTablePanel display, records the override in
        PendingExecution, and refreshes all views.

        R1-AC4: direct overrides write + notify all panels to refresh.
        R8-AC1: SmartBar updated via _refresh_all_views → _sync_smartbar_from_pending.
        R8-AC2: PreFlightSummary refreshed via _refresh_all_views → _update_preflight_summary.
        """
        # Update the ConfigTablePanel's DataTable display
        # (PanelActions.apply_value_edit)
        panel = self.active_panel
        apply_value_edit = getattr(panel, "apply_value_edit", None)
        if panel is not None and apply_value_edit is not None:
            apply_value_edit(field, new_value)

        # An edit staged in a Detail view is destined for a file, not for this
        # run — recording it as a session override would apply it to the next
        # execute even if the user then pressed Esc to discard it.
        if isinstance(panel, SourceChainDetailView):
            self._panel_host.update_chrome_with_focus(focused=True)
            return

        # Record override in PendingExecution (single source of truth)
        if self._pending is not None:
            field_name = getattr(field, "name", None)
            if field_name:
                self._pending.overrides[field_name] = new_value

        # Refresh all views to propagate the change
        self._refresh_all_views()

    def _sync_smartbar_from_fields(self) -> None:
        """Sync SmartBar text to reflect current field values from the config table.

        Rebuilds the SmartBar value as: <command path> <positional_vals>
        --flag1 val1 ... Positional args are bare tokens in declaration order.
        Named options use --flag value syntax.
        Short flags use -x value syntax when available.

        The path is rebuilt from the resolved job, not from the bar's first token:
        under a group that first token is the group, so editing any field used
        to rewrite `deploy web run` as `deploy`.
        """
        if self._active_ring != "command":
            return
        panel = self._panel_host.current_panel_widget
        if not isinstance(panel, ConfigTablePanel):
            return

        # Resolve the path the bar currently spells, so the whole of it
        # survives the rebuild.
        text = self._smart_bar.value
        tokens = text.split() if text.strip() else []
        if not tokens:
            return
        resolution = self.resolve_command(tokens)
        if resolution.job_name is None:
            return

        self._smart_bar.value = sync_overrides_to_bar(
            resolution.job_name,
            panel.fields,
            resolution.group_values,
            self._group_trie,
        )

    def _sync_config_table_from_smartbar(self) -> None:
        """Sync ConfigTablePanel field values from SmartBar CLI args.

        Parses --flag value pairs from the SmartBar and updates matching
        fields in the active ConfigTablePanel.
        """
        if self._active_ring != "command":
            return
        panel = self._panel_host.current_panel_widget
        if not isinstance(panel, ConfigTablePanel):
            return

        # Hand the walk over: `resolution.args` are the job's own tokens, with
        # the path segments and mid-path group flags already consumed. Parsing
        # the raw tail instead binds `web` — a path segment — to the job's
        # first positional.
        text = self._smart_bar.value
        resolution = self.resolve_command(text.split() if text.strip() else [])
        if sync_bar_to_overrides(text, panel.fields, resolution=resolution):
            panel.reload_table()

    def action_select_choice(self) -> None:
        """Select the highlighted autocomplete choice and apply to SmartBar."""
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.accept_highlighted()
        except NoMatches:
            pass

    def action_choice_up(self) -> None:
        """Navigate autocomplete choices up in INSERT mode."""
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            if ac.display:
                ac.option_list.action_cursor_up()
        except NoMatches:
            pass

    def action_choice_down(self) -> None:
        """Navigate autocomplete choices down in INSERT mode."""
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            if ac.display:
                ac.option_list.action_cursor_down()
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # FILTER mode actions
    # ------------------------------------------------------------------

    def action_exit_filter(self) -> None:
        """Exit FILTER mode back to NORMAL without applying filter.

        Restores the SmartBar to its saved command state, unsuppresses
        autocomplete, and clears any active filter on the panel.
        """
        from functualize._cli.tui.panels import Filterable

        # Clear the filter on the panel
        panel = self.active_panel
        if panel is not None and isinstance(panel, Filterable):
            panel.apply_filter("")
        # Restore bar state and unsuppress autocomplete
        self._smart_bar.restore_state()
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.unsuppress()
        except NoMatches:
            pass
        self._focus_state.exit_to_normal()
        # Update panel footer to remove filter indicator
        self._update_panel_filter_indicator("")

    def action_apply_filter(self) -> None:
        """Apply the current filter text and exit FILTER mode.

        Sends the SmartBar value as a filter to the active panel,
        restores the SmartBar, unsuppresses autocomplete, and returns
        to NORMAL mode. Shows a filter indicator in the panel breadcrumb.
        """
        from functualize._cli.tui.panels import Filterable

        filter_text = self._smart_bar.value
        panel = self.active_panel
        if panel is not None and isinstance(panel, Filterable):
            panel.apply_filter(filter_text)
        # Restore bar state and unsuppress autocomplete
        self._smart_bar.restore_state()
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.unsuppress()
        except NoMatches:
            pass
        self._focus_state.exit_to_normal()
        # Update panel breadcrumb/footer with active filter indicator
        self._update_panel_filter_indicator(filter_text)

    # ------------------------------------------------------------------
    # Autocomplete intercept actions
    # ------------------------------------------------------------------

    def action_autocomplete_accept(self) -> None:
        """Accept the current autocomplete suggestion.

        Delegates to the AutoComplete widget's completion logic.
        Completes the currently highlighted option in the dropdown.
        """
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.accept_highlighted()
        except NoMatches:
            pass

    def action_autocomplete_next(self) -> None:
        """Move to next autocomplete suggestion.

        Advances the highlighted option in the dropdown list, wrapping around.
        """
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            if ac.display and ac.option_list.option_count > 0:
                highlighted = ac.option_list.highlighted or 0
                highlighted = (highlighted + 1) % ac.option_list.option_count
                ac.option_list.highlighted = highlighted
        except NoMatches:
            pass

    def action_autocomplete_prev(self) -> None:
        """Move to previous autocomplete suggestion.

        Moves the highlighted option up in the dropdown list, wrapping around.
        """
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            if ac.display and ac.option_list.option_count > 0:
                highlighted = ac.option_list.highlighted or 0
                highlighted = (highlighted - 1) % ac.option_list.option_count
                ac.option_list.highlighted = highlighted
        except NoMatches:
            pass

    def action_autocomplete_dismiss(self) -> None:
        """Dismiss the autocomplete dropdown."""
        try:
            ac = self.query_one(FunctualizeAutoComplete)
            ac.action_hide()
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Observer callbacks
    # ------------------------------------------------------------------

    def _on_focus_changed(self, mode: FocusMode, zone: FocusZone) -> None:
        """FocusState subscriber: update mode indicator + contextual hints.

        Also applies the set_focus(None) safety net for NORMAL mode entry.
        This ensures all key events reach the App's on_key handler even if
        NORMAL mode is entered via a path other than enter_normal_mode()
        (e.g., INSERT → NORMAL via exit_to_normal()).
        """
        # Safety net: remove DOM focus in NORMAL mode so on_key receives all keys.
        # In INSERT mode the SmartBar must retain focus for text input.
        if mode is FocusMode.NORMAL:
            self.set_focus(None)

        # Update panel footer with focus-awareness (R6-AC1, R6-AC2, R6-AC3, R6-AC4)
        if self._panel_host and self._panel_host.is_active and self._panel_host._panels:
            self._panel_host.update_chrome_with_focus(zone is FocusZone.PANEL)

        # Update display footer with focus-awareness (R7-AC1, R7-AC2)
        self._update_display_footer(zone)

        # Update status bar: mode + zone + readiness (R8-AC1, R8-AC3)
        self._update_status_bar(mode, zone)

    def _on_display_slot_visibility(self, visible: bool) -> None:
        """Toggle display section CSS class when visibility changes."""
        try:
            display_section = self.query_one("#display-section")
            if visible:
                display_section.add_class("visible")
                self._update_display_chrome()
            else:
                display_section.remove_class("visible")
        except NoMatches:
            pass

    def _update_display_chrome(self) -> None:
        """Update display breadcrumb, body, and footer from the DisplaySlot state."""
        update_display_chrome(self)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _plugin_instances(self) -> list[Any]:
        """Loaded plugin instances, for bar item collection."""
        loader = getattr(self._func_app, "plugin_loader", None)
        if loader is None:
            return []
        return list(loader.loaded_instances)

    def _update_header(self) -> None:
        """Update header with app name, job counts, and plugin header items."""
        try:
            jobs = self._func_app.get_jobs()
            total = len(jobs)
            # Count CWD jobs (jobs discovered from the current directory)
            cwd_count = count_jobs_in_cwd(jobs, Path.cwd())
            header = self.query_one("#header", Static)
            if cwd_count and cwd_count < total:
                base = (
                    f" func — {self._func_app.name}"
                    f"  ({cwd_count} cwd, {total} total jobs)"
                )
            else:
                base = f" func — {self._func_app.name}  ({total} jobs)"
            plugin_text = render_header_items(self._plugin_instances(), self._func_app)
            header.update(f"{base}  {plugin_text}" if plugin_text else base)
        except Exception as exc:
            # Guards get_jobs() (a domain call, not a query_one lookup) in
            # addition to the header query_one — log so job-discovery
            # failures are visible instead of silently leaving a stale
            # header.
            self.log.warning(
                f"_update_header: failed to refresh header "
                f"({type(exc).__name__}): {exc}"
            )

    def _register_display_providers(self) -> None:
        """Discover and register DisplayProviders with the DisplaySlot.

        Scans for a 'displays.py' module in the current working directory.
        If found, instantiates any classes with the required DisplayProvider
        attributes and registers them with the DisplaySlot.
        """
        register_display_providers(self)

    def _get_job_names(self) -> list[str]:
        """Return list of known job names from the FunctualizeApp."""
        try:
            return [j.name for j in self._func_app.get_jobs()]
        except Exception as exc:
            # get_jobs() is a domain call, not a query_one lookup — log so
            # job-discovery failures are visible instead of silently
            # returning an empty name list.
            self.log.warning(
                f"_get_job_names: get_jobs() failed ({type(exc).__name__}): {exc}"
            )
            return []

    def _get_command_names(self) -> list[str]:
        """Return every name the SmartBar accepts: jobs plus builtin commands.

        Readiness evaluation must know about builtins, or the bar reports
        "Unknown: config" and stays GREY — which makes Enter a silent no-op.
        A job of the same name shadows the builtin, matching dispatch
        precedence.
        """
        names = self._get_job_names()
        known = set(names)
        names.extend(n for n in self._command_tree_names() if n not in known)
        return names

    def _command_tree_names(self) -> list[str]:
        """Top-level names in the shell's one command tree.

        Jobs already come from ``_get_job_names``; what this adds is every other
        top-level node — today the reserved ``builtin`` subtree. Reading it from
        the tree means a name never has to be hardcoded here again.
        """
        try:
            from functualize.app.commands import build_command_tree

            return [node.name for node in build_command_tree(self._func_app)]
        except Exception as exc:  # pragma: no cover - defensive
            self.log.warning(f"_command_tree_names failed: {exc}")
            return []

    def _get_required_fields(self, job_name: str) -> list[str]:
        """Return required field names for the given job.

        Looks up the JobDescriptor and returns names of fields marked
        as required (no default value).
        """
        try:
            descriptor = self._find_job_descriptor(job_name)
            if descriptor is None:
                return []
            fields = get_descriptor_fields(descriptor)
            if not fields:
                return []
            return [f.name for f in fields if getattr(f, "required", False)]
        except Exception as exc:
            # _find_job_descriptor()/get_descriptor_fields() are domain
            # calls, not query_one lookups — log so field-resolution
            # failures are visible instead of silently returning [].
            self.log.warning(
                f"_get_required_fields: field lookup failed for "
                f"{job_name!r} ({type(exc).__name__}): {exc}"
            )
            return []

    @property
    def _group_trie(self) -> Any:
        """The group trie over the booted jobs + cached group options (memoized).

        Built once via the shared `build_group_option_trie`, the CLI's own
        inputs, so inheritance resolves identically in the TUI and CLI (scrutiny
        D2). ``None`` when there are no group options; the caller then treats
        every flag as a job argument (pre-S6b behavior).
        """
        cached = getattr(self, "_group_trie_cache", "unset")
        if cached != "unset":
            return cached
        trie = build_group_option_trie(self._func_app)
        self._group_trie_cache: Any = trie
        return trie

    def resolve_command(self, tokens: list[str]) -> Any:
        """Resolve SmartBar tokens to a job by **space-separated path walk** (S6b).

        The shell navigates groups the way the CLI does — ``deploy web run`` —
        so this delegates to the CLI's own walk. Group flags are consumed
        *mid-path* (``deploy --env prod web run``), which is why there is no
        post-name job/group split: after the command, position makes every flag
        the job's own (D-d), exactly as on the command line.

        Returns a ``TuiCommandResolution`` carrying the resolved job name, the
        job's own remaining argument tokens, the mid-path group values, and the
        two refusal reasons (a dotted path token, an undeclared mid-path flag).
        """
        return resolve_tui_command(self._group_trie, tokens)

    def job_kwargs_for(self, job_name: str, args: list[str]) -> dict[str, Any]:
        """Parse a resolved job's own argument tokens into kwargs."""
        return dict(
            parse_cli_args_to_kwargs(args, fields=self._get_job_fields(job_name))
        )

    def _get_job_fields(self, job_name: str) -> list[Any]:
        """A job's **settable** fields (for parsing, preview and the field table).

        Excludes the ``GroupOptions`` injection parameter. ``opts:
        DeployOptions`` is where the resolved group instance lands — an outlet,
        not an input — so rendering it as a field invites the user to fill in a
        model, and the flags it stands for are offered separately. The CLI
        excludes it by testing the live annotation; here the descriptor is
        cached, so the equivalent signal is the declared type name matching a
        ``GroupOptions`` class on this job's group path (the same test the MCP
        translator applies).
        """
        try:
            descriptor = self._find_job_descriptor(job_name)
            if descriptor is None:
                return []
            fields = get_descriptor_fields(descriptor)
            if not fields:
                return []
            injection_types = {
                spec.class_name
                for spec in group_option_specs_on_path(self._group_trie, job_name)
            }
            return [
                field
                for field in fields
                if (getattr(field, "type_annotation", "") or "").strip()
                not in injection_types
            ]
        except Exception as exc:
            # _find_job_descriptor()/get_descriptor_fields() are domain
            # calls, not query_one lookups — log so field-resolution
            # failures are visible instead of silently returning [].
            self.log.warning(
                f"_get_job_fields: field lookup failed for "
                f"{job_name!r} ({type(exc).__name__}): {exc}"
            )
            return []

    def _find_job_descriptor(self, job_name: str) -> Any:
        """Find a job descriptor by name.

        Tries get_job() first, then falls back to iterating get_jobs().
        The descriptor's fields already carry correct positional/short_flag
        metadata from the provider layer.
        """
        descriptor = self._func_app.get_job(job_name)
        if descriptor is None:
            try:
                for j in self._func_app.get_jobs():
                    if j.name == job_name:
                        descriptor = j
                        break
            except Exception as exc:
                # get_jobs() is a domain call, not a query_one lookup — log
                # and fall back to "descriptor not found".
                self.log.warning(
                    f"_find_job_descriptor: get_jobs() fallback failed for "
                    f"{job_name!r} ({type(exc).__name__}): {exc}"
                )

        return descriptor

    def _group_option_paths(self, job_name: str) -> dict[str, str]:
        """Which group declared each option the job inherits, by field name.

        Outermost declaration wins a name clash, matching where
        ``build_command_line`` writes the flag back. The two have to agree:
        a value attributed to one level and emitted at another would round-trip
        into a different command than the one recorded.
        """
        paths: dict[str, str] = {}
        for spec in group_option_specs_on_path(self._group_trie, job_name):
            for field_desc in spec.fields:
                paths.setdefault(field_desc.name, spec.group)
        return paths

    def _format_preflight_job_header(self, descriptor: Any, job_name: str) -> str:
        """Format the bold job-header line: ``{command} — {first_doc_line}``.

        The command is rendered as the shell spells it — `deploy web run`, not
        `deploy.web.run`. The bar directly above shows the spaced form, and the
        dotted one is a spelling the shell's own resolver refuses; printing it
        here taught a form that cannot be typed back. Ungrouped jobs have no
        dots and are unaffected.
        """
        docstring = getattr(descriptor, "docstring", None) or ""
        doc_lines = docstring.strip().splitlines() if docstring.strip() else []
        first_line = doc_lines[0].strip() if doc_lines else ""
        command = job_name.replace(".", " ")
        return f"[bold]{command} — {first_line}[/bold]"

    def _render_preflight_summary(self, log: RichLog) -> None:
        """Render compact pre-flight summary with single-line-per-field format.

        Layout:
        - Job header: {job_name} — {first_line_of_docstring} (bold)
        - Per field (single line):
          {indicator}{req_mark} {kind_label}{name}{short}: {value} ({source})  {type}  {desc}

        Indicators: ● filled, ○ empty+required, · optional+empty
        Kind label: [arg] for positional plain params, empty otherwise
        Source: omitted for empty plain params; "cli"/"default" for plain with value;
                full source for config params
        Description: truncated with … if line exceeds terminal width

        Requirements: R2-AC1, R2-AC2, R2-AC3, R2-AC4, R2-AC5, R2-AC6, R2-AC7
        """
        try:
            log.clear()
            tokens = (
                self._smart_bar.value.split() if self._smart_bar.value.strip() else []
            )
            if not tokens:
                return
            # Space-separated path walk (S6b), so the pre-flight panel resolves
            # `deploy web run` the same way execution does.
            _preflight_resolution = self.resolve_command(tokens)
            if _preflight_resolution.dotted_token is not None:
                # The shell navigates by spaces. Say so here rather than falling
                # back to the dotted name, which would render a full pre-flight
                # panel for a spelling execution then refuses.
                spaced = _preflight_resolution.dotted_token.replace(".", " ")
                log.write(
                    f"[dim]Navigate groups with spaces:[/dim] [bold]{spaced}[/bold]"
                )
                return
            job_name = _preflight_resolution.job_name or tokens[0]

            # Builtins are recognized commands but not jobs, so they have no
            # descriptor and would otherwise render a blank panel. They still
            # need to explain themselves — especially the sub-app case, where
            # the useful thing to show is which subcommands exist.
            if self._find_job_descriptor(job_name) is None and (
                self._render_tree_preflight(log, tokens)
            ):
                return

            descriptor = self._find_job_descriptor(job_name)
            if descriptor is None:
                return
            # Settable fields only — the GroupOptions injection parameter is not
            # something the user fills in (S6b).
            fields = self._get_job_fields(job_name)
            if not fields:
                # Bare jobs (zero fields) skip the field-table render below,
                # but a READY bare job (e.g. a no-arg `healthcheck`) still
                # needs the job header + Ctrl+S hint surfaced — otherwise
                # the discoverability hint silently disappears for the
                # zero-fields edge case.
                if self._smart_bar.readiness == BarReadiness.READY:
                    log.write(self._format_preflight_job_header(descriptor, job_name))
                    log.write("[dim]Ctrl+Enter run  ·  Ctrl+S save as shortcut[/dim]")
                return

            # --- Job header (bold: job_name — first_line_of_docstring) ---
            log.write(self._format_preflight_job_header(descriptor, job_name))

            # Determine available width for truncation
            try:
                avail_width = self.size.width if self.size.width > 0 else 80
            except AttributeError:
                # self.size is a Textual layout property, not a query_one
                # lookup. Narrowed (rather than logged): this path is
                # exercised routinely by tests that construct the TUI via
                # __new__() without running App.__init__, where self.log
                # itself is unsafe to call (no _logger yet) — AttributeError
                # is the only failure mode in that legitimate case.
                avail_width = 80

            # The job's own argument tokens — the walk already consumed any
            # mid-path group flag, so the field table shows the job's fields
            # and never a group flag misparsed as one (S6b).
            provided = self.job_kwargs_for(job_name, _preflight_resolution.args)

            # Thread real resolved source_type from PendingExecution so unfilled
            # config params show (env)/(file)/... rather than a blind (default).
            resolved_sources: dict[str, str] = {}
            pending = getattr(self, "_pending", None)
            if pending is not None:
                for name, rv in pending.resolved_values.items():
                    source_type = getattr(rv, "source_type", None)
                    if source_type:
                        resolved_sources[name] = source_type

            # The group's own options, after the job's own fields and
            # outermost group first (D-1). They carry their resolved value,
            # their source and their `secret` flag with them, so the line
            # formatter masks a group credential by the same rule it masks a
            # job's — a credential does not stop being one for being declared
            # one level up.
            fields = [
                *fields,
                *_build_group_field_defs(
                    self, job_name, _preflight_resolution.group_values
                ),
            ]

            summary_lines = build_preflight_lines(
                fields, provided, avail_width, resolved_sources=resolved_sources
            )
            if self._smart_bar.readiness == BarReadiness.READY:
                summary_lines.append(
                    "[dim]Ctrl+Enter run  ·  Ctrl+S save as shortcut[/dim]"
                )
            for line in summary_lines:
                log.write(line)

        except Exception as exc:
            # Guards a multi-step render (field lookup, formatting, and a
            # RichLog write loop), not a single query_one lookup — log so
            # a formatting bug is visible instead of a silently blank
            # pre-flight summary.
            self.log.warning(
                f"_render_preflight_summary: failed to render summary "
                f"({type(exc).__name__}): {exc}"
            )

    def _build_command_panels(self) -> list[tuple[str, Any]]:
        """Build command panels based on current job's field definitions.

        Looks at the SmartBar value to identify the recognized job, then
        converts its FieldDescriptors into FieldDef instances and populates
        a ConfigTablePanel. Returns a list of (title, widget) tuples suitable
        for PanelHost.set_panels().

        Returns an empty list if no job is recognized or the job has no fields.
        """
        return build_command_panels(self)

    def _build_general_panels(self) -> list[tuple[str, Any]]:
        """Build general panels (always available, not job-specific).

        Returns panels for: Job Browser (list of all discovered jobs + builtins)
        and Settings.
        """
        return build_general_panels(self)

    def _update_display_footer(self, active_zone: FocusZone) -> None:
        """Update the display footer with focus-aware hints (R7-AC1, R7-AC2).

        When DISPLAY zone has focus: shows nav actions (prev/next if multiple, else just Esc unfocus).
        When DISPLAY zone does NOT have focus: shows how to get focus.
        """
        if not self._display_slot.has_visible_displays:
            return
        try:
            ft = self.query_one("#display-footer", Static)
            if active_zone is FocusZone.DISPLAY:
                actions: list[tuple[str, str]] = []
                widget = self._display_slot.current_interactive_widget
                getter: Any = getattr(widget, "get_available_actions", None)
                if callable(getter):
                    try:
                        raw_actions: Any = getter(True)
                        actions = list(raw_actions)
                    except Exception as exc:
                        # Same fallback contract as PanelHost._get_panel_actions:
                        # one widget's buggy hints must not crash the footer.
                        self.log.warning(
                            f"_update_display_footer: {type(widget).__name__}"
                            f".get_available_actions() raised "
                            f"({type(exc).__name__}): {exc}"
                        )
                if self._display_slot.view_depth > 0:
                    actions.append(("Esc", "back"))
                n = self._display_slot.visible_count
                if n > 1 and self._display_slot.view_depth == 0:
                    actions.append(("Ctrl+U/O", "cycle"))
                actions.append(("Shift+Tab", "cycle zone"))
                ft.update(" " + "  ".join(f"{key} {label}" for key, label in actions))
            else:
                ft.update(" Shift+Tab focus display  Ctrl+U/O cycle")
        except NoMatches:
            pass

    def _update_status_bar(self, mode: FocusMode, zone: FocusZone) -> None:
        """Update the status bar with mode + zone + readiness (R8-AC1, R8-AC3).

        Format: {MODE}  {Zone}  {readiness_indicator}
        No panel action hints here (R8-AC2).
        """
        try:
            status_bar = self.query_one("#status-bar", Static)
            mode_str = _MODE_STYLES.get(mode, "")
            zone_str = _ZONE_NAMES.get(zone, "")
            readiness_str = self._readiness_indicator()
            base = f" {mode_str}  {zone_str}  {readiness_str}"
            env_str = self._environment_indicator()
            if env_str:
                base = f"{base}  {env_str}"
            plugin_text = render_status_items(self._plugin_instances(), self._func_app)
            status_bar.update(f"{base}  {plugin_text}" if plugin_text else base)
        except NoMatches:
            pass

    def _environment_indicator(self) -> str:
        """Render the active environment, and whether anything selected it.

        The environment decides which ``config.<env>.*`` overlay loads, so it
        belongs on the always-visible line. Dim means "defaulted, nothing set
        it" — which is the usual reason an overlay file a user is staring at
        isn't taking effect, so it must be distinguishable at a glance from
        an explicit choice.
        """
        try:
            name = self._func_app.active_environment()
            source = self._func_app.environment_source()
        except AttributeError:
            return ""
        if source is EnvironmentSource.DEFAULT:
            return f"[dim]ENV:{name}[/dim]"
        return f"[bold]ENV:{name}[/bold]"

    def _readiness_indicator(self) -> str:
        """Return a colored readiness string for the status bar (R8-AC6).

        Returns:
            '● Ready' (bold green) when READY,
            '◐ Pending' (bold yellow) when PENDING,
            empty string for GREY/other states.
        """
        readiness = self._smart_bar.readiness
        if readiness == BarReadiness.READY:
            return "[bold green]● Ready[/bold green]"
        if readiness == BarReadiness.PENDING:
            return "[bold yellow]◐ Pending[/bold yellow]"
        return ""

    def _create_completer(self) -> Any:
        """Create the SmartBarAutoComplete completer instance."""
        from functualize._cli.completions.provenance import (
            CompletionProvenanceClassifier,
        )
        from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete

        provenance = CompletionProvenanceClassifier(self._func_app)
        return SmartBarAutoComplete(app=self._func_app, provenance=provenance)

    def _build_pending_execution(self, job_name: str) -> PendingExecution:
        """Construct a PendingExecution from a job's field descriptors.

        Queries the kernel's ResolutionChain to get real resolved values with
        accurate source_type (cli, env, file, default). Falls back to field
        defaults when the resolution chain is unavailable or raises.

        Args:
            job_name: The recognized job name.

        Returns:
            A new PendingExecution instance populated with resolved values.
        """
        return build_pending_execution(self, job_name)

    def _refresh_all_views(self) -> None:
        """Refresh all config views from the current PendingExecution state.

        Updates: pre-flight summary, active panel (if it has a refresh method),
        and syncs SmartBar text from PendingExecution overrides.
        """
        # 1. Update pre-flight summary
        self._update_preflight_summary()

        # 2. Refresh active panel if it has a refresh method
        panel = self.active_panel
        if panel is not None and hasattr(panel, "refresh"):
            try:
                panel.refresh()
            except Exception as exc:
                # panel.refresh() is an arbitrary per-panel override, not a
                # query_one lookup — log so a broken panel refresh is
                # visible instead of a silently stale view.
                self.log.warning(
                    f"_refresh_all_views: {type(panel).__name__}.refresh() "
                    f"raised ({type(exc).__name__}): {exc}"
                )

        # 3. Sync SmartBar text from PendingExecution
        if self._pending is not None:
            self._sync_smartbar_from_pending()

    def _rebuild_if_stale(self) -> None:
        """Rebuild command panels if marked stale (e.g., after loading a snapshot).

        Preserves the current panel index so the user stays on the same
        panel position after rebuild.
        """
        if not getattr(self, "_command_panels_stale", False):
            return
        if self._active_ring != "command":
            return
        self._command_panels_stale = False
        current_idx = self._panel_host.current_index
        self._command_panels = self._build_command_panels()
        if self._command_panels:
            self._panel_host.set_panels(self._command_panels)
            # Restore panel index (will be adjusted by navigate_next/prev after)
            self._panel_host.current_index = min(
                current_idx, len(self._command_panels) - 1
            )
            self._panel_host._show_current_panel()

    def _refresh_diff_view_if_active(self) -> None:
        """Refresh DiffView with current state if it's the active panel (R3-AC2)."""
        panel = self.active_panel
        if not isinstance(panel, DiffViewWidget):
            return
        if self._pending is None:
            return
        previous = self._snapshot_store.get_last_snapshot(self._pending.job_name)
        history = self._snapshot_store.get_snapshots(self._pending.job_name)
        try:
            panel.show_diff(self._pending, previous, history)
        except Exception as exc:
            # show_diff() builds diff/history render data internally and
            # already guards its own query_one lookups — this outer catch
            # is not query-related, so log rather than swallow silently.
            self.log.warning(
                f"_refresh_diff_view_if_active: panel.show_diff() failed "
                f"({type(exc).__name__}): {exc}"
            )

    def _sync_smartbar_from_pending(self) -> None:
        """Sync SmartBar text to reflect current PendingExecution overrides.

        Rebuilds the SmartBar value as: job_name --flag1 val1 --flag2 val2 ...
        based on the PendingExecution's effective values.
        """
        if self._pending is None:
            return

        job_name = self._pending.job_name
        descriptor = self._find_job_descriptor(job_name)
        if descriptor is None:
            return

        field_descriptors = get_descriptor_fields(descriptor)
        if not field_descriptors:
            self._smart_bar.value = build_command_line(
                job_name, [], self._pending.group_option_values, self._group_trie
            )
            return

        self._smart_bar.value = sync_pending_overrides_to_bar(
            field_descriptors, self._pending, self._group_trie
        )

    def _update_preflight_summary(self) -> None:
        """Show/hide the pre-flight summary based on readiness and panel state."""
        try:
            summary = self.query_one("#preflight-summary", RichLog)
            should_show = (
                self._smart_bar.readiness in (BarReadiness.PENDING, BarReadiness.READY)
                and not self._panel_host.is_active
            )
            if should_show:
                summary.display = True
                self._render_preflight_summary(summary)
            else:
                summary.display = False
                summary.clear()
        except NoMatches:
            pass

    def _render_tree_preflight(self, log: RichLog, tokens: list[str]) -> bool:
        """Render the pre-flight summary for any non-job node in the command tree.

        Replaces the builtin-specific renderer: it resolves ``tokens`` in the one
        tree rather than drilling a hardcoded two-level builtin structure, so it
        works at **any** depth and for any provider's nodes. Returns False when
        the path names nothing, letting the caller fall through to its usual
        unknown-command handling.
        """
        try:
            from functualize.app.commands import (
                build_command_tree,
                resolve_command_path,
            )

            node, remaining = resolve_command_path(
                build_command_tree(self._func_app), tokens
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.log.warning(f"_render_tree_preflight failed: {exc}")
            return False

        if node is None:
            return False

        children = node.children()
        matched = tokens[: len(tokens) - len(remaining)]
        path = " ".join(matched)

        # A leftover token that is not a flag is a name that does not exist
        # here. Say so — silently listing the parent's subcommands instead
        # reads as if the typed command were fine.
        unknown = next((t for t in remaining if not t.startswith("-")), None)
        if unknown is not None and children:
            log.write(f"[bold]{path} {unknown}[/bold] — [red]unknown subcommand[/red]")
            log.write(
                f"[dim]Expected one of: {', '.join(c.name for c in children)}[/dim]"
            )
            return True

        log.write(f"[bold]{path}[/bold] — {node.help_text}")
        if children:
            log.write("[dim]Subcommands:[/dim]")
            for child in children:
                log.write(f"  [cyan]{child.name}[/cyan]  [dim]{child.help_text}[/dim]")
        elif node.needs_terminal:
            log.write("[dim]Takes over the terminal while it runs.[/dim]")
        return True

    def _get_visible_zones(self) -> set[FocusZone]:
        """Return the set of currently visible zones for zone cycling."""
        zones: set[FocusZone] = {FocusZone.SMARTBAR}
        if self._display_slot.has_visible_displays:
            zones.add(FocusZone.DISPLAY)
        if self._panel_host.is_active:
            zones.add(FocusZone.PANEL)
        return zones

    def _get_zone_widget(self, zone: FocusZone) -> Widget | None:
        """Map a zone to its primary focusable widget."""
        if zone is FocusZone.SMARTBAR:
            return self._smart_bar
        if zone is FocusZone.DISPLAY:
            # An interactive display's widget takes focus directly (the
            # PanelHost idiom); a legacy non-interactive display falls back
            # to the focusable chrome container.
            widget = self._display_slot.current_interactive_widget
            if widget is not None:
                return widget
            try:
                return self.query_one("#display-section")
            except NoMatches:
                return None
        # PANEL uses set_focus(None) — no widget to focus directly
        return None

    def _update_panel_filter_indicator(self, filter_text: str) -> None:
        """Update the panel host breadcrumb to show the active filter.

        Shows 'filter: <text>' suffix on the breadcrumb when a filter
        is active. Clears it when filter_text is empty.
        """
        if not self._panel_host.is_active:
            return
        try:
            from functualize._cli.tui.breadcrumb_header_widget import BreadcrumbHeader

            bc = self._panel_host.query_one(BreadcrumbHeader)
            # Get the base title from the current panel
            title = self._panel_host.current_title
            if filter_text:
                bc.update(f"{title}  [dim italic]/{filter_text}[/dim italic]")
            else:
                bc.update(title)
        except NoMatches:
            pass
