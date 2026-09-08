# 02 · Corrections to `functualize-vs-pi-workflows`

Full audit with experiment transcripts:
[evidence/scrutiny-report-2026-09-08.md](evidence/scrutiny-report-2026-09-08.md)

Scoreboard: **31 confirmed · 8 falsified (6 load-bearing) · 4 partially true · 5 drifted
counts · 9 findings the study did not make.**

---

## Load-bearing falsifications

### 1. MCP returns no blocked metadata at all
**Study (03-ux §Agent UX; 07 "have now"):** *"On block: `{status: "blocked",
workflow_scope, blocked_on, blocked_reason}`."*
**Actual:** `{status, return_value, duration_ms}` from all four doors —
`run_job` (`_tools.py:250-266`), `get_execution_status` (`:366-381`), `_execute_job`
(`_server.py:271-278`), and every per-job tool. The metadata is built correctly at
`executor.py:1257-1283` and dropped at the boundary. Status is `"Blocked"`, capitalized.
**Impact:** the agent gap is worse than described, and its fix is smaller than anything
in the study's roadmap.

### 2. The graph *is* published — over MCP
**Study (05 §2):** *"Nothing renders a workflow's graph anywhere… you read the Python
file."*
**Actual:** `_describe` (`_workflow_tools.py:471-509`) returns `steps`, `edges`,
`current_position`, `branches`, `pending_gates` with schemas, and `results` — per step:
status, **return_value**, resolved **inputs**, completed_at. `_topology` falls back to
the live declaration for plugin-registered workflows (`:511-536`).
**Impact:** the study inverted who is starved. The CLI's `_scope_summary`
(`builtins.py:831-841`) emits five fields over the same store. W3.1 was sequenced behind
the event log; it needs no event log.

### 3. pi-workflows does not re-run completed nodes on replay
**Study (README "ahead"; 01 §B):** *"pi-workflows re-runs nodes on replay."*
**Actual** — `resumeRun` docstring (`engine.ts:323-326`): *"Completed nodes replay from
the recorded state; only the interrupted node and everything downstream rerun."*
`resumePointFor` (`:440-470`) resumes from the last recorded step and routes forward —
plus handles the crash-between-node-finish-and-run-finish case, which functualize does
not.

### 4. Workflow steps have no args hash
**Study (02 §2; README):** step records keyed `(job, args_hash)`.
**Actual** (`workflow_walker.py:466-473`): `_key(name)` returns `step_key(name, "")`.
The docstring says why. Every key is `"<node>::"`.
**Impact:** with (3), **the only unambiguous functualize graph-model advantage left is
fan-out/join.**

### 5. pi-workflows' source identity is not "path + SHA-256"
**Actual** — `workflowIdentityMismatch` (`engine.ts:1774-1783`) is three checks: root
source deep-equal (`{kind:"file", path, hash}` **or** `{kind:"builtin", id, revision}`),
**every included child's source**, and `definitionDigest` — sha256 over a canonical JSON
snapshot of the *compiled graph* (`store.ts:5036-5062`). Plus `legacySources`
(`catalog.ts:12-17`) mapping old hashes to revisions so shipped-built-in upgrades do not
strand in-flight runs.
**Impact:** W1.3's "(entry point, path, content hash)" is the crude version
pi-workflows moved past — and it is worse in Python, where one file holds many
unrelated jobs. See [06 §2](06-pi-workflows-model.md).

### 6. CLI↔MCP parity does not hold
**Study (07, closing invariant):** *"1:1 parity … the two surfaces never drift."*
**Actual:** CLI `resume <id> <gate>` addresses both; MCP `resume_gate(gate)` and
`resume_workflow(workflow_id)` each address one and refer to the other on ambiguity. No
MCP tool accepts both. `list`/`state` also drift (see (2)).

### 7. `cancel_workflow` promises what nothing enforces
**Not in the study.** Tool description: *"Cancelled scopes are not resumable."* The
string `cancelled` appears **zero times** in `executor.py`, `workflow_walker.py`,
`workflow_runner.py`. `prelude` never reads scope status; `FrontierWalk.start` returns
the persisted position without a status check.

### 8. pi-workflows' agent step is a port, not a Pi feature
**Not in the study.** `AgentStepExecutor` (`types.ts:900-911`) — one method plus three
capability flags. The engine **fails closed** on a missing capability
(`engine.ts:1299-1320`). Two implementations ship, one of them headless with no
conversation (`server/rpc-executor.ts`). See [06 §1](06-pi-workflows-model.md).
**Impact:** W2 should port a shape, not invent one.

---

## Corrections that reduce scope

### 9. A failed *step* is not sticky
**Study (07 §4):** *"a step failure marks the scope `failed` permanently; resume replays
to the same failure."*
**Actual:** `_fail` records `{"status": "failed"}` (`workflow_walker.py:442-456`); the
replay check is `record.get("status") == "success"` (`:314`). Failed steps **re-run** on
resume. `prelude` never reads scope status, so `failed` does not bar re-entry.
Only the **epilogue** is sticky — `record_body` writes on failure too
(`executor.py:1033-1037`) and `prelude` treats any epilogue record as `body_done`.
**Impact:** `--wf-retry-failed` is largely redundant; `--wf-retry-epilogue` is the one
that is needed. Demote and split.

### 10. `save_state` *is* atomic
**Study (02 §5):** *"a crash mid-`update_state` risks a torn JSON file."*
**Actual:** `mkstemp` → write → `flush` → `fsync` → `os.replace`, with tmp cleanup
(`state_format.py:178-201`). The real hazard is the opposite direction — see
[07 item 0](07-roadmap.md). Related: `state_lock` *"degrades to a no-op where OS locking
is unavailable"* (`:205-210`), a hole in "flock serializes writers".

### 11. Fan-out ≠ branching
The study's "general DAGs vs. linear" overstates it. pi-workflows forbids multiple
outgoing *edges* (`graph.ts:66-68`) but a **switch edge has N cases**, so branching and
loops are fully supported. What is forbidden is **concurrency**, and therefore joins.
Correct framing: *joins/concurrency* vs. *state-machine-with-loops-and-failure-routing*.

---

## Drifted counts and citations

| Study | Actual | Source |
|---|---|---|
| 8 built-in workflows | **7** registered + 3 composition-only children | `src/builtins/catalog.ts:10-43` |
| "10-action workflow tool" | **13** — misses `change-settings`, `queue-follow-up`, `remove-follow-up` | `src/extension/index.ts:1235-1280` |
| Rust TUI 13,403 LOC | 13,552 | `wc -l` |
| fan-out check `graph.ts:53-56` | `graph.ts:66-68` | — |
| `run_job` `_tools.py:207-268` | `:207-266` | — |

The 13-vs-10 miscount matters: the three missed actions are the agent-operable surface
for **live settings** and the **follow-up queue**, which the study lists elsewhere as
functualize gaps. The agent-operable delta is wider than its own matrix shows.

---

## What the study got right (do not re-litigate)

`run_job` has no `scope_id` · `resume_gate`/`resume_workflow` deposit only · no pause,
no live-walk cancel, no per-step timeout, no abort signal · no loops, no failure routing,
`_fail` stops the walk · fan-out/join is genuinely functualize-only · pi-workflows action
nodes **require** a declared managed effect, enforced at schema validation
(`schema.ts:120-131`) · leases/events/effects as described (`SQLITE_STATE.md:75-112`) ·
`maxSteps` default 100 · LOC 84,062 / 56,105 / ~1.07k engine · 0 built-in workflows ·
4 skills, none operating workflows · flow-viz is a job tree · `--scope-id` early-parse
(`dispatch.py:79`) · gate tool schemas published minus bound params.

Doc 06 (provenance) survived scrutiny with no errors found. Doc 07's `--wf-` namespace
reasoning is sound, and its pro-argument for keeping the pre-command `--scope-id` is
**stronger** than it claimed — see [01 §A.3](01-surface-inventory.md): only two builders
add the per-command option, and the warm path's gate depends on the discovery cache
carrying workflow topology, which is the documented cold-cache hazard. Keep the global.
