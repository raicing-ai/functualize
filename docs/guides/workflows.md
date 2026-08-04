# Workflows

Workflows let you declare multi-step job graphs that execute in sequence, branch conditionally, and pause for input (gates). They're defined declaratively with the `@workflow` decorator and run through the same execution engine as every other job.

---

## Basic Workflow

```python
from functualize.workflow import workflow, Step, Edge, END

@workflow(
    steps=[
        Step("fetch", job=fetch_data),
        Step("transform", job=transform_data),
        Step("load", job=load_data),
    ],
    edges=[
        Edge(source="fetch", target="transform"),
        Edge(source="transform", target="load"),
        Edge(source="load", target=END),
    ],
)
def etl_pipeline():
    """Extract, transform, and load data."""
```

Steps execute in the order defined by edges. Each step references a registered job function — the job's own `@job` declaration supplies DI, config, deps, guards, and fingerprints. `@workflow` never restates an execution concern.

---

## Vocabulary

Five names. No overlap with `@job`:

| Name | Purpose |
|------|---------|
| `Step(name, job=...)` | References a registered job. The step is a job invocation — DI, config, `Deps`, `Guards`, `Fingerprint`, `Exec` all come from the referenced job. |
| `Gate(name, awaits=Model, tools=[])` | First-class pause point. Waits for input matching a Pydantic model. |
| `Edge(source, target)` | Unconditional transition. `END` is the sentinel for the walk's terminal node. |
| `ConditionalEdge(source, condition, mapping)` | Runtime routing. `condition` is a callable; `mapping` maps return values to step names. |
| `END` | Terminal node. Reaching `END` triggers the epilogue body. |

---

## Conditional Branching

Use `ConditionalEdge` to route based on a step's return value:

```python
from functualize.workflow import workflow, Step, Edge, ConditionalEdge, END

def route_by_status(result) -> str:
    if result["score"] > 0.8:
        return "approve"
    return "review"

@workflow(
    steps=[
        Step("score", job=score_submission),
        Step("approve", job=auto_approve),
        Step("review", job=manual_review),
    ],
    edges=[
        ConditionalEdge(
            source="score",
            condition=route_by_status,
            mapping={"approve": "approve", "review": "review"},
        ),
        Edge(source="approve", target=END),
        Edge(source="review", target=END),
    ],
)
def review_pipeline():
    """Score and route submissions."""
```

Branch choices are recorded in the state store — if a paused workflow is resumed, the branch does not change.

---

## Gates (Input Pauses)

A `Gate` is a first-class workflow node that pauses execution and waits for structured input:

```python
from pydantic import BaseModel, Field
from functualize.workflow import workflow, Step, Gate, Edge, END

class ApprovalInput(BaseModel):
    approved: bool = Field(description="Whether to approve")
    reason: str = Field(default="", description="Approval reason")

@workflow(
    steps=[
        Step("prepare", job=prepare_deploy),
        Gate("approve", awaits=ApprovalInput, tools=["search_hotels"]),
        Step("deploy", job=execute_deploy),
    ],
    edges=[
        Edge(source="prepare", target="approve"),
        Edge(source="approve", target="deploy"),
        Edge(source="deploy", target=END),
    ],
)
def deploy_workflow():
    """Deploy with approval gate."""
```

Gate resolution goes through the gate registry. Three surface outcomes:

| Surface | Resolution |
|---------|-----------|
| Interactive TUI/CLI | Prompts inline for input |
| Non-interactive CLI | Exits with a typed error + resume token |
| MCP (AI agent) | Persists the block; agent calls `resume_workflow(id, input)` |

---

## Epilogue Body

The workflow function's body executes **after** `END` is reached. It receives standard DI:

```python
from functualize.workflow import workflow, Step, Edge, END

@workflow(
    steps=[
        Step(build),
        Step(test),
    ],
    edges=[
        Edge(source="build", target="test"),
        Edge(source="test", target=END),
    ],
)
def release_pipeline(rc: RunContext) -> str:
    rc.log("pipeline complete")
    return "released"
```

The body's return value IS the workflow job's return value. An empty body is legal (returns `None`). This makes a workflow an ordinary job — it can be used in `Deps()`, consumed via `FromJob`, or nested as a `Step`.

## `FromStep`

`FromStep` reads *this walk's* recorded result for one step. Its use is binding a gate tool's argument, so the tool is scoped to exactly what an earlier step produced:

```python
from functualize.workflow import Gate, Tool, FromStep

Gate(
    name="review",
    awaits=Decision,
    tools=[Tool(read_file, allowed=FromStep("setup-vfs"))],
)
```

The agent may call `read_file`, but `allowed` is fixed to whatever `setup-vfs` returned in this scope — a call outside those files is inexpressible rather than refused.

`FromStep` is distinct from [`FromJob`](#) because it can **never** trigger a run: it only reads a step the graph has already ordered and executed. Take the referenced step by name (`FromStep("setup-vfs")`) or by the decorated function (`FromStep(setup_vfs)`); both normalize to the same canonical name.

---

## Chaining and Nesting

Workflows are ordinary jobs in every observable way:

```python
# Chain: workflow as a dependency
@job(deps=Deps("lint_workflow"))
def deploy(sh: Shell): ...

# Consume: workflow's return value feeds a job
@job
def report(artifacts: FromJob["build_workflow"]): ...

# Nest: workflow as a step inside another workflow
@workflow(
    steps=[Step("build", job=build_workflow), Step("deploy", job=deploy)],
    edges=[Edge(source="build", target="deploy"), Edge(source="deploy", target=END)],
)
def full_pipeline(): ...
```

Workflow nesting creates child scopes — state and records are namespaced.

---

## Resume Semantics

Resuming a paused workflow replays it with memoization:

| What | Behavior on resume |
|------|--------------------|
| Completed steps | Never re-run (orchestration determinism) |
| Recorded branch choices | Stable — read from state, not re-evaluated |
| Deposited gate inputs | Stable |
| `Deps` edges | Stale deps re-run (correctness) |

---

## MCP Integration

When `functualize-mcp` is installed, workflows are exposed as MCP tools:

```bash
func builtin mcp serve
```

AI agents can:
- `list_active_workflows()` — see paused/running workflows
- `get_workflow_state(id)` — current step, pending gate, available tools
- `resume_workflow(id, input)` — deposit gate input and advance
- `cancel_workflow(id)` — cancel execution

---

## Validation

Workflow graphs are validated at decoration time:

- Duplicate step names → `ValueError`
- Unknown step references in edges → `ValueError`
- `awaiting` not a BaseModel subclass → `TypeError`

---

## See Also

- [Task Runner Guide](task-runner.md) — `@job` decorator, deps, fingerprints, and guards
- [MCP Guide](mcp.md) — exposing workflows to AI agents
