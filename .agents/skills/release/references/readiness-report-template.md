# Readiness Report Template

The Readiness Report is the deliverable produced after a Pre-Release Audit completes. It must be self-contained — someone reading it without access to the conversation should understand what was audited, what was found, and whether the project is ready to release.

File naming: `.release/reports/pre-release-<YYYY-MM-DD>.md`

---

## Template

```markdown
# Pre-Release Readiness Report

> **Date**: <YYYY-MM-DD>
> **Commit**: `<short SHA>`
> **Branch**: `<branch name>`
> **Skill version**: <release skill version, e.g. 1.0.0>

---

## Executive Summary

<2–3 sentences. State the overall readiness of the project for release: how many
findings were discovered, what the highest severity is, and the resulting verdict.
Be direct and factual.>

**Verdict: READY | READY_WITH_WARNINGS | NOT_READY**

---

## Findings Scoreboard

| Severity | Count |
|----------|-------|
| BLOCKING | <N>   |
| WARNING  | <N>   |
| INFO     | <N>   |
| **Total** | **<N>** |

---

## Detailed Findings

<All findings from the audit, ordered by Severity_Level descending (BLOCKING
first, then WARNING, then INFO). Every finding must have a recommended action.>

| ID | File | Description | Severity | Recommended Action |
|----|------|-------------|----------|--------------------|
| F-001 | `<relative path or "N/A">` | <concise description of the finding> | BLOCKING | <specific, actionable remediation step> |
| F-002 | `<relative path or "N/A">` | <concise description of the finding> | WARNING | <specific, actionable remediation step> |
| F-003 | `<relative path or "N/A">` | <concise description of the finding> | INFO | <specific, actionable remediation step> |

<If the audit produced zero findings, replace the table with:>

_No findings. All audited items passed._

---

## Verdict

**<READY | READY_WITH_WARNINGS | NOT_READY>**

<1–3 sentences of reasoning. Explain the logic:
- READY: all findings are INFO-level or no findings were produced.
- READY_WITH_WARNINGS: at least one WARNING exists but no BLOCKING findings.
- NOT_READY: at least one BLOCKING finding exists that must be resolved before release.>

---

## Verification Command Results

<Summary of commands executed during the audit and their outcomes. Include only
commands that were actually run (e.g., test suite, linter, type checker, build).>

| Command | Exit Code | Summary |
|---------|-----------|---------|
| `<command invocation>` | <0 or non-zero> | <one-line result: "all 142 tests passed", "3 type errors", etc.> |
| `<command invocation>` | <0 or non-zero> | <one-line result> |

<If no verification commands were run, state:>

_No verification commands were executed during this audit._
```

---

## Quality Bar

Before delivering the report, verify:

- [ ] All findings have a recommended action (no empty Recommended Action cells)
- [ ] Verdict matches severity logic (BLOCKING → NOT_READY, WARNING without BLOCKING → READY_WITH_WARNINGS, only INFO or zero findings → READY)
- [ ] Scoreboard math adds up (individual severity counts sum to Total)
- [ ] Findings are ordered by severity descending (BLOCKING first, WARNING second, INFO last)
- [ ] Finding IDs are sequential and unique (F-001, F-002, …)
- [ ] Executive summary verdict matches the Verdict section
- [ ] Every file reference uses a relative path from the project root
- [ ] The report stands alone — no "as discussed" or "see above" references to the conversation
