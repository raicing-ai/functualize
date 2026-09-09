# Plan — workflow-graph-semantics

---

## 1. The approach in one line

**Key the walk's pruning on node-and-iteration instead of node, make failure a routable edge,
name two more step outcomes, and let the walker emit what a watcher follows.**

## 2. Why this is "Incremental" and not another multi-release feature

The roadmap sizes item 9 as *Incremental*, and that is right — but only because F5 exists
first. Each piece here is small **given** something F5 built:

| Piece | Needs from F5 |
|---|---|
| Loops | iteration identity on the step record |
| Failure routing | nothing — but it must preserve the recorded-branch property |
| `timed_out` | a step budget, which is a lease expiry |
| `watch` | the lease (liveness) and the event log |
| `notify` | the effects outbox |

Attempted before F5, every row becomes a subsystem. That is the argument
`10-graph-semantics.md` makes and this plan assumes.

## 3. The one dangerous edit

`workflow_walker.py:227,237-238`:

```python
visited: set[str] = set()
...
# A diamond join is reached once per branch but must run once.
if name in visited:
    continue
```

This set exists for **diamond joins**. Loops need it keyed by `(node, iteration)`. Getting it
wrong in one direction runs a join twice; in the other, a loop still runs once.

**Both failures are silent.** A join running twice looks like a flaky step; a loop running once
looks like the loop condition was false. So the test for §3.1 is written **before** the change
and asserts both properties in one body.

## 4. Files to change

### New

```
src/functualize/_engine/loop_state.py             iteration identity and bounds
tests/workflow/test_loops.py
tests/workflow/test_failure_routing.py
tests/workflow/test_watch_stream.py
tests/integration/test_notify_exactly_once.py
```

### Modified

```
src/functualize/workflow/__init__.py              Loop, OnFailure, Notify
src/functualize/workflow/_validation.py           cycle validation; unbounded cycle refused
src/functualize/_engine/workflow_walker.py        visited keying; failure routing; emit calls
src/functualize/_engine/frontier.py               TERMINAL_SUCCESS; two new outcomes
src/functualize/_cli/builtins.py                  workflow watch
plugins/functualize-mcp/.../_workflow_tools.py    watch_workflow
src/functualize/_engine/agent_providers.py        the notify provider table joins the shared test
```

## 5. Risks

- **R-a · The `visited` change breaks diamond joins silently.** §3. *Mitigation:* one test body
  asserting both properties — a join runs once per iteration **and** a loop's second pass is
  not pruned — written before the change.

- **R-b · Resume into a loop resumes at the wrong iteration.** Replay-skip currently keys on a
  step record whose key has no iteration in it. *Mitigation:* the iteration is part of the step
  key (F5's record), so replay is unambiguous; a test resumes a walk mid-loop and asserts the
  iteration count continues rather than restarting.

- **R-c · Failure routing re-evaluates a predicate that pages.** *Mitigation:* record the
  chosen route on first evaluation and **read** it on replay — the property
  `workflow_walker.py:412-417` already establishes for `ConditionalEdge`, extended, not
  reinvented. A test asserts the predicate is called exactly once across a resume.

- **R-d · `timed_out` is produced by something that lies.** If a step's budget is implemented
  as preemption, `timed_out` claims the work stopped when it did not — the failure
  `exec_policy.py:7-22` rejected. *Mitigation:* `timed_out` is produced **only** by F5's lease
  expiry, and F5's AC-13 grep test already forbids the mechanisms by name.

- **R-e · `watch` becomes a polling loop wearing a stream's clothes.** *Mitigation:* AC-11 —
  the walker emits; nothing polls the store in a loop to render. Sabotage: remove the emit
  calls and confirm `watch` stops updating rather than falling back to polling.

- **R-f · `notify` grows into a broker.** Retries, routing rules, fan-out, a dead-letter queue.
  *Mitigation:* `to` is **opaque to the engine** and the spec says so; N8 is quoted in the
  contract; the provider table is the extension point and it names packages, nothing more.

- **R-g · Cycle validation refuses graphs that work today.** A graph with a cycle is currently
  accepted and runs once; refusing it is a **breaking change for anyone relying on that**.
  *Mitigation:* it is a change from "silently wrong" to "loudly refused", the message names the
  cycle and the fix (add a `Loop` with a bound), and it goes in the CHANGELOG as breaking.

## 6. Ordering

```
W0  cycle validation: an unbounded cycle is refused    (breaking, alone, first)
W1  Loop + iteration identity + visited keying          ← the dangerous edit
W2  OnFailure routing, with the recorded-route property
W3  timed_out / cancelled outcomes + TERMINAL_SUCCESS
W4  walker emits; watch (CLI + MCP)
W5  Notify, on F5's outbox
W6  checkpoint
```

W0 first and alone: it is the only breaking change, and landing it before loops exist means the
refusal is unambiguous — there is no way to satisfy it except by declaring a bound, which is
exactly the intent.

## 7. What this plan does not do

No bus, no broker, no retry policy engine, no second nesting model, no `pause`, no cross-project
listing. `--wf-retry-failed` stays withdrawn.
