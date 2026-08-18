# Report Format

Output template for TARGETED and FULL tier verification runs. SMOKE tier reports inline (pass/fail) without creating a file.

---

## File Location

```
.spec/verification-reports/<document-slug>-<YYYY-MM-DD>.md
```

Create the directory if it doesn't exist. Use the source document's filename (without extension) as the slug. If multiple runs happen on the same day, append a counter: `-2`, `-3`.

---

## Template

```markdown
# E2E Verification Report

**Source document**: `<path to plan/spec/proposal>`
**Date**: <YYYY-MM-DD>
**Tier**: SMOKE | TARGETED | FULL
**Commit**: `<short SHA at time of verification>`
**Verdict**: ✓ PASS | ✗ FAIL | ⚠ PARTIAL

## Summary

<2-3 sentences: what was validated, overall result, key finding if any>

## Impact Analysis

**Changed modules**: <list of modules from blast radius analysis>
**TUI surface affected**: <which panels/features are downstream>
**Tier justification**: <why this tier was chosen>

## Results

| # | Claim | Scenario | Backend | Result | Notes |
|---|-------|----------|---------|--------|-------|
| 1 | TUI boots with job list | showcase boot | observe-tui | ✓ PASS | |
| 2 | Config Table shows fields | showcase Ctrl+R | observe-tui | ✓ PASS | |
| 3 | Pre-flight shows sources | showcase type ping | observe-tui | ✗ FAIL | "source" column missing |
| 4 | Ring nav blocked at depth | showcase drill-down | observe-tui | ✓ PASS | |

## Failures (if any)

### Failure 1: <claim that failed>

**Probe command**:
```bash
<exact command that was run>
```

**Expected**: <what should have appeared>

**Actual** (screen dump excerpt):
```
<relevant portion of the screen dump showing the problem>
```

**Assessment**: <is this a real regression, a timing issue, or a probe construction problem?>

## Coverage

- Claims extracted: N
- Validated (PASS): N
- Failed: N
- No scenario (gap): N
- Skipped (not TUI-observable): N

## Gaps

<List claims that couldn't be validated due to missing scenarios>

- "<claim text>" — needs example coverage in `<suggested location>`

## Recommendations

<If failures found: what to investigate/fix>
<If gaps found: what examples to add>
<If all pass: "No action needed">
```

---

## SMOKE Tier Reporting

SMOKE does not produce a file. Report inline in the conversation:

```
✓ E2E SMOKE PASS — TUI boots in examples/standalone/showcase, "Type a command"
  rendered, `status` job executed without traceback. (commit abc1234)
```

or

```
✗ E2E SMOKE FAIL — TUI failed to boot in examples/standalone/showcase.
  Timeout waiting for "Type a command". Screen dump shows:
  <3-5 relevant lines from the dump>

  This indicates the kernel change broke the boot sequence. Fix before proceeding.
```

---

## TARGETED Tier Reporting

TARGETED produces a file but with a shorter template — skip the full claim extraction table if only 1-3 probes were run. Use the full template if more than 3.

---

## Report Lifecycle

- Reports are informational artifacts, not gates.
- Old reports are not automatically cleaned up — they serve as a history of what was validated when.
- If a report shows FAIL and the issue is subsequently fixed, a new run produces a new report (don't edit the old one).
- Reports reference the commit SHA so anyone can check what code was validated.
