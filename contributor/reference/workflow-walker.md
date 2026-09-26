# Workflow Walker Reference

**Audience:** contributors working on workflow execution, gate resolution, or MCP workflow tools.
**Status:** shipped (Phase 3.5, ADR-005).

## 1. Vocabulary

Five names. No overlap with `@job` — `@workflow` declares what `@job` structurally cannot
(sequencing, routing, and pause points *between* jobs).

| Name | Purpose |
|------|---------|
| `Step(job_ref)` | References a registered job (callable or string). A step *is* a job invocation — DI, config, `Deps`, `Guards`, `Fingerprint`, `Exec` all come from the referenced job's declaration. |
| `Gate(name, awaits=Model, tools=[])` | First-class pause point. Waits for input matching `Model`. Gate resolution goes through the gate registry — same mechanism as `invoke(awaits_input=…)`. |
| `Edge(source, target=END)` | Unconditional transition. `END` is the sentinel for the walk's terminal node. |
| `ConditionalEdge(source, condition, mapping={value: target})` | Runtime routing. `condition` is a Python callable; `mapping` maps return values to step names. |
| `END` | Terminal node. Reaching `END` triggers the epilogue body. |

## 2. `@workflow` Decorator

```python
from functualize.workflow import workflow, Step, Gate, Edge, END

@workflow(
    steps=[
        Step("forecast", job=forecast),
        Gate("preferences", awaits=TripPreferences, tools=["search_hotels"]),
        Step("plan", job=travel_plan),
    ],
    edges=[
        Edge(source="forecast", target="preferences"),
        Edge(source="preferences", target="plan"),
        Edge(source="plan", target=END),
    ],
)
def trip_planner():
    """Multi-step trip planning with AI checkpoint."""
```

- **Topology-only** — the decorator declares only structure.
- **`__workflow_def__`** dunder is set on the function (analogous to `__functualize_job__`).
- **Epilogue body** — the decorated function's body executes after the walk reaches `END`,
  with normal DI. The body's return value IS the workflow job's return value.
  An empty body is legal (returns `None`).
  > **Not implemented:** the `FromJob[step]` / `FromStep[step]` *subscript* injection
  > described below was designed but never built — neither class defines
  > `__class_getitem__`, and no resolver reads them from an epilogue signature.
  > `FromStep`'s implemented use is the gate-tool binding
  > `Tool(job, arg=FromStep("step"))`.

## 3. Walker Mechanics

### One-engine rule

Both `Deps` and `@workflow` edges compile into the **same internal graph representation**
executed by one engine. Two graph vocabularies are acceptable; two graph engines are not.

### FrontierWalk

The walker uses `FrontierWalk` — runtime frontier expansion via `graphlib.TopologicalSorter`.
`ConditionalEdge` makes upfront scheduling impossible (branch targets are unknowable until
the source returns), so the scheduler operates in **push mode**:

1. Prepare the graph
2. Expand frontier: get nodes with no unresolved predecessors
3. Execute each node in the frontier (through the engine)
4. For `ConditionalEdge` sources, evaluate the condition and mark the chosen target
   as ready; mark unchosen targets as skipped
5. Repeat until `END` is reached

### Branch recording

A chosen `ConditionalEdge` key is recorded in the per-scope state store on first
evaluation and *read* on replay. A non-deterministic condition must not change branches
between pause and resume.

## 4. Resume Semantics (Q9)

Resume = **replay + memoization.** Resuming a workflow re-invokes the workflow job;
fingerprints, guards, and per-scope records make completed work skip; the gate resolves
from deposited input this time.

| What | Behavior on resume |
|------|--------------------|
| Completed steps (per-scope) | **Skip** — never re-run (determinism for orchestration) |
| Recorded branch choices | **Stable** — read from per-scope record, not re-evaluated |
| Deposited gate inputs | **Stable** — read from state store |
| `Deps` edges | **Stale deps re-run** (correctness for builds) |
| `FromJob` / `FromStep` injection | **Fresh** — always implies a dependency edge; inject cached value if fingerprint-fresh, otherwise run upstream |
| Scope status while the resume walks | **`running` from entry** — never the `blocked`, `failed` or `completed` it resumed from |

**A resumed walk is live, and says so.** Every entry into a walk stamps the scope `running` — first
entry and resume alike — so a scope resumed from `blocked`, `failed` or `completed` reads `running`
from the moment the walk starts. This was a defect before it was a convention: the resumed branch of
`FrontierWalk.start` left the old status in place, so a walk that finished after resuming wrote
`COMPLETED` over a record that still said `blocked`, and the scope's transition table had to carry
four pairs (`blocked → completed`, `blocked → failed`, `failed → completed`, `failed → blocked`) that
existed only as traces of it. Those four pairs are gone, and the scope machine refuses them.

Two consequences an operator sees:

- `list_scopes` reports a resumed walk as **`running`** — or `abandoned`, once its claim's lease
  lapses — instead of `waiting` / `ready`, so "parked at a gate" and "walking right now" stop looking
  alike.
- `advanceable_scopes` now lists a scope resumed from `failed` or `completed` while it walks, because
  it reads `running`, which the live set holds. A scope resumed from `blocked` was listed before and
  still is.

`blocked` therefore means exactly one thing: the walk stopped at a gate it could not resolve. A gate
the walk resolves inline — the gate service arm in `_engine/workflow_walker.py` — records its slot
through `record_gate` and keeps the status it had, instead of stamping `BLOCKED` on its way through
and leaving a live scope looking parked.

## 5. Epilogue Body

The workflow function's body runs **after** `END` with:

```python
@workflow(steps=[...], edges=[...])
def deploy_pipeline(from_job: FromJob["build"]) -> DeployResult:
    build_artifacts = from_job["build"]
    done = len(build_artifacts.targets)
    return DeployResult(done=done)
```

- All `Step` results are recorded in the scope (§D.7d). The
  `FromJob[step_name]` / `FromStep[step_name]` subscript spelling here is
  **design intent, not current behavior** — see the epilogue note above.
- DI resolves standard capabilities (`Log`, `Shell`, etc.) as usual
- The body's return value IS the workflow's return value
- An empty body returns `None`

## 6. Chaining and Nesting

Workflows are ordinary jobs in every observable way:

```python
# Chain: workflow depends on another workflow
@job(deps=Deps("lint_workflow"))
def deploy(sh: Shell): ...

# Consume: workflow's return value feeds into a job
@job
def report(artifacts: FromJob["build_workflow"]): ...

# Nest: workflow as a step inside another workflow
@workflow(steps=[Step("build", job=build_workflow), ...], ...)
def full_pipeline(): ...

# Nesting creates a child scope — per-scope records are namespaced
```

**Static cycle detection:** cycles between workflows are caught at decoration time
(e.g. `A → deps(B) → deps(A)`).

## 7. Cache Contract

The workflow graph shape is serialized into the discovery cache:

- Step → job name mapping
- Edge topology (source → target pairs)
- Gate definitions (name, awaited model class path, tool list)

**Requires materialization:** condition callables (for `ConditionalEdge`) and schema
validation (for `Gate.awaits` models) require the job module to be imported — the
cache carries opaque references only.

## 8. MCP Tools

`functualize-mcp` exposes workflow tools for AI agents:

| Tool | Purpose |
|------|---------|
| `get_workflow_state(id)` | Graph, results, position, pending gates |
| `list_workflows(workflow_name?, state?, blocked_on?)` | Survey scopes |
| `answer_gate(values, workflow_id?, gate?, …)` | **Record** input for a gate |
| `get_gate_draft(workflow_id?, gate?)` | Supplied / missing / invalid |
| `resume_workflow(id?, input?, gate?, …)` | **Advance** the walk |
| `call_gate_tool(id, tool, args?)` | Run a tool the gate offers |
| `cancel_workflow(id)` | Cancel — terminal, enforced in `WorkflowRunner.prelude` |
| `purge_workflows(state?, older_than_days?)` | Delete finished scopes |

Each has a `func builtin workflow` twin taking the same identifiers, held by
`tests/workflow/test_workflow_surface_parity.py` — which derives both sets from
the live surfaces, so neither can grow alone.

## 9. §D.7 Constraints

The walker engine must honor these four constraints (from the proposal §D.7, ratified
during Phase 3 implementation):

1. **(a) Runtime frontier expansion** — `ConditionalEdge` requires push-mode scheduling
   alongside the pull-mode `Deps` scheduler, over one graph model.
2. **(b) `BLOCKED(awaiting=Model)`** — gates are surface-resolved input acquisition.
   Three surface outcomes: interactive surfaces prompt inline; non-interactive CLI exits
   with typed error + resume token; MCP surfaces persist the block for agents.
3. **(c) Graph position and gate payloads persist** — state store carries blocked-walk
   positions so the walk survives observation and resumption.
4. **(d) Per-scope step-result records** — one record type for replay-skip,
   branch-choice recording, persistent dedupe, and epilogue injection.

## 10. A walk refused at the door: `HELD`

A scope is claimed for the duration of a walk (`durable-run-layer`/T7), so a second walk on the
same scope is refused before it starts. Since FUN-17/T14 that refusal is a **value the caller
branches on**, not an exception, and it has its own outcome (`R-14.2`):

- **`WalkOutcome.HELD`** (`_engine/workflow_walker.py:144`, documented at `:138-143`) means
  *another runner held the scope before this walk started*. It is deliberately distinct from
  `SUPERSEDED`, which is documented as *taken while running*: a `HELD` walk never ran and never
  held the scope, so there is nothing to release and no `walk.end` event to suppress.
- **Where it is produced.** `Walker.run` claims through the port (`workflow_walker.py:346`) and
  branches on `Conflict` **before** its `try` (`:347`), returning
  `WalkReport(HELD, scope_id, error="scope held by <owner> at generation <n>")` (`:352-359`). The
  holder's name and the held generation ride the report's `error`, which is what `LeaseHeldError`
  used to carry — now as data.
- **How it reaches you.** `WorkflowRunner.prelude` sends every non-`COMPLETED` outcome down the
  generic path (`workflow_runner.py:217-223`), and the orchestrator stamps
  `metadata["workflow_status"] = run.outcome.value` (`workflow_orchestrator.py:219`). `BLOCKED`
  becomes `RunStatus.BLOCKED` (`:239`); `HELD` falls through to `RunStatus.FAILURE` (`:246`). So a
  resume of a held scope answers `"status": "failure"` (`app/_workflow_control.py:375-381`) with
  `metadata["workflow_status"] == "held"` and the holder named in the raised error.

**What a `HELD` refusal names, and what it does not.** `Conflict`
(`_types/persistence.py:337-346`) carries `scope_id`, `held_by` and `held_generation` — and
**no expiry**, although `Claimed` carries `expires_at` and the `LeaseHeldError` it replaced carried
`expires_at` as well. The document backend's translation reads `held.owner` and re-reads the lease
only for its generation (`_primitives/document_store.py:509-515`), so the expiry is dropped on the
way through. A reader is told *who* holds the scope and *how stale they are*, never *until when*.

That is not a reason to avoid resuming: it is why the verbs below exist.

| The question | Where it is answered |
|---|---|
| Until when is it held? | `func builtin workflow reclaim <id>` — refuses a **live** lease with `"Workflow '<id>' is held by <owner> until <expires_at>. Cancel it if the holder should stop."` (`app/_workflow_control.py:485-490`; CLI at `_cli/builtins.py:1815`). This is the one surface that still answers the expiry question |
| Is the holder even alive? | `func builtin workflow show <id>` — `state` is derived from the lease clock (`app/_workflow_view.py:196`, helpers at `:80` and `:105`): `running` versus `stalled`/`abandoned`. It reports liveness, **not** the holder — `_describe` (`:335-380`) projects no lease field, so the owner and expiry appear only in the raw scope document `store.get_scope()` returns |
| It should stop now | `func builtin workflow cancel <id>` — takes the scope from a live holder with `force=True` (`app/_workflow_control.py:396-450`) |
| It is gone, I want it | `func builtin workflow reclaim <id>` — takes the scope and immediately releases it, and says plainly that the previous runner was **not** stopped (`app/_workflow_control.py:492-530`) |

Reading the lease directly is also available to callers: `read_lease` / `is_expired`
(`_primitives/lease.py`), or `_lease_has_lapsed` and `walk_is_live`
(`app/_workflow_view.py:80`, `:105`) — the latter stricter, because an **absent** lease is not an
abandoned one.

**Not fixed here.** Giving `Conflict` an expiry, or having the walk read the lease before refusing,
is a change to the persistence port rather than to the walker, and it is recorded as an accepted
surviving smell in `.spec/features/runtime-persistence-ports/plan.md` → *Surviving smells*. Until
that decision is taken, the refusal stays as it is: a refusal that names the holder and defers the
clock to the verbs that own it.
