# 02 — Functualize already has a durable-execution engine

> This is the finding that reorganises the whole evaluation. Read it before `03` and
> `04`, or Restate and DBOS will look like free additions rather than replacements.

## 1. The claim

Restate and DBOS are **durable-execution engines**. Their value proposition is:

> Write ordinary code. We journal every step. When the process dies, we replay the
> journal, skip the steps that already ran, and continue from where you were.

Functualize implements exactly that model, today, in `src/functualize/_engine/`. It is
not a partial version or an aspiration. It is a shipped, documented, tested replay
engine with the same five mechanisms every durable-execution system has.

Here is the doc-comment at the top of the walker, verbatim:

```text
**Resume is replay, not jump-to-position** (§D.7, "replay + memoization"). Every
invocation re-enters at the graph entry; a step already recorded in this scope
is skipped and its recorded return value reused, a branch already chosen is
read rather than re-evaluated, and a gate whose input was deposited passes
through. Nothing suspends and nothing continues — which is why a blocked walk
survives a process exit for free.
```
— `src/functualize/_engine/workflow_walker.py:9-15`

If you have read Restate's or DBOS's documentation, that paragraph should look
familiar. It is the same sentence, about our code.

## 2. The five mechanisms, side by side

Every durable-execution system needs these five. Here is who provides each.

| # | Mechanism | Functualize | Restate | DBOS |
|---|---|---|---|---|
| 1 | **A journal of completed steps** | `ScopeStore.record_step()` / `get_step()` | the invocation journal | `dbos.operation_outputs` |
| 2 | **Memoised replay** — a recorded step is skipped, its result reused | `frontier.py:454`, `workflow_walker.py:759,806` | SDK checks journal before each `ctx.run` | checkpoint lookup before each `@DBOS.step` |
| 3 | **Determinism control** — a branch decided once, read thereafter | `ScopeStore.record_branch()` / `get_branch()` | journal-mismatch detection (RT0016) | "workflow must invoke the same steps in the same order" |
| 4 | **Durable promises** — block on an external event, survive the process | `Gate`: `put_gate` / `deposit_gate_payload` / `reopen_gate` | awakeables, durable promises | `DBOS.send()` / `recv()` |
| 5 | **A code-version fence** — refuse to replay a journal against changed code | `graph_digest()` + `WorkflowGraphChangedError` | immutable deployments; in-flight invocations pinned to their version | `application_version` stamp; recovery only resumes matching versions |

Five for five. There is no row where we have nothing.

## 3. Where each one lives, with line numbers

### 3.1 The journal — step records

`ScopeStore` is the journal. It has 47 public methods
(`src/functualize/_primitives/scope_store.py`), and these are the journal ones:

| Method | Line | Role |
|---|---|---|
| `record_step(scope_id, step_key, record)` | `:369` | append a completed step |
| `get_step(scope_id, step_key)` | `:447` | is this step already done? |
| `record_branch(scope_id, source, target)` | `:564` | pin a conditional choice |
| `get_branch(scope_id, source)` | `:577` | read the pinned choice on replay |
| `put_gate` / `get_gate` | `:585` / `:594` | a durable promise |
| `deposit_gate_payload` | `:602` | resolve the promise from outside |
| `set_position` / `get_position` | `:844` / `:852` | where the walk parked |
| `append_event` / `events_for` | `:387` / `:425` | the observable event log |
| `record_epilogue` / `get_epilogue` | `:860` / `:869` | the once-only tail |
| `claim_scope` / `renew_scope` / `release_scope` | `:715` / `:753` / `:790` | the lease |
| `check_scope_generation` | `:819` | the fence |

A step key is `(job_name, args_hash)` — `frontier.py:476`, `step_key()`. That is the
same composite identity DBOS builds from `(workflow_id, function_id)`.

### 3.2 Memoised replay

```python
# src/functualize/_engine/frontier.py:454
record = self._store.get_step(self._scope_id, step_key(node, args_hash))
```

and the walker, twice:

```python
# src/functualize/_engine/workflow_walker.py:759 and :806
record = self._store.get_step(self._scope_id, self._key(name))
```

A hit means "already ran"; the recorded return value is reused. That is memoised replay,
which is the entire mechanism.

### 3.3 The effecting/pure distinction

This is the part most durable-execution systems make *you* get right, and Functualize
makes it declarative:

```python
def is_effecting(self, node: str) -> bool:
    """Does ``node`` do something the world remembers?

    An effecting step must run exactly once across a crash and a resume;
    a pure one is replayed. The default is pure, because the framework
    cannot tell them apart by looking and guessing wrong in that direction
    re-runs a refund.
    """
    return node in self.effecting
```
— `src/functualize/_engine/frontier.py:71-79`

Compare: in DBOS, a plain `@DBOS.step()` is **at-least-once** and you must make it
idempotent yourself; only `@DBOS.transaction` — a database write in the same Postgres
transaction as the checkpoint — is exactly-once. In Restate, `ctx.run` records the
*result*, and a crash between the side effect and the journal write re-runs the side
effect. Neither system escapes the problem. Both, like us, push it onto a declaration.

We name it `effecting=True`. Restate names it "put it in `ctx.run` and make it
idempotent". DBOS names it `@DBOS.transaction`. **The problem is the same and nobody has
solved it; they have only relocated it.**

### 3.4 The code-version fence

This is the mechanism people assume only a commercial product has.

```python
def graph_digest(declaration: Any) -> str:
    """A stable digest of a workflow's **graph**, not of its file.

    Decision K3, and the reason is risk R-g: a digest of the *source file*
    refuses a resume whenever anything in that file changes — a docstring, an
    unrelated job, a reformat. That is not a safety property, it is a
    permanent annoyance that trains people to bypass the check.
    """
```
— `src/functualize/_engine/workflow_validation.py:212-222`

and the refusal:

```python
class WorkflowGraphChangedError(Exception):
    """A parked walk's graph is not the graph that is loaded now.

    Resuming would replay step records against a different shape: a node that
    no longer exists, an edge that now leads somewhere else, a gate whose
    answer no longer has a step to feed.
    """
```
— `src/functualize/_engine/workflow_validation.py:241-249`

**Ours is better-targeted than both commercial alternatives**, and that is a defensible
claim rather than a boast:

| | What invalidates a parked execution |
|---|---|
| **Functualize** | a change to the workflow **graph** — nodes, edges, entry point. A docstring edit, a reformat, or an unrelated job in the same file does **not** invalidate it. |
| **DBOS** | a change to `application_version`, "a hash of the running application code". Any code change anywhere orphans every in-flight workflow unless you run blue/green. |
| **Restate** | a new deployment registration. In-flight invocations are pinned to the old deployment, which must stay alive to drain them. |

Both alternatives operate at whole-application granularity. We operate at
graph granularity, deliberately, with the reason written down (risk R-g: "trains people
to bypass the check").

### 3.5 The fence against a stale writer

```text
A **monotonically increasing generation** fixes it without trusting any clock.
Every claim increments it, including a reclaim of an expired lease. A write
carries the generation it was acquired under, and the store refuses a write
whose generation is not the current one. So when B reclaims at generation 7, A's
writes at generation 6 are refused — *even though A still believes it holds the
lease*.
```
— `src/functualize/_primitives/lease.py:20-27`

This is the same epoch-fencing idea Restate's partition leaders use ("any late appends
from superseded leaders … carrying lower epochs are fenced at the epoch boundary"). We
designed it independently and wrote the reasoning down.

**It is also currently broken**, in two of the four ways documented in
[`../runtime-persistence-engine-owned/03-the-four-defects.md`](../runtime-persistence-engine-owned/03-the-four-defects.md):
the check exists at exactly one call site, the unrelated `scope-state/<id>` document has
no fence at all (`grep -c generation src/functualize/_primitives/scope_state_store.py`
→ **0**), and the guarded write then calls `substrate.write()` **without** `expect=`.
That is a level-2 defect in an otherwise-correct level-3 design, and it is fixable
without replacing anything.

## 4. What we do *not* have

An honest list, because the comparison is worthless without it.

| Missing | Restate | DBOS | Consequence for us |
|---|---|---|---|
| **Durable timers** — `sleep(12 hours)` that survives a restart | `ctx.sleep(timedelta(...))` | `DBOS.sleep()` | We have no scheduled resumption at all. A blocked walk waits for someone to run `func resume`. |
| **A server-side retry driver** — nobody has to be running for a failed step to be retried | the server re-invokes | the recovery thread re-invokes | Our retries happen inside one process (`_engine/exec_policy.py`); when the process dies, the retry dies. |
| **Cross-machine execution** | partitioned, keyed routing | `executor_id` + queue dequeue | Our substrates are a file or a local SQLite file. |
| **Atomic multi-document commit** | per-object only (no cross-object transaction) | `@DBOS.transaction` within one Postgres tx | Defect B3: no code path commits two documents together. |
| **An operations console** | `restate sql`, web UI | Conductor (paid) | We have `func builtin data show`. |
| **Exactly-once across the crash window** | no — `ctx.run` is at-least-once | no — `@DBOS.step` is at-least-once | Nobody has this. Not a gap against them. |

Read the right-hand column carefully. Of six gaps, **four are real** (timers, an external
retry driver, cross-machine, atomic multi-doc), one is a tooling gap, and one is not a
gap at all because neither competitor has it either.

**And of the four real gaps, exactly one — the atomic multi-document commit — is on the
critical path of the defects we actually have.** It is a level-2 gap. It is fixed by
choosing a transactional substrate, which is what `06-s3.md`, `05-cloudflare.md` and the
existing SQLite plugin are about. It is not fixed by adopting a level-3 engine.

## 5. The shape of the conflict

The question asked was: *does outsourcing durability conflict with our execution engine?*

It does not merely conflict with it. **At level 3, it is a replacement for it.**

```
  what we have today                     what adopting Restate/DBOS means

  RunRequest                             RunRequest
      │                                      │
      ▼                                      ▼
  JobExecutionEngine.run()               JobExecutionEngine.run()
      │                                      │
      ▼                                      ▼
  WorkflowWalker  ─────┐                 ??? ──────► Restate handler / @DBOS.workflow
   1,153 LOC           │                                   │
      │                │ replay                            │ replay
      ▼                │ memoise                           ▼
  FrontierWalk  ───────┤ fence                        their journal
     478 LOC           │ branch-pin                         │
      │                │                                    │
      ▼                │                              their K/V state
  ScopeStore ──────────┘                                    │
     47 methods                                  ──► and ScopeStore still exists,
      │                                              because their state APIs are
      ▼                                              workflow-scoped and cannot
  StoreSubstrate                                     hold `runs`, `fresh`, or
                                                     `shell-history`
```

Note the bottom-right. **Adopting either system does not let you delete the store.**
Restate's state is per-Virtual-Object or per-Workflow-instance, with a documented default
workflow-completion retention of one day. DBOS's `set_event`/`send`/`recv` are keyed by
workflow UUID. Neither is a document store; both research reports say so explicitly. So
the outcome of a full level-3 adoption is:

- a replay engine you deleted and a replay engine you now depend on, **plus**
- the document store you still need, **plus**
- a new server process or a new database, **plus**
- the impedance mismatch in §6.

That is not outsourcing. That is running two durability systems.

## 6. The three integration constraints that decide everything

These are measured, not argued.

### 6.1 The engine is synchronous. Restate's Python SDK is not.

```console
$ grep -rc 'async def' src/functualize/_engine/*.py | grep -v ':0'
(no output)

$ grep -rn 'async def' src/functualize --include=*.py | wc -l
10          # all ten are in _cli/, none in the engine

$ grep -rln 'import asyncio' src/functualize --include=*.py
(no output)
```

Every Restate handler is `async def`, and every context call is awaited:

```python
@my_service.handler()
async def run(ctx: restate.Context):
    result = await ctx.run_typed("LLM call", call_llm, prompt="…")
    await ctx.sleep(delta=timedelta(seconds=10))
```

Making `WorkflowWalker.walk()` awaitable means making its caller awaitable, and its
caller, up to `JobExecutionEngine.run()` — which is the single public execution path and
is called from the CLI, the TUI, the MCP server, and embedded host applications. That is
not an integration; it is a colour change across the entire codebase.

DBOS does not have this problem: its decorators work on ordinary synchronous functions.

### 6.2 Restate inverts control. DBOS does not.

Restate requires your code to be an **ASGI application** that a **Restate server**
connects to and drives:

```python
app = restate.app([my_service])
# then: uvicorn example:app   — and register the deployment with the server
```

Functualize is a CLI that a person runs, and a library a host app imports. There is no
place in that topology for "a server process calls into you." A `func run deploy` on a
laptop would have to: start an ASGI server, start or reach a Restate server, register a
deployment, then issue an HTTP request to itself through that server, and wait.

DBOS keeps control: you call your function, it checkpoints on the way through.
`DBOS.launch()` starts a thread pool and four daemon threads in *your* process.

### 6.3 Neither can be a default, because of ADR-015

The standalone binary's whole purpose is that "the first run needs no network"
(`contributor/adr/015-standalone-distribution-and-self-management.md:31-34`), and CI
asserts its measured size (`:252-253`).

- **Restate** needs a server binary (Rust, embedded RocksDB) — a second process, not
  importable, and the server is **BUSL-1.1** with a four-year Apache-2.0 change date.
- **DBOS** is MIT and importable, but `pip install dbos` pulls `psycopg[binary]` (a
  compiled C extension), `sqlalchemy[asyncio]` (which pulls `greenlet`), `websockets`,
  `click`, `pyyaml`, and `python-dateutil`. Core currently has **four** runtime
  dependencies (`pyproject.toml`). The existing precedent for a dependency of this
  weight is unambiguous: `plugins/functualize-aws/pyproject.toml` says
  "`grep -rn boto3 src/functualize/` must stay at 0."

So even in the most favourable reading, **both are plugins, never core**. Which
immediately raises the question `07` has to answer: a plugin can install a
`StoreSubstrate` today (`EngineHost.substrate`, at `APP_READY` — ADR-022). There is no
port through which a plugin can install a *replay engine*, and inventing one means
inventing a second way for a workflow to be durable, which is precisely the "two seams at
two levels" that ADR-022 removed:

```text
A plugin could give a scope SQLite for its **job state** while the **records describing
that scope** — which steps ran, where the walk stopped, what a human approved — stayed
on the filesystem. A resumed run then found its steps and not its variables.

Nothing prevented that arrangement; it was what the seam was *for*. Two seams at two
levels is how the split brain became reachable.
```
— `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md:48-55`

## 7. What this chapter does not say

It does not say Restate and DBOS are bad. They are good, and both research reports
support that. Restate's epoch-fenced partition leaders and DataFusion SQL introspection
are things we do not have and would take years to build. DBOS's single-Postgres-transaction
checkpoint is a genuinely stronger guarantee than anything we offer.

It says something narrower and more useful: **they solve level 3, we already have level 3,
and our actual defects are at level 2.** Buying a level-3 engine to fix a level-2 bug
means paying the largest possible price for the wrong repair, and then still having to fix
the level-2 bug, because — as §5 shows — the document store does not go away.

Read `08-is-it-cheap.md` for what that price is in lines and dollars.
