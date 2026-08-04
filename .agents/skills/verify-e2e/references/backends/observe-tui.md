# Backend: observe-tui

How to construct and interpret pyte probe commands for E2E TUI validation.

---

## Prerequisites

- The observe-tui skill's pyte probe script exists at: `.agents/skills/observe-tui/scripts/tui_probe.py`
- `uv run --with pyte` is available (pyte is pulled ad-hoc, not a project dependency)
- `ptyprocess` is available (ships with dev env via pexpect)

If the probe script is missing, report that E2E validation cannot run and suggest the user check the observe-tui skill installation.

---

## Command Template

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd <example_dir> \
    [--cols N --rows N] \
    [--timeout SECS] \
    --step "<step1>" \
    --step "<step2>" \
    ... \
    -- <command>
```

Default dimensions: `100×30`. Default timeout: `20s`.

For verify-e2e, always use `--timeout 30` (accounts for cold uv cache on first boot).

---

## Step Kinds

| Step | Syntax | Effect |
|------|--------|--------|
| Wait for text | `wait:TEXT` | Block until TEXT appears anywhere on screen. Exit 2 on timeout. |
| Send keystrokes | `send:KEYS` | Write keys to PTY. |
| Snapshot | `snap:LABEL` | Print current screen (boxed, with cursor and process status). |
| Sleep | `sleep:SECS` | Keep pumping output for SECS seconds. |

A final snapshot always prints regardless of whether an explicit `snap:` step exists.

---

## Key Mapping for `send:` Steps

| Key | Token |
|-----|-------|
| Enter | `<enter>` |
| Tab | `<tab>` |
| Escape | `<esc>` |
| Space | `<space>` |
| Backspace | `<backspace>` |
| Up/Down/Left/Right | `<up>` `<down>` `<left>` `<right>` |
| Home/End | `<home>` `<end>` |
| Page Up/Down | `<pgup>` `<pgdn>` |
| Ctrl+X | `<ctrl+x>` (lowercase letter) |
| Shift+Tab | `<shift+tab>` |

Plain text is sent as-is: `send:ping` types the characters p, i, n, g.

Combine text and special keys: `send:status<enter>` types "status" then presses Enter.

---

## Probe Recipes

### Smoke (boot + one job)

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/standalone/showcase \
    --timeout 30 \
    --step "wait:Type a command" \
    --step "send:status<enter>" \
    --step "sleep:2" \
    --step "snap:smoke" \
    -- uv run func
```

Pass: exit 0, "Type a command" rendered, no traceback in dump.

### Config panel validation

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/standalone/showcase \
    --timeout 30 \
    --step "wait:Type a command" \
    --step "send:ping" \
    --step "sleep:1" \
    --step "send:<ctrl+r>" \
    --step "sleep:1" \
    --step "wait:Config Table" \
    --step "snap:config-panel" \
    -- uv run func
```

Pass: "Config Table" appeared, fields visible in dump.

### Job browser / discovery validation

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/standalone/showcase \
    --timeout 30 \
    --step "wait:Type a command" \
    --step "snap:job-list-populated" \
    -- uv run func
```

Pass: TUI booted (jobs were discovered). Check dump for known job names (status, ping, deploy, etc.).

### Execution result validation

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/standalone/showcase \
    --timeout 30 \
    --step "wait:Type a command" \
    --step "send:status<enter>" \
    --step "sleep:3" \
    --step "snap:execution-result" \
    -- uv run func
```

Pass: After execution, screen shows result (success indicator, output text, or return to prompt).

### Pre-flight validation

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/standalone/showcase \
    --timeout 30 \
    --step "wait:Type a command" \
    --step "send:ping" \
    --step "sleep:1" \
    --step "snap:preflight" \
    -- uv run func
```

Pass: Pre-flight summary visible in dump (field names, values, sources).

---

## Interpreting Results

### Exit codes

| Code | Meaning | Verdict |
|------|---------|---------|
| 0 | All steps completed successfully | Proceed to dump analysis |
| 2 | Timeout on a `wait:` step | FAIL — expected text never rendered |
| 1 | Process crashed or other error | FAIL — likely a code bug |

### Screen dump analysis

After a successful probe (exit 0), examine the printed screen dump for:

1. **Tracebacks**: Any Python traceback in the dump = FAIL regardless of exit code
2. **Expected content**: The text/UI elements the claim says should be present
3. **Unexpected content**: Error messages, "not found" text, empty panels where content is expected
4. **`feed_errors`**: If non-empty, pyte couldn't parse some escape sequences. The layout may be approximate but text content is still reliable. Treat as WARN, not FAIL.

### Timing considerations

- First boot after `uv sync` may be slow (building environment). If `wait:` times out on a cold cache, **retry once** before declaring FAIL.
- Use `sleep:2` after `send:` steps for Textual to process events. For complex interactions (panel transitions, drill-downs), use `sleep:2-3`.
- If a probe is consistently timing out, increase `--timeout` to 45s before concluding the TUI is broken.

### False positives

These are NOT failures:
- Warnings above the TUI (e.g., `VIRTUAL_ENV` mismatch) — environmental noise
- Color/styling differences — pyte doesn't reproduce exact terminal colors
- Cursor position off by one — irrelevant to behavioral correctness

---

## Composing Multiple Probes

For FULL-tier validation with many claims, run probes sequentially. Between probes:
- No cleanup needed (each probe spawns and kills its own process)
- Collect results into the report as you go
- If a probe fails, continue to the next (don't short-circuit unless it's a boot failure indicating everything else will fail too)

Exception: if the SMOKE probe (boot + one job) fails, skip all subsequent probes and report "TUI fails to boot — all further validation skipped."
