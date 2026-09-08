# 03 · pi-workflows, independently modelled

Read from source, not from the previous study. Focused on the parts functualize should
copy, and the parts it should not.

---

## 1. The agent step is a port with declared capabilities — copy this

`src/workflows/types.ts:900-911`:

```ts
export interface AgentStepExecutor {
  readonly assistantMessageMode?: "visible" | "park" | "unsupported";
  readonly preservesActiveTimeBudget?: boolean;
  readonly enforcesToolAllowlist?: boolean;
  runAgentStep(request: AgentStepRequest, signal: AbortSignal): Promise<AgentStepSubmission>;
}
```

The engine does not know Pi exists. It knows one port and three capability flags, and it
**fails closed** rather than degrading (`engine.ts:1299-1320`):

- `assistantMessage` node under `assistantMessageMode === "park"` → persist
  `agent_session_required`, park the run, wait for an origin session.
- under anything else non-`"visible"` → throw *"Assistant completion requires an origin
  Pi session"*.
- `allowedTools` declared with `enforcesToolAllowlist !== true` → throw *"This executor
  cannot enforce the agent tool allowlist; use an origin Pi session"*.
- `preservesActiveTimeBudget !== true` → the node timeout is not persisted across
  resume (`engine.ts:980-992`).

**Two implementations ship:**

| Implementation | Flags | Where the model runs |
|---|---|---|
| origin-session executor (`server/workflow-runner-entry.ts:197-199`) | all three true | the live Pi conversation |
| `RpcStepExecutor` (`server/rpc-executor.ts`) | `assistantMessageMode: "park"\|"unsupported"` | a headless `pi --mode rpc` child, one per run — **no conversation** |

And the **validation-retry loop lives in the executor, not the engine**
(`rpc-executor.ts:80-97`): the engine hands over an `accept(output)` callback; on
rejection the executor re-prompts with the error text and loops.

### Why this is the correction to the previous roadmap's W2

The study proposed inventing an `AgentStep` node kind plus a bespoke MCP submit loop,
and hedged: *"Cross-agent tool restriction outside functualize's own tools is impossible
via MCP alone; document the boundary honestly."*

pi-workflows does not document the boundary — it **types** it, and behaves differently on
each side of it. That is the design to port:

| pi-workflows | functualize equivalent already present |
|---|---|
| `AgentStepExecutor` Protocol | ports-as-Protocol, per `.spec/CONSTITUTION.md` |
| executor injected into the engine | `GateStrategy` / `PromptCollector` / Surface split |
| capability flags → fail closed | `STRATEGY_PROVIDERS` naming the missing package in `blocked_reason` — the same honesty, one rung lower |
| `enforcesToolAllowlist` | `GateToolPolicy` + bound-arg-stripped schemas — **stronger**, since overreach is inexpressible rather than refused |

The implementations functualize would write: MCP-elicitation executor, CLI-prompt
executor, `functualize-ai` executor. Each declares what it can enforce. The engine
refuses a workflow that needs more.

## 2. Source identity is three checks and has an upgrade path

`workflowIdentityMismatch` (`engine.ts:1774-1783`):

1. **Root source**, deep-equal — two kinds:
   `{kind:"file", path, hash}` or `{kind:"builtin", id, revision}`. Built-ins are
   identified by a **declared revision string**, never by content hash;
   `BuiltinWorkflowCatalog.resolve` throws `BuiltinWorkflowRevisionChangedError` on
   mismatch (`catalog.ts:95-113`).
2. **Every included child workflow's source** — `state.workflowSources` vs
   `compositionMetadata(workflow).sources`. Editing a child invalidates the parent.
3. **`definitionDigest`** — sha256 over a canonical JSON snapshot of the *compiled*
   definition (`store.ts:5036-5062`): name, contractId, startAt, structural node
   snapshots, edges, composition, settings scopes. **Callback bodies are not in it** —
   file hashing is what catches those.

And there is a **designed migration**: `legacySources` (`catalog.ts:12-17`, used at
`builtins/catalog.ts:22-42`) maps old `(name, path suffix, content hash)` triples to a
known revision, so runs started under a previous shipped build still resume. This is the
one shim pi-workflows keeps despite an alpha policy of hard cuts — because hard-cutting
here destroys users' in-flight runs.

**For functualize:** hash the *graph*, not the *file*. A Python module holds many
unrelated jobs, so file hashing would invalidate every in-flight run whenever any
neighbouring job is edited. The projection already exists — `workflow_shape_of` /
`shape.to_dict()`, used by `_topology` (`_workflow_tools.py:511-536`). Canonicalize
that. And ship the revision/legacy story with it, not after.

## 3. Effects are required, not encouraged

`schema.ts:120-131` — an action node without a managed effect fails **definition
validation**: *"node ${nodeId} requires a managed effect"*, `recovery` must be
`idempotent` or `manual`, and a `request` must be present. Not a convention; a schema
rule.

The idempotency key is *"the run ID, effect type, full compiled node path, and node visit
number"* (`SQLITE_STATE.md:109`) — note **visit number**, which is what makes effects
work inside loops. An uncertain result becomes `ambiguous` and *"is not repeated without
evidence"*.

## 4. Live settings are optimistic concurrency inside the node dispatcher

Not a side feature. A settings-route node whose scope changes mid-attempt raises
`StaleResourceError`; the engine calls `restoreRunState` to the pre-attempt snapshot,
re-captures the binding, emits `settings_route_retried`, and retries — bounded by
`MAX_SETTINGS_ROUTE_RETRIES` (`engine.ts:627-670`). The step counter is decremented so
the retry does not consume budget.

## 5. Park/resume is finer-grained than "the last durable boundary"

- On park the engine **does not record the in-flight attempt**: *"the projection keeps
  the node as in-flight, and resume reruns it with a fresh attempt"* (`:592-596`).
- A park landing during the `node_started` persist **prevents dispatch entirely**
  (`:965-970`) — *"its discarded side effects would rerun on resume."*
- **Exception:** checkpoint nodes and assistant-message agent nodes keep their **exact
  attempt id** across resume (`:353-373`), *"so durable origin-session work is never
  detached from its contract"* — along with `timeoutMs`/`elapsedMs`, which is how the
  timeout counts active model-turn time only.
- `resumePointFor` handles the crash **between** node-finish and run-finish: a null
  resume point with a recorded terminal result finalizes the run rather than re-walking
  (`:400-410`).

## 6. Failure outcomes are typed for routing

`outcomeForError` (`:916-925`) yields `timed_out` / `cancelled` / `failed`. These are the
values `$result.outcome` switches on (`graph.ts:99-107`), and `resolveNextForOutcome`
only honours `$result.` switches — so a fix-loop can distinguish a timeout from a crash.
If functualize adds failure routing, copy the vocabulary; routing on a boolean throws
away the distinction that makes fix-loops useful.

Related: switch prefixes are validated at definition time *"to prevent the source node
from executing its side effects before a routing error"* (`schema.ts:255-259`). Routing
errors are made unreachable after a side effect, by construction.

## 7. Two costs of pi-workflows' design worth knowing before copying

- **A reserved-word tax.** `RESERVED_WORKFLOW_NAMES` (`schema.ts:271-282`) rejects any
  workflow named `answer`, `cancel`, `change-settings`, `list`, `pause`,
  `queue-follow-up`, `remove-follow-up`, `resume`, `status` — *"the keyword wins the
  argument slot"*. The previous study criticised functualize's separate
  `func builtin workflow` namespace without noting that the single-namespace
  alternative permanently constrains user workflow names.
- **No fan-out at all.** `validateWorkflowEdge` (`graph.ts:66-68`) rejects a second
  outgoing edge outright. Branching and loops are fully supported via switch edges with
  N cases; **concurrency and joins are not.** functualize's `_ready` join deferral
  (`workflow_walker.py:378-396`) is a real capability pi-workflows does not have, and
  after the corrections in [02](02-prior-study-corrections.md) it is the only unambiguous one left.

## 8. Scale, for calibration

| | pi-workflows | functualize |
|---|---|---|
| Engine `src/` | 56,105 TS | 84,062 Py (whole framework) |
| Workflow-specific | `src/workflows/` 18,191 — `store.ts` 5,145, `queue.ts` 2,086, `engine.ts` 1,940 | ~1,072 (walker 483, frontier 247, runner 144, validation 198) |
| Viewer | 13,552 Rust + TS viewer | flow-viz (job tree) |
| Built-ins | 7 registered + 3 composition children | 0 |
| Skills | 6 | 4 (none operate workflows) |
| Docs | ~20 files; `WORKFLOWS.md` 965 lines | ~9 pages |

`store.ts` alone is five times the entire functualize workflow engine. That ratio is the
honest answer to "how much of this is portable": the *shapes* in §§1–6 are, the
implementation is not, and W1 is a multi-release investment where §1 is a single release.
