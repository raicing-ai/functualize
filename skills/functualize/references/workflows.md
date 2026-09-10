# Workflows

A workflow declares a multi-step job graph. It runs through the same execution
engine as any other job — `_engine/workflow_walker.py` walks it,
`workflow_runner.py` executes it, `workflow_validation.py` checks it.

## The declaration

```python
from functualize.workflow import workflow, Step, Edge, END

@workflow(
    steps=[
        Step(fetch_data),
        Step(transform_data),
        Step(load_data),
    ],
    edges=[
        Edge("fetch-data", "transform-data"),
        Edge("transform-data", "load-data"),
        Edge("load-data", END),
    ],
)
def etl_pipeline():
    """Extract, transform, and load data."""
```

`Step` takes the job itself — a callable or its registered name — and nothing
else; there is no separate node name to invent. Edges then reference the job's
**canonical name** (lowercase, hyphenated), which is what `func builtin info`
lists.

## The governing rule

**`@workflow` declares topology and nothing else.** Each `Step` references a
registered job, and that job's own `@job` declaration supplies DI, config,
dependencies, guards, and fingerprints. A workflow never restates an execution
concern — if you find yourself wanting retries or a guard in the graph, it
belongs on the step's job instead.

This is the single most common mistake, because the graph *looks* like the place
to configure the run.

## Vocabulary

Exported from `functualize.workflow`:

| Name | Purpose |
| --- | --- |
| `workflow` | The declaration decorator |
| `Step` | A node that runs a registered job |
| `Gate` | A node that pauses to collect input |
| `AgentStep` | A node performed by an agent, through a registered executor |
| `Tool` | A job a gate offers, with gate-fixed arguments narrowed away |
| `Edge` | A directed connection |
| `ConditionalEdge` | A branch taken on a runtime condition |
| `END` | Terminal sentinel |
| `FromStep` | Reads a recorded step result, to bind a gate tool's argument |

Confirm against the installed version:

```python
import importlib; print(importlib.import_module("functualize.workflow").__all__)
```

(`import functualize.workflow as w` binds the **decorator function**, not the
module — the package re-exports the name. Use `importlib` to reach the module.)

## Agent steps

`AgentStep(name, instructions, executor=None, tools=(), requires=frozenset(),
time_budget_s=None)` hands a node to a registered **executor** instead of running a
local function.

Executors are registered, never discovered:
`app.register_agent_step_executor(MyExecutor())`. An executor is anything with a
`name`, a `capabilities` collection and `execute(ctx) -> AgentStepResult`. Core
ships one, `cli-prompt`, which asks a person. `executor=None` means *the single
registered executor* — with two registered, a step naming none is refused rather
than guessed at.

Three capabilities: `enforces_tool_allowlist`, `preserves_active_time_budget`,
`supports_visible_output`. Two are **implied by the step's own declaration** —
`tools=[...]` implies the first, `time_budget_s=...` the second — and `requires=`
only widens. An executor that cannot honour one makes the step **refuse before the
walk starts**, rather than running with the constraint dropped.

`capabilities` may hold `AgentCapability` members or the bare strings above; they
are compared by value. An unknown name is refused at registration.

`ctx.inputs` is always empty and `AgentStepResult.tool_calls` is dropped by the
walker — both are declared and marked transitional in the source, naming the
feature that completes them: typed step outcomes and a run event stream
respectively.

## Gates

A `Gate` pauses the walk for input. `Tool(read_file, allowed=FromStep(...))`
offers a job to the gate with some arguments already fixed by an earlier step's
recorded result, so the gate presents a narrowed choice rather than a raw call.

Gate resolution lives in `_gate/`. A paused workflow persists as a scope.

### Strategies

`Gate(strategy=...)` names who answers the gate. Only four bare names are
valid — `"resolve"` (config chain), `"prompt"` (interactive surface),
`"ai_inbound"` (an LLM fills the model), `"ai_outbound"` (an external agent
deposits it). Preset names are **not** accepted here; presets are reachable
only through `rc.invoke(..., gate_strategy=...)` and `app.resolve_gate`.

Two are only registered when a plugin is installed: `ai_inbound` by
`functualize-ai`, `ai_outbound` by `functualize-mcp`.

**Blocking is the fallback.** A gate that cannot be resolved blocks, and the
walk is resumable — that includes `strategy=None`, `strategy="ai_outbound"`
(the walker blocks without calling any resolver), and a registered resolver
that fails.

The exception, worth knowing before you reach for it: naming `ai_inbound` on
a gate when `functualize-ai` is **not installed** raises
`ValueError: Unregistered gate strategy` and stops the walk — it does not
block. Declare an AI strategy only when the project depends on the plugin
that registers it.

## Inspecting and resuming

**`answer` records; `resume` advances.** One meaning each, on every surface.

```bash
func builtin workflow list                        # active scopes, with filters
func builtin workflow show <scope>                # graph, results, pending gates
func builtin workflow answer <scope> <gate> --input '{…}'   # records only
func builtin workflow resume <scope>              # advances the walk
func builtin workflow cancel <scope>              # terminal
```

Or, on the workflow job itself, when you already know which workflow it is:

```bash
func <workflow> --wf-status
func <workflow> --wf-resume --wf-input '{…}'      # answer and advance
```

A workflow that paused at a gate is resumable — the scope carries the recorded
step results. `show` is the authority on what a given workflow actually did,
which beats reasoning about the graph.

## When not to use one

A single job that calls others with `Invoke` is simpler and sufficient when the
sequence is straight-line and fully determined in code. Reach for `@workflow`
when the topology itself is the thing worth declaring — branching, gates,
resumability, or a graph an operator needs to see.

Full treatment: `docs/guides/workflows.md`.
