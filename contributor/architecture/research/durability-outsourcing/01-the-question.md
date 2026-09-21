# 01 — The question, restated precisely

> Read this first. It defines the words the rest of the folder uses. If you skip it,
> `03`–`06` will read like product reviews instead of an evaluation.

## 1. What was asked

Five systems were named:

| # | System | What it is, in one line |
|---|---|---|
| 1 | **Restate** | A durable-execution server: your code becomes handlers, it journals every step and replays them after a crash. |
| 2 | **DBOS** | A durable-execution *library*: decorators checkpoint your workflow into Postgres, no server. |
| 3 | **Cloudflare D1** | Managed SQLite at the edge, reachable over HTTP. |
| 4 | **"Cloudflare D2"** | No such product. See `05` §0 for what it most likely means. |
| 5 | **AWS S3** | Object storage, which since 2024 has conditional writes — a genuine compare-and-swap. |

And four questions were asked about them:

1. What if we used them as **the backend store**?
2. For Restate and DBOS: what if we let them provide **durability** itself?
3. **At what level** should the abstraction sit? Should durability and persistence be
   at *different* levels?
4. Is outsourcing durability **cheap**? Does it **conflict with our execution engine**?

Questions 3 and 4 are the real ones. Questions 1 and 2 are how you get the evidence to
answer them.

## 2. The word "durability" is doing three different jobs

This is the single most important thing in this folder, and every muddled conversation
about this topic comes from collapsing these three.

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │ LEVEL 3 — DURABLE EXECUTION                                          │
  │ "a computation survives the death of the process running it"         │
  │                                                                      │
  │ Needs: a journal of completed steps, a rule for replay, a fence      │
  │        against running old code against a new journal                │
  │ Provided by: Restate, DBOS, Temporal … and by Functualize itself     │
  ├──────────────────────────────────────────────────────────────────────┤
  │ LEVEL 2 — TRANSACTIONAL INTEGRITY                                    │
  │ "a state transition commits as one unit, or not at all, and a        │
  │  superseded writer cannot commit at all"                             │
  │                                                                      │
  │ Needs: atomic multi-key commit, compare-and-swap, fencing tokens     │
  │ Provided by: Postgres, SQLite, D1(partly), S3(partly), a flat file   │
  │              NOT at all                                              │
  ├──────────────────────────────────────────────────────────────────────┤
  │ LEVEL 1 — PERSISTENCE                                                │
  │ "the bytes are still there after the power goes out"                 │
  │                                                                      │
  │ Needs: fsync, or someone else's fsync                                │
  │ Provided by: a filesystem, SQLite, S3, D1, R2, anything at all       │
  └──────────────────────────────────────────────────────────────────────┘
```

**Level 1 is nearly free and nearly universal.** Every candidate provides it. It is not
an interesting axis of comparison and choosing a backend on level-1 grounds alone is
how you end up with a store that loses a lease.

**Level 2 is where backends actually differ**, and it is where Functualize is currently
broken — four defects, all of them level-2 defects, documented with runnable
reproductions in
[`../runtime-persistence-engine-owned/03-the-four-defects.md`](../runtime-persistence-engine-owned/03-the-four-defects.md).

**Level 3 is where Restate and DBOS live.** And level 3 is the level Functualize
*already implements* — which is the finding that reorganises this whole evaluation. See
[`02-what-we-already-have.md`](02-what-we-already-have.md).

### Why the layering matters for the question asked

> *"Should durability guarantee and persistence be at different abstraction levels?"*

Yes — and not as a matter of taste. They must be at different levels because **they have
different cardinalities**:

- Persistence (level 1) is chosen **once per application**. One substrate, per ADR-022.
- Transactional integrity (level 2) is a **property of the chosen substrate**, which the
  application must be able to *interrogate* rather than assume — a filesystem and
  Postgres do not offer the same guarantees and pretending they do is how the split
  brain in `03`'s defect B3 got shipped.
- Durable execution (level 3) is a **property of the engine**, and it has to be the same
  regardless of substrate, because the rule "an effecting step runs exactly once across a
  crash" is a statement about *job semantics*, not about where bytes live.

Collapse 3 into 1 and you get the design ADR-022 already rejected: a backend-agnostic
protocol that can only promise the intersection of every backend's capabilities
(`contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md:36-39`).

Collapse 2 into 1 and you get today's bug: `StoreSubstrate.write()` has an `expect=`
parameter for compare-and-swap, and the one fencing site in the codebase
(`src/functualize/_primitives/scope_store.py:250-266`) calls `write()` **without it**.

## 3. What "outsourcing durability" would actually mean

There are three genuinely distinct proposals hiding under that phrase, and they cost
wildly different amounts:

| Proposal | What moves out | What stays | Blast radius |
|---|---|---|---|
| **A. Outsource level 1** — a new substrate | where bytes live | everything else | one plugin, ~300 LOC, precedent exists (`plugins/functualize-state-sqlite/`) |
| **B. Outsource level 2** — a transactional store | atomicity + fencing | the engine's replay rules | the `RuntimeStore` port in the existing design proposal |
| **C. Outsource level 3** — durable execution | the replay engine itself | almost nothing | `_engine/frontier.py` (478 LOC), `_engine/workflow_walker.py` (1,153 LOC), `ScopeStore`'s 47 methods, and the entire sync execution model |

S3, D1 and R2 are candidates for **A**, and partially for **B**.
Restate and DBOS are candidates for **C** only — and pretending they are candidates for
A is the mistake this folder exists to prevent. Neither is a document store.

## 4. The constraints any answer has to survive

These are not preferences. Each is a recorded decision with a file behind it.

| Constraint | Where it is written | What it rules out |
|---|---|---|
| **Offline-complete.** The standalone binary's "first run needs no network. That is the entire reason the binary exists." | `contributor/adr/015-standalone-distribution-and-self-management.md:31-34` | Any *default* backend that requires a network, a server process, or a cloud account |
| **Binary size is CI-gated.** "~100 MB of binary… CI asserts the *measured* size so the number stays visible." | `contributor/adr/015…:252-253` | Heavy dependencies in core |
| **Core takes no cloud SDK.** "`grep -rn boto3 src/functualize/` must stay at 0." | `plugins/functualize-aws/pyproject.toml` | boto3, the Postgres driver, the Restate SDK — all of them are plugin-only |
| **Core has four runtime dependencies.** pydantic, python-dotenv, jinja2, cryptography. | `pyproject.toml` | Adding a fifth needs an argument as strong as the one written next to `cryptography` |
| **One substrate per app, chosen once.** | ADR-022, *Decision* | Per-scope backends, two seams at two levels |
| **The engine is entirely synchronous.** Zero `async def` in `src/functualize/_engine/`; 10 in all of `src/`, all in `_cli/`; `asyncio` is imported nowhere in `src/functualize/`. | measured, `grep -rn 'async def' src/functualize` | Any integration that requires the *call site* to be a coroutine |

That last row is worth pausing on. It is measured, not assumed:

```console
$ grep -rc 'async def' src/functualize/_engine/*.py | grep -v ':0'
(no output — zero async functions in the entire engine layer)

$ grep -rln 'import asyncio' src/functualize --include=*.py
(no output)
```

## 5. How to read the rest of this folder

| Read | For |
|---|---|
| [`02-what-we-already-have.md`](02-what-we-already-have.md) | **Do this second.** The durable-execution engine that already exists here. Without it, `03` and `04` look like free wins. |
| [`03-restate.md`](03-restate.md) | Restate as a level-3 provider |
| [`04-dbos.md`](04-dbos.md) | DBOS as a level-3 provider |
| [`05-cloudflare.md`](05-cloudflare.md) | D1, Durable Objects, R2, Workflows as level-1/2 backends — and what "D2" is |
| [`06-s3.md`](06-s3.md) | S3 conditional writes as a level-2 primitive |
| [`07-the-design.md`](07-the-design.md) | **The answer to question 3.** Where each abstraction sits, and the ports |
| [`08-is-it-cheap.md`](08-is-it-cheap.md) | **The answer to question 4.** Costed, in lines and in dollars |
| [`09-verdict.md`](09-verdict.md) | What to actually do |
