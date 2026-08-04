# TUI Audit Experiments (2026-07)

Headless proofs for claims made during the `src/functualize/_cli` TUI audit.
Each claim below is verified by a pytest test in this folder — run them before
trusting (or updating) the corresponding guidance in
`contributor/guides/steering_textual_tui.md`.

## Run

```bash
uv run pytest tests/tui_audit/ -v
```

All tests pass against Textual 8.2.7 (the pinned venv version).

## What this proves

### 1. `test_key_aliasing.py` — dead keymap entries

Terminals encode Ctrl+I as the same byte as Tab (0x09) and Ctrl+H as
Backspace (0x08). Textual's `XTermParser` normalizes them: a real terminal
**never** delivers `event.key == "ctrl+i"` — it delivers `"tab"` (with
`"ctrl_i"` in `Key.name_aliases`).

Consequence for `key_handler.KEYMAPS`:

| Entry | Mode | Status |
|-------|------|--------|
| `"ctrl+i": "display_next"` | COMMAND | dead — arrives as `tab`, which maps to `autocomplete_toggle` |
| `"ctrl+i": "display_next"` | NORMAL | dead — `tab` unmapped, key silently ignored |
| `"ctrl+h": "ring_first"` | COMMAND + NORMAL | dead — arrives as `backspace` |

Related caveat (not in the tests): `"ctrl+enter": "execute"` only works on
terminals supporting the Kitty keyboard protocol (Textual requests it as a
progressive enhancement — see `textual/drivers/linux_driver.py`). Legacy
terminals send plain `\r`, which parses as `enter` — unmapped in COMMAND mode.

### 2. `test_blocking_worker.py` — sync work in an async worker freezes the TUI

`run_worker(coroutine)` runs ON the UI event loop. A synchronous call inside
it (like `job_execution.execute_job_async` calling the sync
`FunctualizeApp.execute(...)`) stops timers, rendering, and input for the
whole duration. Log lines written before the call don't render until after
it returns — "live output" is an illusion for slow jobs.

The same blocking work in a `thread=True` worker (updating the UI via
`call_from_thread`) keeps the loop responsive. This is the officially
documented pattern (Textual workers guide, FAQ).

### 3. `test_modal_key_leak.py` — overlay Widget modality is not enforced

`ShortcutSaveModal` is a layered `Widget` mounted by `action_save_shortcut`,
which never moves focus into it. A widget's `on_key` only sees keys bubbling
from a focused descendant, so while focus remains on the SmartBar:

- **Escape** hits `KEYMAPS[COMMAND]["escape"] = smartbar_clear`: it wipes the
  user's typed command and the modal **stays open** (escape cannot close it).
- **Ctrl+Enter** still **executes the job** underneath the open modal.

A `ModalScreen` blocks keys structurally. If a layered Widget must be used
(inline-mode constraints), it needs focus moved into it on mount **and** the
dispatcher must refuse app-level actions while an overlay is open.

## Findings verified from source (no test possible headlessly)

- **Screens are supported in inline mode** in Textual 8.x: inline height is
  computed across the whole `screen_stack` (`textual/app.py`,
  `_get_inline_height`) and screens have an `&:inline` CSS pseudo-class
  (`textual/screen.py`). Early-Textual advice that "screens don't work
  inline" is outdated. (A real-terminal spot check is still advisable before
  migrating overlays to `ModalScreen`.)
- **Inline mode is not supported on Windows**: `App._build_driver` falls back
  to the standard driver (`textual/app.py`).
- `key_handler.KeyDispatcher._is_autocomplete_visible` has a dead fallback:
  it imports `functualize._cli.functualize_autocomplete` (module does not
  exist — real path is `functualize._cli.tui.functualize_autocomplete`) and
  swallows the `ImportError`.
