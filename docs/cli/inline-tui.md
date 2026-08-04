# Inline TUI (bare `func`)

Running `func` with no arguments inside a project launches the **inline TUI** —
an interactive command shell that renders under your prompt (no fullscreen
takeover). It is built for composing and executing jobs with live feedback on
argument completeness and configuration resolution.

> Inline rendering requires Linux or macOS. On Windows, Textual falls back to
> a fullscreen driver.

## The SmartBar

The core of the TUI is the SmartBar — an input line that understands your
jobs. As you type, its border color reports **readiness**:

| Border | State | Meaning |
|--------|-------|---------|
| grey | GREY | No recognized job yet |
| yellow | PENDING | Job recognized, required arguments missing |
| green | READY | Command is complete and executable |
| accent | INSERT | You are editing a field value (INSERT mode) |
| red | INVALID | The last edit failed validation |

Press ++tab++ to toggle autocomplete (job names, flags, values with history).
When the bar is READY, ++ctrl+enter++ executes the job in place and streams
its log output below the bar.

## Modes

The TUI is modal, in the vim sense:

- **COMMAND** — default; you type in the SmartBar.
- **NORMAL** — panel navigation (entered when a panel ring opens); keys act
  on the focused panel, stray printable keys are suppressed.
- **INSERT** — editing a single field value (entered with ++i++ on a panel
  row); ++enter++ confirms, ++escape++ cancels.
- **FILTER** — the SmartBar is repurposed as a filter box for the active
  panel (entered with ++slash++); ++enter++ applies, ++escape++ clears.

The status bar at the bottom always shows the current mode and zone.

## Panel rings

Two panel rings give structured views over your command and project:

- ++ctrl+r++ — **command ring** (needs a recognized job): Config Table
  (all fields with effective values and sources), Config Files (the files
  contributing values, editable), and Diff View (current values vs. the last
  run's snapshot).
- ++ctrl+e++ — **general ring**: Jobs (browse and select any discovered
  job) and Settings.

Inside a ring (NORMAL mode):

| Key | Action |
|-----|--------|
| ++j++ / ++k++ / ++h++ / ++l++ (or arrows) | Move the cursor |
| ++ctrl+j++ / ++ctrl+k++ | Next / previous panel in the ring |
| ++ctrl+g++ | First panel in the ring |
| ++ctrl+l++ | Last panel in the ring |
| ++i++ | Edit the selected field (INSERT mode) |
| ++shift+i++ | Persist the selected override to a config file |
| ++r++ | Reset the selected field's override |
| ++slash++ | Filter the panel (FILTER mode) |
| ++enter++ | Drill down (resolution chain / file detail) |
| ++escape++ | Back out of drill-down, then close the ring |

Edits made in the Config Table and text typed in the SmartBar stay in sync —
the bar is the single source of truth for the command being composed.

## The Detail screen

++enter++ on a **Config Files** row or a **Settings** row opens the same Detail
screen, viewed along different axes:

- From **Config Files**, rows are the job's config keys: what *this file* sets,
  what value actually takes effect, and whether this file wins.
- From **Settings**, rows are the sources for one setting, highest precedence
  first — so you can see exactly which layer is deciding the value.

| Marker | Meaning |
|--------|---------|
| `★ winning` | This source decides the effective value |
| `● overridden` | This source sets a value, but a higher one wins |
| `— not set` | This source has no opinion on this key |
| `🔒` | Read-only source (env vars and defaults can't be edited here) |

| Key | Action |
|-----|--------|
| ++j++ / ++k++ | Move the cursor |
| ++i++ | Edit the row's value (INSERT mode) — **staged**, not written |
| ++d++ | Toggle removal of the row's key — also staged |
| ++ctrl+s++ | Write all staged changes to disk, atomically |
| ++escape++ | Discard staged changes and go back |

Nothing touches disk until ++ctrl+s++, which is why ++escape++ can discard
without a confirmation prompt. Values are written with their declared type, so
editing a port writes `port = 9090`, not `port = "9090"`.

## Settings

The Settings panel (General ring, ++ctrl+e++) covers **every** functualize
setting — `[tui]`, `[cli]`, `[discovery]`, and the top-level keys such as
`dotenv` — and resolves through the same files the rest of `func` reads,
lowest to highest:

1. built-in defaults
2. `~/.config/functualize/config.toml` — the global config, for your
   personal preferences across every project
3. project config, found by searching upward from the current directory:
   `pyproject.toml` `[tool.functualize]`, `.functualize.toml`, or
   `.functualize/.functualize.toml` — lets a repo pin settings for everyone
   working in it. Nearest file wins
4. `FUNCTUALIZE_<SECTION>_<KEY>` environment variables (e.g.
   `FUNCTUALIZE_TUI_THEME=dark`, `FUNCTUALIZE_CLI_OUTPUT=json`) — highest,
   for one-off overrides

```toml
# ~/.config/functualize/config.toml
[tui]
theme = "dark"
history_retention = 250

[cli]
output = "rich"
```

There is no separate settings file: the TUI's knobs are a `[tui]` section of
the ordinary config files. A value that fails validation is ignored and the
next layer down wins, so a hand-edited typo degrades rather than breaking
the TUI.

The **Settings Files** panel (next in the General ring) lists those files
with their status, mirroring the Config Files panel. Enter drills into a
file's Detail view; ++n++ offers the conventional locations for creating a
new one — including the global `config.toml` if it doesn't exist yet.
Nothing is created until ++ctrl+s++ in the Detail view.

Pressing ++n++ works on the Config Files panel too, offering
`config.base.toml` and the active environment's overlay
(`config.<env>.toml`) in the project's config directories.

## Other keys (COMMAND mode)

| Key | Action |
|-----|--------|
| ++tab++ | Toggle autocomplete |
| ++ctrl+enter++ | Execute (when READY) or open the command ring (when PENDING) |
| ++enter++ | Execute (fallback for terminals without Ctrl+Enter support — only fires when READY and the autocomplete dropdown is closed) |
| ++ctrl+s++ | Save the current command as a reusable shortcut |
| ++ctrl+u++ | Previous display provider (when a display slot is active) |
| ++ctrl+o++ | Next display provider (when a display slot is active) |
| ++shift+tab++ | Cycle focus between visible zones |
| ++escape++ | Clear the SmartBar |
| ++ctrl+q++ | Quit |

!!! warning "Terminal compatibility"
    - ++ctrl+enter++ requires a terminal supporting the Kitty keyboard
      protocol (Kitty, WezTerm, foot, recent Ghostty/Alacritty). On older
      terminals it arrives as plain ++enter++ — use plain ++enter++ directly
      as the execute fallback (see table above); it works in every terminal.
    - ++ctrl+i++ and ++ctrl+h++ are never bound to anything: terminals encode
      them as ++tab++ and ++backspace++, so a binding on those names could
      never fire. The next-display-provider and first-panel-ring actions
      previously attempted on those keys now use ++ctrl+o++ and ++ctrl+g++
      instead, which terminals deliver unaliased. See
      `tests/tui_audit/test_key_aliasing.py` for the executable proof.

## Execution and snapshots

Executing a job runs it in-process and streams `rc.log()` output into the
output panel. On completion (success or failure), the effective configuration
is recorded as a **snapshot**; the Diff View panel compares your next
invocation against it, and argument values are remembered for autocomplete
history.

!!! note "Long-running jobs"
    Job execution runs in a background thread, so the interface stays
    responsive — key presses, panel navigation, and log rendering continue
    while a job is running. A second execute trigger while a job is already
    running is ignored rather than queued or interrupted.

## Related pages

- [Execution Modes](modes.md) — when bare `func` launches the TUI vs. lists jobs
- [Configuration](config.md) — the precedence chain shown in the Config Table
- [Aliases](aliases.md) and shortcut files — where ++ctrl+s++ output fits in
