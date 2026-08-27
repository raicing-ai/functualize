# TUI Architecture — Inline Textual Shell

Authoritative description of `src/functualize/_cli/tui/` — the inline Textual
app launched by bare `func`. See `contributor/guides/steering_textual_tui.md`
for HARD rules (key aliasing, workers, modality) and the testing playbook;
`contributor/guides/tui-panels.md` for panel CSS/height rules;
`contributor/architecture/tui-command-panel.md` for the command panel ring UX.

## Layout (top to bottom)

`FunctualizeInlineTUI` (`tui/app.py`) composes a single vertical stack:

```
┌──────────────────────────────────────────────────────────────┐
│ #display-section   (hidden unless a DisplayProvider applies) │
│   #display-bc → DisplaySlot (#display-slot-content, the      │
│   display's real mounted widget tree) → #display-footer      │
├────────────────────────────────────────────────────────────────┤
│ #header             app name + job count                     │
├────────────────────────────────────────────────────────────────┤
│ #input-bar → #smart-bar   (the SmartBar Input)                │
│   FunctualizeAutoComplete overlay attached to the SmartBar    │
├────────────────────────────────────────────────────────────────┤
│ #preflight-summary  (RichLog; shown when a job is recognized  │
│                      AND #panel-host is not active)           │
├────────────────────────────────────────────────────────────────┤
│ #panel-host         (PanelHost; hidden until Ctrl+R/Ctrl+E,   │
│                      or auto-surfaced by live.panel)          │
├────────────────────────────────────────────────────────────────┤
│ #live-zone          (Static; PANEL binding for passive        │
│                      live.add constructs, hidden until used)  │
├────────────────────────────────────────────────────────────────┤
│ #output-log         (RichLog; appears once a job executes)    │
├────────────────────────────────────────────────────────────────┤
│ #status-bar         mode + zone + readiness                  │
└──────────────────────────────────────────────────────────────┘
```

Runs inline (under the shell prompt, no alternate screen). Inline mode is
not supported on Windows — Textual falls back to the fullscreen driver there.

## Focus model

`FocusState` (`tui/focus.py`) is the authoritative FSM — `tui/models/focus_state.py`
defines the same shapes but is explicitly commented as "kept for reference
and hint-generation only"; do not treat its `KEYMAPS` as real.

- **Modes**: `COMMAND`, `NORMAL`, `INSERT`, `FILTER`.
- **Zones**: `SMARTBAR` (always visible), `DISPLAY` (visible iff a
  `DisplayProvider` applies), `PANEL` (visible iff `PanelHost.is_active`).
- `Shift+Tab` cycles zones (`action_zone_cycle`), skipping hidden ones.
  Landing on DISPLAY with an *interactive* display (its composed widget has
  `can_focus`) enters NORMAL and focuses the widget; landing back on
  SMARTBAR from NORMAL returns to COMMAND.
- `KeyDispatcher` (`tui/key_handler.py`) is the sole key router — the app's
  `on_key` delegates every keypress to it; it dispatches on `(mode, zone)`.
- `active_panel` (the dispatcher's `action_*` target) is **zone-aware**: in
  NORMAL/DISPLAY it resolves to `DisplaySlot.current_interactive_widget`
  (top of the display's drill-down view stack, else the first focusable
  composed widget); everywhere else it is `PanelHost.current_panel_widget`.
  This is the DisplayProvider/PanelProvider convergence — display widgets
  speak the same interaction contract as panels
  (`functualize.plugin.InteractiveContent`: `action_*` methods +
  `get_available_actions(focused)`), with no second routing mechanism.

## Keybinding map

Source of truth: `tui/key_handler.py`'s `KEYMAPS`.

**COMMAND mode** (SmartBar has focus): `tab` autocomplete toggle · `ctrl+r`
toggle command panel ring · `ctrl+e` toggle general panel ring · `ctrl+enter`
(or plain `enter` when the bar is READY and no autocomplete dropdown is
open) execute · `ctrl+q` quit · `escape` clear SmartBar · `ctrl+g` first
panel in ring · `ctrl+j` next · `ctrl+k` prev · `ctrl+l` last panel · `ctrl+u`
prev display · `ctrl+o` next display · `shift+tab` cycle zone · `ctrl+s`
save shortcut.

**NORMAL mode** (a panel — or an interactive display — has focus):
`j`/`k`/arrows row nav · `h`/`l` column nav · `i` enter INSERT (edit) · `r`
reset override · `/` enter FILTER · `enter` drill down · `ctrl+enter` execute
(Kitty-protocol terminals only; execute stays reachable via Esc → COMMAND) ·
`escape` exit panel (in the DISPLAY zone: pop the display drill-down, else
leave to COMMAND/SmartBar — the display stays visible); ring/display/zone
keys are shared with COMMAND mode. A display drill-down is requested by the
widget posting `Display.DrillDown(widget, title)` (`functualize.ui`) →
`DisplaySlot.push_view`. `I` (`enter_persist`) is bound in `KEYMAPS` but no
concrete panel implements `action_enter_persist` — it is currently a no-op.

**INSERT mode**: `escape` cancel · `enter` confirm edit · `tab` accept
autocomplete choice · `up`/`down` browse choices.

**FILTER mode**: `escape` cancel · `enter` apply filter.

**Never bind** `ctrl+i` / `ctrl+h` / `ctrl+m` — terminals deliver these as
`tab` / `backspace` / `enter`, so an `event.key == "ctrl+i"` check never
fires. `ctrl+enter` only exists on Kitty-protocol terminals; the plain-`enter`
fallback above is what makes execute reachable everywhere.

**Overlay guard**: any `screen_stack` depth > 1 (a `ModalScreen` is open)
makes `KeyDispatcher` pass every key through untouched instead of routing it.

## Panel rings

`PanelHost` (`tui/panel_host.py`) renders whichever ring is active via
`FunctualizeInlineTUI._active_ring: str | None` (a plain string — `"command"`
or `"general"` — not an enum or state machine). Panels are hardcoded
builders, not a dynamic `PanelProvider` registry.

- **Command ring** (`Ctrl+R`, requires a recognized job name) —
  `tui/chain_resolution.py:build_command_panels()`:
  1. `ConfigTablePanel` (`tui/panels/config_table.py`) — "Config Table"
  2. `ConfigFilesPanel` (`tui/panels/config_files.py`) — "Config Files"
  3. `DiffViewWidget` (`tui/diff_view_widget.py`) — "Diff View" (includes an
     embedded session-history table; there is no separate "History" panel)

  See `contributor/architecture/tui-command-panel.md` for the full UX spec
  of these three panels (columns, edit flows, breadcrumb drill-down).

- **General ring** (`Ctrl+E`, always available) —
  `tui/job_listing.py:build_general_panels()`:
  1. `JobBrowserPanel` (`tui/panels/job_browser.py`) — "Jobs"
  2. `SettingsPanel` (`tui/settings_panel.py`) — "Settings"

  There is no standalone "Shortcuts" panel — saving a shortcut is a modal
  dialog (see below), not a browsable panel.

  A job calling `live.panel(construct)` during a PANEL run appends a
  focusable `LivePanelWidget` (`tui/live_panel_widget.py`, wrapping the
  construct) to this ring via `app.mount_live_panel`, auto-surfacing it;
  when the last live panel leaves and the ring was only opened for it, the
  host collapses back to the SmartBar (`_live_panel_autoactivated`).

Ring navigation: `Ctrl+G` first, `Ctrl+J` next, `Ctrl+L` last, `Ctrl+K` prev.
Disabled while a breadcrumb sub-view (drill-down) is open — `Esc` back to
the ring root first.

`tui/models/panel_ring_controller.py` (`PanelRingController`,
`Category.{HIDDEN,PRE_FLIGHT,GENERAL}`) and `tui/panels/ring.py`
(`PanelRing` dataclass) exist but have zero production call sites — the
live ring logic is the plain-string `_active_ring` above.

## Extension protocols

All declared in `plugin/protocols.py`. Wired to real consumption paths
today:

- `DisplayProvider` — `tui/display_slot.py`,
  `tui/display_provider_discovery.py`. Three discovery paths, deduped on
  `display_id`: cache-flagged modules from the job scan (the discovery
  cache's `displays` section — displays co-locate with jobs), the
  `functualize.displays` entry-point group (installed packages), and the
  duck-typed CWD `displays.py` scan (zero-config fallback). The duck-type
  check itself lives in `_primitives/display_detection.py`, reached via
  `functualize.app.utils` re-exports.
- `InteractiveContent` — the converged interaction contract
  (`get_available_actions(focused)`); satisfied opt-in by PanelHost panel
  widgets, display widgets, and `live.panel` constructs. Hosts fall back
  gracefully (footer default, keys inert) when a widget omits it.
- `HeaderItemProvider`, `StatusBarItemProvider`, `BarRenderer` —
  `tui/bar_items.py` collects items from the app's loaded plugin instances
  (`plugin_loader.loaded_instances`), sorts by `item_priority`, skips None,
  joins with double spaces, and appends to the `#header` / `#status-bar`
  Statics; a `BarRenderer` with matching `bar_type` overrides the join
  (last registered wins).

The rest — `PanelProvider`, `SignatureProvider`, `ThemeProvider`,
`PostRunStampProvider` — are declared Protocols with no registration
mechanism or consumer; treat them as reserved shape, not a working
extension point, until something wires them.

## Settings panel

`SettingsPanel` exposes the 7 settings the shell registers
(`default_surface`, `show_session_stamp`, `history_retention`,
`signature_enabled`, `display_auto_switch`,
`default_override_target`, `theme`), validated by `tui/settings_validator.py`. A quick edit posts
`SettingChanged`, which `on_settings_panel_setting_changed` applies to the
running app (`_apply_settings`) — session-scoped, "unsaved". Persisting to a
config file goes through the Enter/Detail source-chain flow, which chooses
*which* source to write to (`FuncSettingsStore`, `_cli/data/func_settings.py`;
env overrides via `FUNCTUALIZE_<SECTION>_<KEY>` always win).

## Theming

`tui/theme_manager.py` defines a `ThemeManager` with 4 built-ins
(`transparent`/`dark`/`light`/`minimal`). The app instantiates it and
`_apply_settings` calls `activate_theme` when `tui.theme` changes, but
`Dark/Light/MinimalTheme.get_css()` still return placeholder comment
strings — so the setting round-trips without visible effect until real CSS
is authored.

## Config Table edit flow

Pressing `i` on a `ConfigTablePanel` row always calls
`action_enter_insert()`, which repurposes the SmartBar itself as the edit
field (`tui/insert_mode.py`'s `InsertModeController`) rather than mounting a
separate inline cell editor. There is currently no reachable "session vs
file vs env" target-selection UI from the Config Table: `data/config_target.py`,
`tui/config_target_discovery.py`, and `data/override_applicator.py` define
that machinery, but none of it has production call sites — edits write into
`PendingExecution.overrides` and read back with source `"cli"`. Persisting a
value to a file happens through the separate **Config Files** panel
(staged edits + `Ctrl+S` atomic write — see `tui-command-panel.md`).

## Autocomplete

Live path: `tui/functualize_autocomplete.py`'s `FunctualizeAutoComplete`
subclasses the real `textual-autocomplete` package (`textual-autocomplete>=4.0.0`,
`[cli]` extra), fed by `tui/smart_bar_autocomplete.py`'s
`SmartBarAutoComplete` (context-aware command/flag/value/positional
candidates). There is no `CompletionList` widget anywhere in the repo —
that name is stale vocabulary from earlier design notes.

Path-typed fields get filesystem suggestions inside this same dropdown via
`tui/path_suggestion_scanner.py`'s `PathSuggestionScanner` (debounced,
dirs-first). `tui/path_field_editor.py`'s `PathFieldEditor` implements a
fuller standalone path-editing widget (relative/absolute modes, `~/`
handling) but is never instantiated in production — INSERT-mode editing
always uses the plain SmartBar input.

## Job execution

`tui/job_execution.py:run_job()` launches jobs via
`app.run_worker(fn, name="cmd-exec", exclusive=True, thread=True)`, so
synchronous job execution never blocks the event loop; UI writes from the
log handler marshal back with `call_from_thread`. `execute_job_async()` is
kept only as a thin synchronous wrapper for tests, not used by `run_job`.

## Shortcut saving

`Ctrl+S` from COMMAND mode opens `ShortcutSaveModal`
(`tui/shortcut_save_modal.py`), a real `ModalScreen[str | None]` — it traps
input structurally (the `KeyDispatcher` overlay guard also passes keys
through while it's open) and dismisses with the saved path or `None` on
cancel.

## CLI argument features reaching the TUI

Positional args (`Arg()`), short flags (`Option("-x", ...)`), stdin params
(`Stdin()`), and `--output` stdout emission are all real and used by the
direct `func <job> ...` CLI path (`app/adapters/cli.py`, Click-backed). The
TUI's own SmartBar-to-kwargs conversion (`tui/cli_arg_parser.py`) is a
simpler, separate re-implementation: it does not accumulate repeated
`--flag` occurrences into a list (a later occurrence overwrites the earlier
one), so multi-value flags work from a direct shell invocation but not from
the SmartBar.
