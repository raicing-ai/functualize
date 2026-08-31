# TUI Command Panel

UX specification for the command panel ring (Ctrl+R) and the pre-flight
summary that appears in the default view. See
`contributor/architecture/tui-architecture.md` for the overall TUI layout,
keybinding map, and focus model this panel ring lives inside.

---

## Overview

The TUI has two config-related display areas that are **mutually exclusive**:

1. **Pre-flight Summary** — a passive, read-only RichLog that shows automatically
   between the SmartBar and the panel slot when a job is recognized AND no panel
   ring is active. It disappears the moment PanelHost activates.

2. **Command Panel Ring** (Ctrl+R) — an interactive PanelHost ring with three
   panels for config editing, file management, and session diffing.

```
┌─────────────────────────────────────────────────────────────────────┐
│  [SmartBar]                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  [Pre-flight Summary]  ← visible when bar is PENDING/READY          │
│                           AND PanelHost is NOT active                │
├─────────────────────────────────────────────────────────────────────┤
│  [PanelHost]           ← visible when Ctrl+R or Ctrl+E toggled on  │
│                           (mutually exclusive with pre-flight)       │
├─────────────────────────────────────────────────────────────────────┤
│  [Output Log]                                                        │
│  [Status Bar]                                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Command Panel Ring (Ctrl+R)

```
  Ctrl+G (first)                         Ctrl+L (last)
    ▼                                         ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│  Config  │──▶│  Config  │──▶│   Diff   │
│  Table   │   │  Files   │   │   View   │
└──────────┘   └──────────┘   └──────────┘
     [1]           [2]             [3]
```

All panels share the same `PendingExecution` state object. Edits in any panel
propagate to all others and sync back to the SmartBar text.

**Available when:** The first SmartBar token matches a known job name (grey, pending, or green bar state).

---

## Panel 1: Config Table

### Purpose

The primary config editing surface. Shows all job fields as a cell-navigable
DataTable with vim-style controls. This is where most config interaction happens.

### Layout

```
┌─ [R:1/3] Config Table ──────────────────────────────────────────┐
│  Setting         │ Value          │ Source      │ Description     │
│  ● region*       │ us-east-1      │ config.toml │ Deploy target   │
│  ▸ ● replicas*  │ 5              │ session     │ Instance count  │
│  ○ timeout*      │                │             │ Max wait secs   │
│  · verbose       │ false          │ default     │ Debug output    │
├──────────────────────────────────────────────────────────────────┤
│  j/k nav  h/l cols  i edit  r reset  / filter  Enter detail     │
│  Ctrl+J/K switch panels  Esc back                                │
└──────────────────────────────────────────────────────────────────┘
```

### Columns

| Column | Content | Editable |
|--------|---------|----------|
| Setting | `indicator name*short_flag` | Read-only (Enter drills down) |
| Value | Current effective value | INSERT mode (i key) |
| Source | Where the value came from | Read-only |
| Description | Field help text | Read-only |

### Indicators

| Symbol | Meaning |
|--------|---------|
| `●` | Field has a value (filled) |
| `○` | Required field, no value yet (blocking execution) |
| `·` | Optional field, no value (non-blocking) |
| `*` | Required field (suffix) |


### Navigation (NORMAL mode, Panel zone focused)

| Key | Action |
|-----|--------|
| j / k | Move cursor down/up (rows wrap) |
| h / l | Move cursor left/right (columns clamp) |
| i | Edit value: enters INSERT mode in SmartBar with current value pre-filled |
| r | Reset field to original chain-resolved value (no-op if unmodified) |
| / | Enter FILTER mode (type to filter fields by name) |
| Enter | Drill down: show resolution chain detail (read-only breadcrumb) |
| Esc | Exit panel (collapse PanelHost, return to SmartBar) |

### Enter → Resolution Chain Detail (Breadcrumb Sub-view)

Pressing Enter on any row pushes a **read-only** breadcrumb level showing the
full resolution chain for that field. This replaces the table content temporarily.

```
┌─ [R:1/3] Config Table > Detail: region ─────────────────────────┐
│                                                                   │
│  Resolution chain for region:                                     │
│                                                                   │
│    ★ CLI              (not set)                                   │
│    ● Session          (not set)                                   │
│    ● Env              DEPLOY_REGION = ""                          │
│    ★ File             config.toml = "us-east-1"    ← winner      │
│    ● Remote           (not configured)                            │
│    ● Default          "us-east-1"                                 │
│                                                                   │
│  Effective: "us-east-1" from file (config.toml)                   │
│                                                                   │
│  Type: str | Required: yes | Choices: us-east-1, us-west-2, ...  │
│  Description: AWS region to deploy to                             │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│  Esc back to table                                                │
└──────────────────────────────────────────────────────────────────┘
```

**Key properties:**
- **Read-only** — no editing in this view. Press Esc to return to the table, then use `i` to edit.
- Shows ALL sources in precedence order (Override → CLI → Env → File → Default).
  There is no `Session` tier and no `Remote` tier: an `i`-key edit becomes a CLI
  token and resolves as `cli`, and nothing in the shipped package constructs a
  `RemoteSource` — `boot.py:781-797` builds `[CliSource, EnvSource, FileSource,
  DefaultSource]`. `Override` is a value deposited by `config.set()` during the
  run, and it outranks CLI (`job_config.py:126-128`, measured).
- `★` marks the winning source, `●` marks others
- Sources with values show the value; sources without show "(not set)" or "(not configured)"
- Shows field metadata: type, required status, choices, description
- If the field has a session override active, a banner shows: `[Session override active]`

**Implementation:** The `ConfigTablePanel` posts a `DrillDownRequested(field_def)` message.
The app receives it, calls `panel_host.push_breadcrumb(f"Detail: {field.name}")`, and
either swaps the panel content or renders into a detail Static below the table. On Esc,
`panel_host.pop_breadcrumb()` restores the table view.

### Edit Flow

**Value edit (i key):**
1. SmartBar switches to INSERT mode, pre-filled with current value
2. Autocomplete shows field choices (if any) or history suggestions
3. Enter confirms → `field.value = new_value`, `field.source = "cli"`
4. SmartBar syncs: `deploy --region us-west-2`

This lives only for this TUI session (the field's source is tagged `"cli"` —
there is no separate persisted "session" source category). To persist a
value to a config file, use the Config Files panel (`Ctrl+J`/`Ctrl+K` to
switch panels within the ring).

**Reset (r):**
- Restores `original_value` and `original_source`
- SmartBar removes the corresponding `--flag value` pair

---

## Panel 2: Config Files

### Purpose

File-centric view of config sources. Shows which files contribute values, their
status (exists/missing/writable), and lets users drill into individual files to
see what they contain and optionally edit values to persist.

### Layout

```
┌─ [R:2/3] Config Files ──────────────────────────────────────────┐
│  File                                   │ Status       │ Fields   │
│  ▸ .functualize.toml [deploy]           │ ● exists     │ region…  │
│    pyproject.toml [tool.functualize.deploy] │ ● exists  │ (none)   │
│    ~/.config/functualize/config.toml    │ ○ not found  │ —        │
├──────────────────────────────────────────────────────────────────┤
│  j/k nav  Enter open  Esc back  Ctrl+J/K switch panels          │
└──────────────────────────────────────────────────────────────────┘
```

### Columns

| Column | Content |
|--------|---------|
| File | Source path + TOML section in brackets (e.g., `.functualize.toml [deploy]`, `pyproject.toml [tool.functualize.deploy]`) |
| Status | `● exists` / `○ not found` / `● exists (read-only)` |
| Fields | Comma-separated list of fields that have values from this file (truncated with `…`). A field declared by a **group** on the job's path is prefixed with its declaring group — `[deploy] env` — because it is read from that group's own section rather than the one in the File column. Unescaped, unlike the `[group]` prefix in the Config Table / pre-flight / diff: this is a plain DataTable cell, not Rich markup |

### Data Source

The panel discovers files by:
1. Scanning all `FieldDef.chain` entries for non-env, non-session, non-default sources
2. Adding ALL standard discovery locations from `ResourceLocator` (`.functualize.toml`, `pyproject.toml`, `~/.config/functualize/config.toml`) — even if no file exists
3. `pyproject.toml` always appears even if the job has no section in it
4. Checking `Path.exists()` and `os.access(path, os.W_OK)` for status
5. Remote sources (SSM, Vault) are excluded — they appear only in the resolution chain detail

**Section naming:** The TOML section is determined by the job's group:
- Ungrouped job `deploy` → section `[deploy]`
- Grouped job `infra.provision` (JOB_GROUP="infra") → section `[infra]`
- Nested group `infra.aws.launch` → section `[infra.aws]`
- In `pyproject.toml`: `[tool.functualize.<section>]`

**Format support:** TOML only. INI is not in the chain by default — post-ADR-007
`boot.py:499` registers `TomlFormatProvider` alone, and `IniFormatProvider` ships
in-tree but must be registered by a plugin. Where a plugin has registered it, INI
values are visible in the resolution chain detail view but are still not editable
through this panel.

### Navigation

| Key | Action |
|-----|--------|
| j / k | Navigate rows |
| Enter | Drill into file (shows all job fields as they appear in this file) |
| Esc | Exit panel / pop breadcrumb if in drill-down |

### Enter → File Detail (Breadcrumb Sub-view)

```
┌─ [R:2/3] Config Files > .functualize.toml ──────────────────────┐
│                                                                   │
│  Fields from .functualize.toml (section: [deploy]):               │
│                                                                   │
│  Field         │ Value in file    │ Status                        │
│  ▸ region      │ "us-east-1"     │ ★ winning                     │
│    timeout     │ "60"            │ overridden by env              │
│    replicas    │ (not set)       │ —                              │
│    verbose     │ (not set)       │ —                              │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│  j/k nav  i edit  d remove  Ctrl+S save  Esc back (discard)     │
└──────────────────────────────────────────────────────────────────┘
```

**Sub-view properties:**
- Shows ALL job fields (not just ones with values in this file)
- "Value in file" shows what this specific file provides (or `(not set)` if absent)
- "Status" indicates: `★ winning` if this file's value is the effective one, `overridden by <source>` if another source takes precedence, `—` if no value here
- Editing is **staged** — changes accumulate in memory until Ctrl+S commits them

### File Edit Interaction

| Key | Action |
|-----|--------|
| i | Edit field value (INSERT mode in SmartBar, same as Config Table) |
| d | Mark field for removal from this file (toggle) |
| Ctrl+S | Write all staged changes atomically to the file |
| Esc | Discard staged changes, return to file list |

**On Ctrl+S:**
1. Reads current file content
2. Applies staged edits (set/remove keys in the appropriate `[section]`)
3. Writes atomically (tempfile + rename)
4. Updates the `ResolutionChain` and refreshes all panels
5. Pops breadcrumb back to file list with success notification

**Constraint:** If file doesn't exist and user edits a value, Ctrl+S creates the
file with a minimal TOML template — only the section header and the edited keys:

```toml
[deploy]
region = "us-east-1"
```

For grouped jobs, the section uses the group name:
```toml
[infra]
timeout = "30"
```

For `pyproject.toml`, uses the nested tool section:
```toml
[tool.functualize.deploy]
region = "us-east-1"
```

---

## Panel 3: Diff View

### Purpose

Shows what changed in the current session compared to the last execution of this
job. Helps users answer "what's different this time?" and optionally load values
from a past session.

### Layout

```
┌─ [R:3/3] Diff View ─────────────────────────────────────────────┐
│  Config Diff from Previous Session                                │
│                                                                   │
│  ~ region:    "us-west-2" → "us-east-1"    (session)             │
│    replicas:  "5"                           (config.toml)         │
│  + timeout:   "30"                          (new field)           │
│  - old_flag:  "yes"                         (removed)             │
│                                                                   │
│  Session History (press u to browse):                             │
│    2026-07-04 14:30 ✓  region=us-west-2, replicas=5              │
│    2026-07-03 09:15 ✗  region=eu-west-1                          │
│    2026-07-01 11:00 ✓  region=us-east-1, replicas=3              │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│  u browse sessions  ↑↓ navigate  Enter load  Esc back           │
└──────────────────────────────────────────────────────────────────┘
```

### Diff Status Indicators

| Prefix | Color | Meaning |
|--------|-------|---------|
| `~` | Yellow | Value changed from previous |
| ` ` | Dim | Unchanged |
| `+` | Green | New field (not in previous execution) |
| `-` | Red | Removed field (was in previous, not in current) |

### Session History

Shows the last N executions (up to 10) with:
- Timestamp (human-readable)
- Outcome icon: `✓` success, `✗` failure, `◌` cancelled
- Concise value summary (first 3 key=value pairs)

### Interaction

| Key | Action |
|-----|--------|
| u | Toggle session selection mode (highlights rows for navigation) |
| ↑ / ↓ | Navigate session history (when in selection mode) |
| Enter | Load selected session's values into PendingExecution as overrides |
| Esc | Exit selection mode, or exit panel |

**Loading a session:**
When user presses Enter on a past session, ALL values from that session are applied
as session overrides via `PendingExecution.set_override()` (full restore). This updates
the Config Table and SmartBar immediately. The user can then selectively `r` (reset)
individual fields they don't want from the loaded session.

### Data Source

- `ConfigSnapshotStore.get_last_snapshot(job_name)` for the comparison baseline
- `ConfigSnapshotStore.get_snapshots(job_name, limit=10)` for history
- `compute_config_diff(pending, previous)` for the diff entries

---

## Pre-flight Summary (Standalone — Not in Panel Ring)

### Purpose

A passive, read-only status display that shows automatically when a job is recognized.
It gives users an at-a-glance view of all field values, sources, and readiness without
requiring any explicit action. It's the "ambient context" you always see while composing
a command.

### Visibility Rules

The pre-flight summary is a `RichLog` widget positioned between the SmartBar and the
PanelHost. Its visibility is governed by:

```python
should_show = (
    bar.readiness in (PENDING, READY)   # A job is recognized
    and not panel_host.is_active         # No panel ring is open
)
```

- **Shows** when: user types a recognized job name (bar turns yellow/green)
- **Hides** when: PanelHost activates (Ctrl+R or Ctrl+E pressed), or bar goes grey (no job)
- **Not focusable** — it's purely informational, never receives keyboard focus

This means the pre-flight summary is the **default view** when you have a job
composed but haven't explicitly opened any panel. It's always there unless you
actively choose to interact with panels.

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                   │
│  deploy — Deploy to target environment                            │
│                                                                   │
│  Deploys the application stack to the specified environment       │
│  with rolling update strategy and health checks.                  │
│                                                                   │
│  ●* region/r:       us-east-1     (config.toml)                   │
│       str [us-east-1|us-west-2|eu-west-1|ap-southeast-1]          │
│       Deploy target region                                        │
│       history: us-west-2, eu-west-1, us-east-1                    │
│  ●* replicas:       5             (session)                       │
│       int                                                         │
│       Number of instances to deploy                               │
│       history: 3, 5                                               │
│  ○* timeout:                                                      │
│       int                                                         │
│       Max wait time in seconds                                    │
│       history: 30, 60                                             │
│  ·  verbose:        false          (default)                      │
│       bool [true|false]                                           │
│       Enable debug output                                         │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Content Sections

**1. Job Header**
- Job name + one-line description (from `JobDescriptor.description` or docstring first line)
- Full docstring body (wrapped, dimmed) — gives the user context about what this job does
- Separates the "what is this?" question from the "what are the inputs?" question below

**2. Fields (multi-line per field)**

Each field renders with a main line and detail lines below it:

Main line:
```
  indicator required_mark kind name/short_flag: value (source)
```

Detail lines (dimmed, indented):
```
       type [choices if enum]
       description
       history: val1, val2, val3
```

Where:
- `indicator`: ● (has value), ○ (required, empty), · (optional, empty)
- `required_mark`: `*` if required, space otherwise
- `kind`: `[arg]` for positional arguments, empty for flags
- `name/short_flag`: e.g., `region/r` if short flag exists
- `value`: effective value, or blank if empty
- `(source)`: where the value comes from — `session`, `config.toml`, `env`, `default`
- `type`: Python type name — `str`, `int`, `float`, `bool`
- `[choices]`: if the field is an enum or has choices, shown as `[val1|val2|val3]` after the type
- `description`: field help text
- `history`: last 3 values used in previous invocations (from `ArgumentHistory`), omitted if no history

**3. Implicit Status**

The pre-flight doesn't need an explicit "status" section because:
- The SmartBar color already communicates readiness (yellow = pending, green = ready)
- Missing required fields are obvious via the `○` indicator
- The user sees at a glance which fields still need values

### Interaction

None — the pre-flight summary is **not interactive**. It has `can_focus = False`.

To interact with config, the user either:
- Types directly in the SmartBar (e.g., `deploy --region us-west-2`)
- Presses Ctrl+R to open the command panel ring (Config Table, Config Files, Diff View)
- Presses Ctrl+Enter to open the Argument Form Modal for quick-fill

### Data Source

- `JobDescriptor.description` / `JobDescriptor.docstring` for the header
- `FieldDef` list (same source as Config Table) for field values and sources
- `ArgumentHistory.get_history(job_name, field_name)` for history lines
- `SmartBar.readiness` to control visibility

### Design Intent

The pre-flight summary is the **ambient awareness layer**. It answers "what's going
on?" without the user needing to do anything. The moment they want to actively
manipulate config, they press Ctrl+R and enter the panel ring. This separation
keeps the default experience lightweight while making power available on demand.

---

## Cross-Panel Behavior

### State Synchronization

All three command panels + the pre-flight summary observe the same `PendingExecution` + `FieldDef` list:

```
SmartBar text ←→ PendingExecution ←→ Command Panels (Ctrl+R)
                       ↓
               Pre-flight Summary (passive observer)
```

- Editing in Config Table → updates SmartBar (adds `--flag value`)
- Typing in SmartBar → updates Config Table field values + refreshes pre-flight
- Loading from Diff View → sets overrides → all panels + pre-flight refresh
- Saving from Config Files → re-resolves chain → all views refresh

### The `secret=` contract

Every panel above renders field values, so every panel is a place a credential can
leak. The rule that keeps them from leaking is governed by
[`contributor/guides/tui-panels.md`](../guides/tui-panels.md) §14 and applies to all
three panels plus the pre-flight summary:

- **Copy `secret=` onto every `FieldDef` you construct.** It rides in on the cached
  descriptor for free, including for group options (ADR-008 Addendum A5), so a
  credential leaks only by a wire being dropped between the descriptor and the panel.
- **Import `display_value` / `is_secret_field` from `functualize.app.utils`, never
  `_types.redaction`.** That is the `lint-imports` seam: `_cli/` may not import an
  underscore-prefixed package, so the public re-export is the only legal path and a
  direct import fails the contract check rather than merely being untidy.
- Detection follows the **declaration**, not the field name. There is no `"token"`
  keyword heuristic — a field is secret because it is declared `Secret[str]` (or
  carries `json_schema_extra={"secret": True}`), which is why a field named
  `sort_key` renders normally and a field named `credential` would too if it were
  not declared.
- Prove masking from a declared `Secret[str]`, never from a stub carrying
  `secret=True` (`wiring-discipline.md` §8), and sabotage-check it: delete the
  kwarg, watch the test go red, restore.

### Panel Refresh Triggers

| Event | What refreshes |
|-------|----------------|
| SmartBar text changes | Config Table, Pre-flight Summary |
| Config Table value edit | SmartBar, Pre-flight Summary, Diff View |
| Config Files Ctrl+S save | All (chain re-resolution) |
| Diff View session load | Config Table, SmartBar, Pre-flight Summary |
| Field reset (r) | SmartBar, Pre-flight Summary |
| PanelHost activates (Ctrl+R) | Pre-flight Summary hides |
| PanelHost collapses (Esc from root) | Pre-flight Summary shows |

### Breadcrumb Navigation

Each panel can push sub-levels. The PanelHost manages a breadcrumb stack:

```
Level 0:  [R:1/3] Config Table                    ← ring navigation works
Level 1:  [R:1/3] Config Table > Detail: region   ← ring nav disabled, Esc pops
```

```
Level 0:  [R:2/3] Config Files                    ← ring navigation works
Level 1:  [R:2/3] Config Files > .functualize.toml ← ring nav disabled, Esc pops
```

**Rule:** Ring navigation (Ctrl+G/J/K/L) is disabled when breadcrumb depth > 0.
The user must Esc back to level 0 before switching panels. This prevents confusion
about which panel they're in.

### Footer Behavior

The DynamicFooter shows only currently-available actions:

| Panel State | Footer Shows |
|-------------|--------------|
| Config Table (level 0) | j/k h/l i edit r reset / filter Enter detail Esc |
| Config Table (level 1, detail) | Esc back |
| Config Files (level 0) | j/k Enter open Esc |
| Config Files (level 1, file edit) | j/k i edit d remove Ctrl+S save Esc discard |
| Diff View (normal) | u sessions Esc |
| Diff View (selection mode) | ↑↓ nav Enter load Esc cancel |

---

## Visual Language Summary

| Symbol | Context | Meaning |
|--------|---------|---------|
| `●` | Indicator | Has value |
| `○` | Indicator | Required, empty |
| `·` | Indicator | Optional, empty |
| `*` | Name suffix | Required field |
| `★` | Resolution chain | Winning source |
| `●` | Resolution chain | Non-winning source |
| `~` | Diff prefix | Changed |
| `+` | Diff prefix | New |
| `-` | Diff prefix | Removed |
| `✓` | History | Successful execution |
| `✗` | History | Failed execution |
| `◌` | History | Cancelled execution |
| `▸` | Row | Cursor position |

---

## Design Decisions

1. **Config Files — file template when creating:** Minimal. Only the section header and the keys the user edited. For grouped jobs (e.g., `infra.provision` with `JOB_GROUP = "infra"`), the section is the group name: `[infra]`. For `pyproject.toml`, the section is `[tool.functualize.<group>]`.

2. **Config Files — what counts as a file source:** Show everything:
   - `pyproject.toml` always appears even if the job has no section in it (it's a possible location).
   - All locations from `ResourceLocator` discovery rules (project root, user home, XDG dirs) are shown even when no file exists.
   - `pyproject.toml` displays as `pyproject.toml [tool.functualize.deploy]` to make the nested section explicit.

3. **Config Table — h/l column navigation:** Keep. Useful for reading wide values/descriptions.

4. **Diff View — "load session" semantics:** Option A — full restore. Load ALL values from the selected session as session overrides. The user can then selectively `r` (reset) individual fields they don't want.

5. **Pre-flight summary — docstring length:** Full docstring. The RichLog's `max-height` handles overflow via scrolling.

6. **Config Files — format support:** TOML only. The panel reads and writes `.toml` files exclusively. INI reaches the chain only when a plugin registers `IniFormatProvider` (ADR-007); where one has, its values are visible in the resolution chain detail but are still not editable through this panel.
