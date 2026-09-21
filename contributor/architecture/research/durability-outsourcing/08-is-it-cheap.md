# 08 — Is outsourcing durability cheap?

> *"Would outsourcing 'durability' be cheap? Does it conflict with our execution engine?"*

Short answer: **at level 1 it is very cheap. At level 3 it is the most expensive thing in
this repository, and it conflicts with the execution engine by replacing it.**

Here is the arithmetic.

## 1. What a level-1 backend costs — measured

We have already done this once, so the number is not an estimate.

```console
$ find plugins/functualize-state-sqlite -name '*.py' | xargs wc -l | tail -1
     774 total          # including tests and an example

$ wc -l plugins/functualize-state-sqlite/src/functualize_state_sqlite/*.py
      14 __init__.py
     113 _plugin.py
     225 substrate.py
     352 total          # the actual implementation
```

**352 lines of implementation, 0 new dependencies, for a complete alternative backend.**
That is what "outsourcing persistence" costs when the seam is in the right place.

A D1 substrate would reuse that file's schema and most of its SQL (`05-cloudflare.md` §A.2
maps every method), replacing `sqlite3` calls with HTTPS calls. Call it 400–500 lines plus
one dependency (`cloudflare`, or `httpx`, in the plugin only).

An S3 substrate is comparable: 350–450 lines plus `boto3`, in a plugin, following the
precedent `plugins/functualize-aws/` already set.

**Level 1 is cheap. This is a solved problem here, and the solution is already shipped.**

## 2. What a level-3 engine costs — measured

The code that would be replaced:

| File | LOC | What it does |
|---|---|---|
| `_engine/workflow_walker.py` | 1,153 | replay + memoisation over the graph |
| `_engine/frontier.py` | 478 | frontier expansion, step records, branch pinning, gates |
| `_engine/workflow_validation.py` | 299 | the graph digest and the version fence |
| `_engine/workflow_orchestrator.py` | 248 | nested workflows, scope ids |
| `_engine/loop_state.py` | 75 | iteration keys for loops |
| **replay engine subtotal** | **2,253** | |
| `_primitives/scope_store.py` | 923 | the journal itself — 47 methods |
| `_primitives/scope_state_store.py` | 235 | per-scope state |
| `_primitives/lease.py` | 305 | fencing |
| **journal subtotal** | **1,463** | |
| **total in the blast radius** | **3,716** | |

Against 102,083 lines in `src/functualize/`.

But the LOC is the *smallest* part of the cost. The rest:

### 2.1 The async conversion (Restate only)

```console
$ grep -rc 'async def' src/functualize/_engine/*.py | grep -v ':0'
(no output — zero async functions in the engine)

$ grep -rln 'import asyncio' src/functualize --include=*.py
(no output)
```

Restate handlers are `async def`. Making the walker awaitable makes
`JobExecutionEngine.run()` awaitable, and `run()` is the single public execution path used
by the CLI, the TUI, the MCP plugin and every embedded host application. That is a
breaking change to the public API of a 0.3.0 library, touching every caller in and out of
this repository.

Not applicable to DBOS, which works on synchronous functions.

### 2.2 The store does not go away

This is the cost people forget, and both research reports confirm it independently:

- **Restate**: "State is only available for Virtual Objects and Workflows"; default
  workflow-completion retention **1 day**; no cross-object transaction
  ([state](https://docs.restate.dev/develop/python/state),
  [server-config](https://docs.restate.dev/references/server-config)).
- **DBOS**: `set_event`/`send`/`recv` live in `dbos.workflow_events` and
  `dbos.notifications`, keyed by workflow UUID, GC'd with the workflow rows
  ([system-tables](https://docs.dbos.dev/explanations/system-tables)).

Neither is a document store. `fresh`, `scopes`, `runs` and `shell-history` still need one.
So the end state of a level-3 adoption is **two durability systems**, not one:

```
  before:  engine ──► ScopeStore ──► substrate

  after:   engine ──► their journal ──► their database
              │
              └────► ScopeStore ──► substrate      (still here, for the other four documents)
```

### 2.3 The dependency, against a rule we already wrote

`pip install dbos` pulls `psycopg[binary]` (compiled C), `sqlalchemy[asyncio]` (pulls
`greenlet`, compiled), `websockets`, `click`, `pyyaml`, `python-dateutil`. Core has
**four** runtime dependencies today.

Restate needs a **separate Rust server binary** with an embedded RocksDB and a persistent
volume, licensed **BUSL-1.1**.

Either way the answer is the same as it was for boto3:

> "The reason this is a plugin at all: boto3 and botocore are ~20MB of wheel and a hard
> AWS coupling. `grep -rn boto3 src/functualize/` must stay at 0."
> — `plugins/functualize-aws/pyproject.toml`

### 2.4 The seam does not exist

A plugin can install a substrate (`EngineHost.substrate`, ADR-022). **There is no port
through which a plugin can install a replay engine**, and creating one recreates the
split brain ADR-022 removed — see `07-the-design.md` §2.

So a level-3 adoption is not a plugin. It is a core change.

### 2.5 The regression nobody prices in

Both alternatives have a **coarser code-version fence** than ours:

| | Invalidates a parked execution |
|---|---|
| Functualize | the workflow **graph** changed |
| DBOS | `application_version` — a hash of the whole application — changed |
| Restate | a new deployment was registered |

On a laptop, DBOS's model means: edit an unrelated job, and your parked workflow becomes a
zombie — `PENDING` in the table, gate open, and no process will ever pick it up, because
recovery only resumes workflows whose stamped version matches. DBOS's documented mitigation
is blue/green deployment, which has no meaning for a terminal the user already closed.

Ours refuses loudly and names both digests
(`_engine/workflow_validation.py:241-263`). Adopting either system trades a good failure
mode for a bad one — and pays 3,716 lines for the privilege.

## 3. The dollar cost, for completeness

Because the question said "cheap", and money is the cheapest part of this.

| Option | Recurring cost for our workload |
|---|---|
| **Filesystem / SQLite** | $0 |
| **Cloudflare D1** | effectively $0 — 25 bn rows read / 50 m written per month included on the paid plan; no egress charge |
| **AWS S3** | ~**$0.001 per workflow** of 200 transitions; ~$1/month at 1,000 such runs |
| **Cloudflare R2** | cheaper than S3 per operation, free egress — but blocked on the CAS-atomicity question (`05-cloudflare.md` §C) |
| **Restate Cloud** | free tier 50,000 durable actions/month; paid pricing not published in a retrievable form |
| **Restate self-hosted** | $0 in licence, one more server to operate, BUSL |
| **DBOS library** | $0 (MIT). Observability UI is $99/mo (Pro) or $499/mo (Teams); self-hosted Conductor is Enterprise-only |

**Money is not the constraint.** At our volumes every option is between free and a
rounding error. Anyone arguing for or against on cost grounds is arguing about the wrong
axis — the real costs are latency (§4), lines (§2), and the offline guarantee (§5).

## 4. The latency cost, which is the real one for level 1

Our write path is read-modify-write. On a filesystem that is microseconds. On any network
store it is a round trip.

| Backend | Per `write()` |
|---|---|
| filesystem | µs |
| local SQLite | µs |
| **D1 over REST** | one HTTPS round trip, plus a possible hop to the primary. Cloudflare's own changelog quantifies an *improvement* of "50-500 ms" from moving auth to the edge, which tells you the prior baseline |
| **S3 from outside AWS** | tens to low hundreds of ms, dominated by internet RTT |

A 200-transition workflow that takes milliseconds locally spends a meaningful fraction of
a minute in network I/O remotely. That is not a reason not to build it; it is a reason it
must be an operator's deliberate choice with the number in the plugin README, and it is
why `StoreProfile.remote` exists in `07-the-design.md` §3.

## 5. The cost that cannot be paid in money or lines

> "**The first run needs no network.** That is the entire reason the binary exists — its
> audience is precisely the machine that cannot reach an index."
> — `contributor/adr/015-standalone-distribution-and-self-management.md:31-34`

Every option in this evaluation except the filesystem and local SQLite is online-only.
D1, R2, Durable Objects, Workflows and S3 have no offline mode. Restate self-hosted runs
offline only if you ship a second binary. DBOS runs offline only in SQLite mode — which is
also the mode that "can't be used in a distributed setting", i.e. the mode that cancels
the benefit you adopted it for.

So **no remote backend can ever be the default**, and that is not a limitation to work
around — it is the product.

## 6. The summary table

| | Level 1 substrate (D1/S3) | Level 3 engine (Restate/DBOS) |
|---|---|---|
| New code | ~350–500 lines, one plugin | ~3,716 lines in the blast radius, in core |
| New core dependencies | **0** | 6 (DBOS) or a second server binary (Restate) |
| Public API change | none | `async` everywhere (Restate) |
| Existing seam? | **yes** — `EngineHost.substrate`, ADR-022 | **no**, and creating one re-opens the split brain |
| Does the store still exist after? | it *is* the store | **yes** — two durability systems |
| Fixes defect B1/B4 (fencing) | yes, with real CAS | incidentally |
| Fixes defect B3 (cross-doc atomicity) | **D1 yes, S3 no** | yes, but so does SQLite |
| Version-fence quality after | unchanged | **worse** |
| Offline after | lost unless declared and refused | lost, or the benefit is cancelled |
| Recurring $ | ~$0–$1/month | ~$0–$499/month |
| Precedent in this repo | `functualize-state-sqlite`, 352 lines, shipped | none |

## 7. So: does it conflict with our execution engine?

**At level 1, no.** A substrate does not know the engine exists. That is the whole point
of ADR-022, and it is why a SQLite backend was 352 lines.

**At level 3, it does not conflict — it substitutes.** You cannot run two replay engines
over one workflow; one of them owns what "this step already ran" means. Adopting Restate
or DBOS means deleting `FrontierWalk` and `WorkflowWalker` and accepting their model of
determinism, their version fence, their serialisation format and their retention policy —
and still keeping a document store for everything their state APIs cannot hold.

The engine is not the part of this system that is broken. **The four defects are all at
level 2** ([`../runtime-persistence-engine-owned/03-the-four-defects.md`](../runtime-persistence-engine-owned/03-the-four-defects.md)),
and three of them are in `scope_store.py` and `scope_state_store.py` — 1,158 lines that a
level-3 adoption does not touch and does not fix.
