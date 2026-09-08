# 01 · Current state — the surface as it is, and its defects

Three surfaces, three audiences: the **CLI builtin group** (record-level, no boot),
**flags on the workflow job itself** (invocation-level), and **MCP tools** (agent-level).
Everything below is verified against `78d9ff4`.

Categories used throughout:
**Control** = changes a run's state · **Observability** = reads a run ·
**Management** = acts on the store as a whole.

---

## A. The complete inventory

### A.1 CLI builtin — `func builtin workflow` (`_cli/builtins.py:820-951`)

| Verb | Class | Signature | What it actually does |
|---|---|---|---|
| `list` | Observability | `--format table\|json` | Scopes with status ∈ {running, blocked}. Emits **5 fields**: id, workflow, status, position, pending-gate *names*. |
| `state <id>` | Observability | `--format table\|json` | The same 5 fields for one scope. No graph, no results, no gate schema — even under `--format json`. |
| `resume <id> <gate>` | Control | `--input JSON` | Validates against the gate model, deposits, prints a resume hint. **Does not advance the walk** (docstring says so). |
| `cancel <id>` | Control | — | Sets scope status to `cancelled`. Nothing else. |

Reads the store directly — no app boot — except `resume`, which needs the app to
materialize the gate's Pydantic model (`app/_workflow_resume.py:34-57`).

### A.2 Adjacent builtins that touch workflow state (and are not labelled as such)

| Verb | Class | Effect on workflows |
|---|---|---|
| `func builtin state show` | Observability | Prints `Scopes: N` — the only place a total count appears |
| `func builtin state clear` | **Management — destructive** | `save_state(path, empty_state())` — **wipes every scope**. Group help says "fingerprints, history"; command help says "Reset runtime state". Neither says *scopes*. |
| `func history` | Observability | Job executions, not walks. Separate section of the envelope. |

### A.3 Flags on a `@workflow` job invocation

| Flag | Layer | Class | Notes |
|---|---|---|---|
| `--scope-id <id>` | **Pre-command, early-parse** (`_cli/dispatch.py:79`, in `_GLOBAL_OPTIONS_ALWAYS_VALUE`) | Control | Resume a scope. Available on every dispatch mode unconditionally. |
| `--scope-id <id>` | **Per-command Click option** (`app/adapters/click_params.py:56-73`) | Control | Added only when the job declares `@workflow`, so it stays off other jobs' `--help`. Per-command wins over pre-command (`:1041`). |
| `--prompt-gates` / `--no-prompt-gates` | Pre-command boolean | Control | Resolve gates inline instead of blocking. Feeds `_gate_strategy_list` (`workflow_walker.py:475-487`). |
| `--force` | Pre-command boolean | Control | Ignores fingerprint freshness. Job-level; does **not** clear workflow step records. |
| `--output auto\|json\|ndjson\|raw\|none` | Pre-command, optional-value | Observability | Serializes the dispatch return value. Not workflow-aware. |

Two injection points add the per-command option, not three as previously claimed:
`create_job_click_command` on the cold/import path (`click_params.py:1230-1233`, gated on
`_declares_workflow(function)`) and `lazy_command` on the warm path
(`lazy_command.py:163-168`, gated on `descriptor.workflow is not None`). The warm gate
depends on the discovery cache carrying workflow topology — which is exactly the
cold-cache hazard documented at `main.py:2075-2081`. **This is why the pre-command
global must stay**: it is the only spelling that survives a cold cache on every mode.

There are **no other workflow flags**. No `--wf-status`, no inline input, no retry, no
epilogue control, no watch.

### A.4 MCP — workflow tools (`functualize_mcp/_workflow_tools.py:168-180`)

| Tool | Class | Signature | Notes |
|---|---|---|---|
| `get_workflow_state` | Observability | `(workflow_id)` | **Rich.** Full `steps` + `edges` topology, `current_position`, `branches`, and `results` — per step: status, **return_value**, resolved **inputs**, completed_at — plus `pending_gates` with input schemas and bound-arg-stripped tool summaries. |
| `list_active_workflows` | Observability | `()` | Same `_describe` projection for every scope with status ∈ {running, blocked}. **No filter parameters at all.** |
| `resume_gate` | Control | `(gate, input)` | Deposit by gate name. Ambiguous across scopes → refuses, points at `resume_workflow`. |
| `resume_workflow` | Control | `(workflow_id, input)` | Deposit by scope. Ambiguous across gates → refuses, points at `resume_gate`. |
| `call_gate_tool` | Control (side-effecting) | `(workflow_id, tool, args)` | Runs a gate-declared tool inside the paused scope. Bound args refused (`:309-323`); calls recorded, never memoized. |
| `cancel_workflow` | Control | `(workflow_id)` | Sets status `cancelled`. Description claims **"Cancelled scopes are not resumable"** — see §C.3. |

### A.5 MCP — execution doors that can *start* a workflow

| Tool | Class | Signature |
|---|---|---|
| `run_job` | Control | `(name, config)` — synchronous, blocking |
| `run_job_async` | Control | `(name, config)` → `{execution_id}`, background thread |
| `get_execution_status` | Observability | `(execution_id)` |
| *per-job tool* (one per discovered job) | Control | generated from the job's config schema |

**None of them accepts `scope_id`.** All four discard `JobResult.metadata`.

---

## B. The inventory read as a matrix

| | Control | Observability | Management |
|---|---|---|---|
| **CLI builtin** | `resume` (deposit only), `cancel` (cosmetic) | `list`, `state` — 5 fields | `state show`, `state clear` (destructive, mislabelled) |
| **Job flags** | `--scope-id`, `--prompt-gates`, `--force` | `--output` (not workflow-aware) | — |
| **MCP** | `resume_gate`, `resume_workflow`, `call_gate_tool`, `cancel_workflow`, `run_job*` | `get_workflow_state`, `list_active_workflows` — full projection | — |

### What the matrix shows

1. **Nothing anywhere advances a blocked walk except re-invoking the job process.**
   Every "resume" verb on every surface is a *deposit*. The only continuation is
   `func <wf> --scope-id X`, which an MCP agent cannot issue.
2. **Observability is inverted.** The agent surface has everything; the human surface
   has five fields. `func builtin workflow state --format json` could emit `_describe`'s
   projection today — same store, same process, function already written.
3. **There is no management category for workflows at all.** No retention, no purge of
   completed scopes, no cross-project view, no per-workflow filter. The only management
   verb that touches scopes is `state clear`, which is all-or-nothing and does not say
   it touches them.
4. **No filters anywhere.** `list_active_workflows()` takes no arguments;
   `workflow list` takes only `--format`. You cannot ask "which runs of
   `release-pipeline` are blocked on `approval`".

---

## C. Gaps that are defects, not missing features

### C.1 The agent cannot learn its own scope id

`run_job` (`_tools.py:250-266`), `get_execution_status` (`:366-381`) and `_execute_job`
(`_server.py:271-278`) each return exactly `{status, return_value, duration_ms}`. The
executor builds `{"workflow_scope", "workflow_status", "blocked_on", "blocked_reason"}`
correctly at `executor.py:1257-1283` and it is dropped at the boundary.

So the agent's honest sequence today is: call `run_job` → receive `"Blocked"` → call
`list_active_workflows()` → receive *every* live scope in the project → guess which one
it just created. There is no correlation id.

Two adjacent defects at the same boundary:

- `RunStatus` is a plain `Enum`, not a `str` enum (`_types/enums.py:12`). `run_job`
  normalizes with `.value`; `_execute_job` returns the raw enum object into a JSON dict.
  The two doors disagree on the shape of `status` — against the plugin's own stated
  intent (`_tools.py:87`).
- The value is `"Blocked"`, capitalized.

### C.2 The two deposit paths store different shapes

`deposit_gate_input` validates with `model(**payload)` then stores the **raw payload**
(`app/_workflow_resume.py:82-90`) — discarding Pydantic defaults and coercion. The
walker's own strategy-resolution path stores `model.model_dump()`
(`workflow_walker.py:270-277`) — coerced, defaults filled.

The walker then feeds whichever it finds straight to the node as its value
(`workflow_walker.py:300`). So the same gate yields a different object depending on
whether a human deposited it or a strategy resolved it. A gate model with a defaulted
field will have that field **missing** on the deposit path.

### C.3 `cancel_workflow` promises what nothing enforces

Tool description (`_workflow_tools.py:455-458`): *"Cancel a running or blocked workflow
scope. **Cancelled scopes are not resumable.**"*

The string `cancelled` appears **zero times** in `executor.py`, `workflow_walker.py` and
`workflow_runner.py`. `WorkflowRunner.prelude` never reads scope status
(`workflow_runner.py:101-127`); `FrontierWalk.start` sees a persisted position and
returns it without a status check (`frontier.py:95-107`). `func <wf> --scope-id
<cancelled-id>` walks the scope to completion and overwrites the status.

### C.4 `state clear` is an undocumented workflow-destroying verb

`StateStore.clear()` writes `empty_state()` (`state_store.py:361-365`). Group help:
*"Manage the runtime state store (fingerprints, history)."* Command help: *"Reset
runtime state. Does not touch the discovery cache."* Neither mentions scopes. A user
clearing stale fingerprints destroys every blocked run and every deposited approval.

This is the same root cause as the version-bump erasure (see
[07-roadmap.md](13-roadmap.md) item 0): the envelope's framing — *"runtime state is
derived, never a source of truth"* (`state_format.py:41-42`) — was written when it held
only fingerprints, and `scopes` was added underneath it without revisiting the rule.

### C.5 A gate, once answered, cannot be corrected

`pending_gates` filters to `payload is None` (`_workflow_resume.py:27-31`). Every
addressing path — CLI `resume`, MCP `resume_gate`, MCP `resume_workflow` — resolves
through it. So a deposited gate is invisible to every tool: `resume_gate` returns
`gate_not_found`. The store itself overwrites happily
(`state_store.py:232-241`) — only the tooling refuses.

Correcting a typo in a deposited approval currently requires hand-editing
`.functualize/state.json`. This is what [04-gate-deposit.md](07-gate-answers.md)
addresses.

---

### C.6 Scope records carry no clock

`_blank_scope()` (`state_store.py:45-56`) is `{workflow, status, steps, branches, gates,
position, epilogue, tool_calls}` — **no timestamps**. The only time data anywhere is
`blocked_at` on gate records and `completed_at` on step and epilogue records.

So "started 5m ago", "running for", "queued since" cannot be rendered by any surface
today, and `list`/`state`/`list_active_workflows` are unordered in time. Any scope-survey
design that shows age needs a store change first.

### C.7 `blocked_at` measures the last poke, not the wait

`_block(node)` passes `blocked_at=_now()` (`workflow_walker.py:459-472`), and `put_gate`
replaces the whole gate record (`state_store.py:215-222`). `_block` runs on **every** walk
that reaches a still-unanswered gate, so each `func <wf> --scope-id X` resets it.

Consequences: an "awaiting 2h" column would report time since the last resume attempt;
and any "newest blocked scope" tiebreak would select the most recently *poked* scope, not
the oldest or newest wait. (The deposited payload is safe — `_block` is only reached when
`payload is None`.)

### C.8 `batch()` is dead code, and its docstring says otherwise

`StateStore.batch()` (`state_store.py:98-114`) exists to hold the lock across many
mutations and write once. The module docstring says *"A run that makes many mutations
should use :meth:`StateStore.batch`"* (`:9-11`).

**It has zero call sites** — nothing in `src/`, `plugins/` or `tests/` calls it. So every
mutation is an independent locked read-modify-write of the whole envelope: `record_step`,
`set_position` and `set_scope_status` fire per node, so a 10-step walk rewrites a file
holding every fingerprint and a 200-entry history ring roughly 30 times.

Two consequences. It is a latent performance issue on the walk's hot path. And it means
scopes and fingerprints are **never written in one transaction**, which is why splitting
them into separate files (B1) carries no atomicity risk.

## D. What a complete surface would look like

Marked **have** / **broken** (exists but wrong) / **missing**.

| Verb | Class | CLI builtin | Job flag | MCP |
|---|---|---|---|---|
| start | Control | have (`func <wf>`) | — | have (`run_job`) |
| **continue a blocked walk** | Control | **missing** | **missing** | **missing** |
| deposit gate input (whole) | Control | have | missing | have |
| **deposit partially / edit** | Control | **missing** | **missing** | **missing** |
| cancel | Control | broken (C.3) | — | broken (C.3) |
| pause | Control | missing | — | missing |
| retry failed epilogue | Control | missing | missing | missing |
| run gate tool | Control | **missing** (MCP-only today) | — | have |
| list runs | Observability | have (thin) | missing | have (rich) |
| inspect one run | Observability | **broken** (thin) | missing | have (rich) |
| filter runs | Observability | missing | missing | missing |
| watch live | Observability | missing | missing | missing |
| purge completed scopes | Management | missing | — | missing |
| clear all state | Management | broken (C.4) | — | missing |

The two rows in bold that cost nothing to fix — **inspect one run** (call `_describe`)
and **run gate tool** (lift from the plugin the way `deposit_gate_input` was lifted) —
are worth more than most of the previous study's W1.
