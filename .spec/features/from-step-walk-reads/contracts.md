# contracts.md — from-step-walk-reads

External interfaces only. No public symbol is added or removed: `FromStep` is
already exported from `functualize.workflow` and listed in
`tests/test_public_api_surface.py`. What changes is what the existing surface
*does*, and the errors it raises.

## 1. `FromStep` — unchanged constructor, widened meaning

```python
from functualize.workflow import FromStep

FromStep(step: str | Callable[..., Any], /)   # unchanged
FromStep("x").name -> str                     # canonical node name, unchanged
```

Accepted positions (spec B1), all with one meaning — *this walk's recorded
value for node `x`*:

```python
# 1. gate tool binding (works today; unchanged meaning)
Gate(name="review", awaits=Decision,
     tools=[Tool(read_file, allowed=FromStep("setup-vfs"))])

# 2. a step job's parameter (new)
@job
def act(ok: Annotated[Approval, FromStep("approve")]) -> Result: ...

# 3. the epilogue's parameter (new)
@workflow(steps=[Step(plan), Gate(name="approve", awaits=Approval), Step(act)],
          edges=[...])
def flow(ok: Annotated[Approval, FromStep("approve")]) -> Result: ...
```

- `x` may name a `Step`, an `AgentStep`, or a `Gate`.
- In positions 2 and 3 the value is rebuilt into the `Annotated` base type
  (`Approval`), the same rebuild `FromJob` performs.
- An argument passed explicitly by the caller is never overwritten.

## 2. Boot-time refusal — `WorkflowDeclarationError`

Raised from workflow-declaration validation at application boot (the same
phase that today raises
`Workflow 'gwf' has a Step referencing unknown job 'approve'.`), before any
scope is opened. One error per offending reference. The message contains, in
words:

- the literal `FromStep(<name>)`;
- the reader: `Step '<step>'`, `the epilogue of workflow '<wf>'`, or
  `Gate '<gate>' tool '<tool>'`;
- the parameter or tool-argument name;
- the workflow name;
- the reason, one of: *not a node of this graph* · *not ordered before the
  reader* · *names the gate whose tools are being bound* · *parameter also
  carries FromJob*;
- the fix, in the style of the existing `FromJob` messages
  (`src/functualize/_engine/workflow_validation.py:74-87`): add an edge, or
  correct the name.

Example (normative wording is the plan's; this is the shape):

```
WorkflowDeclarationError: Step 'act' of workflow 'gwf' reads FromStep('aprove')
(parameter 'ok'), which is not a node of this graph. Nodes: act, approve, plan.
```

## 3. Run-time failure — the reader is not called

When a reference that passed boot validation cannot be satisfied in one walk
(spec B5), the reader (step job, epilogue, or tool) is not invoked. The run
result is a failure (`RunStatus.FAILURE`; for a walk, the step record of the
reader is `failed`, and the walk can be resumed like any other failed step).
The failure message contains the literal `FromStep(<name>)`, the reader, the
parameter, the scope id (when there is one), and the reason:

- *did not run in this walk* (branch not taken) **and the parameter declares no default** — with a default the reader is called with it (spec D2);
- *recorded value could not be carried and is not held by this process*;
- *not running inside a workflow walk* (job executed directly) — the message
  says to pass the argument explicitly or run the job as a step.

It never reads `missing 1 required positional argument`.

The exception class is a Plan decision; it is internal (`functualize._types.errors`
is not a public module) and surfaces to users as the run's error text.

## 4. Tool-binding resolution on both tool surfaces

The in-core gate-tool path (`app/_workflow_control.py`) and the MCP adapter
(`functualize-mcp`, `_workflow_tools.py`) produce **identical** results for the
same scope and binding: the node's recorded value, or the §3 failure — because
the MCP `_call_gate_tool` already delegates to core `call_gate_tool`, which
calls core `_bound_values`. The plugin's own `_bound_values` has no caller and
is deleted in task 5.3. `PluginHost` gains no member; in particular it does
not expose `execution_engine` or `materialize_job`. The core helper keeps its
existing declaration lookup and `({}, None)` no-match result. Both surfaces
retain the same `tool_unresolvable` envelope when declaration loading or
binding resolution raises, including `error` and `message`; the successful
bound-value result remains identical as well. The
`None`-for-not-run result pinned at
`tests/integration/test_part_i_remaining_cells.py:285-286` and
`tests/plugins/test_gate_tool_narrowing.py:661-669` is replaced by §3
(spec D2: a binding has no default, so a skipped node always fails).

## 5. Unchanged surfaces (pinned by AC12)

- `FromJob(job, /, *, run=True)` — constructor, semantics, dependency edges,
  fingerprint reads, and its boot validation messages.
- `from_job_refs`, `from_job_names`, `from_job_types`,
  `declared_dependency_names` — their **return values** for any function stay
  `FromJob`-only (a `FromStep` parameter never becomes a dependency name).
- `ChoiceDecision(state=FromStep(...))` — resolver and messages.
- `func builtin workflow resume <scope> [--input JSON] [--gate NAME]` and the
  `--wf-input` / `--wf-resume` job flags — no new options.
