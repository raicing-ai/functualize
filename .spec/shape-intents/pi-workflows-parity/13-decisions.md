# 13 · Decision register

Every recommendation across this folder, pinned as a numbered decision. Each carries the
rationale pointer and what it forecloses. **Accepted** = decided, ready to implement.
**Open** = needs your call before anything downstream moves.

Status legend: ✅ accepted · ⚠️ accepted with a caveat · ❓ open

---

## A. Naming and contract

| # | Decision | Why | Status |
|---|---|---|---|
| **D1** | **Keep both verbs.** `func builtin workflow resume` stays, unchanged in contract. `deposit` is **added** as the richer verb (draft / partial / `--set` / `--reopen`); `resume` becomes a thin alias for `deposit --input … --commit`. One implementation, two spellings. | Resolved O1: no rename. `resume` is referenced by generated hints, docs and skills, so keeping it costs nothing and breaks nothing; `deposit` carries the new capability. | ✅ |
| **D1a** | **Because both survive, the contracts must be stated loudly.** Every `resume`/`deposit` docstring and `--help` opens with *"Accepting input does not run the workflow."* Every `--wf-resume` surface opens with *"Continues the walk in this process."* | The collision D1 chose not to remove — the record layer says "resume" and means deposit, the invocation layer says "resume" and means advance — is now permanent, so documentation is the whole mitigation. | ✅ |
| **D2** | Collapse MCP `resume_gate` + `resume_workflow` into one **`deposit_gate(workflow_id?, gate?, values, mode, commit)`**. | Neither accepts both today and each refers the caller to the other on ambiguity — the addressing hole ([01 §C.5](01-surface-inventory.md)). One tool with both optional matches the CLI's arity and makes the parity claim true. | ✅ |
| **D3** | Three layers, one rule each: **record** (never advances) · **invocation** (`--wf-*`, always advances) · **execution** (starts/continues). | Gives every future verb an obvious home. | ✅ |

## B. Defects — correctness, not design

| # | Decision | Why | Status |
|---|---|---|---|
| **D4** | **Stop `scopes` being silently erased.** Split the envelope or fail closed with a backup-and-recover instruction on a `format_version` mismatch. | Proven by experiment: a version bump plus one unrelated write destroys every in-flight run and every deposited approval, with no error. The discard rationale was written when the envelope held only fingerprints. | ✅ **Blocking — do first.** |
| **D5** | `func builtin state clear` must name what it destroys; add `--keep-scopes` or an explicit confirmation. | Help says *"fingerprints, history"*; it wipes scopes. Same root cause as D4. | ✅ |
| **D6** | **Return `metadata` from all four MCP execution doors**, and normalize `RunStatus` (`_execute_job` returns the raw `Enum`, `run_job` returns `.value`). | An agent that blocks a workflow currently learns nothing — not even the scope id. The CLI already prints it, so this is an adapter-only regression. | ✅ |
| **D7** | **Enforce `cancel`** (a status check in `prelude`) **or delete** the tool description's *"Cancelled scopes are not resumable."* | `cancelled` appears zero times in the executor, walker and runner. A shipped tool asserts a guarantee that does not exist. | ✅ |
| **D8** | `deposit_gate_input` stores **`model(**payload).model_dump()`**, not the raw dict. | The strategy path already stores `model_dump()`. Same gate, two different objects reach the node; a defaulted field is missing on the deposit path. Two lines, and a precondition for D9 and D14. | ✅ **Do before any deposit or resume work.** |

## C. Architecture

| # | Decision | Why | Status |
|---|---|---|---|
| **D9** | **Lift `_describe`/`_topology`** from the MCP plugin into `app/`, re-exported through `functualize.app.utils`, projection split from rendering per `_cli/info.py`. Four thin callers. | The framework's richest workflow observability currently ships **only in an optional adapter** — the exact surprise ADR-016 forbids. `_cli` may import public folders only, so `app/` is the only legal target. | ✅ |
| **D10** | Add a **derived** `state`: `waiting` · `ready` · `running` · `stalled` · `completed` · `failed` · `cancelled`. Computed by the projection; **no stored field, no version bump**. | Nothing today names "answered, awaiting re-entry" — it reads as `blocked` with no pending gates. `ready` is exactly what `--wf-resume` can advance and what a scheduler polls for. | ✅ |
| **D11** | Child scopes: separator **`/`** not `::` · record `parent` + `mount` · add `blocked_on_child` to the parent · carry the child scope through `WalkReport`. | `::` is overloaded with step keys. A parent blocked on a child's gate records no gate at all and the child's scope id is dropped from the report that names the block — the state is unaddressable over MCP. | ✅ |
| **D12** | Adopt Temporal's **parent close policy** vocabulary (Abandon / Request Cancel / Terminate), declarable per step, default `terminate`. | Cancelling a parent leaves children live; cancelling a child leaves the parent blocked forever. | ⚠️ Deferred to the Tier-2 runner, when cancel can stop a live walk. |
| **D13** | The agent step is a **port**: `AgentStepExecutor` Protocol + capability flags, engine **fails closed** on a missing capability, `EXECUTOR_PROVIDERS` table in core **from day one**. | pi-workflows already generalized this; two implementations ship, one headless. Adding the provider table after the Protocol reproduces the exact defect `STRATEGY_PROVIDERS` was written to fix. | ✅ |
| **D14** | Source identity = **canonical digest of the graph projection** (`workflow_shape_of` → `to_dict()`), plus a declared revision and a legacy-mapping path. Not a file content hash. | A Python module holds many unrelated jobs; file hashing invalidates every in-flight run when a neighbour is edited. pi-workflows moved past exactly this. | ✅ |
| **D15** | Keep **one nesting model** (child scopes). Fix its five defects; do not add pi-workflows-style inlining alongside it. | Child scopes buy independently resumable nesting with zero composition machinery. | ✅ |

## D. Coordination

| # | Decision | Why | Status |
|---|---|---|---|
| **D16** | Build **`note`** — not "message". Scope-scoped, append-only, ring-buffered, **inside the scope record** (no new `_SECTIONS`, no version bump), advisory `to`, **engine never reads it**. | "Message" imports delivery semantics this will not have. The scope carries facts; notes carry the *reasoning* that lets an agent resume after a context reset. | ✅ |
| **D17** | Tasks are **co-addressed, not coupled**: real link address (`scope/node`), validated `kind`, provider-side filter, count-not-contents in the projection. Step jobs write tasks; the walker stays ignorant. | Different mutability, different owner, engine reads neither. A2A keeps Message/Task/Artifact separate for the same reason. | ✅ |
| **D18** | ~~Delete `"workflow_step"` from the docs~~ — **superseded**. D17 is taken, so the link kind stays and gains a real address format plus validation. | Resolved O2: co-address. | ✅ Closed as superseded. |

## E. Task storage — build order

| # | Decision | Why | Status |
|---|---|---|---|
| **D19** | Add **`updated_at`** to `TaskItem` and a **terminal marker** on `DONE`/`SKIPPED`. **First.** | Without them no merge policy beyond primary-wins is principled, and adding them later is a format change to every stored blob. | ✅ |
| **D20** | Ship a **file sink inside `functualize-tasks`** — JSON under `.functualize/`, atomic write, locked. | Highest-value piece in the whole task idea: durable tasks with **one** package instead of four. Today, `functualize-tasks` alone means in-memory and lost at exit. | ✅ |
| **D21** | `MultiTaskProvider`, **architecture A only** — one primary, N write-only projections. Secondary failures degraded and **surfaced**, never fatal, never `logger.debug`. | Fan-out is bookkeeping; multi-source reduce is only worth it for the hand-edit case, which needs D19 first. | ✅ |
| **D22** | **todo.txt** as the first projection, carrying `id:` tags. | The only common format whose identity survives a human edit — so it can later become a *source* without redesign. Markdown loses three of five statuses, so never ship it as the only sink. | ✅ |
| **D23** | Adoption (architecture **B**) behind a flag, after D19, once someone has actually asked for it. | The one case that justifies multi-source reads. | ⚠️ Deferred. |
| **D24** | Remote sinks (multica, Taskwarrior) last, and as architecture B — they own their own ids. | Never simple projections. | ⚠️ Deferred. |
| **D25** | Config stays: one `primary`, a list of `project` targets, one `adopt` boolean. | Per-sink read/write/merge flags is a combinatorial surface nobody gets right. | ✅ |

## F. Boundaries — the rules that hold the line

| # | Decision | Why | Status |
|---|---|---|---|
| **D26** | **Core owns scope state; plugins mirror it.** Any verb reading or writing a scope has its implementation in `app/`, re-exported through `functualize.app.utils`. | `deposit_gate_input` is the precedent; `_describe` is the outstanding violation. `_cli` may import public folders only. | ✅ |
| **D27** | **Never gate workflow *behaviour* on an optional install.** Presentation may degrade; outcomes may not. | ADR-016, already stated in `pyproject.toml`. | ✅ |
| **D28** | **Name the package, never import it.** New pluggable capabilities get a `*_PROVIDERS` table and a grep test, failing as a **block with a diagnostic**. | The best pattern in the repo (`STRATEGY_PROVIDERS`). | ✅ |
| **D29** | **No new import-guarded silent absences.** A missing capability returns a structured `capability_unavailable` naming the package. | MCP's task/history tools vanish with only a `logger.debug` — a caller cannot tell "not installed" from "not permitted" from "broken". | ✅ |
| **D30** | **New scope fields go inside the scope record**, never into `_SECTIONS`. | No version bump, no erasure exposure, and the `StateBackend` swap seam stays open. | ✅ |
| **D31** | **Expose lock + atomic-write helpers on the public surface.** | A file sink needs them and a plugin cannot reach `_primitives`. Useful well beyond tasks. | ✅ |
| **D32** | **Ambiguity rule, everywhere:** zero → error naming the survey verb; exactly one → use it; several → list and exit 2. Never "newest wins". | "Newest wins" is silently picking, and `blocked_at` resets on every re-block so it is not computable anyway. | ✅ |

---

## G. Explicitly not building

| # | Not doing | Because |
|---|---|---|
| **N1** | A message bus — inboxes, routing, delivery guarantees, read receipts | That is A2A/AMQ. The moment `to` becomes load-bearing you own a broker. |
| **N2** | Engine reads of notes | Explicit over hidden. The walker must never branch on a note. |
| **N3** | Notes as a result channel | Step return values, `FromJob` and gate payloads are the data path. Two sources of truth, and the memoized one wins. |
| **N4** | A second nesting model alongside child scopes | One composition model; fix its five defects. |
| **N5** | Peer multi-master task merge (architecture C) | Not buildable: no `updated_at`, and the status enum is not a monotonic lattice. |
| **N6** | A task-shaped coordination channel | No ordering, identity, atomicity or reader position. That is what notes are for. |
| **N7** | `--wf-retry-failed` | Failed steps already re-run on resume. `--wf-retry-epilogue` is the one that is needed. |
| **N8** | `--fresh` | Absence of a resume flag already means a new scope. |
| **N9** | Time columns and `--actor`, for now | No timestamps exist in scope state, and the gate-level `blocked_at` measures the last poke. Adding the columns before the state is dishonest UI. |
| **N10** | `pause`, cross-project listing, a second viewer | Nothing runs long enough to pause without a runner; cross-project wants the indexed store; one renderer over the lifted projection is enough. |
| **N11** | pi-workflows' server-first architecture, one-active-run-per-session slot, and inline-body loading | Runner-per-run with leases first. `workflow = job` is the better generalization. |

---

## H. Resolved questions

| # | Question | Answer | Lands in |
|---|---|---|---|
| **O1** | The `deposit` rename | **Keep both.** `resume` unchanged; `deposit` added as the richer verb. | D1, D1a |
| **O2** | Co-address tasks, or delete the link kind | **Co-address.** | D17 (D18 superseded) |
| **O3** | Version control for this analysis | **Copy to `.spec/shape-intents/` in the `feat/pi-workflows-parity` worktree and commit.** The scrutiny report comes too — `.spec/scrutiny-reports/` is gitignored, so it would otherwise be lost with the worktree. | — |
| **O4** | Sequencing the task work | **Independent track, D19 first.** See §I. | D19–D25 |

## I. O4 — how the task track is sequenced

Waves 0–4 (workflow) and wave 5 (tasks) share **no code**: the workflow work lives in
`_primitives`/`_engine`/`app/`/`_cli` and the core state envelope; the task work lives in
`plugins/functualize-tasks*` and the State domain. They touch different files, different
packages and different stores.

So they run as **two parallel tracks**, with three constraints:

1. **D19 leads its track.** `updated_at` + a terminal marker is a format change to every
   stored task blob. Anything built before it has to be migrated after it.
2. **D31 is the one shared dependency.** The public lock + atomic-write helpers are needed
   by the file sink (D20) and are core work. Land them in the workflow track's wave 2, and
   the task track picks them up.
3. **The task track is delegable.** It needs none of the workflow context in this folder —
   only [12-task-sinks.md](12-task-sinks.md) and decisions D19–D25. Good candidate for a
   separate agent or a later pass.

## Implementation order (decisions mapped to sequence)

| Wave | Decisions | Shape |
|---|---|---|
| **0 — blocking** | D4, D5 | State erasure. Nothing else is safe until this lands. |
| **1 — small, independent** | D6, D7, D8 | Three return dicts, one status check, two lines. |
| **2 — the lift** | D9, D10, D11, D26, D31 | One projection, four callers, child addressing. The largest user-visible gain per line written. |
| **3 — continuation** | D1, D1a, D2, D32 + `--wf-resume`/`--wf-input` | Deposit and continue fuse. `resume` kept, `deposit` added. |
| **4 — coordination** | D16, D17, D30 | Notes inside the scope record; task link addressing. |
| **T — tasks (parallel track)** | D19 → D20, D21, D22, D25 | Independent of waves 0–4. D19 first; needs D31 from wave 2. |
| **6 — Tier 2** | D13, D14, D12, D28, D29 | The port, source identity, durable run layer. |
