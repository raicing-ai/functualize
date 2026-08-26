# Workflows

A workflow declares a multi-step job graph. It runs through the same execution
engine as any other job — `_engine/workflow_walker.py` walks it,
`workflow_runner.py` executes it, `workflow_validation.py` checks it.

## The declaration

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
| `Tool` | A job a gate offers, with gate-fixed arguments narrowed away |
| `Edge` | A directed connection |
| `ConditionalEdge` | A branch taken on a runtime condition |
| `END` | Terminal sentinel |
| `FromStep` | Reads a recorded step result, to bind a gate tool's argument |

Confirm against the installed version:

```python
import functualize.workflow as w; print(w.__all__)
```

## Gates

A `Gate` pauses the walk for input. `Tool(read_file, allowed=FromStep(...))`
offers a job to the gate with some arguments already fixed by an earlier step's
recorded result, so the gate presents a narrowed choice rather than a raw call.

Gate resolution lives in `_gate/`. A paused workflow persists as a scope.

## Inspecting and resuming

```bash
func builtin workflow      # inspect and resume persisted workflow scopes
```

A workflow that paused at a gate is resumable — the scope carries the recorded
step results. This is also the authority on what a given workflow actually did,
which beats reasoning about the graph.

## When not to use one

A single job that calls others with `Invoke` is simpler and sufficient when the
sequence is straight-line and fully determined in code. Reach for `@workflow`
when the topology itself is the thing worth declaring — branching, gates,
resumability, or a graph an operator needs to see.

Full treatment: `docs/guides/workflows.md`.
