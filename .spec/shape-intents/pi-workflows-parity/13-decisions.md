# 13 · Decision register

Every recommendation across this folder, pinned as a numbered decision. Each carries the
rationale pointer and what it forecloses. **Accepted** = decided, ready to implement.
**Open** = needs your call before anything downstream moves.

Status legend: ✅ accepted · ⚠️ accepted with a caveat · ❓ open

---

## A. Naming and contract

| # | Decision | Why | Status |
|---|---|---|---|
| **D1** | **REVISED by [19](19-no-aliases.md): both verbs survive with distinct contracts, not as aliases.** `answer <id> <gate>` records input and never advances; `resume <id>` advances. Original text follows. Keep both record verbs. `func builtin workflow resume` stays, unchanged in contract. `deposit` is **added** as the richer verb (draft / partial / `--set` / `--reopen`); `resume` becomes a thin alias for `deposit --input … --commit`. One implementation, two spellings. | Resolved O1: no rename. `resume` is referenced by generated hints, docs and skills, so keeping it costs nothing and breaks nothing; `deposit` carries the new capability. | ✅ |
| **D1a** | ~~Standing docstring rule~~ — **RETIRED by [19](19-no-aliases.md)**: with `resume` meaning advance everywhere there is no collision left to mitigate. Original text: because both survive, the contracts must be stated loudly. Every record-layer verb's docstring and `--help` opens with *"Accepting input does not run the workflow."* Every invocation-layer surface opens with *"Continues the walk in this process."* Enforced by a grep test, not intention. | Documentation is the mitigation for whatever collision remains after D1b. | ✅ |
| **D1e** | **Delete the early-parse `--scope-id` outright** — no refusal branch. Verified: `detect_mode`'s scan breaks on an unrecognised `--flag` (`dispatch.py:253`), so it becomes the positional, the value is never examined, and the failure is a loud exit 1 that cannot misexecute. Revised from "refuse, not delete" once compat stopped mattering ([16 §1](16-replacing-scope-id.md)). Per-command coverage verified across all five invocation paths, cold and warm ([15](15-scope-id-early-parse-removal.md)). | It is the only member of `_GLOBAL_OPTIONS_ALWAYS_VALUE` addressing persisted state rather than discovery/config/perf, every generated hint and doc already teaches the post-command spelling, and the one historical bug in this area was the global's own plumbing. **Retracts** this folder's earlier claim that the global is the only spelling guaranteed on every dispatch mode. | ✅ |
| **D1o** | **Fix the docs/code contradiction on `resume_workflow`.** `docs/guides/mcp.md:55,200` and `docs/guides/workflows.md:247` all say it **advances**; the code only deposits, and `_workflow_tools.py:21-24` says so explicitly. Under D1 revised the code moves to match the docs, not the reverse. A fifth documentation defect, and the evidence that settled O6. | [19 §1](19-no-aliases.md) | ✅ |
| **D1m** | **Three tiers, by actor.** `builtin workflow` is the rich superset · MCP is at **verb-and-contract parity** with it, pinned by a parity test · `--wf-*` on the job is a **convenience subset** for the invoker, who alone knows which workflow it is. A verb joins the subset only if the workflow is implied, the scope is inferable or already in hand, and it is what someone about to *run* this job wants. | [18](18-three-tier-surface.md) | ✅ |
| **D1n** | **`--wf-continue [id]` replaces both `--scope-id` spellings** — and fixes a defect: an unknown `--scope-id` today *silently starts a new run under it*, so a typo becomes a phantom run. `--wf-continue` requires the scope to exist; `--wf-run-id` is the separate, explicit idempotent start. | [18 §2.2](18-three-tier-surface.md) | ✅ |
| **D1g** | ~~Replace `--scope-id` with a verb and delete the job surface~~ — **revised by D1m**: the verb lands on the record layer, and the job keeps a convenience subset. | [18](18-three-tier-surface.md) | ⚠️ revised |
| **D1g-orig** | **Replace `--scope-id` with a verb, not a flag.** `func builtin workflow continue <id> [--input JSON] [--gate N] [--set K=V]` + MCP `continue_workflow(id)`. A scope knows its own workflow, so a run is addressable by id alone. **Deletes both `--scope-id` spellings, `--wf-resume`/`--wf-continue`, `--wf-input` and `--wf-gate`**, leaving the job command one contract: start. Supersedes [09 §2.2](09-target-matrix-and-lifecycles.md)'s `--wf-resume` family and makes D1b moot. | [16 §2](16-replacing-scope-id.md) | ✅ |
| **D1h** | **Prerequisites for D1g**, both already specified: run-scoped parameters persisted on the scope (`.spec/shape-intents/workflow-run-parameters.md`, Option A) and source/entry identity on the scope (D14). | Without (a), `continue` inherits the resuming shell's environment and permanently bakes in *"one run, two answers, selected by the operator's shell"*. Without (b), single-file-outside-cwd, PEP 723 scripts and `register_dynamic_job` workflows are unreachable. | ✅ |
| **D1j** | ~~No flag conditional on `@workflow`~~ — **withdrawn by D1m**: nine `--wf-*` flags are conditional, deliberately. They are ordinary post-boot Click options, so they never enter `_GLOBAL_OPTIONS_ALWAYS_VALUE` and the cold-cache hazard class stays closed. Original text: the job command starts; the `workflow` group operates. Three layers collapse to two: no flag on a `@workflow` job stays conditional on it being a workflow, which deletes `_scope_id_option`, both injection points, the `_declares_workflow`/`descriptor.workflow` gates and the per-command precedence rule — and with them the cold-cache hazard class (`main.py:2075-2081`), which existed because a state-addressing flag's presence depended on discovery state. | [17 §1-2](17-lifecycle-without-scope-id.md) | ✅ |
| **D1k** | **Preserve caller-chosen run ids as a `--run-id` start flag.** Verified: an unknown `--scope-id` today *creates* the scope, so the flag doubles as start-if-not-exists — CI's one-run-per-SHA, a scheduler's one-run-per-day, an agent's don't-start-twice. `continue <id>` cannot express it. `--run-id` keeps the split clean (start takes a run id, control takes a scope id) and is unconditional, so it reintroduces none of the machinery D1j deletes. | [17 §5.2](17-lifecycle-without-scope-id.md) | ❓ **O5** — recommended, needs your yes |
| **D1l** | **The blocked stderr block and a start-time hint are load-bearing, not polish.** With no `--scope-id`, "re-run the command you remember" is gone, so the blocked output must print the exact `continue` command and `func <wf>` must note when a scope of that workflow is already waiting (a hint, never a refusal). | [17 §5.1](17-lifecycle-without-scope-id.md) | ✅ |
| **D1i** | **Promote the Tier-2 lease.** Once advancing no longer requires knowing the job, two actors will `continue` the same scope; the flock serializes writers but fences no stale walker. | Was a durability nicety; becomes the thing that stops two schedulers double-walking a run. | ⚠️ Tier 2, priority raised |
| **D1f** | **Prerequisite for D1e:** fix the SINGLE_FILE crash when the target file is in the cwd — `func weather.py trip_planner` raises an unhandled `ValueError` from `_register_single_file_peers` because directory discovery already registered the peer. | Do not remove a global whose replacement cannot be exercised in one of the four dispatch modes. Separate defect, found by this audit. | ✅ |
| **D1b** | ~~`--wf-continue` over `--wf-resume`~~ — **RETIRED by [19](19-no-aliases.md)**: `--wf-resume` is the correct spelling once `resume` means advance. Original text: spell the new invocation-layer flag `--wf-continue`, not `--wf-resume`. | [14](14-resume-deposit-collisions.md): today `resume` means *deposit* consistently and the advance operation is **nameless** — the two-meanings collision does not exist yet, and `--wf-resume` would create it. Renaming a flag that has no users, hints, docs or skills is free; renaming `builtin workflow resume` was not, which is why O1 declined it. Same semantics, different spelling. | ❓ **Deviates from the handoff's decision 2 (spelling only).** Recommended. |
| **D1c** | **Fix the blocked stderr block**: numbered steps, each stating its contract inline. | It currently prints a deposit command and an advance command as a flat unlabelled list, so an operator who runs only the first believes they are done while the walk has not moved ([14 §2](14-resume-deposit-collisions.md)). A current defect, independent of naming. | ✅ |
| **D1d** | Fix the group help — *"Inspect and resume persisted workflow scopes"* → *"Inspect, answer, and cancel…"*; rename `_workflow_resume.py` → `_workflow_gate_input.py` and `resume_hint` → `continue_hint`. | No verb in the group advances a walk. `builtins.py:145` and `:149` use the word with both meanings nine lines apart. | ✅ |
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
