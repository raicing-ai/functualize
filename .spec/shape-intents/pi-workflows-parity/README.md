# Shape Intent: pi-workflows Parity — Durable Runs, Agent Continuation, and Coordination

**Status: specified, not yet implemented**
**Date: 2026-09-08**
**Scope: the workflow feature end to end — the walk (`_engine/workflow_walker.py`,
`frontier.py`, `workflow_runner.py`), scope persistence
(`_primitives/state_store.py`, `state_format.py`), the gate deposit path
(`app/_workflow_resume.py`), every delivery surface that addresses a run
(`_cli/builtins.py`, `_cli/dispatch.py`, `app/adapters/click_params.py`,
`plugins/functualize-mcp/`), and the task domain (`plugins/functualize-tasks*`).**

Benchmarked against `github.com/osolmaz/pi-workflows` @ `2b3cf35`. Every claim was
re-derived from source at `78d9ff4`; where a prior study and the code disagreed, the
code won and the disagreement is recorded in [02-corrections.md](02-corrections.md).
One claim (silent scope erasure) is proven by a run experiment, transcript in
[evidence/scrutiny-report-2026-09-08.md](evidence/scrutiny-report-2026-09-08.md).

**Supersedes** the earlier study at `~/code/raicing-ai/functualize-vs-pi-workflows/`,
whose load-bearing claims are falsified in 02. Do not implement from it — in particular
its `handoff-wf-status-decision.md` names a `_scope_id_option()` call site that does not
exist ([08-handoff-critique.md](08-handoff-critique.md) §E-1).

**Decisions of record: [13-decisions.md](13-decisions.md)** — 33 accepted, 11 non-goals,
all four open questions resolved.

---

## Verdict in one paragraph

The previous study's thesis survives: functualize has no durable run layer, no way for
a calling agent to advance a blocked walk, and no agent step primitive. But it
mis-drew the map in three ways that change the build order. **The agent surface is
richer than it claimed** — `get_workflow_state` already publishes the whole graph with
every step's return value — while **the human CLI surface is poorer**, emitting five
fields over the same store. **The agent's execution door is broken in a way it did not
notice**: all three MCP run-doors discard `JobResult.metadata`, so an agent that blocks
a workflow never learns the scope id. And **both of its "functualize is ahead"
durability claims are false**. Meanwhile the most serious defect in the workflow
feature is not a missing capability at all: a `STATE_VERSION` bump — an ordinary
release action — silently erases every in-flight run, and so does
`func builtin state clear`, whose help text names only "fingerprints, history".

## What changed from the previous study

| The previous study said | Actually |
|---|---|
| Agent gets `{status, workflow_scope, blocked_on, blocked_reason}` on block | Gets `{status: "Blocked", return_value: null, duration_ms}`. Metadata dropped at all three doors. |
| "Nothing renders a workflow's graph anywhere" | MCP publishes graph, edges, position, branches, per-step return values + resolved inputs, gate schemas |
| functualize memoizes steps by `(job, args_hash)` | `_key()` hardcodes `args_hash=""`. Node name only. |
| pi-workflows re-runs nodes on replay | It does not. Same resume semantics as functualize. |
| pi-workflows source identity = path + SHA-256 | Three-part: root source (file hash **or** builtin id+revision) + all included child sources + canonical structural digest |
| A failed step is sticky; needs `--wf-retry-failed` | Failed steps re-run on resume automatically. Only the **epilogue** is sticky. |
| pi-workflows agent steps only work inside Pi | The agent step is a **port** with capability flags; a headless non-conversation executor already ships |
| `cancel` marks the scope so it leaves `list` | It does — and the MCP tool's description promises "Cancelled scopes are not resumable", which nothing enforces |
| 8 built-ins · 10 tool actions · 13,403 Rust LOC | 7 built-ins (+3 composition-only) · 13 tool actions · 13,552 |

## Documents

| File | Answers |
|---|---|
| [01-surface-inventory.md](01-surface-inventory.md) | **What control / observability / management verbs exist today**, across CLI builtin, job flags, and MCP — and what each one actually does |
| [02-corrections.md](02-corrections.md) | Every falsified or drifted claim from the previous study, with evidence |
| [03-mcp-assessment.md](03-mcp-assessment.md) | Can an agent run any job over MCP? Is the implementation naive? Context-bloat analysis with numbers |
| [04-gate-deposit.md](04-gate-deposit.md) | Design for `builtin workflow deposit` — partial, whole, and edit-existing gate input |
| [05-tasks-and-workflows.md](05-tasks-and-workflows.md) | What `functualize-tasks` is, and its (non-)relationship to workflows |
| [06-pi-workflows-model.md](06-pi-workflows-model.md) | Independent model of pi-workflows: the executor port, source identity, effects, settings CAS, park semantics |
| [07-roadmap.md](07-roadmap.md) | Revised priority order — four small fixes that beat the previous W1 |
| [08-handoff-critique.md](08-handoff-critique.md) | Assessment of `handoff-wf-status-decision.md` — 4 factual errors, 6 design blockers, amended instructions |
| [09-target-matrix-and-lifecycles.md](09-target-matrix-and-lifecycles.md) | **The target command / flag / MCP matrix**, the derived status model, and eight annotated lifecycles |
| [10-coordination-and-nesting.md](10-coordination-and-nesting.md) | Workflows as a coordination substrate — notes/messages, tasks, and child-scope addressing; prior-art survey (Temporal, A2A, LangGraph, XCom, blackboard) |
| [11-core-plugin-boundaries.md](11-core-plugin-boundaries.md) | Layer + packaging placement for every proposal, the two state systems, and the four fallback patterns |
| [12-task-sinks.md](12-task-sinks.md) | Where `tasks-local` actually stores data, and the fan-out/reduce multi-sink idea — architectures, formats, traps |
| [14-resume-deposit-collisions.md](14-resume-deposit-collisions.md) | Every current and future `resume`/`deposit` collision site, and why the fix is to rename the *flag* rather than the verb |
| [13-decisions.md](13-decisions.md) | **Decision register** — 32 accepted decisions, 11 explicit non-goals, 4 open questions, implementation waves |
| [evidence/verified.md](evidence/verified.md) | file:line index, re-derived |

## The one-line summary of each finding class

- **Data loss** — `scopes` share an envelope whose discard rule was written for `fingerprints`.
- **Broken doors** — the agent's execution path drops the metadata that makes it usable.
- **Missing renderers, not missing data** — the CLI under-reads a store that already has the answers.
- **Unenforced promises** — `cancel_workflow` and `state clear` both document contracts the code does not keep.
- **The port, not the node** — pi-workflows' agent step is a Protocol with declared capabilities. Copy that shape, not a node kind.
- **Observability is behind an optional adapter** — the framework's richest workflow projection ships only in `functualize-mcp`, which the repo's own ADR-016 principle forbids.
- **Nested gates are unaddressable** — a parent blocked on a child's gate records no gate at all, and the child's scope id is dropped from the report that names the block.
- **Nothing names "answered, awaiting re-entry"** — no deposit path writes scope status, so an answered scope reads as `blocked` with no pending gates. A derived `ready` state fixes it for free.
- **Scope state has no clock** — no `started_at`, no scope-level `blocked_at`; the gate-level `blocked_at` resets on every resume attempt. Any survey UI with a time column is currently unbackable.
