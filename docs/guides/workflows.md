# Workflows

Workflows let you declare multi-step job graphs that execute in sequence, branch conditionally, and pause for input (gates). They're defined declaratively with the `@workflow` decorator and run through the same execution engine as every other job.

---

## Basic Workflow

```python
from functualize.workflow import workflow, Step, Edge, END

@workflow(
    steps=[
        Step(fetch_data),
        Step(transform_data),
        Step(load_data),
    ],
    edges=[
        Edge(source="fetch-data", target="transform-data"),
        Edge(source="transform-data", target="load-data"),
        Edge(source="load-data", target=END),
    ],
)
def etl_pipeline():
    """Extract, transform, and load data."""
```

Steps execute in the order defined by edges. Each step references a registered job function — the job's own `@job` declaration supplies DI, config, deps, guards, and fingerprints. `@workflow` never restates an execution concern.

---

## Vocabulary

Six names. No overlap with `@job`:

| Name | Purpose |
|------|---------|
| `Step(job)` | References a registered job — by name or by the decorated function. A step takes nothing else: DI, config, `Deps`, `Guards`, `Fingerprint`, `Exec` all come from the referenced job. Its node name is the job's canonical name (`Step(fetch_data)` → `"fetch-data"`). |
| `Gate(name, awaits=Model, tools=[], strategy=None)` | First-class pause point. Waits for input matching a Pydantic model. `strategy` is one of `"resolve"`, `"prompt"`, `"ai_inbound"`, `"ai_outbound"`, or a registered preset. |
| `AgentStep(name, instructions, executor=None, tools=(), requires=frozenset(), time_budget_s=None)` | A node performed by an **agent**, not by a registered job. See [Agent steps](#agent-steps). |
| `Edge(source, target)` | Unconditional transition. `END` is the sentinel for the walk's terminal node. |
| `ConditionalEdge(source, condition, targets)` | Runtime routing. `condition` is called with the source step's return value; `targets` maps its return value to node names or `END`. |
| `END` | Terminal node. Reaching `END` triggers the epilogue body. |

---

## Agent Steps

`Step` and `Gate` both end in a local function call. `AgentStep` does not: it hands the
work to a registered **executor**, which may talk to a model, an MCP client, or a person at
a terminal. That difference is why it has its own node kind rather than being a job that
happens to call an API.

```python
from functualize import AgentStep, Edge, END, Step, workflow

@workflow(
    steps=[
        Step(fetch_context),
        AgentStep(
            "draft",
            instructions="Draft the release notes from the fetched changelog.",
            tools=["read_file"],
            time_budget_s=120,
        ),
        Step(publish),
    ],
    edges=[
        Edge("fetch-context", "draft"),
        Edge("draft", "publish"),
        Edge("publish", END),
    ],
)
def release() -> str:
    return "released"
```

### Executors are registered, never discovered

```python
app.extensions.register_agent_step_executor(MyExecutor())
```

There is no auto-discovery, on purpose: a surface that acquires behaviour nobody declared is
how a workflow silently changes what it does. Functualize ships one executor, `cli-prompt`,
which asks a person to perform the step.

`executor=None` means *the single registered executor*. That is a unique answer only when
exactly one is registered — with two, a step naming none is **refused**, because handing it
to either would be substituting an executor for the one the step meant.

### Capabilities: what an executor promises it can enforce

| Capability | Means |
|------------|-------|
| `enforces_tool_allowlist` | The executor restricts the agent to the declared `tools`. |
| `preserves_active_time_budget` | The executor honours `time_budget_s`. |
| `supports_visible_output` | The executor can surface the agent's output to the user. |

Two of these are **implied by what the step declares**: `tools=[...]` implies
`enforces_tool_allowlist`, and `time_budget_s=...` implies
`preserves_active_time_budget`. `requires={...}` widens that set; nothing narrows it.

An executor that cannot honour a required capability makes the step **refuse before the
walk starts** — not run with the constraint dropped:

```
Agent step 'draft' requires 'enforces_tool_allowlist', which executor 'plain' does not
declare (it declares: no capabilities). The step is refused — running it would leave the
constraint unenforced.
```

Refusing before the first node matters: by the time a walk is halfway through, the earlier
steps' side effects have already happened for a step that was never going to run.

### Writing an executor

An executor is anything with a `name`, a `capabilities` collection, and `execute(ctx)`:

```python
from functualize.plugin import AgentStepContext, AgentStepResult

class MyExecutor:
    name = "my-agent"
    capabilities = frozenset({"enforces_tool_allowlist"})

    def execute(self, ctx: AgentStepContext) -> AgentStepResult:
        return AgentStepResult(value=run_the_agent(ctx.instructions, ctx.tools))
```

`capabilities` may hold `AgentCapability` members or the bare strings above; they are
compared by value. A name functualize does not define is refused at registration — a
capability nothing requires can never be matched, so it is a typo rather than an extension
point.

`ctx.inputs` and `AgentStepResult.tool_calls` are declared but not yet wired: `inputs` is
always empty until typed step outcomes land, and the walker records `result.value` and
drops `tool_calls` until there is a run event stream to write it to. Both are marked
`TRANSITIONAL` in the source with the feature that completes them.

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
        Step(score_submission),
        Step(auto_approve),
        Step(manual_review),
    ],
    edges=[
        ConditionalEdge(
            source="score-submission",
            condition=route_by_status,
            targets={"approve": "auto-approve", "review": "manual-review"},
        ),
        Edge(source="auto-approve", target=END),
        Edge(source="manual-review", target=END),
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
        Step(prepare_deploy),
        Gate("approve", awaits=ApprovalInput, tools=[search_hotels]),
        Step(execute_deploy),
    ],
    edges=[
        Edge(source="prepare-deploy", target="approve"),
        Edge(source="approve", target="execute-deploy"),
        Edge(source="execute-deploy", target=END),
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

## Getting values into a step

A `Step` takes **no arguments** — it names a job, and that job's own
declaration supplies everything else. There is no way to pin a parameter from
the graph, by design: a step is a pointer at behaviour that is already declared
and independently runnable.

So a value reaches a step the same way it reaches any job:

- **Its config ladder.** Config file, environment variable, and defaults are
  re-resolved on every execution and reach every step of the walk. A
  [group option](group-options.md) is the one lever that covers a whole family
  of jobs at once — `LAB__STRICT=true` is read by every job declaring that
  class.
- **From an earlier step**, with `FromJob`. Inside a walk this is a *read* of
  the recorded result, never a trigger, and boot validation rejects the graph
  unless it already orders that step first.

```python
@job(group="check", deps=Deps("lab.bundle"))
def signoff(parsed: Annotated[Parsed, FromJob("lab.report")]) -> None: ...
```

The **mid-path flag layer is the exception**: it belongs to the command line
that typed it, so `func lab --strict release` does not set `--strict` for the
walk's steps. To steer a whole walk, set a layer each job reads for itself —
`LAB__STRICT=true func lab release`. See
[Group Options](group-options.md#steering-a-whole-run-from-code) for that move
from Python.

To compute a value and share it, make the computation the graph's **first
step** and have the others read it with `FromJob`. The decorated function's own
body cannot do this — it is an epilogue, and runs only after `END`.

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
def report(artifacts: Annotated[list[Artifact], FromJob("build_workflow")]): ...

# Nest: workflow as a step inside another workflow
@workflow(
    steps=[Step(build_workflow), Step(deploy)],
    edges=[Edge(source="build-workflow", target="deploy"), Edge(source="deploy", target=END)],
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
func mcp serve
```

AI agents can:
- `list_workflows()` — survey scopes, filterable by workflow, state, or pending gate
- `get_workflow_state(id)` — current step, pending gate, available tools
- `answer_gate(values, workflow_id?, gate?)` — record gate input
- `resume_workflow(id?, input?)` — advance the walk, optionally answering first
- `cancel_workflow(id)` — cancel execution

---

## Validation

Workflow graphs are validated at decoration time:

- Duplicate step names → `ValueError`
- Unknown step references in edges → `ValueError`
- `awaiting` not a BaseModel subclass → `TypeError`

---

## See Also

- [Composing Capabilities](composition.md) — how this fits with the other capabilities: a combination matrix of what happens at each intersection, and the traps between them
- [Task Runner Guide](task-runner.md) — `@job` decorator, deps, fingerprints, and guards
- [MCP Guide](mcp.md) — exposing workflows to AI agents
