# 10 · Graph semantics — loops, failure routing, typed outcomes, watch

Roadmap item **9**. It depends on [08](08-durable-runs.md) and is the last feature in the
set. Everything here is stated against what the walker does today, read at `e57f0c9`.

---

## A. Failure routing is binary, and the walk ends

`_engine/workflow_walker.py:336-337`:

```python
except Exception as exc:  # a step failure stops the walk
    return self._fail(name, f"{type(exc).__name__}: {exc}")
```

One `except`, one exit. A raising step marks the scope `failed` and the walk is over. There
is no per-step handler, no compensating branch, no route-on-failure edge. A declaration
cannot express *"if fetch fails, run notify-and-stop; otherwise continue"* — the graph has
one failure edge and it is implicit and terminal.

## B. `ConditionalEdge` dispatches on success only

`_choice_for` (`:410-425`) is called with the step's **return value**:

```python
for edge in self._declaration.outgoing(name):
    if isinstance(edge, ConditionalEdge):
        return edge.condition(value)
```

`value` is what the step returned. A step that raised never reaches this line — §A returned
already. So conditional routing and failure are disjoint by construction: **you can branch on
what a step said, never on how it ended.**

> Worth preserving from that method: a branch already recorded for a scope is *read*, and
> the condition is **not called at all** — *"Calling it and discarding the answer would still
> run whatever side effects it has, and would still pay for a condition that shells out or
> hits the network."* Any failure-routing design must keep that property, because a failure
> condition is exactly the kind that logs, pages, or posts.

## C. Loops cannot execute — and the reason is a fix for something else

`workflow_walker.py:227,237-238`:

```python
visited: set[str] = set()
...
# A diamond join is reached once per branch but must run once.
if name in visited:
    continue
```

The `visited` set exists to make a **diamond join** run once when two branches converge on
it. Its side effect is that **no node can ever run twice in one invocation**, which is
precisely what a loop needs.

Resume compounds it: replay skips over records whose outcome is `"success"` (`:314-317`), so
a completed node stays completed across invocations too.

And in-graph cycles are **legal to declare**. `_engine/workflow_validation.py:187-213`
validates workflow *nesting* cycles; nothing validates cycles in the step graph itself. So a
job author can declare a loop, get no error, and watch it execute once.

**This is the most important finding in the document.** Loop support is not a missing
feature bolted onto a neutral design — it requires distinguishing *"this node already ran on
this path"* (the join case, which must stay) from *"this node ran on a previous iteration"*
(the loop case, which must not prune). That is an iteration identity on the step record,
which is a **durable-run-layer** concern. It is the sharpest single reason item 9 depends on
item 8, and it is stronger than the roadmap's own justification.

## D. Step outcomes are two strings

Persisted step outcomes are exactly `"success"` and `"failed"`. `TIMEOUT` and `CANCELLED`
exist only as *run*, *parallel* and *scope* statuses — never as a step's own outcome.

`RunStatus` (`_types/enums.py`) carries **`.resumable`** (`:35`) and **`.ran`** (`:47`).
It has **no `.ok`** — that lives on `WalkReport` (`workflow_walker.py:138-141`). Any design
that assumes `RunStatus.ok` is designing against a method that does not exist.

Decision **L3**: copy pi-workflows' typed vocabulary (`timed_out` / `cancelled` / `failed`)
rather than invent a third. There is a partial hook already — `StepOutcome` exists as a
carrier for a step's value and inputs (`workflow_walker.py:338-340`), so the outcome type has
somewhere to go.

## E. There is no watch, and the code says why

Observation today is **pull-based**: a caller polls the projection in
`src/functualize/app/_workflow_view.py`. The walker emits **no events at all** except
`ON_SCOPE_CREATED`, even though per-step records, branch choices and gate payloads are all
persisted synchronously as it goes.

And the projection's own docstring records the gap that blocks a live view
(`_workflow_view.py:93-96`):

> *"Not derived here: whether a resumed walk is running right now. `FrontierWalk.start` sets
> `RUNNING` only on first entry, so a resumed walk reports `blocked` for its whole duration.
> This function reports what [the store holds]."*

A resumed walk is indistinguishable from a parked one for its entire duration. That is not a
rendering problem — **there is no fact in the store that says "a runner holds this scope
right now"**, and inventing one is exactly a lease with an owner and an expiry ([08](08-durable-runs.md), decision **K2**).

So `watch` is not a TUI feature waiting to be written. It is blocked on the same lease that
fences concurrent `resume`, and the two ship together or neither does.

## F. What item 9 becomes

| Piece | Needs | Because |
|---|---|---|
| **Loops** | iteration identity on the step record | §C — `visited` must distinguish path from iteration |
| **Failure routing** | a step outcome richer than raise/return | §A, §B — routing on failure means the walker must survive one |
| **Typed outcomes** (`timed_out`/`cancelled`/`failed`) | per-step timeouts | §D — `timed_out` is not producible today because nothing times a step |
| **`watch`** | the lease, and walker events | §E — liveness is not derivable from the store |
| **`notify`** | the effects outbox | an at-most-once side effect on a state transition |
| **`--wf-retry-epilogue`** | nothing new | already needed and already scoped (decision **L4**); `--wf-retry-failed` stays withdrawn as largely redundant |

Every row depends on F5. That is why F7 is last, and why it is *"Incremental"* in the
roadmap's own sizing: once the record, the lease, the timeout and the outbox exist, each row
is a small addition rather than a subsystem.

## G. The parity tests this feature finally satisfies

Two of the pi-workflow roadmap's six parity tests are still unmet and land here:

- **Test 2** — `kill -9` the runner mid-workflow; a new runner resumes from the last
  committed node; an effect step re-runs exactly once. *(Needs F5's outbox and lease; F7's
  typed outcomes make the report legible.)*
- **Test 5** — `func builtin workflow watch` shows the live graph while the above runs.
  *(§E.)*

Test 4 — a gate marked *protected* cannot be answered by an agent even though the agent
answered the previous checkpoint — is **F6**'s, not F7's: it is a capability-flag refusal
([09 §D](09-agent-step-port.md)).
