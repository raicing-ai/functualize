# 03 — Restate

**Level 3 (durable execution).** Not a document store. Cannot be our backend store.

## 1. What it is, for someone who has never heard of it

Restate is two things that must both be running:

1. **The Restate Server** — a single Rust binary with an embedded RocksDB. It is a
   *reverse proxy*: every invocation goes through it.
2. **Your service** — an HTTP server (in Python, an ASGI app) exposing handlers. The
   Restate server opens a bidirectional connection to it and drives execution.

You do not call your function. A client calls the *server*; the server calls your
handler, records each step it takes into a journal, and if your process dies, calls a
handler again and feeds it the journal so it skips what already happened.

```python
import restate

my_service = restate.Service("myService")

@my_service.handler()
async def run(ctx: restate.Context):
    result = await ctx.run_typed("LLM call", call_llm, prompt="What is the weather?")
    await ctx.sleep(delta=timedelta(seconds=10), name="wait for payment")

app = restate.app([my_service])   # served by uvicorn/hypercorn
```
— [docs.restate.dev/develop/python/services](https://docs.restate.dev/develop/python/services),
[durable-steps](https://docs.restate.dev/develop/python/durable-steps)

Then, separately: `restate deployments register http://localhost:9080`, and invocations
arrive at `http://restate:8080/myService/run`.

**Three mechanisms worth knowing:**

- **Virtual Objects** — a keyed actor. "Restate guarantees that only one handler executes
  at a time for a given key." That is a server-enforced mutex, and it holds a per-key K/V
  state.
- **Durable promises / awakeables** — block a handler on an external event; it survives
  the process. This is Restate's `Gate`.
- **Epoch fencing** — each partition leader has a monotonically increasing epoch, and
  "any late appends from superseded leaders … carrying lower epochs are fenced at the
  epoch boundary and ignored." That is the same idea as `_primitives/lease.py`,
  implemented in their log layer.

## 2. What it would genuinely give us

Be fair about this first; the verdict is worthless otherwise.

| Capability | We have | Restate has | Worth? |
|---|---|---|---|
| Durable timers (`sleep(12h)` surviving restart) | nothing | `ctx.sleep`, no documented duration cap | **Real.** Our blocked walks wait for a human to run `func resume`. |
| An external driver that retries after the process dies | nothing | the server re-invokes | **Real.** `_engine/exec_policy.py` retries in-process only. |
| Cross-machine execution with automatic failover | nothing | partitioned, keyed routing, epoch-fenced leadership | **Real**, and expensive to build. |
| SQL introspection over live state | `func builtin data show` | Apache DataFusion over `sys_invocation`, `sys_journal`, `state` | Nice. Not load-bearing. |
| Single-writer per key without our own lease | `claim_scope` + generation | server-enforced by keyed routing | Equivalent, theirs is stronger. |

That is a genuinely good product. Nothing below is an argument that Restate is bad.

## 3. The five reasons it cannot be adopted here

### 3.1 It requires `async`. Our engine has none.

Every handler is `async def`; every context call is awaited. Measured against our tree:

```console
$ grep -rc 'async def' src/functualize/_engine/*.py | grep -v ':0'
(no output — zero)

$ grep -rln 'import asyncio' src/functualize --include=*.py
(no output)
```

`WorkflowWalker.walk()` is synchronous, its caller `JobExecutionEngine.run()` is
synchronous, and `run()` is the single public execution path used by the CLI, the TUI,
the MCP plugin, and embedded host applications. Adopting Restate colours the entire call
stack `async`. That is not an integration cost; it is a rewrite of the public API.

### 3.2 It inverts control, and our topology has nowhere to put the server

Functualize is a command a person types and a library a host app imports. Restate needs
your code to be a *server that another server calls*.

To run `func run deploy` on a laptop under Restate you would need to: start an ASGI
server inside the CLI process, have a Restate server running (a second process, or a
cloud account), register the deployment, then issue an HTTP request through that server
back into yourself, and block on the response. For a command whose current cost is
`import` plus a function call.

### 3.3 Offline is dead, and ADR-015 says offline is the point

> "**The first run needs no network.** That is the entire reason the binary exists — its
> audience is precisely the machine that cannot reach an index."
> — `contributor/adr/015-standalone-distribution-and-self-management.md:31-34`

Restate self-hosted does run offline — but it is a separate Rust binary with its own
RocksDB and a persistent volume. Shipping it inside our ~100 MB PyApp payload, across
seven release targets, to give a laptop user a durable `sleep()`, is not a trade anyone
would take.

### 3.4 The server is BUSL-1.1

The Python SDK is MIT — fine. The **server** is Business Source License 1.1, converting
to Apache-2.0 four years after each release, with an Additional Use Grant that prohibits
operating Restate as a managed platform that lets third parties register their own
deployments.

Merely *talking* to a server is unaffected. But we relicensed to Apache-2.0
(`contributor/adr/024-apache-2-0-relicensing.md`), and redistributing a BUSL binary
inside our offline artifact is a licensing conversation we do not need to have.

### 3.5 Its code-version fence is coarser than the one we already have

This is the subtle one, and it is the strongest argument that adopting Restate would be a
*downgrade* in one specific place.

Restate uses **immutable deployments**. In-flight invocations are pinned to the
deployment they started on; that deployment must keep running to drain them. A code
change that touches nothing relevant still produces a new deployment.

Our fence is deliberately narrower:

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

A docstring edit does not invalidate a parked walk here. Under Restate's model, the
question does not even arise — the deployment is new, so the old one must be kept alive.
For a laptop tool where "the old process" means "a terminal the user already closed",
that model does not fit.

## 4. Could Restate be our *backend store*?

No, and the research is explicit about why.

- **State exists only on Virtual Objects and Workflows.** "State is only available for
  Virtual Objects and Workflows" — a plain `Service` handler cannot hold state at all
  ([python/state](https://docs.restate.dev/develop/python/state)).
- **It is retention-bounded.** `default-workflow-completion-retention` is **1 day**;
  `default-journal-retention` is **1 day**
  ([server-config](https://docs.restate.dev/references/server-config)). Our `runs`
  document is a run log people read after the fact.
- **There is no cross-object transaction.** State commits atomically with one handler
  completing, on one key. Two objects are two invocations, durably retried but *not*
  atomic as a pair. Our defect B3 is precisely a cross-document atomicity defect, so this
  fixes nothing.
- **Every write is a journaled side effect of an invocation.** There is no "store this
  JSON" API detached from a handler.

So `fresh`, `scopes`, `runs` and `shell-history` would all still need a real store —
meaning adopting Restate *adds* a dependency without removing one.

## 5. Where Restate would actually make sense here

Not as an adoption. As a **deployment target**, which is a different thing entirely and
costs nothing today:

A hypothetical `functualize-restate` plugin could expose Functualize jobs *as* Restate
handlers, for an operator who already runs Restate and wants our discovery, config,
guards and TUI in front of it. Our engine stays the engine on a laptop; theirs is the
engine in their cluster. That is the same shape as `plugins/functualize-lambda/`.

That is speculative and nobody has asked for it. It is recorded here only so the idea is
not confused with the one this document rejects.

## 6. Verdict

| Question | Answer |
|---|---|
| As a backend store? | **No.** Not a document store; retention-bounded; no cross-key transaction. |
| As a durability provider (level 3)? | **No.** Replaces an engine we have, requires `async`, inverts control, kills offline, BUSL server, coarser version fence. |
| Any adoption path? | Only as a future deployment-target plugin. Not now, not asked for. |

## Facts used, with sources

| Claim | Source |
|---|---|
| Journal + replay model, virtual objects, single-handler-per-key | [key-concepts](https://docs.restate.dev/foundations/key-concepts) |
| Python SDK is an ASGI app served by uvicorn/hypercorn | [python/serving](https://docs.restate.dev/develop/python/serving) |
| `ctx.run` cannot nest or use the context inside | [python/durable-steps](https://docs.restate.dev/develop/python/durable-steps) |
| State only on Virtual Objects/Workflows | [python/state](https://docs.restate.dev/develop/python/state) |
| 1-day default journal/workflow retention | [server-config](https://docs.restate.dev/references/server-config) |
| Immutable deployments; in-flight pinned to their version | [operate/versioning](https://docs.restate.dev/operate/versioning/) |
| Journal mismatch RT0016 is terminal and non-retryable | [references/errors](https://docs.restate.dev/references/errors) |
| Epoch fencing of superseded leaders | [references/architecture](https://docs.restate.dev/references/architecture) |
| Single binary, embedded RocksDB, persistent volume required | [server/overview](https://docs.restate.dev/server/overview) |
| Server is BUSL-1.1, 4-year Apache-2.0 change date | [LICENSE](https://github.com/restatedev/restate/blob/main/LICENSE) |
| Python SDK is MIT; 1.0.0 released 2026-06-23 | [sdk-python](https://github.com/restatedev/sdk-python) |
| Free tier 50,000 durable actions/month | [restate.dev/pricing](https://restate.dev/pricing) |

**Not established by the research** (do not cite these as known): exact paid-tier pricing;
server cold-start cost; exact default state key/value size limits; documented client
behaviour when the server is unreachable; any hard cap on invocation wall-clock duration.
