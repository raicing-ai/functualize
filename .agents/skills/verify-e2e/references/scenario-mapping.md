# Scenario Mapping

How to translate behavioral claims from a document into concrete probe scenarios.

---

## Claim Extraction Rules

Read the target document and extract statements that describe **observable behavior** — what a user would see, hear, or experience. Ignore implementation details.

### Claim patterns to look for

| Pattern in document | Claim type | Example |
|---|---|---|
| "X appears" / "X renders" / "X shows" | Visual presence | "Pre-flight summary appears below SmartBar" |
| "Pressing Y does Z" / "Y triggers Z" | Interaction | "Ctrl+R opens the command ring" |
| "X updates to Y when Z" | Reactive state | "SmartBar updates when config panel edits a value" |
| "X is sorted by Y" | Ordering | "Fields sorted by priority: positional → named → required" |
| "X does NOT appear" / "X is blocked" | Negative assertion | "Ring navigation blocked at breadcrumb depth > 0" |
| "The TUI boots" / "App starts" | Boot | "Inline TUI launches when stdin is a TTY" |
| "Job executes" / "returns success" | Execution | "Job completes with green success indicator" |
| "Error/traceback when X" | Error handling | "Missing required field shows validation error" |

### What to skip

- Architecture statements ("_engine/ is the single execution path")
- Type system claims ("JobDescriptor is a frozen dataclass")
- Performance claims (unless the document specifically says "user perceives no delay")
- Internal implementation details ("uses asyncio.Queue for dispatch")

---

## Mapping Claims to Probe Steps

### Step construction from manual test docs

If `docs/testing/tui-*-manual-test.md` has a matching feature section, translate its Steps directly:

| Manual test step | Probe step |
|---|---|
| "Type `ping` in the SmartBar" | `send:ping` |
| "Press Ctrl+R" | `send:<ctrl+r>` |
| "Wait for recognition" | `sleep:1` |
| "Expect: Panel Host appears showing Config Table" | `wait:Config Table` |
| "Use j/k to navigate" | `send:j` |
| "Press Enter" | `send:<enter>` |

### Step construction from acceptance criteria

ACs are usually less detailed than manual test docs. Build minimal probes:

| AC pattern | Probe |
|---|---|
| "User sees X after doing Y" | `wait:<precondition>` → `send:Y` → `sleep:1` → `wait:X` → `snap` |
| "X is visible on boot" | `wait:X` → `snap` |
| "X and Y are both shown" | `wait:X` → `snap` (check dump for Y) |
| "After executing job, result shows Z" | `send:jobname<enter>` → `sleep:2` → `wait:Z` → `snap` |

### Step construction for targeted tier (kernel changes)

When you know which surface is affected but don't have specific claims:

| Affected surface | Targeted probe |
|---|---|
| Config panel | Boot → `wait:Type a command` → `send:ping` → `sleep:1` → `send:<ctrl+r>` → `sleep:1` → `wait:Config Table` → `snap` |
| Job browser | Boot → `wait:Type a command` → verify job names appear in completions/list |
| Execution output | Boot → `wait:Type a command` → `send:status<enter>` → `sleep:2` → `snap` (check for output/result) |
| Cross-panel sync | Boot → open panel → edit value → check SmartBar reflects it |
| Boot sequence | Boot → `wait:Type a command` → `snap` (just confirm it rendered) |

---

## Negative Assertions

Claims about what should NOT happen need special handling. The pyte probe can't directly assert absence — it only confirms presence. Strategy:

1. Run the probe up to the point where the thing should NOT appear
2. Take a snapshot
3. Examine the screen dump text for the forbidden content
4. If present → FAIL. If absent → PASS.

Example: "Ring navigation is blocked at breadcrumb depth > 0"
```
→ Boot, type ping, Ctrl+R, Enter (drill into detail)
→ send:<ctrl+j> (attempt ring nav)
→ sleep:1
→ snap:ring-blocked-check
→ Examine: if dump still shows "Detail:" → PASS (didn't navigate away)
→ If dump shows a different panel name → FAIL (ring nav wasn't blocked)
```

---

## Grouping Probes for Efficiency

Multiple claims that share a setup can be validated in a single probe run with multiple snap points:

```bash
uv run --with pyte python .agents/skills/observe-tui/scripts/tui_probe.py \
    --cwd examples/standalone/showcase \
    --step "wait:Type a command" \
    --step "snap:claim1-boot-renders" \
    --step "send:ping" \
    --step "sleep:1" \
    --step "snap:claim2-preflight-shows" \
    --step "send:<ctrl+r>" \
    --step "sleep:1" \
    --step "snap:claim3-panel-opens" \
    -- uv run func
```

Group when:
- Claims are sequential (each builds on the previous state)
- All share the same example directory
- Failure in one doesn't invalidate the others (if claim 1 fails, claims 2-3 are also likely invalid)

Don't group when:
- Claims require different example directories
- Claims are independent (a failure in one shouldn't skip the others)
- Claims require different initial state (e.g., with/without env vars)

---

## Coverage Tracking

After mapping, produce a summary:

```
Claims extracted: 12
  Mapped to scenario: 9
  No scenario (gap): 2
  Not TUI-observable (skipped): 1

Probes planned: 7 (some claims share a probe)
Estimated time: ~90s
```

Report gaps prominently — they represent behavior the system cannot currently validate E2E.
