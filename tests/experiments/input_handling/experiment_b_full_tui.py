"""Experiment B Full TUI: Complete panel architecture with Option B editing.

Demonstrates the full TUI architecture from tui-architecture-v2.md:
- Three panel types: Display (above), Pre-flight (Ctrl+R), General (Ctrl+E)
- Ring navigation within panels (Ctrl+H/J/K/L)
- Breadcrumb headers ([R:1/3] Config Table)
- Dynamic contextual footers (change based on focus zone)
- Focus zones: SmartBar → Display → Panel Slot (Shift+Tab cycles)
- Mode indicator: COMMAND / NORMAL / INSERT
- Esc layered: pop breadcrumb → collapse → return to SmartBar
- Option B editing: repurpose SmartBar for INSERT mode with autocomplete

Layout:
    ┌─ Display Panels (Ctrl+U/I) ──────────────────────────────┐
    │ [D:1/2] Docker Services                                   │
    ├─ Header ──────────────────────────────────────────────────┤
    │ func — experiment (3 jobs)                                │
    ├─ SmartBar + AutoComplete ─────────────────────────────────┤
    │ > deploy --region us-east-1                               │
    ├─ Panel Slot (Ctrl+R pre-flight / Ctrl+E general) ────────┤
    │ [R:1/2] Config Table                                      │
    │  region      us-east-1    config.toml                     │
    │ ▸ replicas   3            default                         │
    │  j/k navigate  i edit  Esc back  Ctrl+J/K switch          │
    ├─ Status Bar ──────────────────────────────────────────────┤
    │ -- NORMAL --  Shift+Tab cycle  Ctrl+Q exit                │
    └───────────────────────────────────────────────────────────┘

Run:
    uv run python -m experiments.input_handling.experiment_b_full_tui
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import App, ComposeResult, SystemCommand
from textual.command import Hit, Hits, Provider
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class PanelDef:
    """Definition of a panel in a ring."""

    id: str
    title: str
    rows: list[tuple[str, list[str]]]  # (row_key, [col_values...])
    columns: list[str] = field(default_factory=lambda: ["Setting", "Value", "Source"])


# ─── Panel Ring State ─────────────────────────────────────────────────────────


class PanelRing:
    """Manages a ring of panels with navigation."""

    def __init__(self, type_prefix: str, panels: list[PanelDef]) -> None:
        self.type_prefix = type_prefix
        self.panels = panels
        self.index = 0

    @property
    def current(self) -> PanelDef | None:
        if not self.panels:
            return None
        return self.panels[self.index]

    @property
    def breadcrumb(self) -> str:
        if not self.panels:
            return ""
        p = self.panels[self.index]
        return f"[{self.type_prefix}:{self.index + 1}/{len(self.panels)}] {p.title}"

    def next(self) -> None:
        if self.panels:
            self.index = (self.index + 1) % len(self.panels)

    def prev(self) -> None:
        if self.panels:
            self.index = (self.index - 1) % len(self.panels)

    def first(self) -> None:
        self.index = 0

    def last(self) -> None:
        if self.panels:
            self.index = len(self.panels) - 1


# ─── Focus Zones ─────────────────────────────────────────────────────────────


class FocusZone:
    SMARTBAR = "smartbar"
    DISPLAY = "display"
    PANEL = "panel"

    # Cycle order (skip hidden zones)
    _CYCLE = [SMARTBAR, DISPLAY, PANEL]

    @classmethod
    def next_zone(cls, current: str, visible: set[str]) -> str:
        """Get next zone in cycle, skipping hidden ones."""
        idx = cls._CYCLE.index(current)
        for i in range(1, len(cls._CYCLE) + 1):
            candidate = cls._CYCLE[(idx + i) % len(cls._CYCLE)]
            if candidate in visible:
                return candidate
        return current


# ─── Command Palette Provider ─────────────────────────────────────────────────


class ContextualCommandProvider(Provider):
    """Context-aware command palette provider.

    Yields different commands based on the current mode and zone. This makes
    the command palette a discoverability tool — users who don't remember the
    keybind can search for actions by name.

    Static commands (always available):
    - Open pre-flight panels, Open general panels
    - Focus display, Focus SmartBar
    - Cycle zones

    Context commands (only when applicable):
    - NORMAL + PANEL: Edit field, Drill into detail, Next/Prev panel
    - INSERT: Confirm edit, Cancel edit
    - DISPLAY: Next/Prev display
    """

    async def search(self, query: str) -> Hits:
        """Yield commands matching the query, filtered by current context."""
        app = self.app
        assert isinstance(app, FullTuiApp)

        matcher = self.matcher(query)

        # ─── Always-available commands ────────────────────────────────
        always_commands = [
            ("Open Pre-flight Panels", "Ctrl+R: Show config table and diff view",
             app._cmd_open_preflight),
            ("Open General Panels", "Ctrl+E: Show job browser, history, settings",
             app._cmd_open_general),
            ("Focus Display Zone", "Ctrl+U: Focus the display panels above",
             app._cmd_focus_display),
            ("Focus SmartBar", "Esc: Return focus to the command input",
             app._cmd_focus_smartbar),
            ("Cycle Focus Zone", "Shift+Tab: Move between SmartBar, Display, Panel",
             app._cmd_cycle_zone),
            ("Collapse Panel", "Close the active panel slot",
             app._cmd_collapse_panel),
        ]

        for title, help_text, callback in always_commands:
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), callback, help=help_text)

        # ─── Panel navigation (when a panel ring is active) ───────────
        if app._active_ring and len(app._active_ring.panels) > 1:
            panel_commands = [
                ("Next Panel in Ring", "Ctrl+J: Switch to next panel",
                 app._cmd_ring_next),
                ("Previous Panel in Ring", "Ctrl+K: Switch to previous panel",
                 app._cmd_ring_prev),
                ("First Panel in Ring", "Ctrl+H: Jump to first panel",
                 app._cmd_ring_first),
                ("Last Panel in Ring", "Ctrl+L: Jump to last panel",
                 app._cmd_ring_last),
            ]
            # Add direct panel jump commands
            for i, panel in enumerate(app._active_ring.panels):
                panel_commands.append((
                    f"Go to Panel: {panel.title}",
                    f"Jump to {app._active_ring.type_prefix}:{i+1}/{len(app._active_ring.panels)}",
                    lambda idx=i: app._cmd_ring_goto(idx),
                ))

            for title, help_text, callback in panel_commands:
                score = matcher.match(title)
                if score > 0:
                    yield Hit(score, matcher.highlight(title), callback, help=help_text)

        # ─── NORMAL mode panel actions ────────────────────────────────
        if app._mode == "normal" and app._zone == FocusZone.PANEL:
            normal_commands = [
                ("Edit Current Field", "i/e: Enter INSERT mode to edit the selected row",
                 app._cmd_enter_insert),
                ("Drill Into Detail", "Enter: Show detail view for the selected row",
                 app._cmd_drill_down),
            ]
            for title, help_text, callback in normal_commands:
                score = matcher.match(title)
                if score > 0:
                    yield Hit(score, matcher.highlight(title), callback, help=help_text)

        # ─── Display navigation ───────────────────────────────────────
        if app.query_one("#display-section").has_class("visible"):
            display_commands = [
                ("Previous Display", "Ctrl+U: Show previous display panel",
                 app._cmd_display_prev),
                ("Next Display", "Ctrl+I: Show next display panel",
                 app._cmd_display_next),
            ]
            for title, help_text, callback in display_commands:
                score = matcher.match(title)
                if score > 0:
                    yield Hit(score, matcher.highlight(title), callback, help=help_text)


# ─── Main App ────────────────────────────────────────────────────────────────


class FullTuiApp(App[None]):
    """Full TUI architecture experiment with Option B editing."""

    COMMANDS = App.COMMANDS | {ContextualCommandProvider}

    CSS = """
    Screen { height: auto; }
    #display-section { display: none; height: auto; max-height: 5; }
    #display-section.visible { display: block; }
    #display-breadcrumb { height: 1; background: $primary-darken-2; color: $text; padding: 0 1; }
    #display-content { height: auto; min-height: 1; max-height: 3; padding: 0 1; }
    #display-footer { height: 1; color: $text-muted; padding: 0 1; }
    #header { height: 1; background: $primary; color: $text; text-style: bold; padding: 0 1; }
    #smart-bar { width: 100%; }
    #smart-bar.editing { border: tall green; }
    #smart-bar.invalid { border: tall red; }
    #panel-section { display: none; height: auto; max-height: 12; }
    #panel-section.visible { display: block; }
    #panel-breadcrumb { height: 1; background: $surface; color: $text; text-style: bold; padding: 0 1; }
    #panel-content { height: auto; min-height: 2; max-height: 8; }
    #panel-footer { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    #status-bar { height: 1; background: $surface-darken-1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+p", "command_palette", "Commands")]

    def __init__(self) -> None:
        super().__init__()
        # Mode: command | normal | insert
        self._mode = "command"
        # Focus zone
        self._zone = FocusZone.SMARTBAR
        # Panel rings
        self._display_ring = PanelRing("D", [
            PanelDef("docker", "Docker Services", [
                ("web", ["web", "running", "8080:80"]),
                ("db", ["postgres", "running", "5432:5432"]),
                ("redis", ["redis", "running", "6379:6379"]),
            ], columns=["Service", "Status", "Ports"]),
            PanelDef("git", "Git Status", [
                ("branch", ["branch", "main", ""]),
                ("modified", ["modified", "3 files", ""]),
                ("staged", ["staged", "1 file", ""]),
            ], columns=["Item", "Value", "Detail"]),
        ])
        self._preflight_ring = PanelRing("R", [
            PanelDef("config", "Config Table", [
                ("region", ["region", "us-east-1", "config.toml"]),
                ("replicas", ["replicas", "3", "default"]),
                ("timeout", ["timeout", "30", "env"]),
                ("verbose", ["verbose", "false", "default"]),
            ]),
            PanelDef("diff", "Diff View", [
                ("region", ["region", "us-west-2 → us-east-1", "changed"]),
                ("replicas", ["replicas", "5 → 3", "changed"]),
            ], columns=["Field", "Change", "Status"]),
        ])
        self._general_ring = PanelRing("E", [
            PanelDef("jobs", "Job Browser", [
                ("deploy", ["deploy", "Deploy to environment", "job"]),
                ("test", ["test", "Run test suite", "job"]),
                ("build", ["build", "Build artifacts", "job"]),
            ], columns=["Name", "Description", "Kind"]),
            PanelDef("history", "History", [
                ("run1", ["deploy", "success", "2 min ago"]),
                ("run2", ["test", "failed", "5 min ago"]),
                ("run3", ["build", "success", "10 min ago"]),
            ], columns=["Job", "Result", "When"]),
            PanelDef("shortcuts", "Shortcuts", [
                ("s1", ["deploy-prod", "deploy --region us-east-1", "Ctrl+1"]),
                ("s2", ["quick-test", "test --fast", "Ctrl+2"]),
            ], columns=["Name", "Command", "Key"]),
            PanelDef("settings", "Settings", [
                ("theme", ["theme", "transparent", "default"]),
                ("history_ret", ["history_retention", "50", "config.toml"]),
            ]),
        ])
        # Active panel ring (None = collapsed)
        self._active_ring: PanelRing | None = None
        # Edit state (Option B)
        self._edit_row_key: str | None = None
        self._edit_field_name: str | None = None
        self._saved_bar_text: str = ""
        self._saved_bar_cursor: int = 0
        self._saved_bar_placeholder: str = ""
        # Breadcrumb sub-levels
        self._sub_breadcrumbs: list[str] = []

    # ─── Compose ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Display section (above header)
        with Vertical(id="display-section"):
            yield Static("", id="display-breadcrumb")
            yield Static("", id="display-content")
            yield Static("", id="display-footer")
        # Header
        yield Static(" func — experiment (3 jobs, 2 builtins)", id="header")
        # SmartBar
        yield Input(placeholder="Type a command...", id="smart-bar")
        # Panel section (pre-flight or general)
        with Vertical(id="panel-section"):
            yield Static("", id="panel-breadcrumb")
            yield DataTable(id="panel-table", cursor_type="row")
            yield Static("", id="panel-footer")
        # Status bar
        yield Static("", id="status-bar", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()
        table = self.query_one("#panel-table", DataTable)
        table.can_focus = False
        # Show display panels on startup (simulating providers detected)
        self._show_display()
        self._update_all_chrome()

    # ─── Key Handler ──────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        # If the command palette (or any pushed screen) is active, don't intercept
        from textual.command import CommandPalette

        if any(isinstance(s, CommandPalette) for s in self.screen_stack[1:]):
            return

        # Global keys (work in any mode/zone)
        if event.key == "ctrl+r":
            event.prevent_default()
            event.stop()
            self._toggle_ring(self._preflight_ring)
            return
        elif event.key == "ctrl+e":
            event.prevent_default()
            event.stop()
            self._toggle_ring(self._general_ring)
            return
        elif event.key == "ctrl+u":
            event.prevent_default()
            event.stop()
            self._display_action("prev")
            return
        elif event.key == "ctrl+i" and self._zone == FocusZone.DISPLAY:
            event.prevent_default()
            event.stop()
            self._display_action("next")
            return
        elif event.key == "shift+tab":
            event.prevent_default()
            event.stop()
            self._cycle_zone()
            return

        # Mode-specific keys
        if self._mode == "command":
            pass  # All other keys go to SmartBar (it has focus)

        elif self._mode == "normal":
            if self._zone == FocusZone.DISPLAY:
                # Display zone: Esc returns to SmartBar, j/k do nothing here
                if event.key == "escape":
                    event.prevent_default()
                    event.stop()
                    self._focus_zone(FocusZone.SMARTBAR)
                elif event.key == "ctrl+j":
                    event.prevent_default()
                    event.stop()
                    self._ring_navigate("next")
                elif event.key == "ctrl+k":
                    event.prevent_default()
                    event.stop()
                    self._ring_navigate("prev")
                else:
                    if len(event.key) == 1 and event.key.isprintable():
                        event.prevent_default()
                        event.stop()
            elif self._zone == FocusZone.PANEL:
                # Panel zone: j/k navigate, i edit, Enter drill, Esc layered
                if event.key == "j":
                    event.prevent_default()
                    event.stop()
                    self._panel_cursor_down()
                elif event.key == "k":
                    event.prevent_default()
                    event.stop()
                    self._panel_cursor_up()
                elif event.key == "i" or event.key == "e":
                    event.prevent_default()
                    event.stop()
                    self._enter_insert()
                elif event.key == "enter":
                    event.prevent_default()
                    event.stop()
                    self._drill_down()
                elif event.key == "escape":
                    event.prevent_default()
                    event.stop()
                    self._handle_escape()
                elif event.key == "ctrl+j":
                    event.prevent_default()
                    event.stop()
                    self._ring_navigate("next")
                elif event.key == "ctrl+k":
                    event.prevent_default()
                    event.stop()
                    self._ring_navigate("prev")
                elif event.key == "ctrl+h":
                    event.prevent_default()
                    event.stop()
                    self._ring_navigate("first")
                elif event.key == "ctrl+l":
                    event.prevent_default()
                    event.stop()
                    self._ring_navigate("last")
                else:
                    if len(event.key) == 1 and event.key.isprintable():
                        event.prevent_default()
                        event.stop()

        elif self._mode == "insert":
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._cancel_edit()
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._confirm_edit()
            # Other keys pass to SmartBar (it has focus in INSERT mode)

    # ─── Zone Cycling ─────────────────────────────────────────────────────

    def _cycle_zone(self) -> None:
        """Shift+Tab: cycle through visible zones."""
        visible = {FocusZone.SMARTBAR}
        if self.query_one("#display-section").has_class("visible"):
            visible.add(FocusZone.DISPLAY)
        if self.query_one("#panel-section").has_class("visible"):
            visible.add(FocusZone.PANEL)

        new_zone = FocusZone.next_zone(self._zone, visible)
        self._focus_zone(new_zone)

    def _focus_zone(self, zone: str) -> None:
        """Switch focus to a zone."""
        self._zone = zone
        if zone == FocusZone.SMARTBAR:
            self._mode = "command"
            self.query_one("#smart-bar", Input).focus()
        elif zone == FocusZone.DISPLAY:
            self._mode = "normal"
            self.set_focus(None)
        elif zone == FocusZone.PANEL:
            if self._active_ring:
                self._mode = "normal"
                self.set_focus(None)
            else:
                # No panel active, skip to SmartBar
                self._zone = FocusZone.SMARTBAR
                self._mode = "command"
                self.query_one("#smart-bar", Input).focus()
        self._update_all_chrome()

    # ─── Panel Ring Toggle ────────────────────────────────────────────────

    def _toggle_ring(self, ring: PanelRing) -> None:
        """Toggle a panel ring on/off. If different ring active, switch."""
        if self._active_ring is ring and self._zone == FocusZone.PANEL:
            # Already active and focused → collapse
            self._active_ring = None
            self.query_one("#panel-section").remove_class("visible")
            self._zone = FocusZone.SMARTBAR
            self._mode = "command"
            self.query_one("#smart-bar", Input).focus()
        else:
            # Activate this ring
            self._active_ring = ring
            self._sub_breadcrumbs = []
            self._load_panel_content()
            self.query_one("#panel-section").add_class("visible")
            self._zone = FocusZone.PANEL
            self._mode = "normal"
            self.set_focus(None)
        self._update_all_chrome()

    def _load_panel_content(self) -> None:
        """Load the current panel's data into the DataTable."""
        if not self._active_ring or not self._active_ring.current:
            return
        panel = self._active_ring.current
        table = self.query_one("#panel-table", DataTable)
        table.clear(columns=True)
        for col in panel.columns:
            table.add_column(col, key=col.lower())
        for row_key, cells in panel.rows:
            table.add_row(*cells, key=row_key)

    # ─── Ring Navigation (Ctrl+H/J/K/L) ──────────────────────────────────

    def _ring_navigate(self, direction: str) -> None:
        """Navigate within the active panel ring."""
        if not self._active_ring:
            return
        if direction == "next":
            self._active_ring.next()
        elif direction == "prev":
            self._active_ring.prev()
        elif direction == "first":
            self._active_ring.first()
        elif direction == "last":
            self._active_ring.last()
        self._sub_breadcrumbs = []
        self._load_panel_content()
        self._update_all_chrome()

    # ─── Display Panel ────────────────────────────────────────────────────

    def _show_display(self) -> None:
        """Show the display section."""
        self.query_one("#display-section").add_class("visible")
        self._update_display_content()

    def _display_action(self, action: str) -> None:
        """Ctrl+U/I: navigate display or focus it."""
        if self._zone != FocusZone.DISPLAY:
            # First press → focus the display zone
            self._focus_zone(FocusZone.DISPLAY)
        else:
            # Already focused → navigate
            if action == "prev":
                self._display_ring.prev()
            else:
                self._display_ring.next()
        self._update_display_content()
        self._update_all_chrome()

    def _update_display_content(self) -> None:
        """Render the current display panel."""
        panel = self._display_ring.current
        if not panel:
            return
        breadcrumb = self.query_one("#display-breadcrumb", Static)
        # Show ▸ indicator when display zone is focused
        indicator = "▸ " if self._zone == FocusZone.DISPLAY else "  "
        breadcrumb.update(f"{indicator}{self._display_ring.breadcrumb}")
        # Render content as simple text (real impl would use widgets)
        lines = []
        for _, cells in panel.rows:
            lines.append("  ".join(f"{c:<12}" for c in cells))
        self.query_one("#display-content", Static).update("\n".join(lines))

    # ─── Panel Cursor Navigation ─────────────────────────────────────────

    def _panel_cursor_down(self) -> None:
        table = self.query_one("#panel-table", DataTable)
        if table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1)

    def _panel_cursor_up(self) -> None:
        table = self.query_one("#panel-table", DataTable)
        if table.cursor_row > 0:
            table.move_cursor(row=table.cursor_row - 1)

    # ─── Drill Down (Enter in NORMAL) ────────────────────────────────────

    def _drill_down(self) -> None:
        """Enter key: drill into a sub-panel (breadcrumb push)."""
        if not self._active_ring or not self._active_ring.current:
            return
        table = self.query_one("#panel-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0:
            return
        panel = self._active_ring.current
        if row_idx < len(panel.rows):
            row_key = panel.rows[row_idx][0]
            self._sub_breadcrumbs.append(f"Detail: {row_key}")
            self._update_all_chrome()

    # ─── Escape Handling (layered) ────────────────────────────────────────

    def _handle_escape(self) -> None:
        """Esc: pop breadcrumb → collapse panel → return to SmartBar."""
        if self._sub_breadcrumbs:
            # Pop one breadcrumb level
            self._sub_breadcrumbs.pop()
            self._update_all_chrome()
        elif self._active_ring:
            # Collapse panel, return to SmartBar
            self._active_ring = None
            self.query_one("#panel-section").remove_class("visible")
            self._zone = FocusZone.SMARTBAR
            self._mode = "command"
            self.query_one("#smart-bar", Input).focus()
            self._update_all_chrome()

    # ─── INSERT Mode (Option B: repurpose SmartBar) ───────────────────────

    def _enter_insert(self) -> None:
        """i/e in NORMAL: repurpose SmartBar for editing."""
        if not self._active_ring or not self._active_ring.current:
            return
        table = self.query_one("#panel-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0:
            return
        panel = self._active_ring.current
        if row_idx >= len(panel.rows):
            return

        row_key, cells = panel.rows[row_idx]
        self._edit_row_key = row_key
        self._edit_field_name = cells[0]
        current_value = cells[1] if len(cells) > 1 else ""

        # Save SmartBar state
        bar = self.query_one("#smart-bar", Input)
        self._saved_bar_text = bar.value
        self._saved_bar_cursor = bar.cursor_position
        self._saved_bar_placeholder = bar.placeholder

        # Repurpose SmartBar
        bar.value = current_value
        bar.placeholder = f"Edit: {self._edit_field_name}"
        bar.cursor_position = len(current_value)
        bar.add_class("editing")
        self.set_focus(bar)

        self._mode = "insert"
        self._update_all_chrome()

    def _confirm_edit(self) -> None:
        """Enter in INSERT: apply value, return to NORMAL."""
        bar = self.query_one("#smart-bar", Input)
        new_value = bar.value.strip()

        if new_value and self._edit_row_key and self._active_ring:
            panel = self._active_ring.current
            if panel:
                # Update in-memory data
                for i, (rk, cells) in enumerate(panel.rows):
                    if rk == self._edit_row_key:
                        cells[1] = new_value
                        break
                # Update DataTable display
                table = self.query_one("#panel-table", DataTable)
                table.update_cell(self._edit_row_key, "value", new_value)
                self.notify(f"✓ {self._edit_field_name} = {new_value!r}")

        self._restore_smartbar()

    def _cancel_edit(self) -> None:
        """Esc in INSERT: discard, return to NORMAL."""
        self._restore_smartbar()

    def _restore_smartbar(self) -> None:
        """Restore SmartBar to pre-edit state, return to NORMAL."""
        self._mode = "normal"
        bar = self.query_one("#smart-bar", Input)
        bar.value = self._saved_bar_text
        bar.placeholder = self._saved_bar_placeholder
        bar.cursor_position = self._saved_bar_cursor
        bar.remove_class("editing")
        bar.remove_class("invalid")
        self._edit_row_key = None
        self._edit_field_name = None
        self.set_focus(None)
        self._update_all_chrome()

    # ─── Chrome Updates ───────────────────────────────────────────────────

    def _update_all_chrome(self) -> None:
        """Update breadcrumbs, footers, and status bar."""
        self._update_panel_chrome()
        self._update_display_chrome()
        self._update_status_bar()

    def _update_display_chrome(self) -> None:
        """Update display breadcrumb indicator and footer."""
        # Refresh breadcrumb with focus indicator
        if self.query_one("#display-section").has_class("visible"):
            self._update_display_content()
        self._update_display_footer()

    def _update_panel_chrome(self) -> None:
        """Update panel breadcrumb and footer."""
        breadcrumb = self.query_one("#panel-breadcrumb", Static)
        footer = self.query_one("#panel-footer", Static)

        if not self._active_ring or not self._active_ring.current:
            breadcrumb.update("")
            footer.update("")
            return

        # Breadcrumb
        indicator = "▸ " if self._zone == FocusZone.PANEL else "  "
        bc = self._active_ring.breadcrumb
        if self._sub_breadcrumbs:
            bc += " > " + " > ".join(self._sub_breadcrumbs)
        breadcrumb.update(f"{indicator}{bc}")

        # Footer (context-sensitive)
        if self._zone == FocusZone.PANEL:
            if self._mode == "insert":
                actions = "Enter confirm  Esc cancel"
            elif self._mode == "normal":
                actions_parts = ["j/k navigate"]
                actions_parts.append("i edit")
                actions_parts.append("Enter detail")
                if len(self._active_ring.panels) > 1:
                    actions_parts.append("Ctrl+J/K switch")
                actions_parts.append("Esc back")
                actions = "  ".join(actions_parts)
            else:
                actions = ""
        else:
            # Panel not focused — show how to get there
            key = "Ctrl+R" if self._active_ring is self._preflight_ring else "Ctrl+E"
            actions = f"{key} focus  Shift+Tab cycle"
        footer.update(f" {actions}")

    def _update_display_footer(self) -> None:
        """Update display panel footer."""
        footer = self.query_one("#display-footer", Static)
        if self._zone == FocusZone.DISPLAY:
            n = len(self._display_ring.panels)
            actions = "Ctrl+U prev  Ctrl+I next  Esc unfocus" if n > 1 else "Esc unfocus"
            footer.update(f" {actions}")
        else:
            footer.update(" Ctrl+U/I display  Shift+Tab cycle")

    def _update_status_bar(self) -> None:
        """Update the status bar with mode + zone + global hints."""
        parts: list[str] = []

        # Mode indicator
        if self._mode == "normal":
            parts.append("[bold cyan]-- NORMAL --[/bold cyan]")
        elif self._mode == "insert":
            parts.append("[bold green]-- INSERT --[/bold green]")
        else:
            parts.append("[dim]-- COMMAND --[/dim]")

        # Zone indicator
        zone_labels = {
            FocusZone.SMARTBAR: "SmartBar",
            FocusZone.DISPLAY: "Display",
            FocusZone.PANEL: "Panel",
        }
        parts.append(f"[dim]zone:[/dim] {zone_labels.get(self._zone, '?')}")

        # Global hints
        parts.append("[dim]Shift+Tab[/dim] cycle  [dim]Ctrl+Q[/dim] exit")

        self.query_one("#status-bar", Static).update(f" {'  '.join(parts)}")

    # ─── Command Palette Callbacks ────────────────────────────────────────
    # These are invoked by the ContextualCommandProvider when the user
    # selects a command from the palette (Ctrl+P). They mirror the keybind
    # actions, providing an alternative entry point for discoverability.
    #
    # IMPORTANT: The command palette pushes a modal screen. Our callbacks
    # run while that screen is still dismissing. We use call_after_refresh
    # to defer the actual state change until the palette is fully gone.

    def _cmd_open_preflight(self) -> None:
        """Command: Open Pre-flight Panels."""
        self.call_after_refresh(self._toggle_ring, self._preflight_ring)

    def _cmd_open_general(self) -> None:
        """Command: Open General Panels."""
        self.call_after_refresh(self._toggle_ring, self._general_ring)

    def _cmd_focus_display(self) -> None:
        """Command: Focus Display Zone."""
        self.call_after_refresh(self._display_action, "prev")

    def _cmd_focus_smartbar(self) -> None:
        """Command: Focus SmartBar."""
        self.call_after_refresh(self._focus_zone, FocusZone.SMARTBAR)

    def _cmd_cycle_zone(self) -> None:
        """Command: Cycle Focus Zone."""
        self.call_after_refresh(self._cycle_zone)

    def _cmd_collapse_panel(self) -> None:
        """Command: Collapse the active panel."""
        def _do() -> None:
            if self._active_ring:
                self._active_ring = None
                self.query_one("#panel-section").remove_class("visible")
                self._focus_zone(FocusZone.SMARTBAR)
        self.call_after_refresh(_do)

    def _cmd_ring_next(self) -> None:
        """Command: Next Panel in Ring."""
        self.call_after_refresh(self._ring_navigate, "next")

    def _cmd_ring_prev(self) -> None:
        """Command: Previous Panel in Ring."""
        self.call_after_refresh(self._ring_navigate, "prev")

    def _cmd_ring_first(self) -> None:
        """Command: First Panel in Ring."""
        self.call_after_refresh(self._ring_navigate, "first")

    def _cmd_ring_last(self) -> None:
        """Command: Last Panel in Ring."""
        self.call_after_refresh(self._ring_navigate, "last")

    def _cmd_ring_goto(self, index: int) -> None:
        """Command: Jump to a specific panel by index."""
        def _do() -> None:
            if self._active_ring and 0 <= index < len(self._active_ring.panels):
                self._active_ring.index = index
                self._sub_breadcrumbs = []
                self._load_panel_content()
                self._focus_zone(FocusZone.PANEL)
        self.call_after_refresh(_do)

    def _cmd_enter_insert(self) -> None:
        """Command: Edit Current Field."""
        def _do() -> None:
            if self._zone == FocusZone.PANEL and self._mode == "normal":
                self._enter_insert()
        self.call_after_refresh(_do)

    def _cmd_drill_down(self) -> None:
        """Command: Drill Into Detail."""
        def _do() -> None:
            if self._zone == FocusZone.PANEL and self._mode == "normal":
                self._drill_down()
        self.call_after_refresh(_do)

    def _cmd_display_prev(self) -> None:
        """Command: Previous Display."""
        def _do() -> None:
            self._display_ring.prev()
            self._update_display_content()
            self._update_all_chrome()
        self.call_after_refresh(_do)

    def _cmd_display_next(self) -> None:
        """Command: Next Display."""
        def _do() -> None:
            self._display_ring.next()
            self._update_display_content()
            self._update_all_chrome()
        self.call_after_refresh(_do)


if __name__ == "__main__":
    app = FullTuiApp()
    app.run(inline=True, inline_no_clear=True)
