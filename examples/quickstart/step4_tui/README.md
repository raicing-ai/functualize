# Step 4 — Browse and Run Jobs Interactively (Inline TUI)

Bare `func` in a jobs directory opens the inline TUI: a smart command shell rendered under your prompt (not fullscreen).

## Walkthrough

```bash
cd examples/quickstart/step4_tui
func
```

1. **Type `report`** — the SmartBar border turns **green** (READY) immediately: no required args. Press **Ctrl+Enter** to run it in place; log output streams below the bar.
2. **Type `forecast`** — the bar is **yellow** (PENDING): `--city` is required. Press **Tab** to autocomplete flags, type `--city Tokyo`, and the bar turns green.
3. **Type `compare --city-a Tokyo --city-b Oslo --unit `** — with a trailing space after `--unit`, enum value completions appear (`celsius`, `fahrenheit`).
4. **Press Ctrl+R** — the config panel ring shows every field with its effective value and provenance (CLI / env / config file / default).
5. **Press Ctrl+E** — the general ring: browse all discovered jobs (j/k to navigate) and TUI settings.

SmartBar readiness colors: grey (no job) → yellow PENDING (args missing) → green READY (executable) → red INVALID.

Requires the CLI extra: `pip install "functualize[cli]"`. Inline rendering needs Linux/macOS (Windows falls back to fullscreen).

## More TUI scenarios

Per-feature scenarios (config expansion, value completions, display providers, panel rings, …) live in [`examples/standalone/showcase/`](../../standalone/showcase/).

## Related Documentation

- [Inline TUI reference](../../../docs/cli/inline-tui.md)
