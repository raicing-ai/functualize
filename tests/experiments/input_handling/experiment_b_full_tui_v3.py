"""Experiment B Full TUI v3: Cell navigation, linked edits, bar sync.

Design:
- Config Table shows effective values + their resolution source
- Edit Value (i on Value col) → source auto-becomes "session", SmartBar syncs
- Edit Source (i on Source col) → value auto-updates from that source's chain entry
- Only sources with non-empty values are selectable
- Visual markers: ← (directly edited), ⚡ (auto-linked as consequence)
- Cyan = user-edited cell, Yellow = auto-linked cell
- SmartBar reflects session overrides as --flag value pairs
- Persistence (save to file) is NOT here — it's a separate action/panel

Layout:
    Display → Header → SmartBar → [Choices] → Panel(Breadcrumb+Table+Detail+Footer) → Output → Status

Run:
    uv run python -m experiments.input_handling.experiment_b_full_tui_v3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from textual.app import App, ComposeResult, SystemCommand
from textual.command import Hit, Hits, Provider
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option


# ─── Data Models ──────────────────────────────────────────────────────────────


class EditOrigin(Enum):
    """Which cell was directly edited (the other is auto-linked)."""
    NONE = "none"        # Untouched — from resolution chain
    VALUE = "value"      # User edited Value → Source auto-linked to "session"
    SOURCE = "source"    # User edited Source → Value auto-linked from chain


@dataclass
class ChainEntry:
    """One entry in a field's resolution chain: source → value."""
    source: str
    value: str  # Empty string = this source has no value


@dataclass
class FieldDef:
    """Metadata for a single config field."""
    name: str
    value: str         # Current effective value
    source: str        # Current effective source
    required: bool = False
    choices: list[str] | None = None
    validator: str | None = None
    is_path: bool = False
    chain: list[ChainEntry] = field(default_factory=list)
    # Edit tracking
    edit_origin: EditOrigin = EditOrigin.NONE
    original_value: str = ""   # Pre-edit value (for reset)
    original_source: str = ""  # Pre-edit source (for reset)

    def __post_init__(self):
        if not self.original_value:
            self.original_value = self.value
        if not self.original_source:
            self.original_source = self.source

    def sources_with_values(self) -> list[ChainEntry]:
        """Return only chain entries that have non-empty values."""
        return [e for e in self.chain if e.value]

    def value_for_source(self, source: str) -> str | None:
        """Get the value a specific source provides, or None."""
        for e in self.chain:
            if e.source == source and e.value:
                return e.value
        return None


KNOWN_JOBS: dict[str, dict[str, Any]] = {
    "deploy": {
        "description": "Deploy to environment",
        "fields": [
            FieldDef("region", "us-east-1", "config.toml", required=True,
                     choices=["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"],
                     chain=[ChainEntry("env:DEPLOY_REGION", ""), ChainEntry("config.toml", "us-east-1"),
                            ChainEntry("default", "us-east-1")]),
            FieldDef("replicas", "3", "default", required=True, validator="int",
                     chain=[ChainEntry("config.toml", "5"), ChainEntry("default", "3")]),
            FieldDef("timeout", "30", "env:TIMEOUT", validator="int",
                     chain=[ChainEntry("env:TIMEOUT", "30"), ChainEntry("config.toml", "60"),
                            ChainEntry("default", "30")]),
            FieldDef("verbose", "false", "default", choices=["true", "false"],
                     chain=[ChainEntry("default", "false")]),
        ],
    },
    "test": {
        "description": "Run test suite",
        "fields": [
            FieldDef("suite", "unit", "default", required=True,
                     choices=["unit", "integration", "e2e", "all"],
                     chain=[ChainEntry("default", "unit")]),
            FieldDef("parallel", "true", "config.toml", choices=["true", "false"],
                     chain=[ChainEntry("config.toml", "true"), ChainEntry("default", "false")]),
            FieldDef("timeout", "60", "default", validator="int",
                     chain=[ChainEntry("default", "60")]),
        ],
    },
    "build": {
        "description": "Build artifacts",
        "fields": [
            FieldDef("target", "release", "default", required=True,
                     choices=["debug", "release", "profile"],
                     chain=[ChainEntry("default", "release")]),
            FieldDef("output_dir", "./dist", "default", is_path=True,
                     chain=[ChainEntry("default", "./dist")]),
        ],
    },
}

COLUMNS = [("setting", "Setting", False), ("value", "Value ✏", True), ("source", "Source ✏", True)]
EDITABLE_COL_INDICES = {1, 2}


# ─── Panel Ring / Focus Zone ──────────────────────────────────────────────────

@dataclass
class PanelDef:
    id: str
    title: str
    fields: list[FieldDef] | None = None
    rows: list[tuple[str, list[str]]] | None = None
    columns: list[str] = field(default_factory=lambda: ["Setting", "Value", "Source"])

class PanelRing:
    def __init__(self, prefix: str, panels: list[PanelDef]) -> None:
        self.prefix = prefix
        self.panels = panels
        self.index = 0
    @property
    def current(self) -> PanelDef | None:
        return self.panels[self.index] if self.panels else None
    @property
    def breadcrumb(self) -> str:
        if not self.panels: return ""
        return f"[{self.prefix}:{self.index+1}/{len(self.panels)}] {self.panels[self.index].title}"
    def next(self): self.index = (self.index + 1) % len(self.panels) if self.panels else 0
    def prev(self): self.index = (self.index - 1) % len(self.panels) if self.panels else 0
    def first(self): self.index = 0
    def last(self): self.index = len(self.panels) - 1 if self.panels else 0

class FocusZone:
    SMARTBAR = "smartbar"; DISPLAY = "display"; PANEL = "panel"
    _CYCLE = [SMARTBAR, DISPLAY, PANEL]
    @classmethod
    def next_zone(cls, current, visible):
        idx = cls._CYCLE.index(current)
        for i in range(1, 4):
            c = cls._CYCLE[(idx + i) % 3]
            if c in visible: return c
        return current

class TuiCommands(Provider):
    async def search(self, query: str) -> Hits:
        app = self.app; assert isinstance(app, FullTuiV3App)
        m = self.matcher(query)
        for title, help_t, cb in [
            ("Open Pre-flight", "Ctrl+R", lambda: app.call_after_refresh(app._cmd_preflight)),
            ("Open General", "Ctrl+E", lambda: app.call_after_refresh(app._cmd_general)),
            ("Execute", "Ctrl+Enter", lambda: app.call_after_refresh(app._cmd_execute)),
            ("Focus SmartBar", "Esc", lambda: app.call_after_refresh(app._focus_zone, FocusZone.SMARTBAR)),
        ]:
            s = m.match(title)
            if s > 0: yield Hit(s, m.highlight(title), cb, help=help_t)


# ─── Main App ────────────────────────────────────────────────────────────────

class FullTuiV3App(App[None]):
    COMMANDS = App.COMMANDS | {TuiCommands}
    CSS = """
    Screen { height: auto; }
    #display-section { display: none; height: auto; max-height: 5; }
    #display-section.visible { display: block; }
    #display-bc { height: 1; background: $primary-darken-2; color: $text; padding: 0 1; }
    #display-body { height: auto; min-height: 1; max-height: 2; padding: 0 1; }
    #display-footer { height: 1; color: $text-muted; padding: 0 1; }
    #header { height: 1; background: $primary; color: $text; text-style: bold; padding: 0 1; }
    #smart-bar { width: 100%; }
    #smart-bar.pending { border: tall yellow; }
    #smart-bar.ready { border: tall green; }
    #smart-bar.editing { border: tall $accent; }
    #smart-bar.invalid { border: tall red; }
    #validation-msg { height: 1; display: none; color: red; padding: 0 1; }
    #validation-msg.visible { display: block; }
    #choices-list { display: none; height: auto; max-height: 5; margin: 0 1; border: round $secondary; background: $surface-lighten-1; padding: 0 1; }
    #choices-list.visible { display: block; }
    #panel-section { display: none; height: auto; max-height: 14; }
    #panel-section.visible { display: block; }
    #panel-bc { height: 1; background: $surface; color: $text; text-style: bold; padding: 0 1; }
    #panel-footer { height: 1; background: $surface; color: $text-muted; padding: 0 1; }
    #detail-view { display: none; height: auto; max-height: 6; padding: 0 1; border-top: dashed $surface-lighten-2; }
    #detail-view.visible { display: block; }
    #output-log { display: none; height: auto; max-height: 3; padding: 0 1; border-top: solid $accent; }
    #output-log.visible { display: block; }
    #status-bar { height: 1; background: $surface-darken-1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+p", "command_palette", "Commands")]

    def __init__(self) -> None:
        super().__init__()
        self._mode = "command"  # command | normal | insert | choosing
        self._zone = FocusZone.SMARTBAR
        self._bar_state = "grey"
        self._recognized_job: str | None = None
        self._job_fields: list[FieldDef] | None = None
        self._display_ring = PanelRing("D", [
            PanelDef("docker", "Docker Services",
                     rows=[("web", ["web", "running", "8080:80"]), ("db", ["postgres", "running", "5432"])],
                     columns=["Service", "Status", "Ports"]),
            PanelDef("git", "Git Status",
                     rows=[("branch", ["branch", "main", ""]), ("modified", ["modified", "3 files", ""]),
                           ("staged", ["staged", "1 file", ""])],
                     columns=["Item", "Value", "Detail"]),
        ])
        self._general_ring = PanelRing("E", [
            PanelDef("jobs", "Job Browser",
                     rows=[(n, [n, m["description"], "job"]) for n, m in KNOWN_JOBS.items()],
                     columns=["Name", "Description", "Kind"]),
            PanelDef("settings", "Settings",
                     rows=[("theme", ["theme", "transparent", "default"])]),
        ])
        self._preflight_ring: PanelRing | None = None
        self._active_ring: PanelRing | None = None
        self._edit_field: FieldDef | None = None
        self._edit_col: int = -1
        self._saved_bar = ("", 0, "")
        self._sub_breadcrumbs: list[str] = []
        self._exec_log: list[str] = []
        self._editing_file_source: str | None = None
        self._file_edit_staged: dict[str, str] = {}
        self._persist_flow_field: FieldDef | None = None
        self._persist_flow_files: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="display-section"):
            yield Static("", id="display-bc")
            yield Static("", id="display-body")
            yield Static("", id="display-footer")
        yield Static(" func — experiment (3 jobs)", id="header")
        yield Input(placeholder="Type a command (deploy, test, build)...", id="smart-bar")
        yield Static("", id="validation-msg")
        yield OptionList(id="choices-list")
        with Vertical(id="panel-section"):
            yield Static("", id="panel-bc")
            yield DataTable(id="panel-table", cursor_type="cell")
            yield Static("", id="detail-view")
            yield Static("", id="panel-footer")
        yield Static("", id="output-log")
        yield Static("", id="status-bar", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#smart-bar", Input).focus()
        self.query_one("#panel-table", DataTable).can_focus = False
        self._show_display()
        self._update_all()

    # ─── Bar Readiness + SmartBar Sync ────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "smart-bar": return
        if self._mode == "insert":
            bar = self.query_one("#smart-bar", Input)
            if bar.has_class("invalid"):
                bar.remove_class("invalid"); bar.add_class("editing")
                self._hide_validation()
            self._filter_choices(bar.value)
            return
        self._evaluate_bar(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "smart-bar": return
        if self._mode == "insert":
            self._confirm_edit()
        elif self._mode == "command" and self._bar_state == "ready":
            self._execute_command()

    def _evaluate_bar(self, text: str) -> None:
        bar = self.query_one("#smart-bar", Input)
        bar.remove_class("ready", "pending")
        tokens = text.strip().split() if text.strip() else []
        if not tokens or tokens[0] not in KNOWN_JOBS:
            self._bar_state = "grey"; self._recognized_job = None
            self._job_fields = None; self._preflight_ring = None
        else:
            self._recognized_job = tokens[0]
            self._job_fields = list(KNOWN_JOBS[tokens[0]]["fields"])
            # Reset edit tracking for fresh fields
            for f in self._job_fields:
                f.edit_origin = EditOrigin.NONE
                f.value = f.original_value
                f.source = f.original_source
            required = [f for f in self._job_fields if f.required]
            if all(f.value for f in required):
                self._bar_state = "ready"; bar.add_class("ready")
            else:
                self._bar_state = "pending"; bar.add_class("pending")
            self._build_preflight()
        self._update_all()

    def _build_preflight(self) -> None:
        if not self._job_fields: return
        if self._preflight_ring and self._active_ring is self._preflight_ring: return
        # Build config files panel from discovered sources
        config_files_rows = self._get_config_files_rows()
        self._preflight_ring = PanelRing("R", [
            PanelDef("config", "Config Table", fields=self._job_fields),
            PanelDef("files", "Config Files", rows=config_files_rows,
                     columns=["File", "Status", "Fields"]),
            PanelDef("diff", "Diff View", rows=[("none", ["(no session overrides)", "", ""])],
                     columns=["Field", "Change", "Status"]),
        ])

    def _get_config_files_rows(self) -> list[tuple[str, list[str]]]:
        """Get config file locations from the resolution chain."""
        if not self._job_fields: return []
        # Discover unique file sources from all fields' chains
        file_sources: dict[str, list[str]] = {}  # source → [field_names with values]
        for f in self._job_fields:
            for entry in f.chain:
                if entry.source.startswith("env:"): continue  # Skip env vars
                if entry.source == "session": continue
                if entry.source == "default": continue
                if entry.source not in file_sources:
                    file_sources[entry.source] = []
                if entry.value:
                    file_sources[entry.source].append(f.name)
        # Always offer these standard locations
        standard = [".functualize.toml", "pyproject.toml", "~/.config/functualize"]
        for s in standard:
            if s not in file_sources:
                file_sources[s] = []
        rows = []
        for source, fields_list in file_sources.items():
            status = "has values" if fields_list else "empty"
            fields_str = ", ".join(fields_list[:3])
            if len(fields_list) > 3: fields_str += "..."
            rows.append((source, [source, status, fields_str or "(none)"]))
        return rows

    def _sync_smartbar_from_fields(self) -> None:
        """Update SmartBar to reflect session overrides as --flag value."""
        if not self._recognized_job or not self._job_fields: return
        parts = [self._recognized_job]
        for f in self._job_fields:
            if f.edit_origin != EditOrigin.NONE:
                parts.append(f"--{f.name}")
                parts.append(f.value)
        bar = self.query_one("#smart-bar", Input)
        bar.value = " ".join(parts)
        bar.cursor_position = len(bar.value)

    # ─── Key Handler ──────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        from textual.command import CommandPalette
        if any(isinstance(s, CommandPalette) for s in self.screen_stack[1:]): return
        # Global
        if event.key == "ctrl+r": event.prevent_default(); event.stop(); self._cmd_preflight(); return
        elif event.key == "ctrl+e": event.prevent_default(); event.stop(); self._cmd_general(); return
        elif event.key == "ctrl+u": event.prevent_default(); event.stop(); self._display_action("prev"); return
        elif event.key == "ctrl+i" and self._zone == FocusZone.DISPLAY: event.prevent_default(); event.stop(); self._display_action("next"); return
        elif event.key == "shift+tab": event.prevent_default(); event.stop(); self._cycle_zone(); return
        elif event.key == "ctrl+enter":
            if self._bar_state == "ready": event.prevent_default(); event.stop(); self._execute_command(); return

        if self._mode == "command": pass
        elif self._mode == "normal":
            if self._zone == FocusZone.DISPLAY:
                if event.key == "escape": event.prevent_default(); event.stop(); self._focus_zone(FocusZone.SMARTBAR)
                elif len(event.key) == 1 and event.key.isprintable(): event.prevent_default(); event.stop()
            elif self._zone == FocusZone.PANEL:
                self._handle_panel_key(event)
        elif self._mode == "insert":
            if event.key == "escape": event.prevent_default(); event.stop(); self._cancel_edit()
            elif event.key == "enter": event.prevent_default(); event.stop(); self._confirm_edit()
            elif event.key == "tab": event.prevent_default(); event.stop(); self._accept_choice()
            elif event.key == "down": event.prevent_default(); event.stop(); self._choice_nav(1)
            elif event.key == "up": event.prevent_default(); event.stop(); self._choice_nav(-1)
        elif self._mode == "choosing":
            if event.key == "escape": event.prevent_default(); event.stop(); self._cancel_edit()
            elif event.key == "enter": event.prevent_default(); event.stop(); self._confirm_source_choice()
            elif event.key in ("j", "down"): event.prevent_default(); event.stop(); self._choice_nav(1)
            elif event.key in ("k", "up"): event.prevent_default(); event.stop(); self._choice_nav(-1)
            else: event.prevent_default(); event.stop()

    def _handle_panel_key(self, event) -> None:
        k = event.key
        if k == "j": event.prevent_default(); event.stop(); self._move_cursor(row=1)
        elif k == "k": event.prevent_default(); event.stop(); self._move_cursor(row=-1)
        elif k == "l": event.prevent_default(); event.stop(); self._move_cursor(col=1)
        elif k == "h": event.prevent_default(); event.stop(); self._move_cursor(col=-1)
        elif k == "i": event.prevent_default(); event.stop(); self._enter_insert()
        elif k == "I": event.prevent_default(); event.stop(); self._enter_persist_flow()  # I = edit + persist to file
        elif k == "enter": event.prevent_default(); event.stop(); self._drill_down()
        elif k == "r": event.prevent_default(); event.stop(); self._reset_override()
        elif k == "escape": event.prevent_default(); event.stop(); self._handle_escape()
        elif k == "ctrl+j": event.prevent_default(); event.stop(); self._ring_nav("next")
        elif k == "ctrl+k": event.prevent_default(); event.stop(); self._ring_nav("prev")
        elif k == "ctrl+h": event.prevent_default(); event.stop(); self._ring_nav("first")
        elif k == "ctrl+l": event.prevent_default(); event.stop(); self._ring_nav("last")
        elif len(k) == 1 and k.isprintable(): event.prevent_default(); event.stop()

    def _move_cursor(self, row: int = 0, col: int = 0) -> None:
        t = self.query_one("#panel-table", DataTable)
        nr = max(0, min(t.row_count - 1, t.cursor_row + row))
        nc = max(0, min(len(COLUMNS) - 1, t.cursor_column + col))
        t.move_cursor(row=nr, column=nc)
        self._update_all()

    # ─── INSERT Mode (column-aware with linked edits) ─────────────────────

    def _enter_insert(self) -> None:
        if not self._active_ring or not self._active_ring.current: return
        panel = self._active_ring.current
        if not panel.fields:
            self.notify("Not editable", severity="warning"); return

        table = self.query_one("#panel-table", DataTable)
        row_idx, col_idx = table.cursor_row, table.cursor_column
        if row_idx < 0 or row_idx >= len(panel.fields): return
        field_def = panel.fields[row_idx]
        self._edit_field = field_def
        self._edit_col = col_idx

        if col_idx == 0:
            # Setting col → jump to Value
            table.move_cursor(column=1); col_idx = 1; self._edit_col = 1

        if col_idx == 2:
            # Source column → show source picker (only sources with values)
            available = field_def.sources_with_values()
            if not available:
                self.notify("No alternative sources available", severity="warning"); return
            self._mode = "choosing"
            ol = self.query_one("#choices-list", OptionList)
            ol.clear_options()
            for entry in available:
                marker = "●" if entry.source == field_def.source else " "
                ol.add_option(Option(f"{marker} {entry.source}  (= {entry.value})"))
            ol.highlighted = 0; ol.add_class("visible")
            self.set_focus(None)
            self._update_all()
            return

        # Value column → edit in SmartBar
        bar = self.query_one("#smart-bar", Input)
        self._saved_bar = (bar.value, bar.cursor_position, bar.placeholder)
        bar.value = field_def.value
        bar.cursor_position = len(field_def.value)
        hint = ""
        if field_def.choices: hint = f" [{', '.join(field_def.choices[:4])}]"
        elif field_def.validator == "int": hint = " [int > 0]"
        bar.placeholder = f"Edit: {field_def.name}{hint}"
        bar.add_class("editing"); bar.remove_class("ready", "pending")
        bar.focus()
        if field_def.choices:
            self._show_choices(field_def.choices, field_def.value)
        self._mode = "insert"
        self._hide_validation()
        self._update_all()

    def _show_choices(self, choices, current):
        ol = self.query_one("#choices-list", OptionList)
        ol.clear_options()
        for c in choices: ol.add_option(Option(c))
        ol.add_class("visible")
        for i, c in enumerate(choices):
            if c == current: ol.highlighted = i; break

    def _filter_choices(self, text):
        if not self._edit_field or not self._edit_field.choices: return
        ol = self.query_one("#choices-list", OptionList)
        if not ol.has_class("visible"): return
        ol.clear_options()
        for c in self._edit_field.choices:
            if not text or text.lower() in c.lower(): ol.add_option(Option(c))
        if ol.option_count > 0: ol.highlighted = 0

    def _choice_nav(self, d):
        ol = self.query_one("#choices-list", OptionList)
        if ol.option_count == 0: return
        h = ol.highlighted or 0
        ol.highlighted = max(0, min(ol.option_count - 1, h + d))

    def _accept_choice(self):
        ol = self.query_one("#choices-list", OptionList)
        if ol.option_count == 0 or ol.highlighted is None: return
        opt = ol.get_option_at_index(ol.highlighted)
        val = str(opt.prompt)
        bar = self.query_one("#smart-bar", Input)
        bar.value = val; bar.cursor_position = len(val)

    def _confirm_edit(self):
        """Confirm value edit."""
        if self._mode != "insert": return
        bar = self.query_one("#smart-bar", Input)
        value = bar.value.strip()
        if not value: self._cancel_edit(); return
        err = self._validate(value)
        if err:
            self._show_validation(err)
            bar.add_class("invalid"); bar.remove_class("editing"); return

        if self._edit_field:
            self._edit_field.value = value
            if self._editing_file_source:
                # Persist flow (I key): save to file AND set source
                self._edit_field.source = self._editing_file_source
                self._edit_field.edit_origin = EditOrigin.SOURCE
                self.notify(f"✓ Saved {self._edit_field.name} = {value!r} → {self._editing_file_source}")
                self._editing_file_source = None
            else:
                # Normal edit: source → session
                self._edit_field.source = "session"
                self._edit_field.edit_origin = EditOrigin.VALUE
                self.notify(f"✓ {self._edit_field.name} = {value!r}  [source → session ⚡]")
        self._finish_edit()

    def _confirm_source_choice(self):
        """Confirm in CHOOSING mode: source picker OR persist flow file picker."""
        ol = self.query_one("#choices-list", OptionList)
        if ol.option_count == 0 or ol.highlighted is None: return
        opt_text = str(ol.get_option_at_index(ol.highlighted).prompt)

        # Check if this is the persist flow (I key)
        if self._persist_flow_field and self._persist_flow_files:
            file_choice = opt_text.replace("Save to: ", "").strip()
            field = self._persist_flow_field
            self._hide_choices()
            # Enter INSERT to edit value for that file
            self._edit_field = field
            self._edit_col = 1
            self._editing_file_source = file_choice
            bar = self.query_one("#smart-bar", Input)
            self._saved_bar = (bar.value, bar.cursor_position, bar.placeholder)
            bar.value = field.value
            bar.placeholder = f"Value for {field.name} → {file_choice}"
            bar.cursor_position = len(field.value)
            bar.add_class("editing"); bar.remove_class("ready", "pending")
            bar.focus()
            if field.choices: self._show_choices(field.choices, field.value)
            self._mode = "insert"
            self._persist_flow_field = None
            self._persist_flow_files = []
            self._update_all()
            return

        # Normal source picker (i on Source column)
        source_part = opt_text.lstrip("● ").split("  (=")[0].strip()
        if self._edit_field:
            new_val = self._edit_field.value_for_source(source_part)
            if new_val:
                self._edit_field.source = source_part
                self._edit_field.value = new_val
                self._edit_field.edit_origin = EditOrigin.SOURCE
                self.notify(f"✓ {self._edit_field.name}: source → {source_part}  [value → {new_val!r} ⚡]")
        self._finish_edit()

    def _cancel_edit(self):
        self._hide_choices(); self._restore_bar()
        self._mode = "normal"; self.set_focus(None); self._update_all()

    def _finish_edit(self):
        self._hide_choices(); self._restore_bar()
        self._edit_field = None; self._edit_col = -1
        self._mode = "normal"; self.set_focus(None)
        self._reload_table()
        self._sync_smartbar_from_fields()
        self._evaluate_bar(self.query_one("#smart-bar", Input).value)

    def _restore_bar(self):
        bar = self.query_one("#smart-bar", Input)
        bar.value, bar.cursor_position, bar.placeholder = self._saved_bar
        bar.remove_class("editing", "invalid")
        if self._bar_state == "ready": bar.add_class("ready")
        elif self._bar_state == "pending": bar.add_class("pending")
        self._hide_validation()

    def _hide_choices(self):
        ol = self.query_one("#choices-list", OptionList)
        ol.remove_class("visible"); ol.clear_options()

    def _validate(self, value):
        if not self._edit_field: return None
        if self._edit_field.validator == "int":
            try:
                if int(value) <= 0: return "Must be > 0"
            except ValueError: return f"'{value}' not an integer"
        return None

    def _show_validation(self, msg):
        s = self.query_one("#validation-msg", Static)
        s.update(f" ✗ {msg}"); s.add_class("visible")

    def _hide_validation(self):
        s = self.query_one("#validation-msg", Static)
        s.remove_class("visible"); s.update("")

    def _reset_override(self):
        if not self._active_ring or not self._active_ring.current: return
        panel = self._active_ring.current
        if not panel.fields: return
        t = self.query_one("#panel-table", DataTable)
        idx = t.cursor_row
        if idx < 0 or idx >= len(panel.fields): return
        f = panel.fields[idx]
        if f.edit_origin == EditOrigin.NONE: return
        f.value = f.original_value; f.source = f.original_source
        f.edit_origin = EditOrigin.NONE
        self._reload_table(); self._sync_smartbar_from_fields()
        self._evaluate_bar(self.query_one("#smart-bar", Input).value)
        self.notify(f"↺ Reset {f.name}")

    # ─── Drill Down / Escape / Display / Ring ─────────────────────────────

    def _drill_down(self):
        if self._sub_breadcrumbs: return  # Already in detail
        if not self._active_ring or not self._active_ring.current: return
        panel = self._active_ring.current

        # Config Files panel: Enter → edit that file's values
        if panel.id == "files":
            t = self.query_one("#panel-table", DataTable)
            idx = t.cursor_row
            if panel.rows and idx >= 0 and idx < len(panel.rows):
                file_source = panel.rows[idx][0]
                self._enter_file_edit_view(file_source)
            return

        # Config Table: Enter → resolution chain detail
        if not panel.fields: return
        t = self.query_one("#panel-table", DataTable)
        idx = t.cursor_row
        if idx < 0 or idx >= len(panel.fields): return
        f = panel.fields[idx]
        self._sub_breadcrumbs.append(f"Detail: {f.name}")
        detail = self.query_one("#detail-view", Static)
        lines = [f" [bold]Resolution chain for[/bold] [cyan]{f.name}[/cyan]:"]
        if f.chain:
            for e in f.chain:
                marker = "▸" if e.source == f.source else " "
                val = f"= {e.value!r}" if e.value else "[dim](empty)[/dim]"
                lines.append(f"  {marker} {e.source:<25} {val}")
        lines.append(f"\n [dim]Effective:[/dim] {f.value!r} [dim]from[/dim] {f.source}")
        if f.edit_origin != EditOrigin.NONE:
            lines.append(f" [yellow]Modified:[/yellow] {f.edit_origin.value} was edited")
        detail.update("\n".join(lines)); detail.add_class("visible")
        self._update_all()

    def _enter_file_edit_view(self, file_source: str) -> None:
        """Drill into a config file's edit view: shows fields with values from that source."""
        self._sub_breadcrumbs.append(f"Edit: {file_source}")
        self._editing_file_source = file_source
        # Build staged edits from current chain values for this source
        self._file_edit_staged: dict[str, str] = {}
        if self._job_fields:
            for f in self._job_fields:
                val = f.value_for_source(file_source)
                if val:
                    self._file_edit_staged[f.name] = val
                else:
                    self._file_edit_staged[f.name] = ""  # Empty = not set in this file
        # Reload table to show the file edit view
        self._reload_table()
        self._update_all()

    def _enter_persist_flow(self) -> None:
        """I key in Config Table: pick a file, edit value, save to that file."""
        if not self._active_ring or not self._active_ring.current: return
        panel = self._active_ring.current
        if not panel.fields: return
        t = self.query_one("#panel-table", DataTable)
        idx = t.cursor_row
        if idx < 0 or idx >= len(panel.fields): return
        field_def = panel.fields[idx]
        self._edit_field = field_def
        # Show file picker (same as source picker but for persistence)
        available_files = []
        for entry in field_def.chain:
            if entry.source.startswith("env:") or entry.source in ("session", "default"):
                continue
            available_files.append(entry.source)
        # Add standard locations
        for s in [".functualize.toml", "pyproject.toml", "~/.config/functualize"]:
            if s not in available_files:
                available_files.append(s)
        if not available_files:
            self.notify("No config files available", severity="warning"); return
        self._mode = "choosing"
        self._persist_flow_field = field_def
        self._persist_flow_files = available_files
        ol = self.query_one("#choices-list", OptionList)
        ol.clear_options()
        for f in available_files:
            ol.add_option(Option(f"Save to: {f}"))
        ol.highlighted = 0; ol.add_class("visible")
        self.set_focus(None)
        self._update_all()

    def _handle_escape(self):
        if self._sub_breadcrumbs:
            self._sub_breadcrumbs.pop()
            self.query_one("#detail-view", Static).remove_class("visible")
            # Clean up file edit state if leaving that view
            if self._editing_file_source and not any("Edit:" in b for b in self._sub_breadcrumbs):
                self._editing_file_source = None
                self._file_edit_staged = {}
            self._reload_table()
            self._update_all()
        elif self._active_ring:
            self._active_ring = None
            self.query_one("#panel-section").remove_class("visible")
            self.query_one("#detail-view", Static).remove_class("visible")
            self._editing_file_source = None
            self._file_edit_staged = {}
            self._focus_zone(FocusZone.SMARTBAR)

    def _cycle_zone(self):
        visible = {FocusZone.SMARTBAR}
        if self.query_one("#display-section").has_class("visible"): visible.add(FocusZone.DISPLAY)
        if self.query_one("#panel-section").has_class("visible"): visible.add(FocusZone.PANEL)
        self._focus_zone(FocusZone.next_zone(self._zone, visible))

    def _focus_zone(self, zone):
        self._zone = zone
        if zone == FocusZone.SMARTBAR:
            self._mode = "command"; self.query_one("#smart-bar", Input).focus()
        elif zone == FocusZone.DISPLAY:
            self._mode = "normal"; self.set_focus(None)
        elif zone == FocusZone.PANEL:
            if self._active_ring: self._mode = "normal"; self.set_focus(None)
            else: self._zone = FocusZone.SMARTBAR; self._mode = "command"; self.query_one("#smart-bar", Input).focus()
        self._update_all()

    def _toggle_ring(self, ring):
        if self._active_ring is ring and self._zone == FocusZone.PANEL:
            self._active_ring = None
            self.query_one("#panel-section").remove_class("visible")
            self._focus_zone(FocusZone.SMARTBAR)
        else:
            self._active_ring = ring; self._sub_breadcrumbs = []
            self.query_one("#detail-view", Static).remove_class("visible")
            self._reload_table()
            self.query_one("#panel-section").add_class("visible")
            self._zone = FocusZone.PANEL; self._mode = "normal"; self.set_focus(None)
        self._update_all()

    def _ring_nav(self, d):
        if not self._active_ring: return
        getattr(self._active_ring, d)()
        self._sub_breadcrumbs = []
        self.query_one("#detail-view", Static).remove_class("visible")
        self._reload_table(); self._update_all()

    def _show_display(self):
        self.query_one("#display-section").add_class("visible"); self._update_display()

    def _display_action(self, action):
        if self._zone != FocusZone.DISPLAY: self._focus_zone(FocusZone.DISPLAY)
        else: getattr(self._display_ring, "prev" if action == "prev" else "next")()
        self._update_display(); self._update_all()

    def _update_display(self):
        p = self._display_ring.current
        if not p: return
        ind = "▸ " if self._zone == FocusZone.DISPLAY else "  "
        self.query_one("#display-bc", Static).update(f"{ind}{self._display_ring.breadcrumb}")
        if p.rows:
            self.query_one("#display-body", Static).update(
                "\n".join("  ".join(f"{c:<12}" for c in cells) for _, cells in p.rows))
        # Footer
        ft = self.query_one("#display-footer", Static)
        if self._zone == FocusZone.DISPLAY:
            n = len(self._display_ring.panels)
            actions = "Ctrl+U prev  Ctrl+I next  Esc unfocus" if n > 1 else "Esc unfocus"
            ft.update(f" {actions}")
        else:
            ft.update(" Ctrl+U/I focus display  Shift+Tab cycle")

    def _execute_command(self):
        bar = self.query_one("#smart-bar", Input)
        cmd = bar.value.strip()
        self.query_one("#output-log", Static).add_class("visible")
        self.query_one("#output-log", Static).update(f" [bold green]▶[/bold green] {cmd}  [dim]...done[/dim]")
        self._exec_log.append(cmd); self.notify(f"✓ {cmd}")
        bar.value = ""; self._evaluate_bar("")

    # ─── Table Rendering (with edit markers) ──────────────────────────────

    def _reload_table(self):
        if not self._active_ring or not self._active_ring.current: return
        panel = self._active_ring.current
        table = self.query_one("#panel-table", DataTable)
        saved_row, saved_col = table.cursor_row, table.cursor_column
        table.clear(columns=True)

        # Check if we're in a file edit sub-view
        if self._editing_file_source and self._sub_breadcrumbs and any("Edit:" in b for b in self._sub_breadcrumbs):
            # File edit view: Setting + Value only (no Source column)
            table.add_column("Setting", key="setting")
            table.add_column("Value ✏", key="value")
            if self._job_fields:
                for f in self._job_fields:
                    val = self._file_edit_staged.get(f.name, "")
                    marker = "●" if f.required else " "
                    display_val = val if val else "[dim](not set)[/dim]"
                    table.add_row(f"{marker} {f.name}", display_val, key=f.name)
        elif panel.fields:
            table.add_column("Setting", key="setting")
            table.add_column("Value ✏", key="value")
            table.add_column("Source ✏", key="source")
            for f in panel.fields:
                req = "●" if f.required else " "
                if f.edit_origin == EditOrigin.VALUE:
                    val_display = f"{f.value} ←"
                    src_display = f"session ⚡"
                elif f.edit_origin == EditOrigin.SOURCE:
                    val_display = f"{f.value} ⚡"
                    src_display = f"{f.source} ←"
                else:
                    val_display = f.value
                    src_display = f.source
                table.add_row(f"{req} {f.name}", val_display, src_display, key=f.name)
        elif panel.rows:
            for col in panel.columns:
                table.add_column(col, key=col.lower())
            for rk, cells in panel.rows:
                table.add_row(*cells, key=rk)

        max_row = max(0, table.row_count - 1)
        ncols = len(table.columns)
        max_col = max(0, ncols - 1) if ncols > 0 else 0
        table.move_cursor(row=min(saved_row, max_row), column=min(saved_col, max_col))

    # ─── Chrome Updates ───────────────────────────────────────────────────

    def _update_all(self):
        self._update_panel_chrome()
        if self.query_one("#display-section").has_class("visible"): self._update_display()
        self._update_status()

    def _update_panel_chrome(self):
        bc_w = self.query_one("#panel-bc", Static)
        ft_w = self.query_one("#panel-footer", Static)
        if not self._active_ring or not self._active_ring.current:
            bc_w.update(""); ft_w.update(""); return
        ind = "▸ " if self._zone == FocusZone.PANEL else "  "
        bc = self._active_ring.breadcrumb
        if self._sub_breadcrumbs: bc += " > " + " > ".join(self._sub_breadcrumbs)
        bc_w.update(f"{ind}{bc}")
        if self._zone == FocusZone.PANEL:
            if self._mode == "choosing": ft_w.update(" j/k navigate  Enter select  Esc cancel")
            elif self._mode == "insert": ft_w.update(" Enter confirm  Tab complete  ↑↓ choices  Esc cancel")
            else:
                parts = ["j/k rows", "h/l cols", "i edit cell", "Enter detail", "r reset"]
                if self._active_ring and len(self._active_ring.panels) > 1: parts.append("Ctrl+J/K switch")
                parts.append("Esc back")
                ft_w.update(f" {'  '.join(parts)}")
        else: ft_w.update(" Ctrl+R/E focus  Shift+Tab cycle")

    def _update_status(self):
        parts = []
        styles = {"command": "[dim]COMMAND[/dim]", "normal": "[bold cyan]NORMAL[/bold cyan]",
                  "insert": "[bold green]INSERT[/bold green]", "choosing": "[bold yellow]CHOOSE[/bold yellow]"}
        parts.append(styles.get(self._mode, self._mode))
        zones = {FocusZone.SMARTBAR: "SmartBar", FocusZone.DISPLAY: "Display", FocusZone.PANEL: "Panel"}
        parts.append(f"[dim]{zones.get(self._zone, '?')}[/dim]")
        if self._bar_state == "ready": parts.append("[bold green]● Ready[/bold green]")
        elif self._bar_state == "pending": parts.append("[bold yellow]◐ Pending[/bold yellow]")
        if self._zone == FocusZone.PANEL:
            t = self.query_one("#panel-table", DataTable)
            col_name = COLUMNS[t.cursor_column][1] if t.cursor_column < len(COLUMNS) else "?"
            editable = "✏" if t.cursor_column in EDITABLE_COL_INDICES else "🔒"
            parts.append(f"[dim]col:[/dim] {col_name} {editable}")
        self.query_one("#status-bar", Static).update(f" {'  '.join(parts)}")

    # ─── Command Palette ──────────────────────────────────────────────────

    def _cmd_preflight(self):
        if self._preflight_ring: self._toggle_ring(self._preflight_ring)
        else: self.notify("Type a job name first", severity="warning")
    def _cmd_general(self): self._toggle_ring(self._general_ring)
    def _cmd_execute(self):
        if self._bar_state == "ready": self._execute_command()


if __name__ == "__main__":
    app = FullTuiV3App()
    app.run(inline=True, inline_no_clear=True)
