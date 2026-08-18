---
name: observe-tui
description: >
  Observe and drive the live functualize TUI/CLI in a real PTY so an agent (or
  human) can SEE what the terminal renders. Use when debugging TUI/CLI behavior,
  verifying that a change affects the rendered screen as intended, checking
  TTY-vs-non-TTY divergence, or when asked to manually try examples/flows one by
  one and confirm they run. Also provides container-based sandboxing for testing
  installation instructions, destructive operations, and system-level experiments
  in isolated disposable environments. NOT for writing automated tests —
  Pilot/snapshot tests remain the enforcement layer.
---

# Observe TUI/CLI

Agents developing CLI/TUI features normally cannot see what the terminal
renders. This skill gives you eyes: run the real app in a pseudo-terminal,
reconstruct the screen with an in-memory terminal emulator (pyte), and read it
as plain text — or keep a session alive across turns with tmux.

## Hard boundary: manual/agent verification ONLY

**Never use these tools in automated tests.** Do not import `tui_probe.py`
from pytest, do not add PTY-probe assertions to CI, do not turn these recipes
into test files. The enforcement layer for TUI correctness is and remains:
unit/property tests, Pilot tests (`run_test()`), and `pytest-textual-snapshot`
(see `contributor/guides/steering_textual_tui.md` §4). PTY probing is slower,
timing-sensitive, and environment-dependent — fine for a human-in-the-loop or
agent debugging session, flaky as a gate.

Legitimate uses:

- Debugging: "why does my panel render empty?" — look at the actual screen.
- Change verification: after editing TUI/CLI code, confirm the rendered result
  matches the intent before declaring done (complements `/verify`).
- Exploratory QA on request, e.g. the user says *"try all the examples one by
  one and make sure they run as intended"* — boot each example's TUI, drive a
  command, read the screen, report.
- Checking TTY-dependent branches: bare `func` launches the inline TUI on a
  TTY but prints a plain job list when piped (`src/functualize/_cli/main.py`).
  Only a PTY probe can exercise the TTY branch headlessly.

## Tier 1 — scripted one-shot observation (pyte probe)

The bundled probe spawns a command in a PTY, feeds output through
`pyte.Screen`, and runs an ordered scenario. Zero install: `pyte` is pulled
ad-hoc via `uv run --with pyte`; `ptyprocess` already ships with the dev env
(dependency of `pexpect`).

```bash
# Boot the inline TUI in an example project and confirm it renders
uv run --with pyte python .claude/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/quickstart --step "wait:Type a command" -- uv run func

# Drive it: type into the SmartBar, run a job, watch the result
uv run --with pyte python .claude/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/quickstart \
    --step "wait:Type a command" \
    --step "send:hello<enter>" \
    --step sleep:2 --step "snap:after run" \
    -- uv run func
```

Step kinds (executed in order; a final snapshot always prints):

| Step | Effect |
|---|---|
| `wait:TEXT` | Block until TEXT appears anywhere on screen (`--timeout`, default 20s). Exit code 2 on timeout. |
| `send:KEYS` | Write keys to the PTY. Named tokens: `<enter> <tab> <esc> <space> <backspace> <up> <down> <left> <right> <home> <end> <pgup> <pgdn> <ctrl+X>`. |
| `snap[:LABEL]` | Print the current screen (boxed, with cursor position and process status). |
| `sleep:SECS` | Keep pumping output for SECS seconds. |

Options: `--cwd DIR`, `--cols N --rows N` (default 100×30 — match what you are
debugging), `--timeout SECS`. Command goes after `--`.

Reading results: `wait:` returning ✗ TIMEOUT means the text never rendered —
the screen dump printed after it shows what rendered instead (often a
traceback). `feed_errors` non-empty means pyte hit escape sequences it could
not parse; treat the dump as approximate.

Validated 2026-07-18 against `examples/quickstart` (Textual 8.x inline TUI):
clean render, zero feed errors, keystrokes delivered.

## Tier 2 — persistent session across multiple turns (tmux)

When you need to keep the app alive between separate Bash calls (exploratory
poking, watching a long-running job), use tmux instead of the one-shot probe:

```bash
tmux new-session -d -s probe -x 100 -y 30 -c examples/quickstart 'uv run func'
tmux capture-pane -pt probe          # read the screen (repeat any time)
tmux send-keys -t probe 'hello' Enter
tmux capture-pane -pt probe
tmux kill-session -t probe           # ALWAYS clean up when done
```

Do not busy-poll with sleep loops — capture, decide, act, capture again.
If [`boo`](https://github.com/coder/boo) is installed (`command -v boo`), its
`peek` / `wait` / `send` subcommands are a sharper agent interface for the
same job; prefer it over tmux when available. It is not currently installed.

## Gotchas

- **Textual writes terminal queries** (device attributes, etc.) and gets no
  replies from pyte/tmux; it degrades gracefully — expect default color
  handling, not your terminal's exact palette. Layout and text are faithful.
- **Scrollback is lost** in the pyte probe (fixed-size screen). For long
  non-interactive output, just run the command normally through Bash; use the
  probe only when TTY behavior matters.
- **First boot may be slow** (`uv run` may build the env). If `wait:` times
  out on a cold cache, re-run once before concluding the TUI is broken.
- **Warnings above the TUI** (e.g. `VIRTUAL_ENV` mismatch from nested
  `uv run`) appear in the screen dump; they come from the environment, not
  necessarily from your change.
- Kill what you spawn: the probe terminates its child on exit, but tmux
  sessions persist — always `tmux kill-session` when finished.


## Tier 3 — container sandbox (docker/podman)

When you need a **clean, isolated environment** — testing installation docs,
running destructive operations, verifying the package works from a fresh
`pip install`, or exercising system-level experiments that could damage the
host — use an ephemeral container. The container is disposable: it starts
clean, you run your experiment, and it vanishes.

### When to use containers (vs Tier 1/2)

| Scenario | Use container? |
|---|---|
| Verify the README / docs installation instructions work from scratch | ✓ |
| Test `pip install functualize` or `uv pip install functualize` in a fresh env | ✓ |
| Run destructive operations (rm -rf, global config changes, system package installs) | ✓ |
| Test behavior on a different Python version or distro | ✓ |
| Validate that the built wheel/sdist installs and runs correctly | ✓ |
| Exercise the CLI as an end-user would (no dev dependencies) | ✓ |
| Inspect TUI rendering within the current dev environment | ✗ (use Tier 1/2) |
| Debug specific code paths with breakpoints | ✗ (use normal dev workflow) |

### Container engine detection

The skill is engine-agnostic. Use whichever of `docker` or `podman` is
available — they share the same CLI interface for our purposes:

```bash
# Detect available engine (prefer podman for rootless security)
CONTAINER_ENGINE=$(command -v podman 2>/dev/null || command -v docker 2>/dev/null)
if [ -z "$CONTAINER_ENGINE" ]; then
  echo "ERROR: neither podman nor docker found" >&2
  exit 1
fi
```

All examples below use the variable `$CE` as shorthand for whichever engine is
available. In practice, substitute `docker` or `podman` directly.

### Recipe 1: Test installation instructions (one-shot)

Spin up a clean Python container, mount the project source read-only, and run
the documented install steps exactly as a user would:

```bash
# Test: "pip install from local source" path in README
podman run --rm -it \
  -v "$(pwd)":/src:ro \
  -w /src \
  python:3.11-slim \
  bash -c '
    pip install . &&
    functualize --version &&
    echo "✓ Install from source works"
  '
```

```bash
# Test: "pip install from wheel" (build first, then install in clean container)
uv build --wheel
podman run --rm \
  -v "$(pwd)/dist":/dist:ro \
  python:3.11-slim \
  bash -c '
    pip install /dist/*.whl &&
    func --help &&
    echo "✓ Wheel installs cleanly"
  '
```

```bash
# Test: "uv-based install" as documented
podman run --rm \
  -v "$(pwd)":/src:ro \
  -w /src \
  python:3.11-slim \
  bash -c '
    pip install uv &&
    uv pip install --system . &&
    func --version &&
    echo "✓ uv install path works"
  '
```

### Recipe 2: Test with a specific Python version

```bash
# Verify compatibility across Python versions
for pyver in 3.10 3.11 3.12 3.13; do
  echo "=== Python $pyver ==="
  podman run --rm \
    -v "$(pwd)":/src:ro \
    -w /src \
    "python:${pyver}-slim" \
    bash -c "pip install -q . && func --version"
done
```

### Recipe 3: Interactive exploration / destructive experiments

When you need to poke around, install extra tools, or do things that would
pollute the host:

```bash
# Interactive shell in a clean environment with source mounted
podman run --rm -it \
  -v "$(pwd)":/src:ro \
  -w /src \
  python:3.11-slim \
  bash

# Once inside:
# pip install .               ← install functualize
# pip install functualize[cli] ← with CLI extras
# func scaffold myproject     ← test scaffolding (writes to container, not host)
# rm -rf /everything          ← go wild, it's disposable
```

For experiments that need to write back results:

```bash
# Mount a local scratch dir read-write for outputs
mkdir -p /tmp/sandbox-out
podman run --rm -it \
  -v "$(pwd)":/src:ro \
  -v /tmp/sandbox-out:/out:rw \
  -w /src \
  python:3.11-slim \
  bash -c '
    pip install . &&
    func scaffold /out/test-project &&
    echo "✓ Scaffold output saved to /out"
  '
# Inspect results on host at /tmp/sandbox-out/test-project
```

### Recipe 4: Test the TUI/CLI in a container PTY

Combine Tier 1 (pyte probe) with containers for clean-room TUI verification:

```bash
# Run the pyte probe INSIDE a container with a real PTY
podman run --rm -it \
  -v "$(pwd)":/src:ro \
  -w /src \
  python:3.11-slim \
  bash -c '
    pip install -q . &&
    pip install pyte ptyprocess &&
    cd /tmp && func scaffold test-app && cd test-app &&
    python /src/.claude/skills/observe-tui/scripts/tui_probe.py \
      --step "wait:Type a command" \
      --step "snap:fresh-install-tui" \
      -- func
  '
```

### Recipe 5: Named container for multi-step verification

When one-shot `--rm` isn't enough (you need multiple exec calls across turns):

```bash
# Create and start (kept alive with sleep)
podman run -d --name sandbox \
  -v "$(pwd)":/src:ro \
  -w /src \
  python:3.11-slim \
  sleep infinity

# Run commands against it across multiple turns
podman exec sandbox pip install .
podman exec sandbox func --version
podman exec sandbox bash -c 'cd /tmp && func scaffold myapp && ls myapp/'

# Interactive session when needed
podman exec -it sandbox bash

# ALWAYS clean up when done
podman rm -f sandbox
```

### Recipe 6: Test documentation end-to-end (full README walkthrough)

Script the entire getting-started documentation as a single container run to
catch stale instructions:

```bash
podman run --rm \
  -v "$(pwd)":/src:ro \
  python:3.11-slim \
  bash -c '
    set -e
    echo "Step 1: Install"
    pip install /src[cli]

    echo "Step 2: Scaffold a new project"
    cd /tmp && func scaffold weather-app && cd weather-app

    echo "Step 3: Create a job file"
    mkdir -p jobs
    cat > jobs/hello.py << '\''EOF'\''
def greet(name: str = "world"):
    """Say hello."""
    print(f"Hello, {name}!")
EOF

    echo "Step 4: Run the job"
    func greet --name "Container"

    echo "✓ Full README walkthrough passed"
  '
```

### Best practices for container sandboxing

1. **Always use `--rm`** for one-shot experiments. Forgotten containers
   accumulate and waste disk.

2. **Mount source as read-only** (`:ro`) unless you explicitly need write-back.
   This prevents accidental modification of your working tree.

3. **Prefer `podman` over `docker`** when available — rootless by default,
   no daemon required, identical CLI. Falls back transparently.

4. **Use slim images** (`python:X.Y-slim`) for speed. Full images add 500MB+
   and you rarely need the extra system packages.

5. **Pin the Python version** in the image tag to match what you're testing.
   Don't use `python:latest` — results won't be reproducible.

6. **Don't cache pip downloads** in ephemeral containers — it's wasted I/O.
   The point is a clean slate each time.

7. **Named containers** (`--name sandbox`) are useful for multi-turn agent
   sessions but **must be cleaned up** (`podman rm -f sandbox`) when the
   session ends. Create a cleanup habit.

8. **Network access**: containers have network by default. For true isolation
   (e.g., testing offline install from a wheel), add `--network=none`.

9. **Combining with the pyte probe**: mount the skill scripts read-only and
   run the probe inside the container for clean-room TUI testing (Recipe 4).

### Choosing between Tier 1/2 and Tier 3

```
Need to see the TUI as rendered? ──┐
                                    ├─ Current dev env OK? → Tier 1 (pyte) or Tier 2 (tmux)
                                    └─ Need clean install? → Tier 3 container + pyte inside

Need to test installation docs?   → Tier 3 (always)
Need destructive operations?      → Tier 3 (always)
Need a different Python/OS?       → Tier 3 (always)
Need to keep state across turns?  → Tier 2 (tmux) or Tier 3 (named container)
Quick one-shot screen check?      → Tier 1 (pyte probe, fastest)
```
