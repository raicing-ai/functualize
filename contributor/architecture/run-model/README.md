# Shape Intent: The Run Model — One Request In, One Record Through, One Outcome Out

**Status: specified, not yet implemented**
**Date: 2026-09-09**
**Base: `origin/master` @ `e57f0c9` (0.3.0, after PRs #33–#36)**
**Scope: the whole life of a run — how it starts (`_engine/executor.py::execute`, the
nine doors that call it), what it is while it runs (no durable record today), and how it
ends (nine `RunStatus` translation sites). Plus the two roadmap items that cannot be built
until that life has one shape: the agent-step port and the durable run layer.
Breaking, and free to be — `.spec/CONSTITUTION.md` → Pre-Release Stance.**

This document set merges two bodies of work that were queued separately and are one job:

- **The entrypoint audit** — `contributor/architecture/audit-entrypoint-coverage.md`
  (empirical: 17 surfaces, 13 divergences, 14 leakage rows),
  `contributor/architecture/audit-engine-encapsulation.md` (design: 4 causes, 15 smells,
  a 9-step roadmap), `contributor/adr/020-engine-entrypoint-encapsulation.md` (proposed),
  and their synthesis at `.spec/shape-intents/entrypoint-encapsulation/shape-intent.md`.
- **The pi-workflows parity roadmap** — `~/code/raicing-ai/pi-workflow-parity/`, whose
  Tier 0 and Tier 1 shipped as 0.3.0 and whose Tier 2 (items 7, 8, 9) does not exist.

**Supersedes** neither: both remain the evidence base and are cited throughout. What is new
here is the claim that they are **sequenced**, not merely adjacent — and the eight features
that follow from that.

---

## The finding, in one paragraph

A run has no identity. It is assembled differently by each of **nine** doors, none of which
can name what it produced; it leaves no durable trace of its own progress; and it is
translated into an outcome by **nine** separate sites, two of which were added in the last
release. The roadmap's durable run layer wants to record a thing the codebase has never
named. **`RunRequest` names it on the way in; the run record names it on the way out.** Until
the first exists, the second must be bolted onto nine doors — which is how the codebase got
nine doors in the first place.

## The verdict

| Question | Answer |
|---|---|
| Are the audit's findings still true at `e57f0c9`? | **Yes — 15 of 17 re-verified claims hold, 0 became false.** The two that moved grew in the predicted direction. See [02](02-audit-corrections.md). |
| Are the audit and the roadmap the same work? | **Yes, and in a specific order.** The audit's entry consolidation is a *prerequisite* for the roadmap's durable run layer. See [03](03-the-run-model.md). |
| Can the roadmap be built first? | **Only by instrumenting nine doors** — the exact defect the audit found. |
| Is any of this urgent? | **One item.** D-13: a workflow started through `interactivity.job.submit` gets no scope and can never be resumed. See [04 §C](04-request-and-entry.md). |

## Finding classes

- **Confirmed** — re-derived at `e57f0c9`, with the command that would falsify it.
- **Drifted** — true, but the citation moved; corrected here and in [evidence/](evidence/).
- **New** — found while writing this set, not in either audit.
- **Withdrawn** — an audit claim this set declines to carry, with the reason.

## Index

| # | Document | Holds |
|---|---|---|
| — | [README.md](README.md) | This page |
| — | [CHANGELOG.md](CHANGELOG.md) | Iteration history; **closed arguments — do not re-litigate** |
| 01 | [01-current-state.md](01-current-state.md) | The doors, the leaks, the budgets — re-verified at `e57f0c9` |
| 02 | [02-audit-corrections.md](02-audit-corrections.md) | What drifted since `c0c921f`; the Cause-4 reconciliation |
| 03 | [03-the-run-model.md](03-the-run-model.md) | **The thesis** — one request in, one record through, one outcome out |
| 04 | [04-request-and-entry.md](04-request-and-entry.md) | `RunRequest`, `engine.run`, and the death of the deposit protocol |
| 05 | [05-engine-seal.md](05-engine-seal.md) | `EngineHost`, one `build_engine`, facade budgets as tests |
| 06 | [06-outcome-authority.md](06-outcome-authority.md) | One outcome module; family choice as the only per-surface decision |
| 07 | [07-surface-parity.md](07-surface-parity.md) | The feature × door matrix, restated as a structural guarantee |
| 08 | [08-durable-runs.md](08-durable-runs.md) | Roadmap 8 — events, lifecycle verbs, leases, timeouts, effects outbox |
| 09 | [09-agent-step-port.md](09-agent-step-port.md) | Roadmap 7 — a port with capability flags, failing closed |
| 10 | [10-graph-semantics.md](10-graph-semantics.md) | Roadmap 9 — loops, failure routing, typed outcomes, watch |
| 11 | [11-boundaries.md](11-boundaries.md) | Core / plugin / job, and what this set refuses to build |
| 12 | [12-performance.md](12-performance.md) | Boot budgets, the measured phase, the one real win |
| 13 | [13-roadmap.md](13-roadmap.md) | **The merged roadmap** — features F1…F9, order, traceability |
| 14 | [14-decisions.md](14-decisions.md) | Decision register |
| A | [appendix-a-audit-synthesis.md](appendix-a-audit-synthesis.md) | Reconciling the two audits' numbering |
| — | [evidence/verified.md](evidence/verified.md) | `\| Fact \| Location \|` index at `e57f0c9` |
| — | [evidence/drift-2026-09-09.md](evidence/drift-2026-09-09.md) | The `c0c921f` → `e57f0c9` drift table |

## The design in one page

```
 nine doors (func pre-boot · click adapters · TUI · MCP · HTTP · Lambda · rc.invoke
             · app.execute · guarded_execute)
        │  parse ONLY their own syntax — no resolution, no engine knowledge
        ▼
   RunRequest ──────────────────────────────────────────────► one frozen value object
        │                                                     (name, not function)
        ▼
   FunctualizeApp.execute(request)      the single surface-facing Facade
        │
        ▼
   engine.run(request)                  ← single entry, single authority
        │ resolves name → job (materialize)
        │ opens a RunRecord, emits run.started            ← the durable layer hangs HERE
        │ _execute_lifecycle   (20 steps, Template Method, unchanged)
        │   └ steps/gates walk under a lease with a fencing token
        ▼
   JobResult  +  RunRecord
        │
        ▼
   one outcome module in _types: exit code │ http status │ failure-set │ report line
        │
        ├─► deliver_job_result   ├─► TUI panel   ├─► MCP response   ├─► HTTP / Lambda
             (Adapter: process)      (terminal)       (tool)             (wire)
```

Every arrow above is one authority. Today, five of them are re-derived per door.

## Status

Nine features, specified and planned on `feat/run-model`. Nothing is implemented.
See [13-roadmap.md](13-roadmap.md) for the order and the traceability table.
