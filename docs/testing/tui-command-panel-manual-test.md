# Manual Testing Guide — TUI Command Panel Completion

## Setup

```bash
cd examples/standalone/showcase
func
```

This launches the TUI with multiple jobs (status, ping, send, migrate, deploy, …) that have varying field counts and types, perfect for exercising all new features.

---

## Feature 1: PendingExecution & Pre-Flight Summary

**Tasks covered:** 1, 11
**Requirements:** R1-AC1, R1-AC2, R1-AC3, R1-AC6, R6-AC1 through R6-AC6

### Steps

1. In the SmartBar, type `ping`
2. **Expect:** Pre-flight summary appears below the SmartBar showing:
   - Bold header: `ping — Ping a host`
   - Compact single-line-per-field format: `{indicator}{req_mark} {name}: {value} ({source})  {type}  {description}`
   - Example: `● host: localhost (default)  str  Host to ping`
   - Type and description on the SAME line as the field (no separate detail lines)
   - No full docstring body below the header
3. Type `ping --host 10.0.0.1`
4. **Expect:** Pre-flight updates — host shows `10.0.0.1 (cli)` instead of `localhost (default)`
5. Clear and type `deploy`
6. **Expect:** Required fields show `○*` indicators (empty + required)
7. **Expect:** Fields sorted by priority: positional plain → named plain → required config empty → required config filled → optional config
8. If the job has more than 8 fields, **Expect:** truncation line at bottom: `... +N more — Ctrl+R for all` (dim styling)
9. Plain parameters (marked `[arg]` for positional) are NEVER truncated — always shown regardless of cap

### Feedback

> _Status:_ ✅ Fixed (spec: tui-preflight-and-footer-polish)
> _Previous notes:_
> ~~I want to update the design to minimize the amount of vertical use. This means putting the type and description on the same line as the parameter name.~~
> ~~I want to avoid having a scrollbar for the pre-flight panel. So we need to think about a maximum height before we begin to need to think about showing a scrollbar.~~
>
> _Resolution:_
>
> - Type and description now on same line as parameter name (compact single-line format) — Task 2
> - Pre-flight CSS max-height increased from 4 to 12 — Task 2
> - Truncation cap at 8 fields with `... +N more — Ctrl+R for all` indicator — Task 3
> - Priority sort puts most actionable fields first (positional plain → named plain → required config empty → filled → optional) — Task 1
> - ParamKind enum (PLAIN/CONFIG) classifies fields for appropriate display — Task 1

---

## Feature 2: Command Ring with 3 Panels

**Tasks covered:** 3, 4, 5, 6, 9
**Requirements:** R2-AC1, R3-AC1, R5-AC1

### Steps

1. Type `ping` in the SmartBar (wait for recognition)
2. Press **Ctrl+R** to open the command ring
3. **Expect:** Panel Host appears showing "Config Table" (Panel 1) with fields in a DataTable using **row selection** (full row highlight, no cell cursor)
4. Press **Ctrl+J** (ring next)
5. **Expect:** Switches to "Config Files" (Panel 2) — shows file paths with status
6. Press **Ctrl+J** again
7. **Expect:** Switches to "Diff View" (Panel 3)
8. Press **Ctrl+K** to go back
9. **Expect:** Returns to "Config Files"

### Footer Behavior (Focus-Aware)

1. With Panel zone focused (after Ctrl+R), check the **panel footer**:
    - **Expect at root level:** `Ctrl+J/K switch  j/k navigate  i edit  r reset  / filter  Enter detail  Esc back`
    - Ring nav hints (Ctrl+J/K) only shown when multiple panels exist AND breadcrumb depth == 0
2. Press **Shift+Tab** to cycle focus to another zone (e.g., SmartBar)
3. **Expect panel footer changes to:** `Ctrl+R focus  Shift+Tab cycle`
4. Check the **status bar** (bottom-most line):
    - **Expect format:** `{MODE}  {Zone}  {readiness}` — e.g., `NORMAL  Panel  ● Ready`
    - **Expect NO panel action hints** in the status bar (j/k, i, r, etc. belong in panel footer only)
5. Press **Ctrl+R** again, then **Enter** on a field (drill-down)
6. **Expect panel footer changes to:** `Esc back` (no ring nav hints during drill-down)

### Feedback

> _Status:_ ✅ Fixed (spec: tui-preflight-and-footer-polish)
> _Previous notes:_
> ~~The navigation footer of the panels are not consistent, config table doesn't have j/k mentioned, config file panel does. It seems config table is missing alot of navigation footer hints, including filter.~~
> ~~Config table no longer needs column / cell selection. it just needs row selection now.~~
> ~~It seems the very bottom footer's hints are not consistent and idiomatic.~~
>
> _Resolution:_
>
> - Config Table now uses row-only selection (`cursor_type="row"`) — Task 4
> - Column navigation (h/l) and source chooser removed — Task 4
> - `get_available_actions(focused)` added to ConfigTablePanel with full hint set — Task 5
> - Panel footer is focus-aware: shows panel actions when focused, "how to get here" when not — Task 6
> - Display footer is focus-aware: shows nav actions when DISPLAY focused, focus hint when not — Task 7
> - Status bar simplified to mode + zone + readiness only (no duplicate panel hints) — Task 7
> - All panels now have consistent unfocused hints: `Ctrl+R focus  Shift+Tab cycle` — Tasks 5, 6

---

## Feature 3: Pre-Flight Hides/Shows with Panel Host

**Tasks covered:** 12
**Requirements:** R8-AC5, R8-AC6

### Steps

1. Type `ping` — pre-flight summary is visible
2. Press **Ctrl+R** to open command ring
3. **Expect:** Pre-flight summary disappears (panels take its place)
4. Press **Esc** to collapse the panel host
5. **Expect:** Pre-flight summary reappears

### Feedback

> _Status:_ Pass
> _Notes:_

---

## Feature 4: Resolution Chain Drill-Down

**Tasks covered:** 3, 4
**Requirements:** R5-AC2, R5-AC3, R5-AC4, R5-AC5, R5-AC7

### Steps

1. Type `ping` then press **Ctrl+R** (opens Config Table)
2. Use **j/k** to navigate to the `host` field row
3. Press **Enter**
4. **Expect:** Breadcrumb pushes to "Detail: host" showing:
   - Field metadata: `Type: str | Required: no | Choices: -`
   - Resolution chain with ★/● markers and values or `(not set)`
   - For CONFIG params: all 6 sources (CLI, Session, Env, File, Remote, Default)
   - For PLAIN params: only 3 sources (CLI, Session, Default) with banner: "Plain parameter — resolved from CLI/default only"
   - Description text
5. Press **Esc**
6. **Expect:** Returns to the Config Table (breadcrumb pops)

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 5: Breadcrumb Depth Guard

**Tasks covered:** 2
**Requirements:** R7-AC1, R7-AC2, R7-AC3

### Steps

1. Type `ping`, press **Ctrl+R**, press **Enter** on a field (drill-down active)
2. Press **Ctrl+J** or **Ctrl+K**
3. **Expect:** Nothing happens — ring navigation is blocked (breadcrumb depth > 0)
4. Check panel footer: **Expect:** `Esc back` only (no ring nav hints)
5. Press **Esc** to pop back to Config Table
6. Press **Ctrl+J**
7. **Expect:** Now navigates to Config Files (breadcrumb depth == 0)

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 6: Config Files Panel Navigation

**Tasks covered:** 5, 6
**Requirements:** R2-AC1, R2-AC2, R2-AC3, R2-AC4, R2-AC5, R2-AC16

### Steps

1. Type `ping`, press **Ctrl+R**, then **Ctrl+J** to get to Config Files panel
2. **Expect:** DataTable with 4 standard locations, columns: File, Status, Fields
3. **Expect:** Only CONFIG parameter fields listed (PLAIN params excluded from file discovery)
4. Use **j/k** to navigate rows
5. **Expect:** Cursor wraps from last row back to first
6. Press **/** to enter filter mode, type `pyproject`
7. **Expect:** Only the pyproject.toml row remains visible
8. Press **Esc** to cancel filter (or **Enter** to apply)

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 7: Config Files Drill-Down and Staged Edits

**Tasks covered:** 7
**Requirements:** R2-AC8, R2-AC9, R2-AC10, R2-AC11, R2-AC15

### Steps

1. In the Config Files panel, navigate to a file row and press **Enter**
2. **Expect:** Breadcrumb pushes, detail view shows fields with status:
   - `★ winning` / `— not in file` / `overridden by X`
   - Only CONFIG fields appear (PLAIN parameters excluded from file detail view)
3. Use **j/k** to navigate fields within the detail
4. Press **d** on a field
5. **Expect:** `[DEL]` marker appears on that field
6. Press **d** again
7. **Expect:** `[DEL]` marker toggles off
8. Press **Esc**
9. **Expect:** All staged edits discarded, returns to file list

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 8: TOML File Save (Ctrl+S)

**Tasks covered:** 8
**Requirements:** R2-AC12, R2-AC13, R2-AC14

### Pre-requisite

Add a test section to the example's config file (the showcase already ships a
`.functualize.toml`; append, don't overwrite):

```bash
cd examples/standalone/showcase
echo '[ping]' >> .functualize.toml
echo 'host = "original"' >> .functualize.toml
```

### Steps

1. Restart `func`, type `ping`, **Ctrl+R**, **Ctrl+J** (Config Files)
2. `.functualize.toml` should now show `● exists`
3. Press **Enter** on it to drill down
4. Press **i** on the `host` field, type a new value, press **Enter**
5. **Expect:** `[EDIT]` marker appears
6. Press **Ctrl+S**
7. **Expect:** File is saved, breadcrumb pops, all panels refresh
8. Verify:

   ```bash
   cat .functualize.toml
   ```

   **Expect:** `host = "new-value"` written

### Cleanup

```bash
git checkout -- .functualize.toml
```

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 9: Diff View and Session Load

**Tasks covered:** 9
**Requirements:** R3-AC1, R3-AC2, R3-AC3, R3-AC4

### Steps

1. Type `ping --host 10.0.0.1` and execute the command
2. After execution, type `ping` again
3. Press **Ctrl+R**, then **Ctrl+J** twice to reach "Diff View" (Panel 3)
4. **Expect:** Shows diff between current values and last execution's values
5. If "Load Session" is available, activate it
6. **Expect:** Previous session values apply as overrides, SmartBar updates

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 10: Snapshot Recording

**Tasks covered:** 10
**Requirements:** R4-AC1, R4-AC2, R4-AC3, R4-AC4, R4-AC5

### Steps

1. Type `status` and execute (no args needed — green bar)
2. After execution completes, type `status` again
3. **Ctrl+R**, navigate to Diff View
4. **Expect:** The Diff View shows prior execution with outcome "success"
5. (Optional) Force an error scenario to verify "failure" recording

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 11: Cross-Panel Sync

**Tasks covered:** 12
**Requirements:** R1-AC4, R1-AC5, R8-AC1, R8-AC2, R8-AC3, R8-AC4

### Steps

1. Type `ping`, press **Ctrl+R** (Config Table active)
2. Navigate to `host` field, press **i**, type `192.168.1.1`, press **Enter**
3. **Expect:**
   - Config Table shows the new value
   - SmartBar updates to include `--host 192.168.1.1`
4. Press **Esc** to collapse
5. **Expect:** Pre-flight summary shows `host: 192.168.1.1 (session)`
6. Press **Ctrl+R** again, navigate to the field, press **r** (reset override)
7. **Expect:** Value reverts to `localhost (default)`, SmartBar removes `--host`

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Feature 12: Environment Variable Resolution

**Tasks covered:** 3
**Requirements:** R5-AC1

### Steps

1. Launch with an env var:

   ```bash
   PING_HOST=env-host func
   ```

2. Type `ping`, press **Ctrl+R**, drill down into `host` (Enter)
3. **Expect:** Chain shows `Env` entry with value `env-host`
4. Check that precedence is respected (CLI > Session > Env > File > Default)

### Feedback

> _Status:_ ☐ Pass ☐ Fail ☐ Partial
> _Notes:_

---

## Quick Reference: Key Bindings

| Key             | Context                    | Action                        |
| --------------- | -------------------------- | ----------------------------- |
| Ctrl+R          | COMMAND mode               | Open command ring             |
| Ctrl+J / Ctrl+K | Panel ring (depth 0)       | Next / Previous panel         |
| Shift+Tab       | Any zone                   | Cycle focus between zones     |
| Ctrl+E          | COMMAND mode               | Open general ring             |
| j / k           | NORMAL mode in panel       | Row up / down                 |
| Enter           | Config Table row           | Drill-down (resolution chain) |
| Enter           | Config Files row           | Drill-down (file detail)      |
| Enter           | Settings row               | Drill-down (source chain)     |
| i               | Config Table / Detail view | Edit field (INSERT mode)      |
| r               | Config Table               | Reset override                |
| d               | Detail view                | Toggle staged removal         |
| Ctrl+S          | Detail view                | Save staged changes to TOML   |
| /               | Panel (NORMAL)             | Filter mode                   |
| Esc             | Detail view                | Discard staged changes, back  |
| Esc             | Drill-down                 | Pop breadcrumb                |
| Esc             | Panel root level           | Collapse panel host           |
| Ctrl+Q          | Anywhere                   | Quit                          |

`i` / `d` / `Ctrl+S` in a Detail view are ordinary `KEYMAPS[NORMAL]` entries.
They reach the Detail view because `PanelHost.push_view()` makes it the active
panel, so `KeyDispatcher._resolve_target` routes to it. Outside a Detail view,
`d` and `Ctrl+S` resolve to nothing and are inert.

### Footer Zones (New)

| Zone           | Focused content                                       | Unfocused content                         |
| -------------- | ----------------------------------------------------- | ----------------------------------------- |
| Panel footer   | Panel-specific actions (from `get_available_actions`) | `Ctrl+R focus  Shift+Tab cycle`           |
| Display footer | `Ctrl+U prev  Ctrl+I next  Esc unfocus`               | `Ctrl+U/I focus display  Shift+Tab cycle` |
| Status bar     | `{MODE}  {Zone}  {readiness}` (no action hints)       | Same (always shows mode/zone/readiness)   |

---

## Overall Summary

> _Date tested:_
> _Overall status:_ ☐ All pass ☐ Issues found
> _Blockers:_
>
> _General impressions:_
