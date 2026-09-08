# Feature — workflow-continuation

**Roadmap items 1, 2, 3, 4, 5 and 6** of `pi-workflow-parity/13-roadmap.md`, landed as
one release. Item 0 shipped as `24c5cc0`; Tier 2 (items 7–9) is out of scope and §7 says
why.

---

## 1. The problem

**Nothing anywhere advances a blocked walk except re-invoking the job process, and only
one spelling can do it.**

Every verb called `resume` on every surface is a *deposit*. The CLI's
`builtin workflow resume` says so in its own docstring — *"Accepting input does not run
the workflow"*. MCP's `resume_gate` and `resume_workflow` do the same. The only
continuation is `func <wf> --scope-id X`, which an MCP agent cannot issue.

Around that centre, five verified defects:

### 1.1 The agent cannot learn the scope id it just created

`run_job` (`_tools.py:250-266`), `get_execution_status` (`:366-381`) and `_execute_job`
(`_server.py:271-278`) each return exactly `{status, return_value, duration_ms}`. The
executor builds `{"workflow_scope", "workflow_status", "blocked_on", "blocked_reason"}`
and it is dropped at the boundary. An agent that blocks a workflow receives `"Blocked"`
and must call `list_active_workflows()` and guess which scope is its own.

Two adjacent defects at the same boundary. `RunStatus` is a plain `Enum`, not a `str`
enum (`_types/enums.py:12` — verified), so `run_job` normalizes with `.value` while
`_execute_job` returns the raw enum object into a JSON dict. And the wire value is
`"Blocked"`, capitalized, where the docs say `"blocked"`.

### 1.2 `cancel` promises what nothing enforces

`cancel_workflow`'s description says *"Cancelled scopes are not resumable."*

Verified: `grep -c cancelled` over `_engine/executor.py`, `_engine/workflow_walker.py`
and `_engine/workflow_runner.py` returns **0, 0, 0**. `func <wf> --scope-id
<cancelled-id>` walks the scope to completion and overwrites the status.

### 1.3 One projection, two implementations, and the poor one faces humans

`WorkflowToolProvider._describe` (`_workflow_tools.py:506`) computes the full graph,
position, branch choices, per-step return values and resolved inputs, and gate schemas
with bound-argument-stripped tool summaries. The CLI's `_scope_summary`
(`_cli/builtins.py:935`) emits **five fields** over the same store, in the same process
— even under `--format json`.

Observability is inverted: the agent surface has everything, the human surface has five
fields. This is `pitfalls.md` §6 — a list hardcoded twice has already drifted — and the
drift is measurable: the two disagree on every field but `status`.

`call_gate_tool` is MCP-only for no reason; there is no CLI spelling for running a gate's
tool.

### 1.4 The two deposit paths store different shapes

`deposit_gate_input` (`app/_workflow_resume.py:60-107`) validates with `model(**payload)`
then stores the **raw dict** — discarding Pydantic defaults and coercion. The walker's
strategy path stores `model.model_dump()` (`workflow_walker.py:275` — verified).

So the same gate yields a different object depending on who answered it. A gate model
with a defaulted field has that field **missing** on the deposit path.

A gate also cannot be answered incrementally or corrected: `model(**payload)` is
all-or-nothing, and once `payload` is non-`None`, `pending_gates` stops listing the gate,
so every addressing path answers `gate_not_found`. Correcting a typo in a deposited
approval requires hand-editing `scopes.json`.

### 1.5 `--scope-id` is a category error, and it mints phantom runs

`WorkflowRunner.__init__` does `scope_id or new_scope_id()` and `FrontierWalk.start`
calls `ensure_scope`, so **a typo'd id silently becomes a phantom run** — verified: `func
trip-planner --scope-id my-own-chosen-id-001` exits 5 and creates a blocked scope under
that id.

It exists in two spellings. The pre-command one (`_cli/dispatch.py:79`, in
`_GLOBAL_OPTIONS_ALWAYS_VALUE`) is the only member of that set addressing **persisted
state** rather than discovery/config/perf, and it silently does nothing on a
non-workflow job. Per-command coverage is complete across all five dispatch modes, cold
and warm, so the global is redundant.

### 1.6 MCP loads every job as a tool, unconditionally

`MCPConfig` (`_config.py`) offers `include_tags`, `exclude_tags`, `exclude_jobs` and a
per-job `visibility` marker — all opt-in. There is no way to express *generic door only*.
The description builder appends examples unconditionally
(`_translator.py:186-208`) while the schema builder already inlines them (`:229-268`), so
the better a project documents its jobs, the more context every agent session pays before
saying anything.

### 1.7 The prerequisite defect: SINGLE_FILE crashes in its own directory

```
$ cd /tmp/sf && func weather.py trip_planner --help
ValueError: Cannot register dynamic job 'forecast': a job with this name already exists
```

Directory discovery registers `forecast` from `weather.py`, then
`_register_single_file_peers` (`_cli/main.py:1527`) registers it again and
`register_dynamic_job` (`_app/impl.py`) refuses. The same file **outside** the cwd works.
Unhandled `ValueError` with a traceback rather than an error envelope. It blocks one of
the five per-dispatch-mode tests §5 requires.

---

## 2. User stories

**US-1 · An agent drives a workflow to completion with no human typing.**
It calls `run_job("release")`, receives `{"status": "blocked", "workflow_scope": "a3f9c2",
"blocked_on": ["approval"]}` — its own id, in the reply. It answers the gate and
advances, both over MCP.

**US-2 · A second actor answers a gate one field at a time.**
An operator sets `approved=true` now; a reviewer adds `reason` an hour later. Neither
holds the whole answer. The gate opens when the draft validates whole.

**US-3 · Somebody corrects a typo in an approval.**
`answer <id> <gate> --reopen` moves the payload back to a draft — *unless the walk has
already consumed it*, in which case it refuses and names the position.

**US-4 · An operator sees what the agent sees.**
`func builtin workflow show <id>` prints the graph, the position, each step's return
value and resolved inputs, and each gate's schema — the same projection MCP returns.

**US-5 · The invoker of a workflow continues it without naming it.**
`func release --wf-resume` advances the one advanceable scope of `release`. With several,
it lists them and exits 2. It never guesses.

**US-6 · A cancelled run stays cancelled.**
`resume` on it exits 2 and points at a fresh start.

**US-7 · An agent session pays for eleven tools, not eleven plus ninety.**
`job_tools = "none"` in `MCPConfig` leaves the generic door, which now carries everything
the per-job tools carried.

---

## 3. Behaviour

### 3.1 The vocabulary

> **`answer` records. `resume` advances.** One meaning each, on every surface.

`answer <id> <gate>` fills a gate's payload slot and never runs anything. `resume <id>`
walks to the next durable boundary. Two verbs, distinct contracts, **no aliases**.

`resume` moving from *deposit* to *advance* matches what the repository already
documents: `docs/guides/mcp.md:55` describes `resume_workflow` as *"Advance a paused
workflow"*, `:200` says the workflow *"resumes when the AI agent calls
`resume_workflow`"*, and `docs/guides/workflows.md:247` says *"deposit gate input **and
advance**"*. The code moves to match the docs.

### 3.2 Derived run state

`status` stays the stored field. `state` is **derived** by the projection — no new stored
field, no `STATE_VERSION` bump, no `SCOPES_VERSION` bump:

| Derived `state` | Derivation | Means |
|---|---|---|
| `waiting` | status `blocked` **and** pending gates | needs an answer |
| `ready` | status `blocked`, **no** pending gates, no failed epilogue | answered — needs `resume` |
| `running` | status `running` | executing now |
| `completed` | status `completed`, epilogue ok or absent | done |
| `stalled` | status `completed`, epilogue `failed` | the sticky-body case |
| `failed` | status `failed` | a step raised; `resume` re-runs it |
| `cancelled` | status `cancelled` | terminal — `resume` refused |

`ready` is exactly the set `resume` can advance without input, and exactly what a
scheduler polls for.

### 3.3 Ambiguity never guesses

Zero candidates → error naming the survey verb. Exactly one → use it. Several → list them
and exit 2. **Never "newest wins"** — `blocked_at` resets on every re-block, so it is not
computable anyway.

### 3.4 The three tiers

| Operation | Tier 1 · `builtin workflow` | Tier 2 · MCP | Tier 3 · `--wf-*` |
|---|---|---|---|
| resume (advance) | `resume <id> [--input] [--gate] [--retry-epilogue]` | `resume_workflow(id, input?, gate?, retry_epilogue?)` | `--wf-resume [id]` |
| answer (record only) | `answer <id> <gate> [--input\|--set\|--unset\|--clear] [--show] [--commit/--no-commit] [--reopen]` | `answer_gate(id?, gate?, values, mode, commit, reopen)` | — |
| survey | `list [--workflow N] [--state S] [--blocked-on G] [--format]` | `list_workflows(workflow_name?, state?, blocked_on?)` | `--wf-status` |
| inspect | `show <id> [--format]` | `get_workflow_state(id)` | `--wf-show [id]` |
| gate tool | `gate-tool <id> <tool> [--args]` | `call_gate_tool(id, tool, args)` | — |
| cancel | `cancel <id>` | `cancel_workflow(id)` | — |
| purge | `purge [--older-than] [--state]` | `purge_workflows(...)` | — |

Tier 3 is a **strict subset**, not a separate design. A verb earns a `--wf-*` flag only
if the workflow is implied, the scope is inferable or in hand, and it is what someone
holding this job command wants. Nine flags:

```
  --wf-resume [ID]     Advance a scope of this workflow (the only advanceable one
                       if ID is omitted). Walks in this process.
  --wf-input JSON      Gate input for --wf-resume: validated, recorded, then the
                       walk advances.
  --wf-gate NAME       Which pending gate --wf-input answers (when several).
  --wf-status          List this workflow's scopes, then exit 0.
  --wf-show [ID]       Full projection of one scope, then exit 0.
  --wf-retry-epilogue  With --wf-resume: clear a stalled epilogue and re-fire it.
  --wf-run-id ID       Start under a caller-chosen scope id (idempotent start).
```

Gated to `@workflow` jobs, so a plain `@job`'s `--help` is unchanged. `--wf-show` renders
the **same** full projection as `builtin workflow show`; the flag saves naming the
workflow, it does not reduce the output.

### 3.5 `--scope-id` is deleted, both spellings

`--wf-resume` is strictly more capable, and fixes the phantom-run defect by splitting
*start under an id* (`--wf-run-id`, which may mint) from *advance an id* (`--wf-resume`,
which requires the scope to exist).

| | `--scope-id X` | `--wf-resume [X]` |
|---|---|---|
| Advance a named scope | yes | yes |
| Omit the id when unambiguous | no | **yes** |
| Fuse gate input | no | **yes** (`--wf-input`) |
| Unknown id | **silently starts a new run under it** | **errors** |
| Pre-command spelling | yes (a category error) | no |

No deprecation shim. Pre-command `--scope-id` becomes an unknown flag: `detect_mode`'s
scan skips boolean, always-value, optional-value, `--opt=value` and short options, so a
bare `--scope-id` falls through to the `break` and **becomes the first positional** —
`Error: Unknown command 'scope-id'`, exit 1. Loud, non-zero, and incapable of running the
wrong thing.

### 3.6 The gate draft slot

One new field on the gate record. `payload` is untouched in shape and meaning.

```
gates: { "approval": {
    "model": ..., "input_schema": ..., "tools": ..., "blocked_at": ...,
    "payload": null,                    # unchanged: null until COMPLETE and VALID
    "draft": {"values": {...}, "updated_at": "..."}   # new
} }
```

**The invariant that makes this safe: `payload` is only ever written by a full,
successful `model(**draft.values)`, and it is written as `model_dump()`.** Partial input
lives in `draft`; the walker never reads it. A blocked walk stays blocked until the draft
validates whole. Nothing about resume, replay or memoization changes.

Auto-commit is the default: every mutating `answer` attempts a commit at the end, so the
existing one-shot flow is unchanged.

`--reopen` is a separate explicit verb, **refused when the walk has consumed the
payload** — a scope whose position is past the gate has already used the answer, and
reopening would silently diverge recorded results from the answer that produced them.

### 3.7 Parity is pinned by a test, not asserted

1. One implementation per verb, in `app/`, re-exported through `functualize.app.utils` —
   the only arrangement `_cli` may legally import.
2. Same addressing: `answer_gate(id?, gate?)` accepts **both**, each optional when
   unambiguous.
3. Same result shape: `show` and `get_workflow_state` return the same projection;
   `list --format json` and `list_workflows` return the same rows.
4. Same error codes: one table, both surfaces.
5. **A parity test enumerates the verbs** and fails when either surface gains a verb or a
   parameter the other lacks. This is `pitfalls.md` §19 — a rule that cannot be shared
   needs a parity test, not a comment.

**The one honest exception:** `--prompt-gates` resolves gates interactively, inline. MCP
cannot — its strategy is `ai_outbound`, which always blocks by design. Parity is on
**verbs and their contracts**, not on interactive capability. Documented, not pretended.

### 3.8 MCP tool-surface control

`MCPConfig.job_tools: "all" | "tagged" | "none"`, default `"all"` (today's behaviour).
`"tagged"` registers only jobs carrying an opt-in tag; `"none"` registers none. Safe only
because 3.1's metadata fix means the generic door loses nothing.

Per-job tool descriptions stop appending examples that the schema already carries.

---

## 4. Acceptance criteria

**Metadata and status (item 1)**

- **AC-1** `run_job` on a workflow that blocks returns `workflow_scope`, `workflow_status`
  and `blocked_on` alongside `status`/`return_value`/`duration_ms`.
- **AC-2** `get_execution_status` and `_execute_job` return the same metadata keys as
  `run_job` for the same run.
- **AC-3** Every MCP door returns `status` as a **string**, never an `Enum` object; a
  blocked run's wire value is `"blocked"`, lowercase, on all four doors.

**Cancel (item 2)**

- **AC-4** Invoking a workflow job against a cancelled scope refuses with exit 2 and does
  not advance the walk or overwrite the status.
- **AC-5** `resume` on a cancelled scope refuses identically on CLI and MCP, with error
  code `scope_cancelled`.

**Projection (item 3)**

- **AC-6** `func builtin workflow show <id> --format json` and MCP
  `get_workflow_state(id)` return **byte-identical** JSON for the same scope.
- **AC-7** `func builtin workflow list --format json` and MCP `list_workflows()` return
  the same rows, including the derived `state` field.
- **AC-8** `list` filters by `--workflow`, `--state` and `--blocked-on`; MCP takes the
  same three parameters.
- **AC-9** `func builtin workflow gate-tool <id> <tool>` runs a gate tool with the same
  bound-argument refusal as MCP `call_gate_tool`.

**Gate answers (item 4)**

- **AC-10** A gate answered through `answer` and the same gate resolved by a strategy
  produce an **identical** stored payload, including Pydantic defaults.
- **AC-11** `answer <id> <gate> --set k=v` with a required field still missing stores a
  draft, leaves `payload` null, and reports what is missing.
- **AC-12** A draft that validates whole auto-commits: `payload` is written as
  `model_dump()` and the draft is cleared.
- **AC-13** `--no-commit` leaves a complete draft uncommitted and `payload` null.
- **AC-14** `--reopen` on a gate whose scope is still blocked at it moves `payload` back
  to `draft`; `--reopen` on a gate the walk has passed **refuses** and names the position.
- **AC-15** `answer --show --format json` reports `draft`, `satisfied`, `missing`,
  `invalid` and `complete`.

**Surface (item 5)**

- **AC-16** `func <wf> --wf-resume <id>` advances the walk in-process — a step that had
  not run, runs.
- **AC-17** `--wf-resume` with no id and exactly one advanceable scope uses it; with
  several, it lists them and exits 2; with none, it errors naming `--wf-status`.
- **AC-18** `--wf-resume <unknown-id>` **errors** and creates no scope.
- **AC-19** `--wf-run-id <new-id>` starts a run under that id, and running it twice is
  idempotent (the second invocation resumes, not restarts).
- **AC-20** `--wf-resume` is honoured in JOB, GROUP, UNKNOWN, SINGLE_FILE and embedded-app
  dispatch, **cold cache and warm** — a resumed scope replays rather than minting a new id.
- **AC-21** A plain `@job` carries no `--wf-*` flags on `--help`.
- **AC-22** Pre-command `--scope-id` exits non-zero and does **not** consume the job name
  as its value.
- **AC-23** `--scope-id` appears nowhere in `src/`, in either spelling.
- **AC-24** `func weather.py trip_planner --help` from the file's own directory succeeds.
- **AC-25** `--wf-status` and `--wf-show` exit 0 without running the job.

**MCP surface (item 6)**

- **AC-26** `job_tools="none"` registers zero per-job tools and leaves the core, workflow
  and generic-door tools intact.
- **AC-27** `job_tools="tagged"` registers only jobs carrying the opt-in tag.
- **AC-28** A per-job tool description no longer repeats examples the schema carries.

**Parity (cross-cutting)**

- **AC-29** A parity test enumerates every verb on both surfaces and fails when either
  gains a verb or parameter the other lacks.

---

## 5. Out of scope, deliberately

- **`--wf-watch`** — needs a live position stream, which is Tier 2's lease work.
- **Time columns and `--actor`** — scope records carry no timestamps
  (`_blank_scope` is `{workflow, status, steps, branches, gates, position, epilogue,
  tool_calls}`), and `blocked_at` resets on every re-block, so it measures the last
  resume attempt rather than the wait. Cannot be rendered honestly; not rendered.
- **`--wf-retry-failed`** — failed steps already re-run on resume. Redundant.
- **`run_job_async` lifecycle** (cancellation, persistence, eviction) — belongs with the
  durable run layer.
- **Concurrency fencing.** Advancing without naming the job makes concurrent `resume` one
  keystroke. The flock serializes writers but fences no stale walker. This feature ships
  the verb; the lease is Tier 2.

## 6. Prior art this feature is consistent with

- `pitfalls.md` §6 — one registry plus a test that checks it. The projection lift is
  exactly this: one implementation, plus AC-6/AC-7 asserting the two callers agree.
- `pitfalls.md` §19 — a rule that cannot be shared needs a parity test. AC-29.
- `pitfalls.md` §23 — two dispatch paths, one result-handling contract. The `--wf-*`
  family has two injection points (`click_params.py:1316` cold, `lazy_command.py:173`
  warm) and AC-20 runs every assertion on both.
- `pitfalls.md` §22 — a reader must not reconstruct a key the writer computed. The
  projection reads `scope["position"]`; it does not re-derive it.

## 7. Why Tier 2 is not here

Roadmap items 7 (agent-step port), 8 (durable run layer) and 9 (loops, failure routing,
watch, notify) are excluded. This is the roadmap's own sequencing, not a scope cut made
here: its table marks item 7 *"One release"* gated on item 5, item 8 *"Multi-release"*,
and item 9 *"Incremental"* gated on 8. Item 8 alone is an event log, lifecycle verbs,
runner leases, per-step timeouts and an effects outbox. Building any of it before item 5
exists would be building on the surface this feature defines.
