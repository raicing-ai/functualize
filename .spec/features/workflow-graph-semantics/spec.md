# Feature — workflow-graph-semantics

Implements **F7** of `contributor/architecture/run-model/13-roadmap.md` — pi-workflows roadmap
**item 9**, sized by that roadmap as *"Incremental"*.

**Depends on:** `durable-run-layer` (F5) **and `agent-step-port` (F6)** — F7 edits four
files F6 owns (`_engine/workflow_walker.py`, `_engine/agent_providers.py`,
`workflow/__init__.py`, `workflow/_validation.py`), and `agent_providers.py` does not
exist until F6 T2 creates it. The roadmap order (`F5 ∥ F6 → F7`) already sequences them;
this line records *why*, so F7 is never read as independent of F6. **Blocks:** nothing — this is the last feature in the
set.

---

## 1. The problem

Four capabilities the roadmap groups together, and one reason they are grouped: **every one of
them needs something F5 builds.**

### 1.1 Failure routing is binary, and the walk ends

`_engine/workflow_walker.py:336-337` — one `except`, one exit:

```python
except Exception as exc:  # a step failure stops the walk
    return self._fail(name, f"{type(exc).__name__}: {exc}")
```

A raising step marks the scope `failed` and the walk is over. There is no per-step handler, no
compensating branch, no route-on-failure edge. A declaration cannot express *"if fetch fails,
run notify-and-stop; otherwise continue"*.

### 1.2 Conditions see success only

`_choice_for` (`workflow_walker.py:410-425`) is called with the step's **return value**:

```python
for edge in self._declaration.outgoing(name):
    if isinstance(edge, ConditionalEdge):
        return edge.condition(value)
```

A step that raised never reaches this line — §1.1 returned already. **Conditional routing and
failure are disjoint by construction:** you can branch on what a step said, never on how it
ended.

> One property to preserve: a branch already recorded for a scope is **read**, and the
> condition is not called at all — *"Calling it and discarding the answer would still run
> whatever side effects it has, and would still pay for a condition that shells out or hits the
> network."* Any failure-routing design must keep that, because a failure condition is exactly
> the kind that logs, pages, or posts.

### 1.3 Loops cannot execute, and the blocker is a fix for something else

`workflow_walker.py:227,237-238` — verified: `visited` appears **3** times in the file:

```python
visited: set[str] = set()
...
# A diamond join is reached once per branch but must run once.
if name in visited:
    continue
```

The `visited` set exists to make a **diamond join** run once when two branches converge. Its
side effect is that **no node can run twice in one invocation**, which is exactly what a loop
needs.

Resume compounds it: replay skips records whose outcome is `"success"` (`:314-317`), so a
completed node stays completed across invocations too.

And in-graph cycles are **legal to declare**. `_engine/workflow_validation.py:184-185` guards
workflow-to-workflow nesting cycles only — *"ordinary jobs terminate a chain and are already
cycle-checked as deps"*. **Nothing validates cycles in the step graph.** A job author can
declare a loop, get no error, and watch it execute once.

> **This is the most important finding in the feature.** Loop support is not a switch. It
> requires distinguishing *"this node already ran on this path"* (the join case, which must
> stay) from *"this node ran on a previous iteration"* (the loop case, which must not prune) —
> an **iteration identity on the step record**, which is a durable-run concern. It is the
> sharpest reason item 9 depends on item 8, and it is stronger than the roadmap's own
> justification.

### 1.4 Step outcomes are two strings

Persisted outcomes are exactly `"success"` and `"failed"` (`frontier.py`, verified: 2 hits).
`TIMEOUT` and `CANCELLED` exist as *run*, *parallel* and *scope* statuses — never as a step's
own outcome.

`RunStatus` (`_types/enums.py:15-32`) is `SUCCESS · FAILURE · BLOCKED · SKIPPED · RUNNING ·
CANCELLED · TIMEOUT · UNKNOWN · REFUSED`, with `.resumable` and `.ran` — and **no `.ok`**;
that is on `WalkReport` (`workflow_walker.py:138-141`).

### 1.5 There is no watch, and the code says why

Observation is **pull-based**: a caller polls `app/_workflow_view.py`. The walker emits
**zero** events — verified: `rg -c 'emit\(' src/functualize/_engine/workflow_walker.py` → `0`
— even though per-step records, branch choices and gate payloads are all persisted
synchronously as it goes.

And the projection's own docstring names the blocker (`_workflow_view.py:93-97`):

> *"Not derived here: whether a resumed walk is running right now. `FrontierWalk.start` sets
> `RUNNING` only on first entry, so a resumed walk reports `blocked` for its whole duration…
> live-versus-parked needs a lease."*

A resumed walk is indistinguishable from a parked one for its entire duration. That is not a
rendering problem — **there is no fact in the store that says a runner holds this scope right
now**, and inventing one is F5's lease.

---

## 2. User stories

- **US-1** As a workflow author, I declare what happens when a step fails, instead of the whole
  walk stopping.
- **US-2** As a workflow author, I express "retry this until it succeeds, up to N times" in the
  graph rather than inside a step.
- **US-3** As an operator, I watch a running workflow's graph advance, live.
- **US-4** As an operator, a step that ran out of its budget reports `timed_out`, distinctly
  from one that failed.
- **US-5** As a workflow author, I am told at declaration time that my loop is a loop — not
  after watching it run once.

---

## 3. Behaviour

### 3.1 Loops execute, and the join still runs once

The `visited` set becomes keyed by **node and iteration**, not node alone. A diamond join still
runs once per iteration; a loop's second pass is a new iteration and is not pruned.

Iteration identity lives on the step record (F5), which is why this cannot be done first.

**A declared cycle is validated**: a graph with a cycle and no bound is refused at declaration
with a message naming the cycle. Today it is accepted and silently runs once — the worst of
both.

### 3.2 Failure becomes routable

A step may declare where control goes when it raises. Absent a declaration, **today's behaviour
is unchanged**: the walk stops and the scope is `failed`.

> The recorded-branch property (§1.2) is preserved: a failure route already chosen for a scope
> is **read** on replay, never re-evaluated. A failure condition is exactly the kind that pages.

### 3.3 Typed step outcomes

Step outcomes gain `timed_out` and `cancelled`, copying pi-workflows' vocabulary rather than
inventing a third (decision **L3**). `timed_out` is producible only because F5 gives a step a
budget — as a **lease expiry**, not preemption.

Replay-skip keys on the **set of terminal-success outcomes**, not the literal string
`"success"`, so a new outcome does not silently become replayable.

### 3.4 `watch`

`func builtin workflow watch <id>` renders a live graph. It works because F5 gives the store a
liveness fact (the lease) and an event stream to follow — the two things §1.5 says are missing.

Streaming reuses the existing `Live` / surface-routing seam; **the walker gains emit calls, not
a second observation channel.**

### 3.5 `notify`

A workflow may declare a notification on a state transition. It is an **effect**, so it rides
F5's outbox and fires **at most once** across a crash.

> Not a message bus, not a broker — **N8**. A notification is an effect with a declared target,
> and the moment `to` becomes load-bearing routing, that is A2A/AMQ.

### 3.6 `--wf-retry-epilogue` stays; `--wf-retry-failed` stays withdrawn

Decision **L4**, inherited. The epilogue is genuinely sticky; a general retry-failed is largely
redundant once failure is routable.

### 3.7 What must not change

- A diamond join runs **once per iteration**.
- Resume replays completed work rather than re-running it.
- A recorded branch is read, never re-evaluated.
- `_execute_lifecycle`'s 20-step order.
- A workflow with no new declarations behaves exactly as it does today.

---

## 4. Acceptance criteria

**Loops**

- **AC-1** A cyclic graph with a declared bound executes its cycle more than once.
- **AC-2** A diamond join still runs exactly once **per iteration**.
- **AC-3** A cyclic graph with **no** bound is refused at declaration, naming the cycle.
  *(Today it is accepted and runs once.)*
- **AC-4** Resume into a loop resumes at the correct iteration, not the first.

**Failure routing**

- **AC-5** A step may declare a failure route; control follows it and the walk continues.
- **AC-6** Without a declaration, a raising step stops the walk and marks the scope `failed` —
  **unchanged**.
- **AC-7** A failure route already recorded for a scope is **read** on replay; its condition is
  not re-evaluated.

**Typed outcomes**

- **AC-8** Step outcomes include `timed_out` and `cancelled`, distinctly from `failed`.
- **AC-9** Replay-skip keys on the terminal-success set, not the literal `"success"`.

**Watch**

- **AC-10** `func builtin workflow watch <id>` shows the graph advancing live, including
  through a resume. *(pi-workflows parity test 5.)*
- **AC-11** The walker emits step-level events; nothing polls the store in a loop to render.
- **AC-12** `watch` on a scope with no live lease reports it parked, not running.

**Notify**

- **AC-13** A declared notification fires **exactly once** across a `kill -9`.
- **AC-14** No message bus, no broker, no routing table — a target, and an effect.

---

## 5. Out of scope

- A message bus, engine reads of notes, or notes as a result channel — **N1**, **N2**, **N3**
  of the pi-workflows register.
- `--wf-retry-failed` — **L4**.
- A second nesting model — **N4**.
- Cross-project listing, `pause`, or a second viewer — **N10**.

## 6. Prior art

- **pi-workflows** — the typed outcome vocabulary this copies rather than reinvents.
- **`workflow_walker.py:412-417`** — the recorded-branch property, and the reason for it.
- **`app/_workflow_view.py:93-97`** — the codebase naming the watch blocker before it was
  specified.
- **`pitfalls.md` §7** — *only the epilogue is sticky*, which is why **L4** stands.
