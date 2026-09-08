# 08 · Coordination — notes, and tasks

Can a workflow carry **messages** between agents, and can it carry **tasks**? Prior art
surveyed, then a design grounded in what the code permits. Child-scope addressing is
[09](09-nesting.md).

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
   ([13 item 0](13-roadmap.md)). Messages would evaporate exactly as scopes do. **Item 0
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
  (Contrast the gate `draft`, which *is* editable — see [07](07-gate-answers.md) — because
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
| **Expiry** | The ring buffer, plus `purge` ([05](05-target-surface.md)). |
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

[08 §4](08-coordination.md) established that `functualize-tasks` and workflows share
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

## 5. Recommendation, and what not to build

**Build, in this order:**

1. **Nothing until [13 item 0](13-roadmap.md).** Notes and tasks both live in the envelope
   that a version bump silently empties.
2. **D-C then D-B** (child scope through the report; `blocked_on_child` on the parent).
   Two small fixes that make nested gated workflows addressable at all — today the
   blocked-on-child state is genuinely unaddressable over MCP.
3. **D-A and D-E** (`/` separator, `parent`/`mount`, `list --tree`, hide children by
   default). Fold into the projection lift ([13 item 3](13-roadmap.md)) — same code, same
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
