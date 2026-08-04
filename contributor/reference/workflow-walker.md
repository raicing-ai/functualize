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
| `get_workflow_state(id)` | Current step, pending gate, available tools |
| `list_active_workflows()` | All paused/running workflows |
| `resume_gate(id, input_data)` | Deposit input for a blocked gate |
| `resume_workflow(id)` | Resume a paused workflow |
| `cancel_workflow(id)` | Cancel a running workflow |

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
