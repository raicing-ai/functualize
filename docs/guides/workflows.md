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
| `Gate(name, awaits=Model, tools=[], strategy=None)` | First-class pause point. Waits for input matching a Pydantic model. `strategy` is one of `"resolve"`, `"prompt"`, `"ai_inbound"`, or `"ai_outbound"`; see [Gate Strategies](ai.md#gate-strategies) for the preset distinction. |
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

When a gate blocks, the walk opens a request with its own `request_id`. That ID
stays stable while the request is open, after an answer is accepted, and when
the resumed walk consumes it. `gate_draft(app, store, scope_id, gate)` includes
a `resolution` field with `request_id`, `request_status`, and `candidates`.
Each candidate reports its ID, ordinal, source, submission time, and recorded
outcome, detail, and errors; the read view does not expose candidate payloads
or re-evaluate their outcomes.

`answer_gate(..., reopen=True)` can correct an accepted answer while the walk
is still parked at that gate. Reopening gives the replacement request a new ID
and preserves the old request under `superseded`. Once the walk has passed the
gate, reopening is refused. A direct `deposit_gate_input(...)` accepts one
answer for an open request; a second deposit returns
`{"error": "gate_already_answered", ...}` and leaves the first answer intact.
Invalid deposits are recorded as invalid candidates and leave the request open.

A gate is addressed by its declared name or by its canonical form —
`approve_refund` and `approve-refund` both reach the one gate — and
`workflow list` prints the canonical form. Naming a gate the workflow does
not have raises `GateNotFoundError` from the Python API; the CLI prints the
error and exits 1, and MCP returns a `gate_not_found` result carrying the
gates that do exist.

### Decision gates

A gate can let a **decision provider** fill one field of its model with
`decide=ChoiceDecision(...)`. The provider proposes one of the options the
workflow declares, reading the recorded result of a step the workflow names;
the workflow's own thresholds decide whether the proposal is taken:

```python
from typing import Literal

from pydantic import BaseModel
from functualize.workflow import (
    END,
    ChoiceDecision,
    ConditionalEdge,
    Edge,
    FromStep,
    Gate,
    Step,
    workflow,
)

class Route(BaseModel):
    route: Literal["billing", "returns", "shipping"]

class Approval(BaseModel):
    approved: bool

@workflow(
    steps=[
        Step(intake),                          # returns the ticket text
        Gate(
            name="route",
            awaits=Route,
            decide=ChoiceDecision(
                field="route",
                instructions="Route the ticket to the team that owns it.",
                options={
                    "billing": "a question about an invoice or a charge",
                    "returns": "the customer wants to send something back",
                    "shipping": "where a parcel is, or when it arrives",
                },
                state=FromStep("intake"),
                accept_at=0.70,                # the proposal's probability
                min_margin=0.10,               # its lead over the runner-up
            ),
        ),
        Step(bill),
        Step(ship),
        Gate(name="approve_refund", awaits=Approval),   # a person, always
        Step(refund, effecting=True),
    ],
    edges=[
        Edge("intake", "route"),
        ConditionalEdge(
            source="route",
            condition=lambda answer: answer["route"],
            targets={
                "billing": "bill",
                "shipping": "ship",
                "returns": "approve_refund",
            },
        ),
        Edge("approve_refund", "refund"),
        Edge("bill", END),
        Edge("ship", END),
        Edge("refund", END),
    ],
)
def support():
    """Route a ticket; refunds need a person."""
```

- **The declaration is checked when it is made.** `field` must be a field of
  `awaits` typed as a `Literal` of strings or a `StrEnum`, and its allowed
  values must be exactly the keys of `options`; `0 < accept_at <= 1` and
  `0 <= min_margin < 1`. A mismatch is a `ValueError` at import, not a gate
  that cannot be answered at run time. `decide` implies
  `strategy="decision"`; any other strategy with it is refused.
- **The provider proposes; the workflow decides.** The proposal is accepted
  only when its probability reaches `accept_at` *and* leads the runner-up by
  at least `min_margin`. The provider's own confidence score is recorded and
  never consulted. The strategy is registered by the `functualize-decision-jev`
  plugin (experimental; it needs `OPENCODE_API_KEY`); without it the gate
  records the rung `unavailable` and blocks.
- **Anything short of acceptance blocks for a person** — unless the decision
  declares a fallback (below). A weak proposal, a
  rate limit or a provider error is a failed rung, never a retry or a wait; the
  gate falls through to `prompt` and `resolve` and blocks with a reason such as
  `decision: jev/jev-1.13-free proposed 'returns' at 0.54 (margin 0.08);
  workflow requires >= 0.70, margin >= 0.10`. Answering the gate
  (`answer_gate`) takes the answered branch; address a gate by its stored,
  canonical name, which is the one `blocked_on` reports (`approve_refund` is
  stored as `approve-refund`). A resumed walk never asks the provider again:
  the accepted or answered value is replayed from the record.
- **The rule is part of the graph.** A walk parked at, or after, a decision gate
  refuses to resume if the module has since changed that gate's thresholds,
  options, instructions or model — the same refusal a moved edge gets.

**The framework does not decide which options need a person — the workflow
does, by routing those branches through a second gate.** Above, an accepted
`returns` still stops at `approve_refund` before the effecting `refund` step,
while an accepted `billing` or `shipping` proceeds with nobody involved. An
option routed straight to an effecting step is executed on the model's answer
alone.

The ticket text reaches the provider as data (the request's `state`), never as
part of its instructions, and an answer outside the declared options is
refused rather than followed — so text in a ticket cannot open a branch the
workflow did not declare.

#### Fallback and the decision record

A decision can name the option the gate takes when no proposal is accepted:

```python
from functualize.workflow import ChoiceDecision, FromStep

ROUTER = ChoiceDecision(
    field="route",
    instructions="Choose how this request should be handled.",
    options={
        "deterministic": "a fixed rule or lookup answers it; no model needed",
        "cheap_model": "a short, low-risk text task a small model can do",
        "frontier_agent": "multi-step reasoning or tool use is required",
        "human_review": "risky, ambiguous, or needs a person's judgement",
    },
    state=FromStep("intake"),
    accept_at=0.70,
    min_margin=0.10,
    fallback="human_review",
)
```

- **The fallback is declared on the decision, never as a field default.**
  `ChoiceDecision(fallback=...)` must be one of the options, and it must
  complete the answer by itself: every other field of `awaits` needs a
  default. A default on the decided field is refused at import — it would
  bypass the decision, because a fully defaulted answer completes the gate
  before any strategy, the provider included, is asked.
- **A gate with a fallback never blocks at the router.** Its ladder is
  `decision` → `resolve` rather than `decision` → `prompt` → `resolve`: when
  the decision rung fails for any reason — a weak proposal, a rate limit, no
  provider installed — the existing `resolve` rung takes the fallback and the
  walk follows that branch. If the fallback means "a person looks at it",
  route its branch through a second `Gate`, as the reference workflow routes
  `human_review` to a `review` gate. The fallback is part of the rule, so it
  joins the graph digest.
- **The decision rung records its evidence beside its verdict.** Whenever the
  provider was asked, the rung's candidate carries one flat, JSON-safe mapping
  — `schema`, `field`, `state` (the step, and the SHA-256 and length of the
  text, never the text), `rule` (its digest, `accept_at`, `min_margin` and the
  fallback), `provider`, `model`, `requested_model`, `proposal`,
  `distribution`, `confidence` (recorded, never read by the rule),
  `probability`, `margin`, `verdict`, `failure`, `latency_seconds`,
  `input_tokens` and `output_tokens` — and `gate_draft(...)` shows it as the
  candidate's `evidence`. Only the gate writes it: an `evidence` key inside a
  submitted answer never becomes a candidate's evidence. A rung whose
  provider is not installed is `unavailable` and records none.

`decision_record(store, scope_id, gate)` (from `functualize.app.utils`,
**provisional**) reads one routed gate back as a single record — who took it,
on which route, and why the decision did not:

```python
from functualize.app.utils import ScopeStore, decision_record

record = decision_record(ScopeStore(app.substrate), scope_id, "route")
# {"gate": "route", "request_id": "...", "route": "human_review",
#  "decided_by": "fallback", "fallback_used": True,
#  "reason": "decision: ... proposed 'deterministic' at 0.55 ...",
#  "evidence": {"schema": "decision-evidence/1", ...}}
```

`decided_by` is `"decision"`, `"fallback"`, `"person"`, or `None` while the
gate is open; `reason` is the decision rung's own detail when the fallback
took over. The record is a projection of what was recorded at the time —
nothing is re-evaluated.

Two runs on the same input can route differently: the provider is
probabilistic. The records make that visible; they do not prevent it.

The worked example is
[`examples/standalone/hermetic_router/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/hermetic_router/):
one gate, four routes, a `human_review` fallback, and tests that run it with a
fake provider and with none.

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

### Where a paused workflow actually lives

A gate pauses a run and waits for a person. Everything the resumed run needs —
which steps completed, which branch the walk took, where it stopped, and the
values the person deposited — is in a **scope record**, and that record has to
still be there when somebody comes back.

By default it is a file: `.functualize/scopes.json` in your project, with each
run's job state beside it in `.functualize/scope-state/`. That is the right
default and it is fine on a laptop or a long-lived build server.

**It is not fine anywhere the filesystem does not outlive the process**, and
that is most places you would deploy this:

| Where | What happens with the default |
|---|---|
| AWS Lambda, Cloud Run, Cloud Functions | the container is gone; the paused run is gone with it |
| A container that is rebuilt or rescheduled | same, unless `.functualize/` is a mounted volume |
| More than one worker behind a load balancer | the gate is answered on the worker that happens to receive the request, which is usually not the one holding the record |
| CI, per-job runners | every run starts from nothing, so a gate can be reached but never answered |

The symptom is specific and easy to misread: the run blocks at exit code 5 and
prints a `--wf-resume <id>` instruction, and that command then reports **"No
workflow scope"** — because the process being asked never had the record.

### Configuring a durable store

Install a substrate plugin. The store that ships is SQLite:

```bash
pip install functualize-substrate-sqlite
```

With it installed, every runtime document — scope records, job state, the
freshness ledger, the run log — goes to one database instead of one directory.
Point it wherever your processes can all reach:

```toml
# .functualize.toml
[plugin.substrate-sqlite]
db_path = "/mnt/shared/functualize/state.db"
```

`func builtin data show` reports where each one actually is, which is the
command to run when a resume cannot find its scope.

**It moves all of them, or none.** There is no way to keep scope records in the
database and their job state on disk: a resumed run would come back with its
steps intact and its variables empty, which is the failure this arrangement
exists to prevent.

### Writing your own

A substrate is six methods — `read`, `write`, `lock`, `clear`, `delete`,
`describe` — over documents named by string keys. Implement
`functualize._types.protocols.StoreSubstrate` and offer it from a plugin's
registration call; boot asks for it while selecting the store, after
configuration has resolved:

```python
def __call__(self, app):
    app.offer_substrate(lambda app: MySubstrate(...))
```

A call, not an assignment: a storage claim made after boot has selected the
store is **refused** rather than half-applied, and a property setter has nowhere
to say so. `app.substrate` reads the storage *in effect*.

Two things a backend without a shared filesystem must get right:

- **`lock(*keys)` may be a no-op.** If your backend cannot offer mutual
  exclusion, say so by doing nothing, and rely on the next point.
- **`write(key, payload, expect=revision)` returns `False`** when the stored
  revision has moved. That is a compare-and-swap, and it is what a backend uses
  instead of a lock. A caller that gets `False` must re-read and retry.

See `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md` for
why this is a document port rather than a key-value protocol.

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
