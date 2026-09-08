# Scrutiny — `functualize-vs-pi-workflows` study

**Target:** `~/code/raicing-ai/functualize-vs-pi-workflows/` (7 docs + 3 evidence files, dated 2026-09-08)
**Verified against:** functualize @ `78d9ff4`, pi-workflows @ `2b3cf35`
**Reviewer:** adversarial audit, code-first (claims re-derived from source, not from the study's own citations)
**Verdict: REVISE.** The spine is sound; two of the three headline conclusions need rewriting, and one critical defect the study never looked at outranks most of its roadmap.

---

## Executive summary

The study's central thesis — *functualize has a durable-run gap and no agent step contract; `workflow = job` is the right generalization primitive* — survives scrutiny. Its architectural instincts are good and most of its 200-odd factual claims check out.

But it is wrong in three ways that change what you should build:

1. **It understates the agent gap in the one place that is cheap to fix.** All three MCP execution doors silently discard `JobResult.metadata`, so an agent that blocks a workflow does not even learn the scope id. The study assumed it did.
2. **It overstates the observability gap.** `get_workflow_state` already publishes the full graph, per-step return values, resolved inputs, branch choices and gate schemas. The study says "nothing renders a workflow's graph anywhere." Roadmap W3.1 is largely already built and is being sequenced behind the largest workstream for no reason.
3. **Both of its "functualize is ahead" durability claims are wrong.** Workflow-step memoization has no args hash (it is hardcoded `""`), and pi-workflows does *not* re-run completed nodes on replay — its resume semantics are the same as functualize's.

And the study missed a **data-loss defect**: a `STATE_VERSION` bump — an ordinary release action — silently and permanently erases every in-flight workflow run, including deposited human approvals. Proven by experiment below. This should outrank every W1 item in the roadmap.

Finally, the single most useful thing in either codebase went unmentioned: pi-workflows' agent step is already a **port** (`AgentStepExecutor`) with declared capability flags and a fail-closed engine. The study proposes inventing that from scratch as "W2"; it should be ported, and it maps onto functualize's existing ports-as-Protocol constitution.

---

## Scoreboard

| Verdict | Count | Notes |
|---|---|---|
| CONFIRMED | 31 | The study's spine — see §"What holds" |
| FALSIFIED | 8 | 6 load-bearing, 2 cosmetic |
| PARTIALLY TRUE | 4 | Right direction, wrong mechanism |
| DRIFTED / miscounted | 5 | Cosmetic; line numbers and inventory counts |
| NEW (not in study) | 9 | 2 critical, 4 load-bearing, 3 contextual |

---

## Critical findings

### C-1 · Silent, total, unwarned state erasure — *not in the study* — **BLOCKING**

`src/functualize/_primitives/state_format.py`

`load_state` degrades **any** unreadable state to `empty_state()` (`:168-175`), and `normalize_state` does the same for a `format_version` mismatch (`:150-151`). Because every writer is `update_state` = load → mutate → save (`:296-310`), the next ordinary write persists the empty envelope.

The header comment justifies this (`:40-47`):

> *A version mismatch discards the file (runtime state is derived, never a source of truth — the worst case is one extra run).*

The very next line of that same comment lists what lives in the file: `scopes (per-scope step records, recorded branch choices, gate payloads, blocked position, epilogue record)`. **A blocked workflow scope is not derived state.** There is no way to re-derive "the human approved prod at 14:03 with reason X". The rationale was written when the envelope held only fingerprints; `scopes` was added to the same envelope (`_SECTIONS`, `:56`) without revisiting it.

**Experiment (run, then cleaned up):**

```
BEFORE  scopes: ['a3f9c2e1b7d4']          # blocked run, gate payload {"approved": true, ...}
on-disk scopes still present: ['a3f9c2e1b7d4']   # after bumping format_version to 2
# ... one unrelated fingerprint write via update_state() ...
AFTER   scopes: []
AFTER   file  : {}
RESULT: gate payload survived? False
```

No error, no warning, no backup. Triggered by an unrelated job recording a fingerprint. Same path for a truncated file or a hand-edit that breaks JSON.

This is precisely the failure mode pi-workflows designed against: `docs/SQLITE_STATE.md:47-67` — DDL digest verification, **fail closed** with a backup-and-reset instruction, state untouched.

**Fix shape (cheap, no W1 dependency):** split the envelope so `scopes` has its own file and its own version, or fail closed on a scopes-bearing mismatch (rename to `state.json.bak-v1`, refuse, print the recovery command). Do not let a release note double as a data-deletion trigger.

### C-2 · pi-workflows already generalized the agent step to a port — *not in the study* — **load-bearing for W2**

`src/workflows/types.ts:900-911`

```ts
export interface AgentStepExecutor {
  readonly assistantMessageMode?: "visible" | "park" | "unsupported";
  readonly preservesActiveTimeBudget?: boolean;
  readonly enforcesToolAllowlist?: boolean;
  runAgentStep(request: AgentStepRequest, signal: AbortSignal): Promise<AgentStepSubmission>;
}
```

The engine does not know about Pi. It knows about one port and three declared capabilities, and it **fails closed** when a workflow needs a capability the executor lacks (`engine.ts:1299-1320`): an `assistantMessage` node under a non-visible executor either parks for an origin session or throws; `allowedTools` under `enforcesToolAllowlist !== true` throws *"This executor cannot enforce the agent tool allowlist; use an origin Pi session."* The active-time-budget persistence is likewise gated on `preservesActiveTimeBudget` (`engine.ts:980`).

Two implementations already ship: the origin-session executor (`server/workflow-runner-entry.ts:197-199`, all three capabilities true) and `RpcStepExecutor` (`server/rpc-executor.ts`), which runs agent steps in a headless `pi --mode rpc` child — **no conversation involved**. The validation-retry loop lives in the *executor*, not the engine: the engine hands over an `accept(output)` callback and the executor re-prompts on rejection (`rpc-executor.ts:80-97`).

**Why this changes the roadmap.** The study frames this as "pi-workflows made the *conversation* the delivery surface" and proposes W2 as new invention: an `AgentStep` node kind plus a bespoke MCP submit loop. The right move is to port the **shape**: one `AgentStepExecutor`-equivalent Protocol with capability flags, implementations for MCP-elicitation / CLI-prompt / `functualize-ai`, and an engine that refuses rather than degrades. That is what functualize's own constitution already prescribes (ports-as-Protocol), and it is the same ladder shape as the existing `GateStrategy` / `PromptCollector` split.

It also answers the study's own hedge — *"Cross-agent tool restriction outside functualize's own tools is impossible via MCP alone; document the boundary honestly."* pi-workflows does not document the boundary. It **types** it, and behaves differently on each side.

---

## Falsified claims

### FALSIFIED-1 · MCP does not return blocked metadata at all — **load-bearing**

**Study (03-ux §Agent UX, step 2; 07 "have now" table):** *"On block: `{status: "blocked", workflow_scope, blocked_on, blocked_reason}` — the agent must map this to `resume_workflow`."*

**Actual:** all three execution doors return exactly `{status, return_value, duration_ms}` and drop `JobResult.metadata`:

- `_tools.py:250-266` — `run_job`
- `_tools.py:366-381` — `get_execution_status` (async door)
- `_server.py:271-278` — `_execute_job`, the funnel for every per-job tool

The metadata is built correctly (`executor.py:1257-1283`) and thrown away at the boundary. So an MCP agent that starts a gated workflow receives `status: "Blocked"` and nothing else — no scope id, no gate name, no reason. It must call `list_active_workflows` and guess which scope is its own.

**Impact:** the agent gap is *worse* than the study says, and its cheapest fix is smaller than anything in the roadmap — add `metadata` to three return dicts. Do this before W2.

Two adjacent defects at the same boundary:

- `RunStatus` is a plain `Enum`, not a `str` enum (`_types/enums.py:12`). `_run_job` normalizes with `.value`; `_execute_job` returns the raw enum object into a JSON dict. Per-job tools and `run_job` therefore disagree on the shape of `status` — against the plugin's own stated intent (`_tools.py:87`: *"a client parsing `run_job` should not have to handle a second error shape"*).
- The status string is `"Blocked"`, not `"blocked"`. The study writes it lowercase throughout.

### FALSIFIED-2 · The workflow graph *is* published over MCP — **load-bearing**

**Study (05-ux §2):** *"Nothing renders a workflow's graph anywhere. To know that `release-pipeline` blocks at `approval` and expects `{...}`, you read the Python file that declares it."*

**Actual:** `_workflow_tools.py:471-509` (`_describe`, used by both `get_workflow_state` and `list_active_workflows`) returns the declared `steps` and `edges`, `current_position`, `branches`, `pending_gates` with input schemas, and — per its own comment — **every step's `return_value`, resolved `inputs` and `completed_at`**. `_topology` (`:511-536`) even falls back to the live declaration for plugin-registered workflows so the graph is never empty for a live job.

What is actually missing is a *renderer*. The CLI's `_scope_summary` (`builtins.py:833-843`) emits five fields — id, name, status, position, gate names — over the same store that holds all of the above.

**Impact:** the study inverts who is starved. The **agent** surface is rich; the **human** surface is impoverished. Roadmap W3.1 ("Run view + widget … start with `func builtin workflow watch`") is sequenced behind W1's event log, but a `func builtin workflow state --format json` that emits `_describe`'s projection needs no event log, no new storage, and no new code beyond calling the function that already exists. Promote it.

### FALSIFIED-3 · pi-workflows does not re-run completed nodes on replay — **load-bearing**

**Study (README "Where functualize is ahead"; 01-parity B and comparison-data):** *"Memoization + fingerprints: steps skip by `(job, args_hash)` freshness; pi-workflows re-runs nodes on replay."* / *"Step memoization/fingerprints | functualize Y | pi-workflows N"*

**Actual** (`engine.ts:323-326`, docstring on `resumeRun`):

> *Completed nodes replay from the recorded state; only the interrupted node and everything downstream rerun.*

`resumePointFor` (`:440-470`) resumes from the last recorded step and routes forward — the same semantics as functualize's walker. It additionally handles the crash-between-node-finish-and-run-finish case, which functualize does not.

functualize *is* ahead on cross-run **fingerprint freshness** for jobs (`--force`), which is a different feature. Rewrite the row; do not claim it as a replay advantage.

### FALSIFIED-4 · Workflow step memoization has no args hash — **load-bearing**

**Study (02-arch §2; README):** step records keyed `(job, args_hash)`.

**Actual** (`workflow_walker.py:466-473`):

```python
def _key(name: str) -> str:
    """... The args hash is empty because a `Step` takes no arguments ..."""
    return step_key(name, "")
```

Every workflow step key is `"<node>::"`. Workflow-level memoization is by **node name only**. The `(job, args_hash)` scheme exists in `state_store.record_step`'s contract (`:172-178`) but the walker never uses the second half. The study's second headline "ahead" claim is really "the walker skips completed nodes on resume" — which, per FALSIFIED-3, pi-workflows also does.

Net: after FALSIFIED-3 and -4, **the only unambiguous functualize graph-model advantage is fan-out/join** (which is real — see §What holds).

### FALSIFIED-5 · `cancel_workflow` documents a contract it does not enforce — *not in the study* — **load-bearing**

`_workflow_tools.py:453-458` — tool description: *"Cancel a running or blocked workflow scope. **Cancelled scopes are not resumable.**"*

They are. The string `cancelled` appears **zero times** across `executor.py`, `workflow_walker.py` and `workflow_runner.py`. `WorkflowRunner.prelude` (`workflow_runner.py:101-127`) never reads scope status; `FrontierWalk.start` (`frontier.py:95-107`) sees a persisted position and returns it without a status check. `func <wf> --scope-id <cancelled-id>` walks the scope to completion.

The study noted "nothing stops a running walk" but missed that nothing stops a *future* walk either, and that a shipped tool description asserts otherwise. Cancel is currently cosmetic: it hides the scope from `list`.

### FALSIFIED-6 · CLI↔MCP workflow parity does not hold — **load-bearing for doc 07**

**Study (07, final section):** *"invariant — 1:1 parity with the MCP workflow tools … both call `deposit_gate_input`, so the two surfaces never drift."*

They share the deposit *implementation* but not the *addressing*:

| Surface | Addressing |
|---|---|
| CLI `func builtin workflow resume <id> <gate>` (`builtins.py:901-912`) | scope **and** gate |
| MCP `resume_gate(gate, input)` (`:212`) | gate only |
| MCP `resume_workflow(workflow_id, input)` (`:247`) | scope only |

No MCP tool accepts both. The two tools refer to each other on ambiguity — `resume_gate` says *"Use resume_workflow with a workflow_id"*, `resume_workflow` says *"Use resume_gate to name one"* — so any case needing joint addressing has no MCP expression. (I could not construct a reachable single-scope multi-pending-gate state from the walker, which returns on the first block; so `resume_workflow`'s `ambiguous_gate` branch may be dead. Either way, 07's parity invariant is stated as fact and is not one. Marked PARTIALLY VERIFIED.)

`list`/`state` also drift: CLI emits 5 fields, MCP emits the full graph + results (FALSIFIED-2).

### FALSIFIED-7 · pi-workflows' source identity is not "path + SHA-256" — **load-bearing for W1.3**

**Study (01-parity B, 02-arch §5, evidence, 04 W1.3):** *"source identity (path + SHA-256) verified first"*, and W1.3 proposes functualize *"Record (entry point, path, content hash) at start."*

**Actual** — `workflowIdentityMismatch` (`engine.ts:1774-1783`) is a **three-part** check:

1. **Root source**, deep-equal. Two kinds: `{kind:"file", path, hash}` **or** `{kind:"builtin", id, revision}`. Built-ins are identified by a *declared revision string*, never by content hash — `BuiltinWorkflowCatalog.resolve` throws `BuiltinWorkflowRevisionChangedError` on mismatch (`catalog.ts:95-113`).
2. **Every included child workflow's source** (`state.workflowSources` vs `compositionMetadata(workflow).sources`). Editing an `includeWorkflow` child invalidates the parent's resume.
3. **`definitionDigest`** — sha256 over a canonical JSON snapshot of the *compiled graph* (`store.ts:5036-5062`): name, contractId, startAt, structural node snapshots, edges, composition, settings scopes. Node callback bodies are not in it.

And there is a **designed upgrade path** the study never mentions: `legacySources` (`catalog.ts:12-17`, used at `builtins/catalog.ts:22-42`) maps old `(name, path suffix, content hash)` triples to a known revision so runs started under a previous shipped build still resume. This is the one shim pi-workflows keeps despite its stated alpha policy of hard cuts — because hard-cutting here destroys users' in-flight runs.

**Why this matters for functualize.** Hashing the `.py` *file* is the crude version pi-workflows deliberately moved past, and it is worse in Python: a workflow's file holds many unrelated jobs, so editing any of them would invalidate every in-flight run of the workflow. The available and better analogue is a canonical digest of `steps`/`edges`/gate models — functualize already has that projection (`workflow_shape_of`, `shape.to_dict()`, used by `_topology`). W1.3 should specify the structural digest plus an explicit revision/legacy story, not a file hash.

### FALSIFIED-8 (cosmetic) · `save_state` *is* atomic

**Study (02-arch §5):** *"a crash mid-`update_state` risks a torn JSON file (atomicity of save is delegated to `update_state` impl)."*

`save_state` (`state_format.py:178-201`) is `mkstemp` → write → `flush` → `fsync` → `os.replace`, with tmp cleanup on any exception. Torn writes are handled correctly. The real hazard is C-1, in the opposite direction: the file is written safely and *read* destructively.

Related, and also missed: `state_lock` *"degrades to a no-op where OS locking is unavailable"* (`:205-210`, `_acquire_lock` returns unlocked on ImportError). The study's "flock serializes writers" has a silent hole on filesystems/platforms without working locks.

### FALSIFIED-9 (cosmetic) · a failed *step* is not sticky

**Study (07 §4):** *"Today a step failure marks the scope `failed` permanently; resume replays to the same failure."*

`_fail` records `{"status": "failed"}` (`workflow_walker.py:442-456`), and the replay check is `record.get("status") == "success"` (`:314`). A failed step record is therefore **not** replayed — resume re-runs it. `prelude` never reads scope status, so `failed` does not bar re-entry either.

The **epilogue** genuinely is sticky: `record_body` writes on failure too (`executor.py:1033-1037`, `status="failed"`), and `prelude` treats any epilogue record as `body_done` (`workflow_runner.py:120-126`).

**Impact on 07's priority 4:** `--wf-retry-failed <node>` is largely redundant — transient step failures already retry on resume. `--wf-retry-epilogue` is the one that is actually needed. Demote and split.

---

## Drift / miscounts (cosmetic, but fix them — they are cited as evidence)

| Study says | Actual | Where |
|---|---|---|
| 8 built-in workflows | **7** registered (`plain-summary`, `autoplan`, `autodoc`, `autoimplement`, `plan-approval`, `sanity-check`, `monitor`) + 3 composition-only children (`change-verification`, `plan-change`, `workspace-preparation`) | `src/builtins/catalog.ts:10-43` |
| "10-action workflow tool" | **13** actions — the study misses `change-settings`, `queue-follow-up`, `remove-follow-up` | `src/extension/index.ts:1235-1280` |
| Rust TUI 13,403 LOC | 13,552 | `find tui -name '*.rs' \| xargs wc -l` |
| fan-out check at `graph.ts:53-56` | `graph.ts:66-68` | — |
| `run_job` at `_tools.py:207-268` | `:207-266` | — |

The 13-vs-10 miscount matters more than it looks: the three missed actions are exactly the agent-operable surface for **live settings** and the **follow-up queue**, which the study elsewhere lists as functualize gaps. The agent-operable delta is wider than the study's own matrix shows.

---

## What holds (spot-verified, no changes needed)

- `run_job` / `run_job_async` have **no** `scope_id` parameter — an MCP agent cannot resume a walk. `_tools.py:207`, `:278`. **The study's central claim. Confirmed.**
- `resume_gate` and `resume_workflow` deposit only; both delegate to `_deposit` → `deposit_gate_input`, which returns a CLI-shaped hint. `_workflow_tools.py:212-278`, `app/_workflow_resume.py:60-107`.
- No pause, no live-walk cancellation, no per-step timeout, no abort signal anywhere in the walker/runner/frontier. Verified by absence.
- No loops, no failure routing; `_fail` stops the walk. `workflow_walker.py:442-456`.
- **Fan-out and joins are genuinely functualize-only.** `validateWorkflowEdge` throws on a second outgoing edge (`graph.ts:66-68`); `_ready` implements real join deferral with a cycle tie-break (`workflow_walker.py:378-396`). Note the correct framing: pi-workflows forbids *concurrency*, not *branching* — a switch edge has N cases. "General DAGs vs. linear" overstates it; "joins/concurrency vs. state-machine-with-loops" is right.
- pi-workflows action nodes **require** a declared managed effect — enforced at schema validation, not convention: `schema.ts:120-131`, *"node ${nodeId} requires a managed effect"*.
- Leases (owner token hash + monotonic generation), immutable `events`, transactional `effects` outbox with deterministic keys and `ambiguous` status: `docs/SQLITE_STATE.md:75-112`. As described.
- `maxSteps` loop bound (default 100), enforced in the run loop; composition transition nodes excluded from the budget; per-include step limits via `assertInvocationStepLimit`. `engine.ts:555-573`.
- LOC: functualize `src/` 84,062 ✓; pi-workflows `src/` 56,105 ✓; functualize workflow engine 1,072 (study said ≈1,100) ✓.
- functualize ships **0** built-in workflows ✓; **4** skills, none about operating workflows ✓; flow-viz renders a *job* execution tree ✓.
- `--scope-id` sits in `_GLOBAL_OPTIONS_ALWAYS_VALUE` (`dispatch.py:63-81`) ✓ — doc 07's entire premise checks out.
- Gate tool binding publishes schemas minus bound params (`_tool_summaries`, `:578`); bound args refused at dispatch (`:309-323`). Structure confirmed by location; behaviour not exercised.

---

## Things worth knowing that the study never looked at

- **N-7 · pi-workflows pays for its single namespace.** `RESERVED_WORKFLOW_NAMES` (`schema.ts:271-282`) rejects any workflow named `answer`, `cancel`, `change-settings`, `list`, `pause`, `queue-follow-up`, `remove-follow-up`, `resume`, `status` — *"the keyword wins the argument slot."* Doc 05 criticises functualize's separate `func builtin workflow` namespace without noting that the alternative has a permanent reserved-word tax on user workflow names. Relevant if 07's flags or a `func workflow <name>` verb ever land.
- **N-8 · Live settings are woven into the execution loop, not bolted on.** A settings-route node whose scope changes mid-attempt raises `StaleResourceError`; the engine restores pre-attempt state (`restoreRunState`), re-captures the binding, emits a `settings_route_retried` event and retries — bounded by `MAX_SETTINGS_ROUTE_RETRIES` (`engine.ts:627-670`). The study lists "Live settings (JSON Patch)" as one row in a table. It is optimistic concurrency inside the node dispatcher.
- **N-9 · pi-workflows' failure outcomes are typed for routing.** `outcomeForError` yields `timed_out` / `cancelled` / `failed` (`engine.ts:916-925`), which is what `$result.outcome` switches on. If functualize adds failure routing (W3.3), copy the outcome vocabulary — routing on a bare boolean loses the distinction that makes fix-loops useful.
- **N-10 · The park/resume boundary is precise.** On park the engine **does not record the in-flight attempt** (*"the projection keeps the node as in-flight, and resume reruns it with a fresh attempt"*, `engine.ts:592-596`), and a park landing during the `node_started` persist prevents dispatch entirely (`:965-970`) — *"its discarded side effects would rerun on resume."* Checkpoint and assistant-message nodes are the exceptions: they keep their exact attempt id across resume so a durable origin-session contract is never orphaned (`:353-373`). This is the level of care an eventual functualize pause/resume needs, and it is finer-grained than "park at the last durable boundary."

---

## Adoption recommendation: **REVISE**

Keep: the thesis, the architecture comparison, the three-workstream structure, doc 06 (provenance) which I found no errors in, and doc 07's flag namespace reasoning (`--wf-` prefix, early-parse layer untouched) which is sound.

### Required revisions

1. **Rewrite the "Where functualize is ahead" list.** Delete the memoization/replay claim (FALSIFIED-3, -4). Fan-out/join, gate tool-binding security, `workflow = job`, and delivery breadth survive.
2. **Rewrite 05 §2.** The graph, results and inputs are published over MCP. The starved surface is the CLI.
3. **Correct the MCP block story throughout** (03, 05, 07) — no metadata reaches the agent at all.
4. **Rewrite W1.3.** Structural digest + revision + legacy mapping, not file content hash.
5. **Rewrite W2 around a port, not a node kind.** Model it on `AgentStepExecutor`: one Protocol, declared capability flags, engine fails closed. Cite `enforcesToolAllowlist` as the answer to the study's own tool-restriction hedge.
6. **Drop 07's parity invariant** or restate it as an aspiration; and split `--wf-retry-failed` (mostly redundant) from `--wf-retry-epilogue` (needed).
7. **Fix the counts:** 7 built-ins, 13 tool actions, 13,552 Rust LOC, and the five line-number citations.

### Revised priority order

| # | Work | Why it moved |
|---|---|---|
| 0 | **Fix C-1** — stop `scopes` being silently discarded on version bump or corruption | Data loss. Not in the study at all. A release note currently deletes users' in-flight runs. |
| 1 | **Return `metadata` from `run_job` / `run_job_async` / `get_execution_status` / `_execute_job`** (+ normalize `RunStatus`) | Three-line fix; without it every downstream agent story is guesswork (FALSIFIED-1) |
| 2 | **`func builtin workflow state --format json` → `_describe`'s projection** | The renderer is the only missing piece; no event log needed (FALSIFIED-2). Was W3.1, gated behind W1. |
| 3 | **Enforce or delete `cancel_workflow`'s "not resumable"** | A shipped tool asserts a guarantee that does not exist (FALSIFIED-5) |
| 4 | `--wf-resume` + `--wf-input` (fuse deposit and continue) | Unchanged — study's #1, still right |
| 5 | W2 as a port | Per C-2 |
| 6 | W1 durable run layer (events, lifecycle verbs, runner, leases) | Unchanged, but C-1 must land first |

Items 0–3 are all small, all independent of the durable-run layer, and together close more of the practical agent gap than W1 does.

---

## Method notes

- Claims were re-derived from source; the study's own citations were checked last. Five had drifted line numbers, which is why the counts above are re-measured rather than quoted.
- One mini-experiment was run (C-1), in an isolated temp directory against `src/functualize` on `sys.path`, and removed afterwards. No files in either repository were modified.
- Not verified: gate tool-binding *behaviour* (structure only); pi-workflows' Rust TUI, channels/Telegram delivery, and resource-managers runtime were read only at the docs level; `resume_workflow`'s `ambiguous_gate` reachability is unresolved (marked PARTIALLY VERIFIED in FALSIFIED-6).
