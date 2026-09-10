# Review triage — five adversarial reviews of the completed features

Five read-only reviewers audited the five features whose gates had passed, on
four axes each: scrutiny (falsify the ACs), architecture, design patterns and
refactoring, code smells. **46 findings**: 8 Blocking, 21 Serious, 13 Minor,
4 Nit.

This file is the ledger. Every finding gets a verdict, and the two questions the
maintainer asked of each one:

- **Why the implementer missed it** — not as blame; as the shape of the gap, so
  the next task can be written to close it.
- **What test would have caught it** — because a finding without a test is a
  finding that comes back.

Anything **not fixed** appears here with its reason: needs a decision, or
deferred and why. Nothing is dropped silently.

## Status key

`FIXED` · `CONFIRMED` (reproduced, not yet fixed) · `TRIAGING` · `NEEDS DECISION`
· `DEFERRED` · `REJECTED` (checked, does not hold)

---

## Findings that are the same defect wearing different clothes

Several findings are one class. Fixing the class settles them together, and the
aggregate test is worth more than five separate ones.

**Class A — a gate or test that cannot fail.** The signature defect of this
branch: six were already found during execution, and the reviewers found four
more.
`rre F2` · `rre F13` · `roa B2` · `roa S4` · `asp B-1` · `adj B2`

**Class B — a `tasks.md` record that no longer holds against HEAD.** A gate is
authored by running it, but nothing re-runs it after later tasks change the code,
so a `[x]` can rest on a value that has since moved.
`rre F3` · `adj M5` · `asp S-4` · `jof` (T1's gate unsatisfiable at its named path)

> **Class A and Class B share one fix**: a test that reads every `tasks.md`, runs
> every gate it declares, and asserts the recorded `after:` value still holds. It
> converts "the gate was true once" into "the gate is true now", and it fails
> loudly for a gate that cannot fail at all (its `now:` and `after:` are equal).

**Class C — an acceptance criterion kept by nothing.**
`rre F4` · `roa B1` (fixed) · `roa B2`

**Class D — prose that outlived the code it described.**
`rre F11` · `rre F12` · `roa S2` · `roa S3` · `adj M1` · `adj N1` · `jof` (the
`Freshness` docstring demonstrating an unreachable path)

**Class E — real behaviour defects.** These are the ones a user would hit.
`rre F1` (fixed) · `adj S3` (fixed) · `adj S1` · `adj S2` · `adj S4` · `adj S5` ·
`adj B2` · `asp S-1` · `asp S-2` · `asp S-3`

**Class F — architecture and design judgements.** Several of these are genuine
trade-offs rather than errors, and some want the maintainer's call.
`rre F6` · `rre F7` · `rre F8` · `rre F9` · `rre F10` · `roa A1` · `roa A2` ·
`roa A3`
