# Input Handling Experiments

Testing approaches for INSERT mode editing in the TUI panel system.

## Root Cause (CRITICAL FINDING)

**The bug is NOT about nested Input widgets failing to receive focus.**

The actual root cause:

> When the SmartBar (an `Input` widget) has focus and the app enters NORMAL mode,
> printable characters ('i', 'j', 'k', '/') are consumed by the Input's internal
> handler — they become text in the SmartBar instead of reaching the App's `on_key`.
> The centralized key routing never sees them.

**The fix:** Call `self.set_focus(None)` when transitioning from COMMAND → NORMAL mode.
This removes focus from the SmartBar so key events reach the App-level handler.

Once this fix is applied, even the "nested Input with `display: none` toggle" approach
works in Textual's test harness. The focus system is fine — the problem was that
another widget was consuming keys before they reached the dispatch logic.

## Experiments

### `experiment_truly_broken.py`
Demonstrates the actual bug: SmartBar stays focused in NORMAL mode, eats all
printable keys. The `on_key` handler for NORMAL mode is unreachable.

### `experiment_broken_nested.py` (now fixed)
Shows that nested Input with CSS toggle WORKS once SmartBar is blurred.
`set_focus(None)` in NORMAL mode + `app.set_focus(input)` in INSERT mode = working.

### `experiment_a_editbar.py` — Programmatic Key Forwarding
A dedicated EditBar widget shown during INSERT mode. Instead of relying on
Textual's focus for delivering keystrokes, the App's `on_key` handler
programmatically inserts characters into the EditBar's `.value`.

- **Pros**: Zero reliance on Textual focus system. Works regardless of widget nesting.
  Full control over key routing (backspace, arrows, home/end all handled manually).
- **Cons**: Must manually implement every editing operation (backspace, delete,
  cursor movement, selection). Misses Input widget features (undo, paste, etc).
- **Best for**: When focus is completely unreliable or you want total control.

### `experiment_b_repurpose_smartbar.py` — Reuse SmartBar
When 'i' is pressed, save SmartBar state, replace its content with the cell
value, and re-focus it. The SmartBar IS the edit widget.

- **Pros**: Zero new widgets. SmartBar already works perfectly. All Input
  features (paste, undo, selection) work natively. Vim-like feel (command line editing).
- **Cons**: SmartBar content disappears during editing (can confuse user).
  State save/restore adds complexity. Can't show command and edit simultaneously.
- **Best for**: Simple UX where one "input line" is sufficient.

### `experiment_c_modal.py` — Modal Overlay
Mount a small overlay widget at `layer: modal` level. The modal's Input
receives focus because it's mounted fresh (no display toggle needed).

- **Pros**: Clean separation. Focus works naturally (newly mounted widget).
  Previous commit's QuickOverrideModal used this pattern successfully.
  Modal captures all input — no key routing conflicts.
- **Cons**: Visually heavier. Breaks the "vim flow" of quick edits.
  Must be mounted/removed dynamically (DOM manipulation).
- **Best for**: Complex editing (multi-field, choices) where a distinct UI is appropriate.

## Test Results

| Approach | Input receives keystrokes? | UX feel | Complexity |
|----------|---------------------------|---------|------------|
| A: EditBar (programmatic) | ✅ YES | Good — vim-like edit line | Medium (manual key handling) |
| B: Repurpose SmartBar | ✅ YES | Good — familiar single input | Low (state save/restore) |
| C: Modal | ✅ YES | Good — clear separation | Low (mount/remove) |
| Truly broken (no blur) | ❌ NO | — | Shows the root cause |
| Nested + blur | ✅ YES | Good — inline | Low (just blur + focus) |

## Recommendation for the Real TUI

**Fix the root cause first:**
```python
# In inline_tui.py, when transitioning COMMAND → NORMAL:
self.set_focus(None)  # Remove focus from SmartBar
```

Then choose the INSERT mode approach based on requirements:

1. **For simple value editing (Settings panel):** Option B (repurpose SmartBar) is simplest.
   The SmartBar already works, so no new widgets needed. Save/restore is ~10 lines.

2. **For editing with autocomplete choices:** Option A (EditBar with programmatic forwarding)
   gives total control over the input lifecycle. Can attach choice filtering independently.

3. **For complex multi-step flows:** Option C (modal) matches the old QuickOverrideModal
   pattern that was already proven to work.

**All three can coexist** — use Option B for quick edits, Option C for complex flows.

## Running

```bash
# All tests
uv run pytest experiments/input_handling/test_input_handling.py -v

# Individual experiments (interactive, run in a terminal)
uv run python -m experiments.input_handling.experiment_a_editbar
uv run python -m experiments.input_handling.experiment_b_repurpose_smartbar
uv run python -m experiments.input_handling.experiment_c_modal
uv run python -m experiments.input_handling.experiment_truly_broken
uv run python -m experiments.input_handling.experiment_broken_nested
```
