# Claim Format

Every claim extracted from the document under scrutiny follows this structure. Claims are the atomic unit of verification — the entire workflow operates on them.

---

## Structure

```markdown
### [CATEGORY-NN] <One-line statement of the claim>

- **Source**: Document section/heading where this appears, with quote if short
- **Type**: FACT | ASSUMPTION | INTERFACE | ARCHITECTURE | MEASUREMENT | DEPENDENCY | SCOPE
- **Load-bearing**: YES | NO — does the proposal's design depend on this being true?
- **Verification strategy**: How to check this (1–2 sentences)
- **Verdict**: (filled in Phase 3) CONFIRMED | DRIFTED | FALSIFIED | STALE | UNTESTABLE | PARTIALLY TRUE
- **Evidence**: (filled in Phase 3) `file:line`, command output, or experiment reference
- **Severity**: (filled in Phase 3, only for non-CONFIRMED) Cosmetic | Load-bearing | Blocking
- **Notes**: (filled in Phase 3) What changed, what's the impact, what would fix it
```

---

## Extraction Guidance

### What counts as a claim

A claim is any statement that:
- Asserts something about the current state of the codebase
- Asserts something about how the codebase behaves
- Asserts a quantitative measurement
- Defines an interface or protocol that must be compatible with existing code
- States what is or isn't in scope for a change
- Assumes something that isn't explicitly verified in the document itself

### What is NOT a claim

- Statements of intent ("we will build X") — unless they assume preconditions
- Definitions ("a daemon is a long-running process") — unless claiming the codebase uses that definition
- Rationale ("this is better because...") — unless the rationale depends on a factual assertion
- Future-tense proposals ("the thin client will be ~500 LOC") — these are goals, not claims. BUT: "the thin client needs only `std::os::unix::net`" IS a claim about feasibility.

### Density rules

- **Tables**: Each row is usually 1–3 claims. A comparison table ("current vs proposed") has claims in the "current" column.
- **Code snippets**: Each snippet claims "this is how the interface will look" — verify that existing code can call/use it as shown.
- **Architecture diagrams / module lists**: Each module name is a claim about existence; each arrow is a claim about dependency direction.
- **Measurements**: Every number is a claim. "~400ms" is testable (or at least, you can verify the methodology makes sense).
- **Negations**: "X is NOT Y" or "never Z" are strong claims — they assert an invariant. Check if there are any violations.

### Implicit claims

The hardest to catch and often the most load-bearing:

- "Uses the same FunctualizeApp" → implies FunctualizeApp's interface supports this use case without modification
- "Jobs never know they're in a daemon" → implies the execution path preserves all RunContext behavior
- "Identical behavior" → implies complete behavioral equivalence, which is a very strong claim
- "Zero per-invocation file I/O" → implies no lazy loading, no runtime config checking
- Module placement claims ("lives in `_daemon/`") → implies this fits the existing layer rules

### Prioritization

Not all claims are equal. Prioritize investigation of:

1. **Load-bearing claims** — if false, the design fails
2. **Assumption claims** — often unchecked by the document author
3. **Scope claims** — underestimating scope is the #1 proposal failure mode
4. **Interface claims** — incompatible interfaces are expensive to discover late
5. **Measurement claims** — easy to get wrong, often load-bearing for performance-motivated designs
6. **Fact claims** — usually the easiest to verify and the most likely to drift

---

## Example: Extracting claims from a proposal paragraph

**Document text:**
> After all import optimizations, the framework boots in ~110ms but wall clock is ~400ms because CPython startup (~290ms) is irreducible per-invocation. A persistent daemon amortizes it.

**Extracted claims:**

```markdown
### [MEASUREMENT-01] Framework boot time is ~110ms after import optimizations

- **Source**: "Why a daemon" section, opening paragraph
- **Type**: MEASUREMENT
- **Load-bearing**: YES — the daemon's value proposition depends on this being the actual breakdown
- **Verification strategy**: Check if boot timing is measured anywhere (benchmarks, CI, test fixtures). If not, assess whether the import chain supports this estimate.

### [MEASUREMENT-02] CPython startup overhead is ~290ms per invocation

- **Source**: "Why a daemon" section, opening paragraph
- **Type**: MEASUREMENT
- **Load-bearing**: YES — if CPython startup is actually fast (e.g., with a wheel), the daemon motivation weakens
- **Verification strategy**: This is a platform measurement. Check if the document's "Current (editable)" vs "Current (wheel)" numbers are consistent with known CPython startup costs. Look for any benchmarking scripts.

### [FACT-01] Import optimizations have already been applied

- **Source**: "After all import optimizations" (implicit — claims optimizations are done, not planned)
- **Type**: FACT
- **Load-bearing**: NO (cosmetic if wrong — but affects timing claims)
- **Verification strategy**: Check git history for import optimization work. Look for lazy imports, `__init__.py` patterns.
```

---

## Claim count expectations

| Document size | Expected claims |
|--------------|----------------|
| Short proposal (1–2 pages) | 10–25 |
| Medium proposal (3–5 pages) | 25–50 |
| Detailed design (5+ pages) | 50–100+ |
| ADR (decision record) | 5–15 (focused) |

If you extract fewer than 10 claims from a multi-page document, you're likely missing implicit claims. If you extract more than 100, consider grouping related claims under a parent claim.
