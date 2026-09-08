# 10 · Workflows as a coordination substrate, and child-scope addressing

Three questions: can a workflow carry **messages** between agents · can it carry **tasks** ·
how do we address **children of children**. Prior art surveyed, then a design grounded in
what the code actually permits.

---

## 1. Prior art — what everyone else built

| System | The primitive | What transfers |
|---|---|---|
| **Temporal** | **Signals** (async write, fire-and-forget), **Queries** (sync read, cannot block), **Updates** (sync write, *validated*, returns a result) | The **triad is the right decomposition.** functualize has one verb (deposit) doing the job of Update, and nothing at all for Signal or Query. |
| **A2A** (Linux Foundation, v1.0) | **Task** (unit of work, id + status over many rounds), **Message** (role + typed Parts), **Artifact** (finished deliverable) | Three *distinct* objects in a mature protocol. Do not collapse messages, tasks and results into one log. |
| **LangGraph** | Typed state channels with **per-key reducers**; `interrupt()` + `Command(resume=…)` on the same `thread_id` | Reducers are the answer to concurrent writers: declare the merge (append vs. overwrite) per key. Also: one re-invocation path serves both crash-recovery and approval-resume — which is already functualize's `--scope-id` model. |
| **Airflow XCom** | key + value + timestamp, `xcom_push` / `xcom_pull`, explicitly *"small amounts of data"* | The closest DAG-engine analogue, and its documented size caveat is the constraint §3 has to respect. |
| **Blackboard architecture** (classic AI, revived for LLM agents) | Agents never address each other; they read and write a shared structured workspace | **This is the honest name for what you are describing.** Indirect coordination through accumulated partial results, not a bus. |
| **Agent inbox / AMQ, file-based agent queues** | Per-agent inboxes, routing, read receipts, expiry | The four primitives such systems converge on — identity, permission, expiry, routing — are the checklist for §3.4. |
| **pi-workflows** | `includeWorkflow` — *"Composition keeps one run, trace, pause state, cancellation state, and final presentation"* | See §5: it **avoids the child-addressing problem entirely** by not having child runs. |

**The distinction that matters:** a *blackboard* is scope-scoped and read by whoever
happens to be working. A *bus* routes addressed messages between named agents with
delivery guarantees. The first is a small feature on top of state functualize already
has. The second is a different product (AMQ, A2A) and functualize should not become it.

---

## 2. What the code permits — the constraints any design must respect

Verified before designing:

1. **Append-under-lock already works and is already used.** `update_state` re-reads
   *inside* `state_lock` (`state_format.py:296-310`), so two processes appending to a
   list merge rather than clobber. `tool_calls` on the scope record does exactly this —
   *"calls recorded, never memoized."* A message log is architecturally proven.
2. **But every write rewrites the whole file.** `save_state` serializes the entire
   envelope on every mutation. An unbounded append-only log makes every *unrelated*
   state write more expensive, forever. The existing precedent is a ring buffer:
   `HISTORY_LIMIT = 200` (`state_format.py:53`).
3. **The envelope is destroyed by a version bump and by `state clear`**
   ([07 item 0](07-roadmap.md)). Messages would evaporate exactly as scopes do. **Item 0
   is a hard prerequisite** — a coordination log that silently empties is worse than none.
4. **No timestamps exist on scope records** (`_blank_scope`, `state_store.py:45-56`).
   Messages must carry their own.
5. **`::` is already overloaded** — step keys are `"<job>::<args_hash>"`
   (`frontier.py:245-247`) *and* child scopes are `"<scope>::<step>"`
   (`executor.py:1208`). See §5.2.

---

## 3. Design — `note`, a scope-scoped blackboard

### 3.1 The primitive

One append-only list on the scope record, beside `tool_calls`:

```python
"notes": [
  {
    "id": "n-0007",
    "at": "2026-09-08T14:03:11Z",
    "actor": {"kind": "agent", "name": "claude-code", "session": "…"},
    "node": "deploy",              # optional — which node this is about
    "kind": "note",                # note | finding | question | answer | handoff
    "to": null,                    # optional addressee, advisory only
    "in_reply_to": null,           # optional thread link
    "body": "Registry auth rotated; deploy step needs the new secret before retry."
  }
]
```

**Call it `note`, not `message`.** "Message" imports delivery semantics — queues,
acknowledgement, routing — that this does not have and should not grow. A note is
*written on the scope*, and whoever picks the scope up reads it. That is the blackboard
contract, stated in the name.

### 3.2 The verbs

| Surface | Spelling |
|---|---|
| CLI record layer | `func builtin workflow note <id> --add "…" [--node N] [--kind K] [--to A]`<br>`func builtin workflow note <id> [--since ID] [--node N] [--format json]` |
| MCP | `add_workflow_note(workflow_id, body, node?, kind?, to?, in_reply_to?)`<br>`read_workflow_notes(workflow_id, since?, node?, limit?)` |
| Job flag | `--wf-note "…"` — write a note as part of an invocation |
| Projection | notes included in `get_workflow_state` / `show`, newest-last, capped |

`--since <note-id>` is what makes this usable for an interleaved agent: *"what happened
on this scope since I last looked"* is one call, not a diff of the whole scope.

### 3.3 The rules that keep it a blackboard

- **Append-only.** No edit, no delete. Corrections are new notes with `in_reply_to`.
  (Contrast the gate `draft`, which *is* editable — see [04](04-gate-deposit.md) — because
  a draft is an unanswered question and a note is a recorded observation.)
- **Bounded.** Ring-buffer per scope, `NOTES_LIMIT` in the shape of `HISTORY_LIMIT`, plus
  a body-length cap. Constraint §2.2 is not optional.
- **Advisory addressing.** `to` is a hint, never a filter or a permission. There are no
  inboxes, no delivery, no read receipts. An agent that wants those wants AMQ.
- **Never read by the engine.** The walker must not branch on notes. That is the
  *explicit over hidden* line, and it is the same line pi-workflows draws when its graph
  engine refuses to import the resource-manager runtime.
- **Not secret-bearing.** Same rule the provenance design already pins: no config values,
  no gate payloads copied in.

### 3.4 Checked against the four primitives agent-messaging systems converge on

| Primitive | Answer |
|---|---|
| **Identity** | `actor` — same capture the provenance design specifies (MCP `clientInfo.name`, `FUNCTUALIZE_ACTOR`, tty ⇒ human). Blocked on that work. |
| **Permission** | Whoever can open the project can read and write. Notes are *not* a security boundary — say so in the docs, the way pi-workflows says `allowedTools` is *"an exact tool allowlist, not a filesystem sandbox."* |
| **Expiry** | The ring buffer, plus `purge` ([09 §2.1](09-target-matrix-and-lifecycles.md)). |
| **Routing** | Deliberately absent. The scope *is* the address. |

### 3.5 What this buys, concretely

Agent A exhausts its context mid-run and stops. Agent B picks up the scope:

```
read_workflow_notes("a3f9c2…")
  → n-0004  agent:claude-code  node=build   "artifact pinned to 1.2.3-rc4, not rc3"
    n-0005  agent:claude-code  node=deploy  "registry auth rotated — needs new secret"
    n-0006  human              node=approve "approved on the condition rc4 is used"
get_workflow_state("a3f9c2…")
  → graph + every step's return value + resolved inputs + pending gates
run_job("release-pipeline", scope_id="a3f9c2…")
```

The scope already carried the *facts* (step results, branch choices, gate answers). What
it could not carry was the *reasoning* — why rc4, what the human meant by "approved". That
gap is what notes close, and it is genuinely the thing that makes interleaved agent work
survive a context reset.

---

## 4. Tasks — address them, do not couple them

[05](05-tasks-and-workflows.md) established that `functualize-tasks` and workflows share
exactly one unvalidated string (`TaskLink.kind == "workflow_step"`) and no code path.

**Do not merge tasks into the note log, and do not reimplement notes inside tasks.** A2A
keeps Message, Task and Artifact as three objects for a reason, and the shapes genuinely
differ:

| | Notes | Tasks | Step records |
|---|---|---|---|
| Mutability | append-only | mutable status | write-once per node |
| Owner | any actor | the task domain | the walker |
| Read by engine | never | never | always |
| Lifetime | ring-buffered | until deleted | the scope's |

The cheap, correct integration is **co-addressing**, not coupling:

1. **Give the link a real address.** `TaskLink(kind="workflow_scope", target="a3f9c2…/deploy")`
   — the same path form §5 settles on — with a helper that builds it and validation that
   `kind` is one of the declared values (it is bare `str` today).
2. **Filter on it.** `tasks.list(linked_to=…)` and MCP `list_tasks(linked_to=…)`.
   Provider work only.
3. **Let step jobs write tasks.** A step that wants a task trail injects `Tasks`. The
   walker stays ignorant.
4. **Surface the count, not the contents,** in the scope projection: `"tasks": {"open": 3,
   "done": 7, "link": "a3f9c2…"}`. One number tells a reader to go look; copying the task
   list into the scope record duplicates a store.

If tasks are *not* going to be addressed this way, then **delete `"workflow_step"` from
the three docstrings and the MCP tool help** — today it advertises an integration that
does not exist.

---

## 5. Child workflows — addressing, and the fork nobody wrote down

### 5.1 The two available models

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

### 5.2 The five defects

**D-A · The separator is overloaded.** `::` means *step key* (`"<job>::<args_hash>"`,
`frontier.py:245-247`) **and** *scope descent* (`executor.py:1208`). `_job_of` does
`split("::", 1)[0]` on step keys; a grandchild scope id needs `rsplit`. Two namespaces,
one token, no parser can tell them apart from the string alone.
**Fix:** child scopes use `/`. `a3f9c2…/deploy/verify`. Matches pi-workflows' mountPath,
frees `::` for step keys, and is pre-release-safe.

**D-B · A parent blocked on a child's gate is unnameable.** The `StepBlocked` path sets
position and status and **never calls `_block`** (`workflow_walker.py:319-337`), so the
parent's `gates` stays `{}`. Result: `status: blocked`, `pending_gates: []` — *identical*
to the "answered, awaiting re-entry" state ([09 §1 D-1](09-target-matrix-and-lifecycles.md)).
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

### 5.3 "Ad infinitum" is already bounded — twice, weakly

- Boot rejects `@workflow` nesting **cycles** (`workflow_validation.py:184-197`,
  `WorkflowDeclarationError`), so depth is bounded by the declaration graph.
- `max_invoke_depth = 10` exists (`executor.py:184`) but the workflow-step path passes
  `invoke_depth` through **unchanged** (`:843`), so it does not bound nesting.

That is fine for statically declared graphs and thin for `register_dynamic_job`. **Add a
`max_workflow_depth` guard** (mirroring pi-workflows' `assertInvocationStepLimit`, which
bounds each included workflow's steps rather than trusting the shape), and refuse with the
path so the message names the offender.

### 5.4 The addressing rule, stated once

```
<scope-id>                       a top-level run
<scope-id>/<step>                a nested workflow at that step
<scope-id>/<step>/<step>         …recursively, no depth special-casing
<scope-id>[/<step>…]#<node>      a node within a scope  (notes, task links, gate refs)
```

Deterministic and derived, so **re-entry finds the same child** — which is the whole
reason the id is not fresh (`executor.py:1200-1207` explains it). Every verb in
[09](09-target-matrix-and-lifecycles.md) takes this path wherever it takes a scope id;
`--descendants` on read verbs and a close policy on `cancel` are the only additions.

---

## 6. Recommendation, and what not to build

**Build, in this order:**

1. **Nothing until [07 item 0](07-roadmap.md).** Notes and tasks both live in the envelope
   that a version bump silently empties.
2. **D-C then D-B** (child scope through the report; `blocked_on_child` on the parent).
   Two small fixes that make nested gated workflows addressable at all — today the
   blocked-on-child state is genuinely unaddressable over MCP.
3. **D-A and D-E** (`/` separator, `parent`/`mount`, `list --tree`, hide children by
   default). Fold into the projection lift ([07 item 3](07-roadmap.md)) — same code, same
   release.
4. **`note`** — after item 0, sized as a ring buffer, no routing. Its `actor` field is
   blocked on provenance; ship `actor: unknown` rather than guessing.
5. **Task co-addressing** — docs and a provider filter. Not a roadmap item.
6. **D-D parent close policy** — with the Tier-2 runner, when cancel can actually stop a
   live walk.

**Do not build:**

- **A message bus.** No inboxes, no routing, no delivery guarantees, no read receipts.
  That is A2A/AMQ, and the moment `to` becomes load-bearing you own a broker.
- **Engine reads of notes.** The walker must never branch on a note. Explicit over hidden.
- **Notes as a result channel.** Step return values, `FromJob` and the gate `payload` are
  the data path and already work. Notes carry *reasoning*, not *values* — the moment they
  carry values you have two sources of truth and the memoized one wins.
- **A second nesting model.** Do not add pi-workflows-style inlining alongside child
  scopes. One composition model; fix its five defects.

## Sources

- [Temporal — Workflow message passing (Signals, Queries, Updates)](https://docs.temporal.io/encyclopedia/workflow-message-passing)
- [Temporal — Child Workflows](https://docs.temporal.io/child-workflows) · [Parent Close Policy](https://docs.temporal.io/parent-close-policy)
- [A2A Protocol architecture & specification](https://tyk.io/learning-center/a2a-protocol-architecture-and-technical-specification/) · [A2A v1 2026 overview](https://pub.towardsai.net/a2a-protocol-v1-2026-how-ai-agents-actually-talk-to-each-other-c500079bca73)
- [LangGraph — Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) · [Human-in-the-loop interrupts and state](https://medium.com/data-science-collective/architecting-human-in-the-loop-agents-interrupts-persistence-and-state-management-in-langgraph-fa36c9663d6f)
- [Airflow — passing data between tasks (XCom)](https://www.astronomer.io/docs/learn/airflow-passing-data-between-tasks)
- [Blackboard architecture for multi-agent AI](https://medium.com/@edoardo.schepis/patterns-for-democratic-multi-agent-ai-blackboard-architecture-part-1-69fed2b958b4) · [Multi-agent context sharing patterns](https://fast.io/resources/multi-agent-context-sharing-patterns/)
- [Inter-agent communication patterns (2026)](https://www.taskade.com/blog/inter-agent-communication-patterns) · [agent-message-queue (file-based)](https://github.com/avivsinai/agent-message-queue)
- pi-workflows `docs/WORKFLOW_COMPOSITION.md` @ `2b3cf35`
