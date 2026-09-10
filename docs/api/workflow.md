# Workflow Module

::: functualize.workflow
    options:
      show_root_heading: true
      members_order: source

---

## Overview

The `functualize.workflow` module provides graph-based workflow execution with multi-step job orchestration, branching logic, and conditional execution paths.

**Module location:** `src/functualize/workflow/`

```python
from functualize.workflow import (
    workflow,
    Step,
    Gate,
    AgentStep,
    Edge,
    ConditionalEdge,
    END,
)
```

---

## `@workflow` Decorator

The `@workflow` decorator transforms a function into a multi-step workflow. The decorated function should return a workflow graph description.

```python
from functualize.workflow import workflow, Step, Edge, END

@workflow(
    steps=[
        Step(step1),
        Step(step2),
    ],
    edges=[
        Edge(source="step1", target="step2"),
        Edge(source="step2", target=END),
    ],
)
def multi_step_job(config, rc):
    """Define a workflow with multiple steps."""
    rc.log("Workflow complete")
```

---

## `Step`

A workflow node that runs a registered job. A step wraps a reference to a job — its registered name or the decorated function itself. It carries no behavior of its own; the job's `@job` declaration (deps, guards, caching) is what runs.

```python
from functualize.workflow import Step

step = Step("validate_data")
step = Step(validate_data)  # callable reference
```

| Attribute | Type | Description |
|---|---|---|
| `job` | `str \| Callable` | The registered job name or decorated function |
| `name` (property) | `str` | Graph key for this node (the referenced job's normalized name) |

!!! note
    `Step` only takes a `job` argument. There are no `action` or `name`
    constructor parameters — the job declaration already describes what runs.

---

## `AgentStep`

A workflow node performed by an **agent**, through a registered executor, rather than by a
registered job. The third node kind, and the first whose execution is not a local function
call: it runs somewhere else, can take arbitrarily long, and can be **refused**.

```python
from functualize.workflow import AgentStep

AgentStep(
    "draft",
    instructions="Draft the release notes from the fetched changelog.",
    tools=["read_file"],
    time_budget_s=120,
)
```

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Graph key for this node — the address it is recorded under, and the name a refusal reports |
| `instructions` | `str` | What the step asks the agent to do. Required, and may not be blank |
| `executor` | `str \| None` | The registered executor that services this step. `None` means *the only registered executor*; with two registered, a step naming none is refused rather than guessed at |
| `tools` | `Sequence[str]` | The tool allowlist. Declaring any tool implies `enforces_tool_allowlist`. An empty sequence declares no constraint, which is not the same statement as "no tools" |
| `requires` | `frozenset[AgentCapability]` | Capabilities needed on top of the implied ones. Widening is explicit; narrowing is not possible |
| `time_budget_s` | `float \| None` | Active-time budget in seconds. Declaring one implies `preserves_active_time_budget` |

!!! note "Refused, never degraded"
    An executor that cannot honour a required capability makes the step refuse **before the
    walk starts**. Running it with the constraint dropped would produce a workflow that
    appears to have restricted tools it left wide open.

See [Workflows → Agent steps](../guides/workflows.md#agent-steps) for executors,
capabilities and a worked graph.

---

## `Edge`

Represents a directed connection between two workflow steps.

```python
from functualize.workflow import Edge, END

# source and target name workflow nodes
edge = Edge(source="start", target="process")
final_edge = Edge(source="process", target=END)
```

| Attribute | Type | Description |
|---|---|---|
| `source` | `str` | Name of the source node |
| `target` | `str \| END` | Name of the target node, or `END` to terminate |

!!! note
    `Edge` takes `source` and `target` as keyword arguments naming nodes,
    not Step objects.

---

## `ConditionalEdge`

Represents a branching connection based on a runtime condition.

```python
from functualize.workflow import ConditionalEdge, END

# Maps condition keys to target nodes
conditional = ConditionalEdge(
    source="check",
    condition=lambda: "success" if all_green() else "failure",
    targets={
        "success": "success_handler",
        "failure": "failure_handler",
    },
)
```

| Attribute | Type | Description |
|---|---|---|
| `source` | `str` | Name of the source node |
| `condition` | `Callable` | Returns a key into `targets` |
| `targets` | `dict[str, str \| END]` | Mapping of condition keys to node names or `END` |

---

## `END`

A sentinel value marking the end of a workflow. Used in workflow graph definitions to indicate the termination point.

```python
from functualize.workflow import workflow, Step, Edge, END

@workflow(
    steps=[Step("work")],
    edges=[Edge(source="work", target=END)],
)
def simple_workflow(config, rc):
    rc.log("Work done")
```

---

## Internal Location

Workflow types live in `functualize._types.workflow`:

- `_types/workflow.py` — Step, Gate, AgentStep, Edge, ConditionalEdge, END, WorkflowShape, WorkflowDeclaration
- `workflow/_decorator.py` — `@workflow` decorator and execution engine
- `workflow/_validation.py` — Graph validation and cycle detection

!!! warning "Internal API"
    Modules under `functualize.workflow._*` are implementation details. Import types from `functualize.workflow` instead.
