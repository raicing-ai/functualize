# 09 · Child workflows — addressing and lifecycle

How nested scopes are named, the five defects in that naming today, and the bound on depth.

---

## 1. The two available models

### 1.1 The choice each project made

**pi-workflows chose inlining.** `WORKFLOW_COMPOSITION.md`:

> *Composition keeps one run, trace, pause state, cancellation state, and final
> presentation. Controllers remain the correct tool for independent or indefinitely
> reconciled child runs.*

Included workflows are mounted at node paths (`parent/child/node`) inside **one** run.
There is no child run to address, no second pause state, no cascade question. Independent
child runs are a *different subsystem* (resource-manager controllers).

**functualize chose child scopes.** `Step(wf)` derives `f"{parent}::{step}"`
(`executor.py:1200-1212`), recursively — a grandchild is `parent::step::substep`. Each is
a real scope with its own step records, gate slots and epilogue.

Neither is wrong. functualize's buys something real: a nested workflow is independently
resumable, independently inspectable, and `workflow = job` stays true with **zero**
composition machinery — pi-workflows needed `includeWorkflow`, typed exits, `contractId`,
mount paths and `assertInvocationStepLimit` to get less. **Keep the model.** But it has
five unpaid costs.

## 2. The five defects

**D-A · The separator is overloaded.** `::` means *step key* (`"<job>::<args_hash>"`,
`frontier.py:245-247`) **and** *scope descent* (`executor.py:1208`). `_job_of` does
`split("::", 1)[0]` on step keys; a grandchild scope id needs `rsplit`. Two namespaces,
one token, no parser can tell them apart from the string alone.
**Fix:** child scopes use `/`. `a3f9c2…/deploy/verify`. Matches pi-workflows' mountPath,
frees `::` for step keys, and is pre-release-safe.

**D-B · A parent blocked on a child's gate is unnameable.** The `StepBlocked` path sets
position and status and **never calls `_block`** (`workflow_walker.py:319-337`), so the
parent's `gates` stays `{}`. Result: `status: blocked`, `pending_gates: []` — *identical*
to the "answered, awaiting re-entry" state ([01 §C.6](01-current-state.md)).
And `resume_workflow(parent_id, …)` answers with the self-contradiction
*"no gate awaiting input (status: blocked)"*.
**Fix:** record `blocked_on_child: {"scope": "a3f9c2…/deploy", "gate": "approval"}` on the
parent. Derived state becomes `waiting:child`, and the message points at the child.

**D-C · `WalkReport` throws away the child scope.** `StepBlocked` carries it
(`workflow_walker.py:57-69`) and the walker uses only `blocked.blocked_on`. So
`metadata.workflow_scope` names the **parent** while `blocked_on` names a gate that lives
in the **child** — a caller cannot address what it was told about.
**Fix:** one field through the report. Trivial, and it is what makes D-B's message
possible.

**D-D · No parent close policy.** Cancelling a parent leaves children live; cancelling a
child leaves the parent blocked forever. Temporal names exactly this and offers three
options — **Abandon**, **Request Cancel**, **Terminate** (its default).
**Fix:** adopt the vocabulary. Default `terminate` for `cancel`, declarable per step:
`Step(child_wf, on_parent_cancel="abandon")`. A cascade is a store walk over the id
prefix, which the path form makes a one-liner.

**D-E · Listings are flat.** `scope_ids()` returns every key sorted
(`state_store.py:307-309`); nothing groups, links or filters. `a3f9c2…` and
`a3f9c2…/deploy` are peer rows with no indication one contains the other.
**Fix:** record `parent` and `mount` on the child at creation, then `list --tree`,
`show --descendants`, and a default that **hides children** unless `--all` — a run should
appear once.

## 3. Depth is already bounded — twice, weakly

- Boot rejects `@workflow` nesting **cycles** (`workflow_validation.py:184-197`,
  `WorkflowDeclarationError`), so depth is bounded by the declaration graph.
- `max_invoke_depth = 10` exists (`executor.py:184`) but the workflow-step path passes
  `invoke_depth` through **unchanged** (`:843`), so it does not bound nesting.

That is fine for statically declared graphs and thin for `register_dynamic_job`. **Add a
`max_workflow_depth` guard** (mirroring pi-workflows' `assertInvocationStepLimit`, which
bounds each included workflow's steps rather than trusting the shape), and refuse with the
path so the message names the offender.

## 4. The addressing rule

```
<scope-id>                       a top-level run
<scope-id>/<step>                a nested workflow at that step
<scope-id>/<step>/<step>         …recursively, no depth special-casing
<scope-id>[/<step>…]#<node>      a node within a scope  (notes, task links, gate refs)
```

Deterministic and derived, so **re-entry finds the same child** — which is the whole
reason the id is not fresh (`executor.py:1200-1207` explains it). Every verb in
[05](05-target-surface.md) takes this path wherever it takes a scope id;
`--descendants` on read verbs and a close policy on `cancel` are the only additions.

---


## 5. Build order

1. **D-C then D-B** — carry the child scope through `WalkReport`, then record
   `blocked_on_child` on the parent. Two small fixes that make nested gated workflows
   addressable at all; today the blocked-on-child state is unaddressable over MCP.
2. **D-A and D-E** — the `/` separator, `parent`/`mount`, `list --tree`, and hiding
   children by default. Fold into the projection lift ([13 item 3](13-roadmap.md)) —
   same code, same release.
3. **D-D parent close policy** — with the tier-2 runner, when cancel can actually stop
   a live walk.

## Sources

- [Temporal — Workflow message passing (Signals, Queries, Updates)](https://docs.temporal.io/encyclopedia/workflow-message-passing)
- [Temporal — Child Workflows](https://docs.temporal.io/child-workflows) · [Parent Close Policy](https://docs.temporal.io/parent-close-policy)
- [A2A Protocol architecture & specification](https://tyk.io/learning-center/a2a-protocol-architecture-and-technical-specification/) · [A2A v1 2026 overview](https://pub.towardsai.net/a2a-protocol-v1-2026-how-ai-agents-actually-talk-to-each-other-c500079bca73)
- [LangGraph — Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) · [Human-in-the-loop interrupts and state](https://medium.com/data-science-collective/architecting-human-in-the-loop-agents-interrupts-persistence-and-state-management-in-langgraph-fa36c9663d6f)
- [Airflow — passing data between tasks (XCom)](https://www.astronomer.io/docs/learn/airflow-passing-data-between-tasks)
- [Blackboard architecture for multi-agent AI](https://medium.com/@edoardo.schepis/patterns-for-democratic-multi-agent-ai-blackboard-architecture-part-1-69fed2b958b4) · [Multi-agent context sharing patterns](https://fast.io/resources/multi-agent-context-sharing-patterns/)
- [Inter-agent communication patterns (2026)](https://www.taskade.com/blog/inter-agent-communication-patterns) · [agent-message-queue (file-based)](https://github.com/avivsinai/agent-message-queue)
- pi-workflows `docs/WORKFLOW_COMPOSITION.md` @ `2b3cf35`
