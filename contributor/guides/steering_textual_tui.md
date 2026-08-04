# Steering: Textual TUI — Architecture & Foolproof Testing

> **Audience**: AI agents and humans working on the Textual-based inline TUI in
> `src/functualize/_cli/tui/`.
> **Verified against**: Textual **8.2.7** (installed in `.venv`),
> textual-autocomplete 4.x. Claims marked *(proven)* have executable proofs in
> [`tests/tui_audit/`](../../tests/tui_audit/README.md) — run
> `uv run pytest tests/tui_audit/ -v` before trusting or changing them.
> Where the repo deviates from a general Textual recommendation, the
> deviation is called out explicitly in §5.

---

## 1. What kind of TUI this is (read first)

`func` with no arguments launches an **inline-mode** Textual app
(`inline_tui.launch_inline_tui` → `FunctualizeInlineTUI.run(inline=True)`).
Inline mode renders under the shell prompt without the alternate screen. This
shapes every architectural rule below:

- The layout is a fixed vertical stack of rows (display slot, header,
  SmartBar, preflight, autocomplete, PanelHost, output log, status bar) that
  grows/shrinks with content — there is no fullscreen workspace to split.
- Height discipline is existential: any child without a `min-height` can
  collapse to zero inside the overflow containers. The enforcement rules live
  in `contributor/guides/tui-panels.md` (agent-facing) and
  `contributor/guides/tui-development.md` (human-facing) — both are mandatory
  reading before touching panels. Do not duplicate their content here.
- Inline mode is **not supported on Windows** — Textual silently falls back
  to the standard fullscreen driver (`textual/app.py`, `_build_driver`).
- Screens (including `ModalScreen`) **are** supported in inline mode in
  Textual 8.x: inline height is computed over the whole `screen_stack` and
  screens have an `&:inline` CSS pseudo-class. Early-Textual advice that
  "screens don't work inline" is outdated. Spot-check in a real terminal
  before migrating overlays, but do not treat inline mode as a reason to
  avoid `ModalScreen`.

### The interaction model

The TUI is a modal (vim-like) editor over a command bar:

- `FocusState` (`tui/focus.py`) is an FSM over
  `(FocusMode, FocusZone)`: modes COMMAND / NORMAL / INSERT / FILTER, zones
  SMARTBAR / DISPLAY / PANEL.
- `KeyDispatcher` (`tui/key_handler.py`) is the **sole** key router: the app's
  `on_key` delegates every key to it, and it looks up `KEYMAPS[mode]` to call
  `action_*` methods (on the active panel first, else the app).
- This repo deliberately does **not** use Textual `BINDINGS` for the main app.
  That is a legitimate choice for a modal UI (per-mode keymaps are one table
  instead of scattered `check_action` logic), but it has costs — see §2.2 and
  §5. New code must not introduce a *second* key-routing mechanism: either a
  key goes through `KEYMAPS`, or it is a widget-local `on_key` for a focused
  widget's internal editing keys. Nothing else.

---

## 2. Architecture rules

### 2.1 Keep the TUI layer thin; logic lives in plain modules

The dependency direction is one-way: `tui/` imports domain/data modules
(`_cli/data/`, `_cli/completions/`, plain-function modules like
`tui/sync.py`, `tui/chain_resolution.py`, `tui/missing_args.py`); those
modules never require a running app. Everything decidable without a screen
(tokenizing, readiness evaluation, chain resolution, diff computation,
shortcut generation) stays in pure functions/dataclasses tested with plain
pytest + Hypothesis. **If a widget method contains an `if` about business
rules, move it to a plain module.** The repo already follows this well —
`app.py` is a composition root that wires state machines and delegates.

Import-linter enforces the package layering (`pyproject.toml`
`[tool.importlinter]`); `_cli` may import textual, inner layers may not.

### 2.2 Key bindings — terminal reality (proven)

Rules that are non-negotiable because of how terminals encode keys:

- **Never bind `ctrl+i`, `ctrl+h`, or `ctrl+m`.** Terminals send the same
  byte as Tab (0x09), Backspace (0x08), and Enter (0x0D) respectively;
  Textual's parser normalizes to `tab` / `backspace` / `enter`, so an
  `event.key == "ctrl+i"` comparison **never matches real input**
  *(proven: `tests/tui_audit/test_key_aliasing.py`)*. If you must honor
  the ctrl-variant, match against `event.name_aliases` (contains e.g.
  `ctrl_i`) — but prefer binding `tab`/`backspace`/`enter` deliberately.
- **`ctrl+enter` only exists on terminals with the Kitty keyboard protocol**
  (Textual requests it as a progressive enhancement). On legacy terminals it
  arrives as plain `enter`. Any critical action bound to `ctrl+enter` needs a
  fallback binding that works everywhere.
- **`ctrl+c` is not quit** in modern Textual (it is copy/`help_quit`);
  `ctrl+q` is the quit default. The repo already binds `ctrl+q` → quit.
- Every entry added to `KEYMAPS` must have a Pilot test that presses the key
  and asserts the effect (§4.3). Dead keymap entries shipped precisely
  because no test pressed them.

### 2.3 Widgets communicate upward via Messages only

Child widgets post namespaced `Message` subclasses; the app handles them.
The repo does this consistently (28 message classes; only one stray
`self.app.*` call). Keep it that way:

- Namespace the message class inside the emitting widget
  (`JobBrowserPanel.JobSelected`).
- Handler methods on the app must type the event parameter with the real
  message class, **not `event: Any`** — `Any` silently breaks when a field is
  renamed. (Current violation — see §5.)
- Prefer `@on(Widget.Message)` decorators for new handlers; they are
  greppable and explicit.

### 2.4 Duck typing: use the Protocol, not `hasattr`

Panels already have one structural contract done right: `Filterable`
(`tui/panels/__init__.py`), checked with `isinstance`. Extend that pattern —
a `PanelActions` Protocol should declare `get_cursor_field()`,
`action_reset_override()`, `apply_value_edit()`, etc. — instead of the
current `hasattr(panel, "get_cursor_field")` scattering, and never reach into
another widget's privates (`panel._fields`, `panel._reload_table`,
`panel_host._type_prefix` are current violations; add public accessors).

### 2.5 Workers: sync work MUST run in a thread worker (proven)

`run_worker(coroutine)` runs **on the UI event loop**. A synchronous call
inside it freezes rendering, timers, and input for its whole duration, and
RichLog lines written before the call render only after it returns
*(proven: `tests/tui_audit/test_blocking_worker.py`)*.

- Blocking/sync work (job execution, file scans, subprocesses):
  `run_worker(fn, thread=True)` or `@work(thread=True)`; update the UI with
  `self.app.call_from_thread(...)` or by posting messages.
- Async work stays an async worker, but must actually await — no sync calls
  longer than a frame.
- Use `exclusive=True` + `group=` so repeated triggers cancel stale runs.
- `job_execution.run_job()` follows this rule: it launches execution via
  `run_worker(fn, thread=True)` and marshals RichLog writes back through
  `call_from_thread` (`_TuiLogHandler.emit`) whenever off the loop thread.
  `execute_job_async()` still exists as a synchronous wrapper kept for
  tests — it is not on the `run_job` path and must not be reintroduced there.

### 2.6 Modality must be enforced, not simulated (proven)

An overlay `Widget` on a `modal` layer does **not** block keys by itself.
Widget `on_key` only fires for keys bubbling from a focused descendant; if
focus stays outside the overlay, every key goes to the app's KeyDispatcher
*(proven: `tests/tui_audit/test_modal_key_leak.py`)*.

Rules for any dialog/overlay:

1. Prefer `ModalScreen[ResultT]` — it blocks keys structurally and returns a
   result via `dismiss()`. It works in inline mode (§1). `ShortcutSaveModal`
   (`tui/shortcut_save_modal.py`) follows this rule.
2. If a layered Widget is used anyway, it MUST (a) move focus into itself on
   mount, and (b) the `KeyDispatcher` MUST refuse app-level dispatch while an
   overlay is mounted — `KeyDispatcher._is_overlay_active()` already does
   this generically for any `screen_stack` depth > 1, not just
   `CommandPalette`.
3. Never write files from a bare keypress without a confirm step.

### 2.7 Reactive attributes for derived UI state

Hold derived state as `reactive(...)` and let `watch_*` update the UI
(`DisplaySlot.is_visible_slot` already does this, watched from `app.py`).
Never keep header/status text in sync manually from multiple call sites —
route all of it through one `_update_status_bar`-style method or a reactive.

### 2.8 Errors: no silent `except Exception: pass`

Broad silent swallows hide real bugs — a `getattr(obj, name, None)` check
that legitimately can't find the attribute is not the same as swallowing an
exception the call site doesn't understand.

- Catch the narrowest exception that the situation can actually raise.
- If a UI query can legitimately miss (`query_one` before mount), use
  `query(...).first()`-style checks or catch `NoMatches` specifically.
- If you truly must swallow, log it: `self.log.warning(...)` — never bare
  `pass`.

### 2.9 Styling

- All static layout/colors in `DEFAULT_CSS` (the repo convention — there is
  no app-level `.tcss` file; the scaffolder's generated screens use
  `CSS_PATH`, which is fine for user-facing scaffolds).
- Use Textual theme variables (`$primary`, `$surface`, `$error`,
  `$text-muted`) so themes work — the repo does this.
- Every PanelHost child declares `min-height` — see
  `contributor/guides/tui-panels.md` (HARD rule).

### 2.10 Widget selection cheat-sheet

| Need | Use | Not |
|------|-----|-----|
| Tabular panel data (jobs, config fields) | `DataTable` (`cursor_type="row"`) inside a panel widget with explicit heights | hand-rolled ListViews |
| Streamed output / detail text | `RichLog` (manages its own height) | Static you append to |
| Dialogs | `ModalScreen[T]` (or focus-capturing overlay per §2.6) | layered Widget without focus capture |
| Toasts ("nothing to undo") | `self.notify(..., severity="warning")` | writing into a status Static |
| Read-only syntax-highlighted excerpt | `Static` + `rich.syntax.Syntax` (Pygments lexers; zero new deps) | `TextArea` + tree-sitter (`textual[syntax]` extra — do not add) |
| Open `$EDITOR`, or anything else that owns the terminal | `app.request_handoff(tokens)` — the orchestrator exits the shell, runs it on the main thread, relaunches | `with self.app.suspend(): ...` — **raises `SuspendNotSupported` in inline mode**, which is the mode the shell runs in |

---

## 3. Dependencies — current state

| Package | Status | Note |
|---------|--------|------|
| `textual>=8.0` (`[cli]` extra) | OK | Floor matches the modern APIs the code relies on (key aliasing, inline screen-stack support). Env has 8.2.7. |
| `textual-autocomplete>=4.0.0` | OK | Subclassed by `FunctualizeAutoComplete`. |
| `pytest-asyncio` | ✅ present (dev) | `asyncio_mode = "auto"` already set in `[tool.pytest.ini_options]`. |
| `pytest-textual-snapshot>=1.0.0` | ✅ present (dev) | Used by `tests/_cli/test_snapshot_baseline.py`. |
| `textual-dev` | not installed | Optional; useful for `textual console` while developing. |

---

## 4. Foolproof testing playbook

### 4.1 The test pyramid (and where the repo actually is)

1. **Plain unit + property tests (bulk)** — pure modules, no running app.
   ~58 files in `tests/_cli/` do this; it is the repo's strength.
2. **Pilot tests** — drive real keys end-to-end
   (`tests/_cli/test_keymaps_pilot_coverage.py`,
   `tests/_cli/test_mode_transition_pilot.py`, `tests/tui/test_tui_pilot.py`).
   Every `KEYMAPS` entry and every mode transition needs at least one Pilot
   test that presses the terminal-delivered key name (§4.3).
3. **Snapshot tests** — `tests/_cli/test_snapshot_baseline.py` covers a
   handful of stable layout states.

Heavy `MagicMock`-based tests that call unbound app methods
(`FunctualizeInlineTUI.action_execute(mock)`) verify branch logic but prove
nothing about wiring — prefer a real app over mocks for anything
key/focus/mount related.

### 4.2 Constructing the real app in tests

```python
@pytest.fixture()
def tui_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))  # isolate stores
    monkeypatch.chdir(tmp_path)                                   # isolate cwd scans
    func_app = FunctualizeApp(name="testapp")
    func_app.register_dynamic_job("greet", lambda name="world": None)
    from functualize._cli.tui.app import FunctualizeInlineTUI
    return FunctualizeInlineTUI(func_app)
```

(Working example: `tests/tui_audit/test_modal_key_leak.py`.)
Caveat: dynamic jobs currently yield no field defs
(`_get_job_fields(...) == []`), so panel flows need a decorated/discovered
job fixture instead.

### 4.3 Pilot fundamentals

```python
async def test_escape_clears_smartbar(tui_app):
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "greet"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert tui_app._smart_bar.value == ""
```

Rules that eliminate flakiness:

- **Every assertion is preceded by `await pilot.pause()`** — it drains the
  message queue.
- **Wait for workers** before asserting on execution results:
  `await app.workers.wait_for_complete()`.
- **Never assert wall-clock timing** — assert "after pause", not timers.
- **Fix the size**: `run_test(size=(w, h))`. Note `run_test` is headless and
  NOT inline — it cannot catch inline-height rendering bugs (that is what
  the min-height steering rules and manual checks are for).
- **Simulate keys for binding coverage, call actions for logic coverage.**
  `pilot.press("ctrl+r")` proves the keymap entry; `app.action_panel_command_toggle()`
  tests behavior without re-proving the keymap. Keep at least one test that
  presses every documented key **through the terminal-delivered name**
  (press `tab`, not `ctrl+i` — Pilot bypasses the terminal encoder, so
  pressing `ctrl+i` would "work" in a test while being dead in real use).
- All filesystem inputs from `tmp_path`; XDG env vars patched (the repo's
  conftest has XDG isolation fixtures — use them).

### 4.4 Snapshot tests (`pytest-textual-snapshot`)

- Snapshot **stable states only**: default empty state, READY bar, panel
  ring open, modal open, error state.
- Seed with deterministic fixture data; no timestamps, no real scanning.
- Workflow: first run fails → inspect the HTML report → if correct,
  `pytest --snapshot-update` to commit the SVG baseline.

### 4.5 This repo's conventions (do not deviate)

- Hypothesis profiles are registered in `tests/conftest.py`:
  `dev` = 10 examples, `default` = 100 (loaded by default), `ci` = 200.
  **Do not hardcode `@settings(max_examples=...)`** — it defeats profiles.
- Slow auto-skip matches nodeids containing `_props` / `_properties` /
  `_property`, or the `slow` marker. `*_pbt.py` filenames do **not** match —
  they must carry `@pytest.mark.slow` explicitly (existing `_pbt` files do).
- Pilot/TUI tests are NOT slow-marked — they run in the default suite
  (milliseconds headless).
- Test commands: `uv run pytest -x -q --no-header` (fast) and
  `uv run pytest --run-slow` (full PBT). Prototype experiments run explicitly:
  `uv run pytest tests/experiments/<name>/` (excluded from default collection
  via `norecursedirs`).

### 4.6 What NOT to test

- Textual internals (that DataTable scrolls, that RichLog wraps).
- Exact ANSI/escape output (snapshots cover visuals).
- Colors by RGB — assert on domain state or CSS classes.

---

## 5. Compliance audit — repo vs. recommendations

| # | Recommendation | Status | Evidence / action |
|---|----------------|--------|-------------------|
| 1 | Thin TUI layer, logic in pure modules | ✅ fulfilled | `sync.py`, `chain_resolution.py`, `missing_args.py`, etc.; app.py is a composition root |
| 2 | Messages upward, no `self.app.*` mutation from widgets | ✅ mostly | 28 message classes; one stray call (`editable_table.py`, `set_focus`) |
| 3 | CSS via `DEFAULT_CSS` + theme variables, no inline styles | ✅ fulfilled | 13 widgets; zero `styles.x =` assignments |
| 4 | `pytest-asyncio` + `asyncio_mode=auto` + snapshot plugin installed | ✅ fulfilled | `pyproject.toml` |
| 5 | No unbindable keys in keymaps | ✅ fulfilled | `KEYMAPS` uses `ctrl+g`/`ctrl+o` for ring/display nav, not `ctrl+h`/`ctrl+i`; `ctrl+enter` has a plain-`enter` fallback when the bar is READY |
| 6 | Sync work in thread workers only | ✅ fulfilled | `job_execution.run_job()` uses `run_worker(fn, thread=True)` + `call_from_thread`; `execute_job_async` is a test-only wrapper, not on this path |
| 7 | Modality enforced (ModalScreen or focus-capturing overlay + dispatcher guard) | ✅ fulfilled | `ShortcutSaveModal` is a `ModalScreen`; `KeyDispatcher._is_overlay_active()` refuses app-level dispatch for any `screen_stack` depth > 1 |
| 8 | No silent `except Exception: pass` | ⚠️ partial | The broken-import fallback and the `app.py` tautology are gone; ~35 `except Exception` remain in `tui/`, most logging via `as exc`/`as e` rather than bare `pass` |
| 9 | Typed message handlers / Protocols over `hasattr` | ⚠️ partial | `PanelActions` Protocol now exists (`tui/panels/__init__.py`) alongside `Filterable`; a few `event: Any` handlers and `hasattr(panel, ...)` call sites remain |
| 10 | Pilot coverage for every documented key | ✅ mostly | `tests/_cli/test_keymaps_pilot_coverage.py`, `tests/_cli/test_mode_transition_pilot.py`, `tests/tui/test_tui_pilot.py`, `tests/_cli/test_source_chain_detail_pilot.py` (drill-down flows) |
| 15 | Drill-down sub-views are pushed widgets, not parent mode flags | ✅ fulfilled | `PanelHost.push_view`/`pop_view`; `current_panel_widget` returns the top, so `KeyDispatcher._resolve_target` reaches the sub-view with no second routing mechanism. Previously `ConfigFilesPanel._in_detail` left the list panel active and every detail key dead but Esc. |
| 16 | Every posted Message has a handler | ✅ fulfilled | `tests/_cli/test_typed_message_handlers_unit.py::test_every_posted_message_has_a_handler` derives the check by walking each panel's `Message` subclasses — a hand-written expected-list previously encoded the missing handlers as expected |
| 11 | Snapshot tests for stable states | ✅ started | `tests/_cli/test_snapshot_baseline.py` |
| 12 | `textual>=8.0` floor in `[cli]` extra | ✅ fulfilled | `pyproject.toml` |
| 13 | PanelHost children declare `min-height` | ✅ fulfilled | enforced by `contributor/guides/tui-panels.md`; panels comply |
| 14 | Reactives + watchers for derived state | ⚠️ partial | `DisplaySlot` yes; status bar/header still hand-synced from several sites |

Priority order for anything still open: 8 → 9 (defect-breeding-ground
cleanup), then keep growing 10/11 coverage as new keys/panels are added.

---

## 6. Development workflow

- Run the real thing: `uv run func` in a directory with jobs (inline mode
  needs a real Linux/macOS terminal; not Windows, not headless).
- To *observe* the running TUI/CLI headlessly (agents, remote shells), use
  the `observe-tui` skill (`.claude/skills/observe-tui/SKILL.md`): a
  pyte-based PTY screen probe plus tmux session driving. It is a debugging /
  manual-verification aid only — never wire it into pytest or CI; the
  enforcement layer stays Pilot + snapshot tests (§4).
- Debug prints go to `self.log(...)` viewed via `textual console`
  (`uv add --dev textual-dev`), never `print()` — stdout corrupts inline
  rendering under the prompt.
- Before changing key handling, workers, or overlay behavior, re-run
  `uv run pytest tests/tui_audit/ -v` and update the experiments if
  the contract changes.
- New TUI behavior claims (rendering quirks, focus rules, driver behavior)
  get proven in `tests/experiments/<topic>/` with a README + pytest file
  first — the existing `tests/experiments/input_handling/` and
  `tests/experiments/offscreen_textual/` folders show the convention.
