"""Experiment B Full TUI v2: Bar readiness, target selector, autocomplete.

Extends experiment_b_full_tui with:
1. Bar readiness (grey→green) — recognizes job names, Ctrl+Enter executes
2. e/E target selector — e=session override, E=choose persistence target
3. Autocomplete integration — swappable completer for command/field modes

Known jobs: deploy, test, build
Type a job name → bar turns green → Ctrl+Enter "executes"
Ctrl+R opens pre-flight (only when job recognized)
e = quick edit (session), E = edit with target choice

Run:
    uv run python -m experiments.input_handling.experiment_b_full_tui_v2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.app import App, ComposeResult, SystemCommand
from textual.command import Hit, Hits, Provider
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

# Try importing textual-autocomplete
try:
    from textual_autocomplete import AutoComplete, DropdownItem
    from textual_autocomplete._autocomplete import TargetState

    HAS_AUTOCOMPLETE = True
except ImportError:
    HAS_AUTOCOMPLETE = False


# ─── Data Models ──────────────────────────────────────────────────────────────

# Simulated job registry
KNOWN_JOBS = {
    "deploy": {
        "description": "Deploy to environment",
        "fields": {
            "region": {"value": "us-east-1", "source": "config.toml",
                       "choices": ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]},
            "replicas": {"value": "3", "source": "default", "validator": "int"},
            "timeout": {"value": "30", "source": "env", "validator": "int"},
            "verbose": {"value": "false", "source": "default",
                        "choices": ["true", "false"]},
        },
    },
    "test": {
        "description": "Run test suite",
        "fields": {
            "suite": {"value": "unit", "source": "default",
                      "choices": ["unit", "integration", "e2e", "all"]},
            "parallel": {"value": "true", "source": "config.toml",
                         "choices": ["true", "false"]},
            "timeout": {"value": "60", "source": "default", "validator": "int"},
        },
    },
    "build": {
        "description": "Build artifacts",
        "fields": {
            "target": {"value": "release", "source": "default",
                       "choices": ["debug", "release", "profile"]},
            "output_dir": {"value": "./dist", "source": "default", "is_path": True},
        },
    },
}

PERSIST_TARGETS = [
    ("session", "This session only"),
    ("file", ".functualize.toml"),
    ("pyproject", "pyproject.toml [tool.functualize]"),
    ("user", "~/.config/functualize/config.toml"),
    ("env", "Environment variable"),
]


@dataclass
class PanelDef:
    """Definition of a panel in a ring."""
    id: str
    title: str
    rows: list[tuple[str, list[str]]]
    columns: list[str] = field(default_factory=lambda: ["Setting", "Value", "Source"])


class PanelRing:
    """Manages a ring of panels with navigation."""
    def __init__(self, type_prefix: str, panels: list[PanelDef]) -> None:
        self.type_prefix = type_prefix
        self.panels = panels
        self.index = 0

    @property
    def current(self) -> PanelDef | None:
        return self.panels[self.index] if self.panels else None

    @property
    def breadcrumb(self) -> str:
        if not self.panels:
            return ""
        return f"[{self.type_prefix}:{self.index + 1}/{len(self.panels)}] {self.panels[self.index].title}"

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


class FocusZone:
    SMARTBAR = "smartbar"
    DISPLAY = "display"
    PANEL = "panel"
    _CYCLE = [SMARTBAR, DISPLAY, PANEL]

    @classmethod
    def next_zone(cls, current: str, visible: set[str]) -> str:
        idx = cls._CYCLE.index(current)
        for i in range(1, len(cls._CYCLE) + 1):
            candidate = cls._CYCLE[(idx + i) % len(cls._CYCLE)]
            if candidate in visible:
                return candidate
        return current


# ─── Swappable Autocomplete Completer ─────────────────────────────────────────


class TuiCompleter:
    """Swappable completer: command mode → job/flag completions, edit mode → field choices."""

    def __init__(self) -> None:
        self._mode = "command"
        self._choices: list[str] = []
        self._field_name = ""

    def set_command_mode(self) -> None:
        self._mode = "command"
        self._choices = []

    def set_edit_mode(self, field_name: str, choices: list[str] | None = None) -> None:
        self._mode = "field_edit"
        self._field_name = field_name
        self._choices = choices or []

    @property
    def mode(self) -> str:
        return self._mode

    def get_items(self, value: str) -> list:
        if not HAS_AUTOCOMPLETE:
            return []
        if self._mode == "command":
            return self._command_items(value)
        return self._edit_items(value)

    def _command_items(self, value: str) -> list:
        partial = value.strip().lower()
        tokens = value.split()
        # If first token matches a job, show flags
        if tokens and tokens[0] in KNOWN_JOBS:
            job = KNOWN_JOBS[tokens[0]]
            items = []
            for fname in job["fields"]:
                flag = f"--{fname}"
                if partial and flag not in value:
                    if len(tokens) > 1 and tokens[-1].startswith("--"):
                        if fname.startswith(tokens[-1][2:]):
                            items.append(DropdownItem(main=flag))
                    else:
                        items.append(DropdownItem(main=flag))
                elif not any(f"--{fname}" in value for _ in [1]):
                    items.append(DropdownItem(main=flag))
            return items[:10]
        # Show job names
        items = []
        for name, meta in KNOWN_JOBS.items():
            if partial and partial not in name:
                continue
            items.append(DropdownItem(main=f"{name}  — {meta['description']}"))
        return items[:10]

    def _edit_items(self, value: str) -> list:
        partial = value.lower()
        items = []
        for choice in self._choices:
            if partial and partial not in choice.lower():
                continue
            items.append(DropdownItem(main=choice))
        return items


if HAS_AUTOCOMPLETE:
    class TuiAutoComplete(AutoComplete):
        def __init__(self, target: Input, completer: TuiCompleter, **kwargs) -> None:
            super().__init__(target, candidates=None, **kwargs)
            self._completer = completer

        def get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
            return self._completer.get_items(target_state.text)

        def get_search_string(self, target_state: TargetState) -> str:
            return target_state.text

        def should_show_dropdown(self, search_string: str) -> bool:
            if self._completer.mode == "field_edit":
                return self.option_list.option_count > 0
            return bool(search_string.strip()) and self.option_list.option_count > 0


# ─── Command Palette Provider ─────────────────────────────────────────────────


class ContextualCommands(Provider):
    async def search(self, query: str) -> Hits:
        app = self.app
        assert isinstance(app, FullTuiV2App)
        matcher = self.matcher(query)
        commands = [
            ("Open Pre-flight Panels", "Ctrl+R", app._cmd_open_preflight),
            ("Open General Panels", "Ctrl+E", app._cmd_open_general),
            ("Focus SmartBar", "Esc", app._cmd_focus_smartbar),
            ("Execute Command", "Ctrl+Enter", app._cmd_execute),
            ("Cycle Focus Zone", "Shift+Tab", app._cmd_cycle_zone),
        ]
        if app._active_ring and len(app._active_ring.panels) > 1:
            commands.append(("Next Panel", "Ctrl+J", app._cmd_ring_next))
            commands.append(("Previous Panel", "Ctrl+K", app._cmd_ring_prev))
            for i, p in enumerate(app._active_ring.panels):
                commands.append((f"Go to: {p.title}", f"Panel {i+1}", lambda idx=i: app._cmd_ring_goto(idx)))
        if app._mode == "normal" and app._zone == FocusZone.PANEL:
            commands.append(("Edit Field (session)", "e", app._cmd_edit_session))
            commands.append(("Edit Field (choose target)", "E", app._cmd_edit_target))
        for title, help_text, cb in commands:
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), cb, help=help_text)


# ─── Main App ────────────────────────────────────────────────────────────────


class FullTuiV2App(App[None]):
    """Full TUI v2: readiness, target selector, autocomplete."""

    COMMANDS = App.COMMANDS | {ContextualCommands}

    CSS = """
    Screen { height: auto; }
    #display-section { display: none; height: auto; max-height: 5; }
    #display-section.visible { display: block; }
    #display-breadcrumb { height: 1; background: $primary-darken-2; color: $text; padding: 0 1; }
    #display-content { height: auto; min-height: 1; max-height: 3; padding: 0 1; }
    #header { height: 1; background: $primary; color: $text; text-style: bold; padding: 0 1; }
    #smart-bar { width: 100%; }
    #smart-bar.ready { border: tall green; }
    #smart-bar.editing { border: tall $accent; }
    #smart-bar.invalid { border: tall red; }
    #validation-msg { height: 1; display: none; color: red; padding: 0 1; }
    #validation-msg.visible { display: block; }
    #panel-section { display: none; height: auto; max-height: 14; }
    #panel-section.visible { display: block; }
    #panel-breadcrumb { height: 1; background: $surface; color: $text; text-style: bold; padding: 0 1; }
    #panel-footer { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    #target-selector { display: none; height: auto; max-height: 6; padding: 0 1; border: round $secondary; }
    #target-selector.visible { display: block; }
    #output-log { display: none; height: auto; max-height: 4; padding: 0 1; border-top: solid $accent; }
    #output-log.visible { display: block; }
    #status-bar { height: 1; background: $surface-darken-1; color: $text-muted; padding: 0 1; }
    AutoComplete { background: $surface-lighten-1; padding: 0 1; margin: 0 1 0 1; }
    AutoComplete > OptionList { background: $surface-lighten-1; border: round $secondary; padding: 0 1; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+p", "command_palette", "Commands")]

    def __init__(self) -> None:
        super().__init__()
        self._mode = "command"  # command | normal | insert | target_select
        self._zone = FocusZone.SMARTBAR
        self._is_ready = False
        self._recognized_job: str | None = None
        self._completer = TuiCompleter()
        # Panel rings
        self._display_ring = PanelRing("D", [
            PanelDef("docker", "Docker Services", [
                ("web", ["web", "running", "8080:80"]),
                ("db", ["postgres", "running", "5432:5432"]),
            ], columns=["Service", "Status", "Ports"]),
            PanelDef("git", "Git Status", [
                ("branch", ["branch", "main", ""]),
                ("modified", ["modified", "3 files", ""]),
            ], columns=["Item", "Value", "Detail"]),
        ])
        self._preflight_ring: PanelRing | None = None  # Built dynamically from recognized job
        self._general_ring = PanelRing("E", [
            PanelDef("jobs", "Job Browser", [
                (n, [n, m["description"], "job"]) for n, m in KNOWN_JOBS.items()
            ], columns=["Name", "Description", "Kind"]),
            PanelDef("settings", "Settings", [
                ("theme", ["theme", "transparent", "default"]),
            ]),
        ])
        self._active_ring: PanelRing | None = None
        # Edit state
        self._edit_row_key: str | None = None
        self._edit_field_name: str | None = None
        self._edit_with_target: bool = False
        self._saved_bar_text = ""
        self._saved_bar_cursor = 0
        self._saved_bar_placeholder = ""
        self._sub_breadcrumbs: list[str] = []
        # Execution log
        self._exec_log: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="display-section"):
            yield Static("", id="display-breadcrumb")
            yield Static("", id="display-content")
        yield Static(" func — experiment (3 jobs)", id="header")
        smart_bar = Input(placeholder="Type a command...", id="smart-bar")
        yield smart_bar
        # Note: textual-autocomplete integration deferred — its Enter/Tab handling
        # conflicts with our modal key routing. Use Tab in INSERT to cycle choices instead.
        yield Static("", id="validation-msg")
        with Vertical(id="panel-section"):
            yield Static("", id="panel-breadcrumb")
            yield DataTable(id="panel-table", cursor_type="row")
            yield OptionList(id="target-selector")
            yield Static("", id="panel-footer")
        yield Static("", id="output-log")
        yield Static("", id="status-bar", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()
        table = self.query_one("#panel-table", DataTable)
        table.can_focus = False
        self._show_display()
        self._update_all_chrome()

    # ─── Input Changed: Bar Readiness ─────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "smart-bar":
            return
        if self._mode == "insert":
            # Clear validation errors on typing
            bar = self.query_one("#smart-bar", Input)
            if bar.has_class("invalid"):
                bar.remove_class("invalid")
                bar.add_class("editing")
                self._hide_validation()
            return
        # Check bar readiness
        text = event.value.strip()
        tokens = text.split() if text else []
        bar = self.query_one("#smart-bar", Input)
        if tokens and tokens[0] in KNOWN_JOBS:
            self._is_ready = True
            self._recognized_job = tokens[0]
            bar.add_class("ready")
            self._build_preflight_ring(tokens[0])
        else:
            self._is_ready = False
            self._recognized_job = None
            bar.remove_class("ready")
            self._preflight_ring = None
        self._update_all_chrome()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter from SmartBar — Input posts this when Enter is pressed."""
        if event.input.id != "smart-bar":
            return
        if self._mode == "insert":
            self._confirm_edit()
        elif self._mode == "command" and self._is_ready:
            self._execute_command()

    def _build_preflight_ring(self, job_name: str) -> None:
        """Build pre-flight ring from recognized job's fields. Skip if already built for same job."""
        # Don't rebuild if we already have a preflight ring for this job
        if self._preflight_ring is not None and self._active_ring is self._preflight_ring:
            return
        job = KNOWN_JOBS.get(job_name)
        if not job:
            return
        rows = []
        for fname, fmeta in job["fields"].items():
            rows.append((fname, [fname, fmeta["value"], fmeta["source"]]))
        self._preflight_ring = PanelRing("R", [
            PanelDef("config", "Config Table", rows),
            PanelDef("diff", "Diff View", [
                ("no_changes", ["(no overrides yet)", "", ""]),
            ], columns=["Field", "Change", "Status"]),
        ])

    # ─── Key Handler ──────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        from textual.command import CommandPalette
        if any(isinstance(s, CommandPalette) for s in self.screen_stack[1:]):
            return

        # Global keys
        if event.key == "ctrl+r":
            event.prevent_default()
            event.stop()
            if self._preflight_ring:
                self._toggle_ring(self._preflight_ring)
            else:
                self.notify("Type a job name first", severity="warning")
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
        elif event.key == "ctrl+enter" or (event.key == "enter" and self._mode == "command" and self._is_ready):
            if self._mode == "command" and self._is_ready:
                event.prevent_default()
                event.stop()
                self._execute_command()
                return

        # Mode-specific
        if self._mode == "command":
            pass  # Keys go to SmartBar

        elif self._mode == "normal":
            if self._zone == FocusZone.DISPLAY:
                if event.key == "escape":
                    event.prevent_default()
                    event.stop()
                    self._focus_zone(FocusZone.SMARTBAR)
                else:
                    if len(event.key) == 1 and event.key.isprintable():
                        event.prevent_default()
                        event.stop()
            elif self._zone == FocusZone.PANEL:
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
                    self._enter_insert(with_target=False)
                elif event.key == "E":
                    event.prevent_default()
                    event.stop()
                    self._enter_insert(with_target=True)
                elif event.key == "enter":
                    event.prevent_default()
                    event.stop()
                    self._drill_down()
                elif event.key == "r":
                    event.prevent_default()
                    event.stop()
                    self._reset_override()
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

        elif self._mode == "target_select":
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._cancel_target_select()
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self._confirm_target_select()
            elif event.key == "j" or event.key == "down":
                event.prevent_default()
                event.stop()
                ol = self.query_one("#target-selector", OptionList)
                if ol.highlighted is not None and ol.highlighted < ol.option_count - 1:
                    ol.highlighted = ol.highlighted + 1
            elif event.key == "k" or event.key == "up":
                event.prevent_default()
                event.stop()
                ol = self.query_one("#target-selector", OptionList)
                if ol.highlighted is not None and ol.highlighted > 0:
                    ol.highlighted = ol.highlighted - 1
            else:
                event.prevent_default()
                event.stop()

    # ─── Execution ────────────────────────────────────────────────────────

    def _execute_command(self) -> None:
        """Ctrl+Enter: execute the recognized command."""
        bar = self.query_one("#smart-bar", Input)
        cmd = bar.value.strip()
        # Show output log
        log = self.query_one("#output-log", Static)
        log.add_class("visible")
        log.update(f" [bold green]▶ Executing:[/bold green] {cmd}\n [dim]...completed successfully[/dim]")
        self._exec_log.append(cmd)
        self.notify(f"✓ Executed: {cmd}")
        # Clear bar
        bar.value = ""
        self._is_ready = False
        self._recognized_job = None
        bar.remove_class("ready")
        self._update_all_chrome()

    # ─── Zone / Ring Management ───────────────────────────────────────────

    def _cycle_zone(self) -> None:
        visible = {FocusZone.SMARTBAR}
        if self.query_one("#display-section").has_class("visible"):
            visible.add(FocusZone.DISPLAY)
        if self.query_one("#panel-section").has_class("visible"):
            visible.add(FocusZone.PANEL)
        self._focus_zone(FocusZone.next_zone(self._zone, visible))

    def _focus_zone(self, zone: str) -> None:
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
                self._zone = FocusZone.SMARTBAR
                self._mode = "command"
                self.query_one("#smart-bar", Input).focus()
        self._update_all_chrome()

    def _toggle_ring(self, ring: PanelRing) -> None:
        if self._active_ring is ring and self._zone == FocusZone.PANEL:
            self._active_ring = None
            self.query_one("#panel-section").remove_class("visible")
            self._focus_zone(FocusZone.SMARTBAR)
        else:
            self._active_ring = ring
            self._sub_breadcrumbs = []
            self._load_panel_content()
            self.query_one("#panel-section").add_class("visible")
            self._zone = FocusZone.PANEL
            self._mode = "normal"
            self.set_focus(None)
        self._update_all_chrome()

    def _load_panel_content(self) -> None:
        if not self._active_ring or not self._active_ring.current:
            return
        panel = self._active_ring.current
        table = self.query_one("#panel-table", DataTable)
        table.clear(columns=True)
        for col in panel.columns:
            table.add_column(col, key=col.lower())
        for row_key, cells in panel.rows:
            table.add_row(*cells, key=row_key)

    def _ring_navigate(self, direction: str) -> None:
        if not self._active_ring:
            return
        getattr(self._active_ring, direction)()
        self._sub_breadcrumbs = []
        self._load_panel_content()
        self._update_all_chrome()

    def _panel_cursor_down(self) -> None:
        table = self.query_one("#panel-table", DataTable)
        if table.cursor_row < table.row_count - 1:
            table.move_cursor(row=table.cursor_row + 1)

    def _panel_cursor_up(self) -> None:
        table = self.query_one("#panel-table", DataTable)
        if table.cursor_row > 0:
            table.move_cursor(row=table.cursor_row - 1)

    # ─── INSERT Mode (Option B + target selector) ─────────────────────────

    def _enter_insert(self, with_target: bool = False) -> None:
        """e/E: repurpose SmartBar for editing. E shows target selector after."""
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
        self._edit_with_target = with_target
        current_value = cells[1] if len(cells) > 1 else ""

        # Save SmartBar state
        bar = self.query_one("#smart-bar", Input)
        self._saved_bar_text = bar.value
        self._saved_bar_cursor = bar.cursor_position
        self._saved_bar_placeholder = bar.placeholder

        # Get choices for autocomplete
        choices = self._get_field_choices(self._edit_field_name)

        # Repurpose SmartBar
        bar.value = current_value
        hint = f" [{', '.join(choices)}]" if choices else ""
        bar.placeholder = f"Edit: {self._edit_field_name}{hint}"
        bar.cursor_position = len(current_value)
        bar.add_class("editing")
        bar.remove_class("ready")
        self._completer.set_edit_mode(self._edit_field_name, choices)
        bar.focus()  # Use widget.focus() not app.set_focus() for reliable Input focus

        self._mode = "insert"
        self._hide_validation()
        self._update_all_chrome()

    def _get_field_choices(self, field_name: str) -> list[str]:
        """Get choices for a field from the recognized job."""
        if self._recognized_job and self._recognized_job in KNOWN_JOBS:
            fields = KNOWN_JOBS[self._recognized_job]["fields"]
            if field_name in fields:
                return fields[field_name].get("choices", [])
        return []

    def _get_field_validator(self, field_name: str) -> str | None:
        """Get validator type for a field."""
        if self._recognized_job and self._recognized_job in KNOWN_JOBS:
            fields = KNOWN_JOBS[self._recognized_job]["fields"]
            if field_name in fields:
                return fields[field_name].get("validator")
        return None

    def _validate_value(self, value: str) -> str | None:
        """Validate value. Returns error message or None."""
        validator = self._get_field_validator(self._edit_field_name or "")
        if validator == "int":
            try:
                n = int(value)
                if n <= 0:
                    return "Must be a positive integer"
            except ValueError:
                return f"'{value}' is not a valid integer"
        return None

    def _confirm_edit(self) -> None:
        """Enter in INSERT: validate, then apply or show target selector."""
        if self._mode != "insert":
            return  # Guard against double-fire from on_key + on_input_submitted
        bar = self.query_one("#smart-bar", Input)
        new_value = bar.value.strip()
        if not new_value:
            self._cancel_edit()
            return

        # Validate
        error = self._validate_value(new_value)
        if error:
            self._show_validation(error)
            bar.add_class("invalid")
            bar.remove_class("editing")
            return

        if self._edit_with_target:
            # Show target selector
            self._show_target_selector(new_value)
        else:
            # Apply directly as session override
            self._apply_edit(new_value, "session")

    def _cancel_edit(self) -> None:
        self._restore_smartbar()

    # ─── Target Selector (E key) ──────────────────────────────────────────

    def _show_target_selector(self, value: str) -> None:
        """After edit confirmed, show persistence target choices."""
        self._mode = "target_select"
        # Store the pending value
        self._pending_edit_value = value
        # Populate OptionList
        ol = self.query_one("#target-selector", OptionList)
        ol.clear_options()
        for _key, label in PERSIST_TARGETS:
            ol.add_option(Option(label))
        ol.highlighted = 0
        ol.add_class("visible")
        # Hide SmartBar editing visual
        bar = self.query_one("#smart-bar", Input)
        bar.remove_class("editing")
        self.set_focus(None)
        self._update_all_chrome()

    def _confirm_target_select(self) -> None:
        """Enter in target_select: apply edit with chosen target."""
        ol = self.query_one("#target-selector", OptionList)
        idx = ol.highlighted or 0
        if idx < len(PERSIST_TARGETS):
            target_key, target_label = PERSIST_TARGETS[idx]
            self._apply_edit(self._pending_edit_value, target_key)
            self.notify(f"Saved to: {target_label}")
        self._hide_target_selector()
        self._restore_smartbar()

    def _cancel_target_select(self) -> None:
        """Esc in target_select: cancel, discard edit."""
        self._hide_target_selector()
        self._restore_smartbar()

    def _hide_target_selector(self) -> None:
        ol = self.query_one("#target-selector", OptionList)
        ol.remove_class("visible")
        ol.clear_options()

    # ─── Apply Edit ───────────────────────────────────────────────────────

    def _apply_edit(self, value: str, target: str) -> None:
        """Apply the edit value to the panel data and update DataTable."""
        if not self._edit_row_key or not self._active_ring:
            return
        panel = self._active_ring.current
        if not panel:
            return
        # Update in-memory data
        for i, (rk, cells) in enumerate(panel.rows):
            if rk == self._edit_row_key:
                cells[1] = value
                cells[2] = target if target != "session" else "session ✎"
                break
        # Update table
        table = self.query_one("#panel-table", DataTable)
        try:
            table.update_cell(self._edit_row_key, "value", value)
            table.update_cell(self._edit_row_key, "source",
                              target if target != "session" else "session ✎")
        except Exception:
            pass
        self.notify(f"✓ {self._edit_field_name} = {value!r} [{target}]")

    def _reset_override(self) -> None:
        """r key: reset override on current row."""
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
        # Only reset if it was a session override
        if "session" in cells[2]:
            # Restore original value from KNOWN_JOBS
            if self._recognized_job and self._recognized_job in KNOWN_JOBS:
                fields = KNOWN_JOBS[self._recognized_job]["fields"]
                if row_key in fields:
                    cells[1] = fields[row_key]["value"]
                    cells[2] = fields[row_key]["source"]
                    table.update_cell(row_key, "value", cells[1])
                    table.update_cell(row_key, "source", cells[2])
                    self.notify(f"↺ Reset {row_key}")

    def _restore_smartbar(self) -> None:
        self._mode = "normal"
        bar = self.query_one("#smart-bar", Input)
        bar.value = self._saved_bar_text
        bar.placeholder = self._saved_bar_placeholder
        bar.cursor_position = self._saved_bar_cursor
        bar.remove_class("editing", "invalid")
        if self._is_ready:
            bar.add_class("ready")
        self._edit_row_key = None
        self._edit_field_name = None
        self._edit_with_target = False
        self._completer.set_command_mode()
        self._hide_validation()
        self.set_focus(None)
        self._update_all_chrome()

    # ─── Display, Drill, Escape ───────────────────────────────────────────

    def _show_display(self) -> None:
        self.query_one("#display-section").add_class("visible")
        self._update_display_content()

    def _display_action(self, action: str) -> None:
        if self._zone != FocusZone.DISPLAY:
            self._focus_zone(FocusZone.DISPLAY)
        else:
            getattr(self._display_ring, "prev" if action == "prev" else "next")()
        self._update_display_content()
        self._update_all_chrome()

    def _update_display_content(self) -> None:
        panel = self._display_ring.current
        if not panel:
            return
        indicator = "▸ " if self._zone == FocusZone.DISPLAY else "  "
        self.query_one("#display-breadcrumb", Static).update(
            f"{indicator}{self._display_ring.breadcrumb}")
        lines = ["  ".join(f"{c:<12}" for c in cells) for _, cells in panel.rows]
        self.query_one("#display-content", Static).update("\n".join(lines))

    def _drill_down(self) -> None:
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

    def _handle_escape(self) -> None:
        if self._sub_breadcrumbs:
            self._sub_breadcrumbs.pop()
            self._update_all_chrome()
        elif self._active_ring:
            self._active_ring = None
            self.query_one("#panel-section").remove_class("visible")
            self._focus_zone(FocusZone.SMARTBAR)

    # ─── Validation Helpers ───────────────────────────────────────────────

    def _show_validation(self, msg: str) -> None:
        v = self.query_one("#validation-msg", Static)
        v.update(f" ✗ {msg}")
        v.add_class("visible")

    def _hide_validation(self) -> None:
        v = self.query_one("#validation-msg", Static)
        v.remove_class("visible")
        v.update("")

    # ─── Chrome Updates ───────────────────────────────────────────────────

    def _update_all_chrome(self) -> None:
        self._update_panel_chrome()
        if self.query_one("#display-section").has_class("visible"):
            self._update_display_content()
        self._update_status_bar()

    def _update_panel_chrome(self) -> None:
        breadcrumb = self.query_one("#panel-breadcrumb", Static)
        footer = self.query_one("#panel-footer", Static)
        if not self._active_ring or not self._active_ring.current:
            breadcrumb.update("")
            footer.update("")
            return
        indicator = "▸ " if self._zone == FocusZone.PANEL else "  "
        bc = self._active_ring.breadcrumb
        if self._sub_breadcrumbs:
            bc += " > " + " > ".join(self._sub_breadcrumbs)
        breadcrumb.update(f"{indicator}{bc}")
        # Footer
        if self._zone == FocusZone.PANEL:
            if self._mode == "target_select":
                footer.update(" j/k navigate  Enter select  Esc cancel")
            elif self._mode == "insert":
                footer.update(" Enter confirm  Esc cancel")
            elif self._mode == "normal":
                parts = ["j/k navigate", "e edit", "E edit+target", "r reset"]
                if len(self._active_ring.panels) > 1:
                    parts.append("Ctrl+J/K switch")
                parts.append("Esc back")
                footer.update(f" {'  '.join(parts)}")
        else:
            key = "Ctrl+R" if self._active_ring is self._preflight_ring else "Ctrl+E"
            footer.update(f" {key} focus  Shift+Tab cycle")

    def _update_status_bar(self) -> None:
        parts: list[str] = []
        mode_styles = {
            "command": "[dim]COMMAND[/dim]",
            "normal": "[bold cyan]NORMAL[/bold cyan]",
            "insert": "[bold green]INSERT[/bold green]",
            "target_select": "[bold yellow]TARGET[/bold yellow]",
        }
        parts.append(mode_styles.get(self._mode, self._mode))
        zone_labels = {FocusZone.SMARTBAR: "SmartBar", FocusZone.DISPLAY: "Display", FocusZone.PANEL: "Panel"}
        parts.append(f"[dim]zone:[/dim] {zone_labels.get(self._zone, '?')}")
        if self._is_ready:
            parts.append("[bold green]● Ready[/bold green] Ctrl+Enter run")
        elif self._recognized_job:
            parts.append(f"[dim]job:[/dim] {self._recognized_job}")
        self.query_one("#status-bar", Static).update(f" {'  '.join(parts)}")

    # ─── Command Palette Callbacks ────────────────────────────────────────

    def _cmd_open_preflight(self) -> None:
        def _do():
            if self._preflight_ring:
                self._toggle_ring(self._preflight_ring)
            else:
                self.notify("Type a job name first", severity="warning")
        self.call_after_refresh(_do)

    def _cmd_open_general(self) -> None:
        self.call_after_refresh(self._toggle_ring, self._general_ring)

    def _cmd_focus_smartbar(self) -> None:
        self.call_after_refresh(self._focus_zone, FocusZone.SMARTBAR)

    def _cmd_execute(self) -> None:
        def _do():
            if self._is_ready:
                self._execute_command()
        self.call_after_refresh(_do)

    def _cmd_cycle_zone(self) -> None:
        self.call_after_refresh(self._cycle_zone)

    def _cmd_ring_next(self) -> None:
        self.call_after_refresh(self._ring_navigate, "next")

    def _cmd_ring_prev(self) -> None:
        self.call_after_refresh(self._ring_navigate, "prev")

    def _cmd_ring_goto(self, index: int) -> None:
        def _do():
            if self._active_ring and 0 <= index < len(self._active_ring.panels):
                self._active_ring.index = index
                self._sub_breadcrumbs = []
                self._load_panel_content()
                self._focus_zone(FocusZone.PANEL)
        self.call_after_refresh(_do)

    def _cmd_edit_session(self) -> None:
        def _do():
            if self._zone == FocusZone.PANEL and self._mode == "normal":
                self._enter_insert(with_target=False)
        self.call_after_refresh(_do)

    def _cmd_edit_target(self) -> None:
        def _do():
            if self._zone == FocusZone.PANEL and self._mode == "normal":
                self._enter_insert(with_target=True)
        self.call_after_refresh(_do)


if __name__ == "__main__":
    app = FullTuiV2App()
    app.run(inline=True, inline_no_clear=True)
