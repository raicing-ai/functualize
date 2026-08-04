# Scrutiny Report Template

The report is the deliverable. It must be self-contained — someone reading it without access to the conversation should understand what was scrutinized, what was found, and what to do about it.

File naming: `.spec/scrutiny-reports/<document-slug>-<YYYY-MM-DD>.md`

---

## Template

```markdown
# Scrutiny Report: <Document Title>

> **Document**: `<relative path to the scrutinized document>`
> **Scrutinized on**: <YYYY-MM-DD>
> **Codebase at**: commit `<short SHA>` on branch `<branch>`
> **Mode**: quick | standard | deep
> **Skill version**: 1.1.0

---

## Executive Summary

<2–4 sentences. Overall assessment: is this document current, is the design
feasible, what's the adoption risk level? Be direct.>

---

## Adoption Recommendation

**Verdict: ADOPT | REVISE | DEFER | REJECT**

<1–3 sentences of reasoning. For REVISE: what specifically must change before
adoption. For DEFER: what external condition must be met first. For REJECT:
why the approach is fundamentally unsuitable.>

---

## Scoreboard

| Verdict | Count | Load-bearing | Blocking |
|---------|-------|-------------|----------|
| CONFIRMED | N | N | — |
| DRIFTED | N | N | N |
| FALSIFIED | N | N | N |
| STALE | N | N | N |
| UNTESTABLE | N | N | — |
| PARTIALLY TRUE | N | N | N |
| **Total** | **N** | | |

---

## Standards Index

<The yardstick the design pass (Phase 3.5) was judged against — Phase 1.5
output. The author must be able to see and appeal against these standards.
Omit entries with no applicable claims.>

- **Binding rules applied**: <constitution/ADR/enforcement config, with the specific rule cited>
- **Authoritative docs consulted**: <doc path + the domain it governs>
- **Idioms used as precedent**: <idiom name> — `<file:line>` (N instances) — <strength: established | weak (single instance)>
- **Repo-specific concerns**: <testing strategy / transitional-change rules / migration coordination, as applicable>

---

## Critical Findings

<Only findings with severity Load-bearing or Blocking, ordered by severity
(Blocking first). Label each by pass: [FACTUAL] or [DESIGN]. Each finding is
a condensed version of the claim or design-evaluation entry.>

### [CLAIM-ID] <claim statement>

- **Pass**: FACTUAL | DESIGN
- **Verdict**: FALSIFIED | DRIFTED | STALE | CONCERN | VIOLATION
- **Severity**: Blocking | Load-bearing
- **Evidence / Standard**: <factual: file:line, command output, experiment reference — design: the citable standard (rule, idiom at file:line, or named failure mode)>
- **Scenario** (design findings only): <the reachable scenario, question-form, built from the proposal's own components>
- **Impact on proposal**: <1–2 sentences: what breaks if this isn't addressed>
- **Suggested resolution**: <1–2 sentences: how to fix the document or the approach>

(Repeat for each critical finding.)

---

## Design Evaluation

<Phase 3.5 output. Present for standard and deep modes; in quick mode this
covers only VIOLATION candidates on load-bearing INTERFACE/ARCHITECTURE
claims.>

### SOUND decisions (the denominator)

<Major design decisions judged and passed, with the supporting standard. This
list is what makes the CONCERN/VIOLATION counts meaningful — do not omit it.>

| Decision | Standard / steelman survived |
|---|---|
| <decision> | <rule, idiom at file:line, or the forcing constraint> |

### Design findings

| # | Decision (claim ref) | Lens | Verdict | Severity | Scenario / standard |
|---|---|---|---|---|---|
| D-01 | <what was judged> (IF-02) | <lens name> | CONCERN/VIOLATION/UNJUDGEABLE | <severity> | <question-form scenario + cited standard> |

### Lens artifacts

<Embed small artifacts; summarize large ones. Always record negative results
explicitly — unhandled grid cells, unjustified deltas, substitution failures,
missing forcing constraints, rejected edges.>

- **Liskov walk**: <substitution failures, or "all implementations substitute cleanly">
- **Precedent diff**: <unjustified deltas, or "no unjustified deltas vs <analog>">
- **Null-alternative**: <mechanisms without a cited forcing constraint, or "all machinery forced">
- **Lifecycle walk**: <unhandled cells, or "grid fully covered">
- **Import-arrow audit**: <edges violating binding rules, or "all edges legal">

---

## Experiment Results

<Only present if experiments were run. Omit section if none.>

### Experiment: [CLAIM-ID] <claim statement>

- **Hypothesis**: <what was tested>
- **Method**:
  ```bash
  <exact commands>
  ```
- **Result**:
  ```
  <output>
  ```
- **Interpretation**: CONFIRMED | FALSIFIED | INCONCLUSIVE
- **Notes**: <caveats, platform specifics>

(Repeat for each experiment.)

---

## Full Claim Table

<Every extracted claim, grouped by category. This is the exhaustive record.>

### FACT Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| FACT-01 | <statement> | YES/NO | CONFIRMED/etc | —/Cosmetic/etc | <file:line or note> |
| FACT-02 | ... | | | | |

### ASSUMPTION Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| ... | | | | | |

### INTERFACE Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| ... | | | | | |

### ARCHITECTURE Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| ... | | | | | |

### MEASUREMENT Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| ... | | | | | |

### DEPENDENCY Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| ... | | | | | |

### SCOPE Claims

| # | Claim | Load-bearing | Verdict | Severity | Evidence (brief) |
|---|-------|-------------|---------|----------|------------------|
| ... | | | | | |

---

## Scope Analysis

<If the proposal makes scope claims, this section maps the ACTUAL blast radius
versus the claimed scope.>

### Claimed scope
<List of modules/files the proposal says it touches>

### Actual scope (traced)
<List of modules/files that would actually be affected, based on dependency
tracing>

### Unclaimed dependencies
<Files/modules the proposal doesn't mention but that import from affected
modules — these would need updating or at minimum testing>

---

## Observations

<Sub-finding notes that don't meet the CONCERN bar (no reachable scenario) or
the factual-evidence bar. This section NEVER gates adoption — if something
here should gate, promote it by constructing the scenario or finding the
evidence; otherwise leave it here.>

- <observation>

---

## Revision Guidance

<Only present for REVISE or REJECT verdicts. Specific, actionable items.>

For a REVISE verdict, list what must change:

1. **<Section/claim>**: <what's wrong> → <what should replace it>
2. **<Section/claim>**: <what's wrong> → <what should replace it>
...

For adoption planning, note:
- **Prerequisites**: what must be true/done before this proposal can proceed
- **Risk areas**: which parts of the proposal carry the most uncertainty
- **Suggested experiments**: investigations worth running before committing to implementation
- **Ordering constraints**: what other proposals/work must land first or concurrently

---

## Methodology Notes

<Brief record of what was and wasn't checked, so future re-scrutiny can pick
up where this left off.>

- **Investigation depth**: quick | standard | deep
- **Claims sampled vs exhaustive**: <note if sampling was used>
- **Experiments run**: N (or "none — quick mode")
- **Not checked**: <anything deliberately skipped and why>
- **Time spent**: <rough estimate for calibrating future scrutiny>
```

---

## Quality Bar

Before delivering the report, verify:

- [ ] Every non-CONFIRMED verdict cites specific evidence (file:line, command output, or experiment)
- [ ] Load-bearing assessments are honest (not everything is load-bearing; not everything is cosmetic)
- [ ] The executive summary matches the detailed findings (no surprise blocking issues buried in the table)
- [ ] Revision guidance is actionable — a different agent could update the document from these instructions
- [ ] The scoreboard math adds up (totals match claim count)
- [ ] No secret values reproduced anywhere in the report
- [ ] The report stands alone — no "as discussed" or "see above" references to the conversation
- [ ] The standards index is present and every entry is itself verifiable (rule/doc/file:line)
- [ ] Every design finding cites a standard AND a reachable scenario — no preference-as-finding survived
- [ ] Design findings use the design vocabulary (SOUND/CONCERN/VIOLATION/UNJUDGEABLE), never the factual one — and vice versa
- [ ] The SOUND denominator is present — the reader can see how much was judged and passed
- [ ] Lens artifacts record negative results explicitly (unhandled cells, unjustified deltas, substitution failures)
- [ ] Observations contains nothing that should gate — anything gating was promoted with a scenario or evidence
