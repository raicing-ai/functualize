# TUI Panel Widget Guidelines

> Companion steering: `contributor/guides/steering_textual_tui.md` covers
> architecture-wide HARD rules (key aliasing, workers, modality, testing)
> with executable proofs in `tests/tui_audit/`. This file covers
> panel-specific constraints. Applies to all work in `src/functualize/_cli/tui/`.

## Height Requirements for PanelHost Children

The PanelHost uses this CSS for its content area (values may drift — the
source of truth is `src/functualize/_cli/tui/panel_host.py` `DEFAULT_CSS`):

```css
PanelHost .panel-host-content {
    height: auto;
    min-height: 1;
    max-height: 16;
    overflow-y: auto;
}
PanelHost .panel-host-content > * {
    display: none;
}
PanelHost .panel-host-content > .panel-visible {
    display: block;
}
```

**Any widget mounted inside PanelHost MUST declare `min-height` in its `DEFAULT_CSS`.**
Without it, `height: auto` collapses to zero inside the overflow container and the widget renders invisible even though its data is populated and `on_mount` fires correctly.

### Pattern: Panel widget with DataTable

```python
class MyPanel(Widget):
    DEFAULT_CSS = """
    MyPanel {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    MyPanel DataTable {
        height: auto;
        min-height: 2;
        max-height: 10;
    }
    """
```

### Why this is needed

- `RichLog` works without explicit height because it manages its own `virtual_size` and content rendering — it expands to fit written content.
- `DataTable` inside a custom `Widget` wrapper defaults to `height: auto` which resolves to 0 when the parent chain uses `overflow-y: auto` + `max-height`.
- `SettingsPanel` (which works correctly) already has `min-height: 4` in its `DEFAULT_CSS`.

### Reference: existing panels and their height strategy

| Panel | Strategy | Works? |
|-------|----------|--------|
| `SettingsPanel` | `DEFAULT_CSS` with `min-height: 4` | ✅ |
| `JobBrowserPanel` | `DEFAULT_CSS` with `min-height: 3` on widget + `min-height: 2` on DataTable | ✅ |
| `ConfigTablePanel` | `DEFAULT_CSS` with `min-height: 3` on widget + `min-height: 2` on DataTable | ✅ |
| Old RichLog panels | RichLog handles its own height internally | ✅ |

## Deferred Population Pattern

When a panel is built in `_build_general_panels()` or `_build_command_panels()`, `set_jobs()`/`set_fields()` is called BEFORE the widget is mounted by PanelHost. The DataTable (`self._table`) doesn't exist until `compose()` runs after mounting.

**Use the `_populated` flag pattern:**

```python
def set_jobs(self, jobs):
    self._jobs = list(jobs)
    self._populated = False
    self._populate_table()  # no-op if _table is None

def compose(self):
    self._table = DataTable(...)
    self._populated = False
    yield self._table

def on_mount(self):
    self._populate_table()  # actually adds rows now

def _populate_table(self):
    if self._populated or not self._jobs or self._table is None:
        return
    self._table.clear()
    for job in self._jobs:
        self._table.add_row(...)
    self._populated = True
```

This handles all timing scenarios:
- `set_jobs` before mount → deferred to `on_mount`
- `set_jobs` after mount → immediate population
- Re-mount (ring switch) → `compose` resets `_populated`, `on_mount` re-populates

## HARD Rules from the TUI Audit (2026-07)

Proven by `tests/tui_audit/` — run `uv run pytest tests/tui_audit/ -v`:

1. **Never add `ctrl+i`, `ctrl+h`, or `ctrl+m` to `KEYMAPS`** in
   `key_handler.py`. Terminals deliver them as `tab` / `backspace` / `enter`;
   an `event.key == "ctrl+i"` entry never matches real input. `ctrl+enter`
   only works on Kitty-protocol terminals — critical actions need a fallback.
2. **Sync/blocking work MUST run in a thread worker**
   (`run_worker(fn, thread=True)`), never inside an async worker coroutine.
   A sync call on the event loop freezes rendering and input for its whole
   duration. Update the UI from threads via `call_from_thread`.
3. **Overlay widgets do not block keys.** Any modal-like overlay must move
   focus into itself on mount AND the KeyDispatcher must refuse app-level
   dispatch while an overlay is mounted (prefer `ModalScreen` — it works in
   inline mode on Textual 8.x).
4. **No `except Exception: pass`.** Catch the narrowest exception; log with
   `self.log.warning(...)` if a swallow is genuinely required.
5. **Every new `KEYMAPS` entry needs a Pilot test** that presses the
   terminal-delivered key name and asserts the effect.

## HARD Rules from the Source-Chain Detail work (2026-07)

Proven by `tests/_cli/test_source_chain_detail_pilot.py`:

6. **A sub-view is a pushed widget, never a mode flag on the parent panel.**
   Use `PanelHost.push_view(widget, title)` / `pop_view()`. `KeyDispatcher`
   routes keys to `app.active_panel`, which is `PanelHost.current_panel_widget`
   — so a panel that keeps its list widget active while rendering a "detail
   mode" gets every key routed to the *list*. This is exactly how the Config
   Files detail view ended up with j/k moving a hidden cursor and `i`/`d`/
   `Ctrl+S` doing nothing at all, while ~400 lines of staged-edit and
   atomic-save code sat there fully implemented and unreachable.
7. **A panel Message with no `on_*` handler is a silent no-op.** Posting is not
   wiring. `SettingsPanel.SettingChanged` and `ConfigFilesPanel.InsertRequested`
   were both posted into the void for months, which is what made the Settings
   panel display-only. `tests/_cli/test_typed_message_handlers_unit.py::
   test_every_posted_message_has_a_handler` now derives this check from the
   code — do not replace it with a hand-maintained list of handler names.
8. **Never name a widget method `_render`.** It shadows Textual's internal
   `Widget._render()`; returning `None` from it makes the compositor blow up
   with `AttributeError: 'NoneType' object has no attribute 'render_strips'`
   on every Pilot test.
9. **A detail/drill-down view must re-render.** A one-shot `RichLog` written
   once at mount cannot show a staged edit, so any key that mutates state is
   invisible even when it fires. Use a widget that rebuilds from state.
10. **Test drill-down flows with Pilot, not by calling `action_*`.** Direct
    `action_*` unit tests passed against a feature that no key could reach.
    Panel-field flows also need **discovered** jobs with a **Pydantic config
    class**: `register_dynamic_job` yields no field descriptors, and a plain
    function's params are `ParamKind.PLAIN` (CLI/default only), so they are
    correctly excluded from file detail (R5-AC5) and the test would be vacuous.

## HARD Rules from the GroupOptions panel work (2026-08)

Proven by `tests/tui_group_options/` and the extended
`tests/group_options/test_surface_parity.py`. The decisions behind them are
ADR-009; these are the rules for not reintroducing the defects.

11. **Never read the bar's first token as the job name.** Resolve the path —
    `app.resolve_command(tokens)` — and use `resolution.job_name` and
    `resolution.args`. Under a group the first token is the *group*, and
    `_get_command_names()` includes group nodes, so a group passes a naive
    recognition check and then reports zero required fields.

    This single mistake produced **nine** defects at once: a truncated command
    path, a bar rewritten in a spelling its own resolver refuses, dropped group
    flags, a path segment bound to the job's first positional (silent data
    corruption), a shortcut saved under a group name, panels never built,
    readiness computed against the group, missing-args detection disabled, and
    completion retiring flags the user had not used.

    It is mechanically detectable, so check it rather than trusting review:

    ```bash
    grep -rn "tokens\[0\]"  src/functualize/_cli/tui/ --include="*.py"   # must be 3
    grep -rn "tokens\[1:\]" src/functualize/_cli/tui/ --include="*.py"   # must be 1
    ```

    The sanctioned survivors are `cli_arg_parser.py` (the `trie is None`
    fallback — the one owner of "no trie → flat"; route degradations through it
    rather than writing a second copy), `app.py`'s resolver-backed
    `resolution.job_name or tokens[0]`, and `job_execution.py`'s `builtin`
    guard, which can only ever match the reserved node.

12. **The bar is rebuilt by one emitter, never by string-joining a name.**
    `build_command_line` (`_cli/tui/sync.py`) is the only way to produce bar
    text. Four separate writers previously agreed by luck; the property that
    matters — `emit(resolve(text)) == text` — is only testable if there is one
    of them. A new write-back site calls it or it will drift.

13. **A field that is not the job's own carries `group_path`, and every
    renderer says so the same way.** `[deploy] --env`, prefix dimmed, flag
    undimmed. `FieldDef.group_path` and `ConfigDiffEntry.group_path` default to
    `None`, which is what makes an ungrouped project byte-identical
    *structurally* rather than by discipline — keep new fields defaulted for
    the same reason.

14. **Copy `secret=` onto every `FieldDef` you construct.** It rides in on the
    cached descriptor for free, including for group options
    (ADR-008 Addendum A5), so a credential leaks only by a wire being dropped
    on the way to the panel. Import `display_value` / `is_secret_field` from
    `functualize.app.utils`, never `_types.redaction` — that is the
    `lint-imports` seam. Prove masking from a **declared** `Secret[str]`, not a
    stub with `secret=True` (`wiring-discipline.md` §8), and sabotage-check it:
    delete the kwarg, watch the test go red, restore.

15. **A surface that renders a field's *kind* gets a probe in
    `tests/group_options/test_surface_parity.py`.** Two of the five recorded
    leaks got past that harness because it drove the *resolvers*, and a field's
    kind is decided again on the way to the screen. A resolver probe is not a
    render probe. Anything a user can read a field name from can file it under
    the wrong kind.

16. **Check the shell's idea of a valid flag against real `--help` output.**
    When the bar validates flags, a false rejection — greying out a command the
    CLI accepts — is far worse than the permissiveness it replaces. Click
    renders a job's boolean as a **pair** (`--verbose/--no-verbose`), so the
    negative spelling is real even though no field is named `no_verbose`; a
    group's boolean has no pair (`_flag_aliases` in `_cli/dispatch.py`). A
    field-name check alone greys out `build --no-optimize`, which is valid, and
    that is exactly what it did until the two lists were diffed job by job
    across every example project.
