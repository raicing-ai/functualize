# Offscreen Textual Experiment

Tests whether we can keep a Textual app's event loop running (widgets updating)
while muting its terminal output, letting a separate "execution runtime" own
the physical terminal during job execution.

## What this proves

1. Textual widgets continue receiving messages and updating state while offscreen
2. When rendering resumes, the widgets reflect the correct final state
3. A raw ANSI renderer can own the terminal during the "muted" period

## Run

Interactive experiment (press 's' to start execution mode, 'q' to quit):

```bash
uv run python experiments/offscreen_textual/experiment.py
```

Automated tests (headless proof):

```bash
uv run pytest experiments/offscreen_textual/test_offscreen.py -v
```

## Results

All 4 automated tests pass, proving:

- `_begin_batch()` suppresses rendering but the event loop keeps running
- Widget reactive attributes update normally while offscreen
- Watchers fire for every mutation (no events are lost)
- Async tasks can mutate widget state concurrently
- When `_end_batch()` is called, widgets already have correct final state
- No buffering, journaling, or replay logic is needed

## Key Insight

Textual's `_begin_batch()` / `_end_batch()` (exposed as `batch_update()` context
manager) provides exactly what we need. The rendering path in `App._display()`
early-returns when `_batch_count > 0`, but the message pump, timers, reactives,
and workers all continue normally.

This means during job execution we can:
1. Call `_begin_batch()` to mute Textual's terminal output
2. Let the ExecutionRuntime write raw ANSI to the physical terminal
3. Continue dispatching OutputRenderer events to Textual widgets (they update)
4. Call `_end_batch()` when done — Textual repaints with correct final state
