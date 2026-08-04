# Showcase — the all-in-one standalone example

One directory that exercises (almost) everything `func` can do: the three CLI
modes, the inline TUI with all its panels and completion flows, every rendering
surface (plain stdout, live zones, full-screen terminal ownership), layered
config resolution, ambient displays, and AI in both directions.

Everything below runs from **this directory**:

```bash
cd examples/standalone/showcase
```

## Layout

| Path | Purpose |
|------|---------|
| `.functualize.toml` | Project settings in the non-`pyproject.toml` format (`jobs_directories`) — job *values* live in the `config.*.toml` layer files |
| `config.base.toml` | Base config: `[tui] default_surface` + baseline `release` values |
| `config.dev.toml` | DEV overlay (active by default) — overrides some `release` values |
| `jobs/basics.py` | `status`, `ping`, `send`, `migrate` — SmartBar flows by required-arg count |
| `jobs/deploys.py` | `deploy`, `deploy_rollback`, `deploy_status`, `build`, `inspect` — autocomplete, enum value completions, full modal, path fields |
| `jobs/configcheck.py` | `release`, `analyze`, `healthcheck` — config inspector, source chain, sensitive-field masking |
| `jobs/surfaces.py` | `greet`, `sync`, `fetch`, `edit`, `report` — plain / live / scrollback / full-screen / adaptive surfaces |
| `jobs/unix_style.py` | `say`, `transform`, `ship` — positional args, short flags, stdin |
| `jobs/ai_jobs.py` | `ai_write` (outbound AI), `ai_review` (inbound AI) — key-free via `MockAI` |
| `displays.py` | `GitBranchDisplay` + `PythonDisplay` — ambient displays above the TUI header |
| `scripts/` | Mode A single-file jobs: `hello.py`, `tasks.py`, `data_processor.py` (not discovered — run by path) |
| `test_showcase.py` | Unit tests proving every job body works |

## Setup

```bash
pip install "functualize[cli]" functualize-ai functualize-state functualize-tasks
# or, from the repo root, use the dev env:  uv sync --all-extras
```

In the checklists below, `func` means `func` from your install — inside this
repo use `uv run func`.

---

## Part 1 — CLI (no TUI)

### 1.1 Mode A: single-file execution (`scripts/`)

The `scripts/` folder is *not* in `jobs_directories`, so these files are only
reachable by path — exactly what Mode A is for.

```bash
func scripts/hello.py greet --name World          # → Hello, World!
func scripts/hello.py greet --name Alice --enthusiasm 3   # → Hello, Alice!!!
func scripts/tasks.py deploy --target production  # → Deployed to production
func scripts/tasks.py status                      # → All systems operational
func scripts/data_processor.py process --input-path ./sample.csv --format json
func scripts/data_processor.py summarize --input-path ./sample.csv
```

- [ ] Each command runs the named function; its log/print output is shown
  (direct runs surface output, not return values)
- [ ] `func scripts/tasks.py` (multiple jobs, no name) lists the file's functions

### 1.2 Mode B: run discovered jobs by name

```bash
func healthcheck                 # no-arg job
func send --message "hi there"   # required flag
func say World -g hey            # positional arg + short flag  → hey, World!
echo "hello world" | func transform -f title      # stdin feeds the [stdin] param
func ship staging -i api:v2 -r 5 --dry-run        # positional + short flags + bool
func ai-write --topic "Python async patterns" --style tutorial
func ai-review --repo my-org/api --focus security
```

- [ ] `say`/`ship` accept positional values without flag names
- [ ] `transform` reads piped stdin when `--data` is omitted; an explicit
  `--data` value wins over the pipe
- [ ] The AI jobs run without any API key (MockAI) and print structured results

### 1.3 Mode C: listing

```bash
func | cat        # piped → plain listing, no TUI
```

- [ ] All 22 jobs from `jobs/` are listed; nothing from `scripts/` or `tests/` appears

### 1.4 Direct-run surfaces (no TUI involved)

```bash
func sync --files 6      # live-updating table at the bottom + per-file log lines above it
func fetch --endpoints 6 # scrollback only: log(), rc.log(), and dim ⚡ event lines
func edit                # full-screen editor owns the terminal; Ctrl+Q quits back to the shell
func report              # in a terminal: full-screen table (q to quit)
func report | cat        # piped: same job degrades to the live-table path, plain output
```

- [ ] `sync` shows a redrawing table while ✓-lines scroll into history above it
- [ ] `edit` refuses with a clear message when piped: `func edit | cat`
- [ ] `report` adapts: full-screen when it owns a terminal, plain/live otherwise

---

## Part 2 — Inline TUI

Launch with a bare `func` in a real terminal. Keyboard reference: **Tab**
autocomplete · **Shift+Tab** cycle focus zones · **Enter / Ctrl+Enter** run a
ready command · **Ctrl+R** toggle the pre-flight ring · **Ctrl+E** settings
ring · **Ctrl+J/K** next/prev panel · **Ctrl+U/O** cycle displays (Ctrl+I is
Tab in terminals and is never bound) · **Ctrl+S** save shortcut · **Esc** back ·
**Ctrl+Q** quit.

### 2.1 SmartBar flows (jobs graded by required args)

| Type this | Expect |
|-----------|--------|
| `status` | Bar turns **green** (`● Ready`) immediately; Enter executes; log lines + `✓ Done` appear below |
| `ping` | Green (all optional); Enter runs with defaults |
| `send` | Pending (1 required); Ctrl+R opens the Config Table with `message` marked `○ *` |
| `migrate` | Pending (3 required); Config Table shows 3 required fields, `direction` offers up/down |
| `deploy` | Pending (5 required); Ctrl+R → Config Table with `service/version/env/region/protocol` required |

- [ ] Ctrl+S on a green-bar command opens the shortcut save dialog

### 2.2 Autocomplete & value completions

- [ ] Empty bar + Tab → all jobs listed; typing `dep` filters to the `deploy*` family
- [ ] `deploy --` → flag completions; a flag already used disappears from the list
- [ ] `deploy --env ` (trailing space) → `dev staging production canary`
- [ ] `deploy --env s` → filters to `staging`
- [ ] `inspect --level ` → log levels; `inspect --format ` → json/text/table/csv
- [ ] `build --source-dir ./` → filesystem path suggestions
- [ ] `say ` → the dropdown offers the positional slot `<name>  ([1] name str)`; `transform`'s `data` accepts stdin (see §1.2)

### 2.3 Pre-flight ring (Ctrl+R on a grey bar)

1. Type `deploy` (leave args empty, Esc to dismiss the dropdown) → press **Ctrl+R**
   - [ ] Config Table opens (`[R:1/3]`): `service/version/env/region/protocol` required (`○ *`), the rest show defaults with `source: default`
2. **Ctrl+J** → next panel in the ring (Config Files, then Diff); **Ctrl+K** → back
3. j/k navigate; **Enter** drills into Field Detail; **i** edits inline; **r** resets an override; **/** filters; **Esc** pops back
4. **Ctrl+R** again → collapses the ring
5. Complete the command → bar green → **Enter** executes

### 2.4 Config inspector (the `release` job)

Launch as: `RELEASE_DB_PASSWORD=env-secret-pw func`

1. Type `release` (green — all optional) → **Ctrl+R** to open pre-flight
2. The Config Table shows each field's winning value **and its source**:
   - [ ] `environment` → `dev`, source **file** (the DEV overlay)
   - [ ] `region` → `us-west-2`, source file (dev overlay beat base's `us-east-1`)
   - [ ] `replicas` → 1 from `config.dev.toml` (base had 2, default 3)
   - [ ] `timeout` → 60 from `config.base.toml` (default 30)
   - [ ] `api_key` → from `config.base.toml`, **masked** in field detail
   - [ ] `db_password` → source **env** (`env-secret-pw`); `analyze`'s `output_token` masked too ("token" keyword)
3. **Ctrl+J** → Config Files panel
   - [ ] `config.base.toml` (env `base`) and `config.dev.toml` (env `dev`) both listed as ★ active
4. Environment banding: quit, relaunch as `FUNCTUALIZE_ENV=prod func`
   - [ ] `release` now resolves `region us-east-1`, `replicas 2` (dev overlay inert)
5. `healthcheck` + Ctrl+R
   - [ ] Pre-flight shows "No configuration fields for this job"

### 2.5 Settings ring & displays

- [ ] **Ctrl+E** → general ring (works with an empty bar): `[E:1/3]` Jobs → Ctrl+J → `[E:2/3]` Settings → `[E:3/3]` Settings Files; Ctrl+E again collapses
- [ ] On launch the display slot above the header shows **Git** (`⎇ <branch>`) — from `displays.py`
- [ ] **Ctrl+U / Ctrl+O** cycle to the **Python** display and back
- [ ] **Shift+Tab** cycles focus SmartBar → display zone → panel slot; Esc returns
- [ ] Type `report` → the Git display surfaces (it declares `linked_jobs = ["report"]`)

### 2.6 Surfaces from inside the TUI

- [ ] `greet --name TUI` → output renders in the TUI panel (default_surface = panel)
- [ ] `sync --files 6` → live table + scrollback lines in the TUI's stdout zone
- [ ] `edit` → the TUI steps aside, the full-screen editor owns the terminal, quitting (Ctrl+Q) relaunches the TUI
- [ ] `report` → full-screen table (the adaptive job got terminal ownership); q returns
- [ ] Relaunch as `FUNCTUALIZE_TUI_DEFAULT_SURFACE=stdout func` → `greet` now prints to the stdout zone instead of the panel

---

## Part 3 — Automated tests

```bash
uv run pytest examples/standalone/showcase/ -v
```

- [ ] All tests pass — they call every job body directly (TUI behavior is the
  manual checklist above; Pilot/snapshot tests in `tests/` are the enforcement
  layer)

## Related documentation

- [CLI Modes](../../../docs/cli/modes.md) · [Configuration](../../../docs/cli/config.md) · [Interactivity & Surfaces](../../../docs/guides/interactivity.md) · [AI Guide](../../../docs/guides/ai.md) · [MCP Guide](../../../docs/guides/mcp.md)
- Discovery filters have their own lab: [`../discovery_lab/`](../discovery_lab/) · config precedence: [`../config_lab/`](../config_lab/)
