# 14 · Decision register

Every accepted decision, renumbered clean. Reversals and retired arguments are in
[CHANGELOG §2-3](CHANGELOG.md) — **not** here, so this file reads as one set.

---

## A. Vocabulary and layering

| # | Decision | Where |
|---|---|---|
| **A1** | **`answer` records, `resume` advances.** Two verbs, distinct contracts, **no aliases**. `answer <id> <gate>` fills a gate's payload slot and never runs anything; `resume <id>` walks to the next durable boundary. | [05 §2.3](05-target-surface.md) |
| **A2** | **`answer` over `deposit`** as the user-facing record verb — pi-workflows' word for the same operation, and `deposit` is overloaded three ways internally. `deposit_gate_input` stays as the internal function name. | [05 §2.3](05-target-surface.md) |
| **A3** | **Three tiers, by actor.** `builtin workflow` is the rich superset · MCP matches it verb for verb · `--wf-*` on the job is a convenience subset, admitted only by the inclusion test. | [05 §1](05-target-surface.md) |
| **A4** | **`--wf-resume [id]` replaces both `--scope-id` spellings**, and errors on an unknown id instead of silently minting a phantom run. | [05 §2.2](05-target-surface.md) |
| **A5** | **Delete the early-parse `--scope-id` outright** — no refusal branch. `detect_mode` breaks on an unrecognised `--flag`, so deletion fails loud and cannot misexecute. | [12 §3](12-scope-id.md) |
| **A6** | **Ambiguity never guesses.** Zero → error naming the survey verb; one → use it; several → list and exit 2. Never "newest wins". | [05 §5](05-target-surface.md) |
| **A7** | **MCP parity is pinned by a test**, not asserted: one implementation per verb, same addressing, same result shape, same error codes. One honest exception — `--prompt-gates` is CLI-only. | [05 §4](05-target-surface.md) |
| **A8** | **`--wf-run-id <id>` for idempotent start.** An unknown `--scope-id` today *creates* the scope, so start-if-not-exists exists only as a side effect of the flag's double duty. `--wf-run-id` makes it explicit and unconditional (a *start* parameter, so it reintroduces none of the control-flag machinery), while `--wf-resume` errors on an unknown id. Serves CI's one-run-per-SHA, a scheduler's one-run-per-day, an agent's don't-start-twice. | [05 §2.2](05-target-surface.md) |
| **A9** | **The blocked output is load-bearing.** Exit 5 prints the exact `resume` command with each step's contract stated inline; `func <wf>` hints when a scope of that workflow is waiting. | [06](06-lifecycles.md) |

## B. Defects — correctness, not design

| # | Decision | Where |
|---|---|---|
| **B1** | **Stop `scopes` being silently erased.** Split the envelope or fail closed with a backup-and-recover instruction on a `format_version` mismatch. **Blocking — do first.** | [13 item 0](13-roadmap.md) |
| **B2** | `func builtin state clear` must name what it destroys; add `--keep-scopes` or a confirmation. | [01 §C.4](01-current-state.md) |
| **B3** | **Return `metadata` from all four MCP execution doors**, and normalize `RunStatus` — `_execute_job` returns the raw `Enum` where `run_job` returns `.value`. | [01 §C.1](01-current-state.md) |
| **B4** | **Enforce `cancel`** with a status check in `prelude`, or delete the tool description's *"Cancelled scopes are not resumable."* | [01 §C.3](01-current-state.md) |
| **B5** | `deposit_gate_input` stores **`model(**payload).model_dump()`**, not the raw dict — the strategy path already does. Do before any answer or resume work. | [01 §C.2](01-current-state.md) |
| **B6** | **Fix the docs/code contradiction on `resume_workflow`.** Three doc sites say it advances; the code only deposits. Under A1 the code moves to match the docs. | [05 §2.3](05-target-surface.md) |
| **B7** | **Fix the SINGLE_FILE crash** when the target file is in the cwd — an unhandled `ValueError` from `_register_single_file_peers`. Prerequisite for A5's per-mode tests. | [12 §4](12-scope-id.md) |
| **B8** | Fix the group help — *"Inspect and resume persisted workflow scopes"* → *"Inspect, answer, resume, and cancel…"*; rename `app/_workflow_resume.py` → `_workflow_gate_input.py`. | [12](12-scope-id.md) |

## C. Architecture

| # | Decision | Where |
|---|---|---|
| **C1** | **Lift `_describe`/`_topology`** into `app/`, re-exported through `functualize.app.utils`, projection split from rendering per `_cli/info.py`. Four thin callers. | [13 item 3](13-roadmap.md) |
| **C2** | **Derived `state`** — `waiting` · `ready` · `running` · `stalled` · `completed` · `failed` · `cancelled`. Computed by the projection; no stored field, no version bump. | [05 §3](05-target-surface.md) |
| **C3** | Child scopes: separator **`/`** not `::` · record `parent` + `mount` · `blocked_on_child` on the parent · carry the child scope through `WalkReport`. | [09 §2](09-nesting.md) |
| **C4** | Adopt Temporal's **parent close policy** vocabulary (Abandon / Request Cancel / Terminate), declarable per step, default `terminate`. *Deferred to the tier-2 runner.* | [09 §2](09-nesting.md) |
| **C5** | The agent step is a **port**: `AgentStepExecutor` Protocol + capability flags, engine **fails closed** on a missing capability, `EXECUTOR_PROVIDERS` in core from day one. | [03 §1](03-pi-workflows.md) |
| **C6** | Source identity = **canonical digest of the graph projection**, plus a declared revision and a legacy-mapping path. Not a file content hash. | [03 §2](03-pi-workflows.md) |
| **C7** | Keep **one nesting model** (child scopes). Fix its five defects; do not add inlining alongside it. | [09 §1](09-nesting.md) |
| **C8** | **Promote the lease.** Advancing without knowing the job makes concurrent `resume` one keystroke; the flock fences no stale walker. *Tier 2, priority raised.* | [06 §L3](06-lifecycles.md) |
| **C9** | **Add a `max_workflow_depth` guard.** Cycles are rejected at boot but `max_invoke_depth` does not apply to workflow nesting. | [09 §3](09-nesting.md) |

## D. Gate answers and coordination

| # | Decision | Where |
|---|---|---|
| **D1** | **A `draft` slot beside `payload`.** `payload` is only ever written by a complete, valid `model_dump()`; partial input lives in `draft` and the walker never reads it. | [07 §2](07-gate-answers.md) |
| **D2** | `--reopen` is an explicit verb, **refused** once the walk has consumed the payload. | [07 §3](07-gate-answers.md) |
| **D3** | `--show` reports draft, schema, `missing` and `invalid` — the one genuinely new computation. | [07 §4](07-gate-answers.md) |
| **D4** | **MCP `answer_gate(id?, gate?)` accepts both identifiers**, each optional when unambiguous — closing the hole where two tools each referred the caller to the other. | [05 §4](05-target-surface.md) |
| **D5** | Build **`note`** — not "message". Scope-scoped, append-only, ring-buffered, **inside the scope record** (no new `_SECTIONS`, no version bump), advisory `to`, **engine never reads it**. | [08 §3](08-coordination.md) |
| **D6** | Tasks are **co-addressed, not coupled**: a real link address (`scope/node`), validated `kind`, a provider-side filter, and count-not-contents in the projection. | [08 §4](08-coordination.md) |

## E. Task storage

| # | Decision | Where |
|---|---|---|
| **E1** | Add **`updated_at`** to `TaskItem` and a **terminal marker** on `DONE`/`SKIPPED`. **First** — a format change to every stored blob if deferred. | [10 §7](10-task-storage.md) |
| **E2** | Ship a **file sink inside `functualize-tasks`** — JSON under `.functualize/`, atomic write, locked. Durable tasks with one package instead of four. | [10 §4](10-task-storage.md) |
| **E3** | `MultiTaskProvider`, **architecture A only** — one primary, N write-only projections. Secondary failures degraded and **surfaced**, never fatal, never `logger.debug`. | [10 §3](10-task-storage.md) |
| **E4** | **todo.txt** as the first projection, carrying `id:` tags — the only common format whose identity survives a human edit. | [10 §5](10-task-storage.md) |
| **E5** | Config stays: one `primary`, a list of `project` targets, one `adopt` boolean. | [10 §6](10-task-storage.md) |
| **E6** | Adoption (architecture B) and remote sinks are **deferred** until E1 exists and someone asks. | [10 §7](10-task-storage.md) |

## F. Boundaries

| # | Decision | Where |
|---|---|---|
| **F1** | **Core owns scope state; plugins mirror it.** Any verb reading or writing a scope has its implementation in `app/`, re-exported through `functualize.app.utils`. | [11 §8](11-boundaries.md) |
| **F2** | **Never gate workflow *behaviour* on an optional install.** Presentation may degrade; outcomes may not. | [11 §1](11-boundaries.md) |
| **F3** | **Name the package, never import it.** New pluggable capabilities get a `*_PROVIDERS` table and a grep test, failing as a **block with a diagnostic**. | [11 §4](11-boundaries.md) |
| **F4** | **No new import-guarded silent absences.** A missing capability returns a structured `capability_unavailable` naming the package. | [11 §4](11-boundaries.md) |
| **F5** | **New scope fields go inside the scope record**, never into `_SECTIONS` — no version bump, and the `StateBackend` swap seam stays open. | [11 §2](11-boundaries.md) |
| **F6** | **Expose lock + atomic-write helpers publicly.** A file sink needs them and a plugin cannot reach `_primitives`. | [11 §7](11-boundaries.md) |

## G. Explicitly not building

| # | Not doing | Because |
|---|---|---|
| **N1** | A message bus — inboxes, routing, delivery guarantees, read receipts | That is A2A/AMQ. The moment `to` becomes load-bearing you own a broker. |
| **N2** | Engine reads of notes | Explicit over hidden. The walker must never branch on a note. |
| **N3** | Notes as a result channel | Step return values, `FromJob` and gate payloads are the data path. Two sources of truth, and the memoized one wins. |
| **N4** | A second nesting model | One composition model; fix its five defects. |
| **N5** | Peer multi-master task merge (architecture C) | Not buildable: no `updated_at`, and the status enum is not a monotonic lattice. |
| **N6** | A task-shaped coordination channel | No ordering, identity, atomicity or reader position. Notes exist for that. |
| **N7** | A step-level retry flag | Failed steps already re-run on resume. Only the epilogue is sticky. |
| **N8** | `--fresh` | Absence of a resume flag already means a new scope. |
| **N9** | Time columns and `--actor`, for now | Scope records carry no timestamps, and the gate-level `blocked_at` measures the last poke. |
| **N10** | `pause`, cross-project listing, a second viewer | Nothing runs long enough to pause without a runner; cross-project wants the indexed store; one renderer is enough. |
| **N11** | pi-workflows' server-first architecture, one-active-run-per-session slot, and inline-body loading | Runner-per-run with leases first. `workflow = job` is the better generalization. |

## H. Open

None. Every question is settled; see [CHANGELOG §3](CHANGELOG.md) for what not to
re-litigate.

## I. Two parallel tracks

The workflow work (waves 0-4) and the task work (E1-E6) share **no code** — different
packages, different stores, different files. So they run in parallel, with three
constraints:

1. **E1 leads its track.** `updated_at` plus a terminal marker is a format change to every
   stored task blob.
2. **F6 is the one shared dependency.** The public lock and atomic-write helpers are core
   work; land them in wave 2 and the task track picks them up.
3. **The task track is delegable.** It needs only [10](10-task-storage.md) and E1-E6.

## J. Implementation waves

| Wave | Decisions | Shape |
|---|---|---|
| **0 — blocking** | B1, B2 | State erasure. Nothing else is safe until this lands. |
| **1 — small, independent** | B3, B4, B5, B6 | Four return dicts, one status check, two lines, one docs pass. |
| **2 — the lift** | C1, C2, C3, F1, F6 | One projection, four callers, child addressing. Largest user-visible gain per line written. |
| **3 — the surface** | A1-A9, B7, B8, D1-D4 | The three tiers, the vocabulary, `--scope-id` removal, gate drafts. |
| **4 — coordination** | D5, D6, F5 | Notes inside the scope record; task link addressing. |
| **T — tasks (parallel)** | E1 → E2, E3, E4, E5 | Independent of 0-4; needs F6 from wave 2. |
| **5 — the port** | C5, F3, F4 | `AgentStepExecutor` and the provider table. |
| **6 — durable runs** | C6, C8, C9, C4 | Source identity, leases, depth guard, close policy. |
