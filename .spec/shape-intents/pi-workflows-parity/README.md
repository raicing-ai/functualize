# Shape Intent: pi-workflows Parity — Durable Runs, Agent Continuation, and Coordination

**Status: specified, not yet implemented**
**Date: 2026-09-08**
**Scope: the workflow feature end to end — the walk (`_engine/workflow_walker.py`,
`frontier.py`, `workflow_runner.py`), scope persistence
(`_primitives/state_store.py`, `state_format.py`), the gate answer path
(`app/_workflow_resume.py`), every delivery surface that addresses a run
(`_cli/builtins.py`, `_cli/dispatch.py`, `app/adapters/click_params.py`,
`plugins/functualize-mcp/`), and the task domain (`plugins/functualize-tasks*`).**

Benchmarked against `github.com/osolmaz/pi-workflows` @ `2b3cf35`. Every claim was
re-derived from source at `78d9ff4`. One claim — silent scope erasure — is proven by a run
experiment, transcript in
[evidence/scrutiny-report-2026-09-08.md](evidence/scrutiny-report-2026-09-08.md).

**Supersedes** the earlier study at `~/code/raicing-ai/functualize-vs-pi-workflows/`,
whose load-bearing claims are falsified in [02](02-prior-study-corrections.md). Do not
implement from it — in particular its `handoff-wf-status-decision.md` names a
`_scope_id_option()` call site that does not exist
([Appendix A §E-1](appendix-a-handoff-critique.md)).

---

## Verdict

The prior study's thesis holds: functualize has no durable run layer, no way for a calling
agent to advance a blocked walk, and no agent step primitive. But it mis-drew the map in
three ways that change the build order.

**The agent surface is richer than it claimed** — `get_workflow_state` already publishes
the whole graph with every step's return value — while **the human CLI surface is poorer**,
emitting five fields over the same store. **The agent's execution door is broken in a way
it did not notice**: all four MCP run-doors discard `JobResult.metadata`, so an agent that
blocks a workflow never learns the scope id. And **both of its "functualize is ahead"
durability claims are false**.

Meanwhile the most serious defect in the workflow feature is not a missing capability at
all: a `STATE_VERSION` bump — an ordinary release action — silently erases every in-flight
run, and so does `func builtin state clear`, whose help text names only "fingerprints,
history".

## The five finding classes

- **Data loss** — `scopes` share an envelope whose discard rule was written for
  `fingerprints`.
- **Broken doors** — the agent's execution path drops the metadata that makes it usable.
- **Missing renderers, not missing data** — the CLI under-reads a store that already has
  the answers, and the richest projection ships only in an optional adapter.
- **Unenforced promises** — `cancel_workflow`, `state clear` and three MCP doc sites all
  describe contracts the code does not keep.
- **The port, not the node** — pi-workflows' agent step is a Protocol with declared
  capabilities. Copy that shape, not a node kind.

## Documents

Read in order; each assumes the one before it.

| # | File | Contents |
|---|---|---|
| — | [CHANGELOG.md](CHANGELOG.md) | **Iteration history and closed arguments.** Read §3 before re-opening any decision. |
| 01 | [01-current-state.md](01-current-state.md) | What exists today: the control / observability / management inventory across CLI, job flags and MCP, and the defects in it |
| 02 | [02-prior-study-corrections.md](02-prior-study-corrections.md) | Every falsified or drifted claim from the prior study, with evidence |
| 03 | [03-pi-workflows.md](03-pi-workflows.md) | The benchmark, independently modelled: the executor port, source identity, effects, settings CAS, park semantics |
| 04 | [04-mcp.md](04-mcp.md) | Can an agent run any job? Is the adapter naive? Context-bloat analysis with numbers |
| 05 | [05-target-surface.md](05-target-surface.md) | **The target design.** Three tiers, the verb vocabulary, derived run state, the parity contract |
| 06 | [06-lifecycles.md](06-lifecycles.md) | Nine walkthroughs — what using it feels like, per actor |
| 07 | [07-gate-answers.md](07-gate-answers.md) | Partial, whole and corrected gate answers: the draft slot |
| 08 | [08-coordination.md](08-coordination.md) | Notes as a scope-scoped blackboard, and how tasks relate |
| 09 | [09-nesting.md](09-nesting.md) | Child-scope addressing, its five defects, and the bound on depth |
| 10 | [10-task-storage.md](10-task-storage.md) | Where tasks live, and the fan-out/reduce multi-sink design |
| 11 | [11-boundaries.md](11-boundaries.md) | Core / plugin placement for every proposal, and the four fallback patterns |
| 12 | [12-scope-id.md](12-scope-id.md) | Removing `--scope-id`: per-mode empirical coverage and the removal steps |
| 13 | [13-roadmap.md](13-roadmap.md) | Priority order and implementation waves |
| 14 | [14-decisions.md](14-decisions.md) | **The decision register** — every accepted decision, non-goal, and open question |
| A | [appendix-a-handoff-critique.md](appendix-a-handoff-critique.md) | Assessment of the in-flight `--wf-status` handoff: four factual errors, six design blockers |
| — | [evidence/verified.md](evidence/verified.md) | file:line index, re-derived |
| — | [evidence/scrutiny-report-2026-09-08.md](evidence/scrutiny-report-2026-09-08.md) | The full audit with experiment transcripts |

## The design in one page

Three tiers, by actor — **`builtin workflow` is the rich superset, MCP matches it verb for
verb, and `--wf-*` on the job is a convenience subset** for the invoker, whose one unique
piece of knowledge is which workflow it is.

One vocabulary: **`answer` records, `resume` advances.** Two verbs, distinct contracts, no
aliases. `--scope-id` goes, both spellings, replaced by `--wf-resume [id]` — which can
omit the id, can fuse gate input, and errors on an unknown id instead of silently minting
a phantom run.

Full matrix in [05](05-target-surface.md). Build order in [13](13-roadmap.md): four small
defect fixes and the projection lift come before the durable run layer, and together close
more of the practical agent gap than it does.

## Status

Specification only — **no source changes**. One question is open: **O5**, `--wf-run-id`
for idempotent start ([05 §2.2](05-target-surface.md)). Everything else is settled; see
[CHANGELOG §3](CHANGELOG.md) for what not to re-litigate.
