# ADR-028: Storage Is Pluggable, Execution Is Not — No Port for a Durable-Execution Provider

**Status**: accepted
**Date**: 2026-09-23
**Deciders**: maintainer, during `runtime-persistence-ports` (FUN-17)

## Context

Functualize is acquiring pluggable storage. The adjacent question arrives
immediately and will keep arriving: **if storage is pluggable, why not
durability itself?** Hand workflow execution to Restate or DBOS, let them own
replay and retries, and delete the machinery that does it today.

This is the single most re-proposable idea in this area, which is why it gets an
ADR rather than a paragraph. It was evaluated in full — the vendors' semantics,
their state models, their version fences, their dependency footprints — and
rejected. Without a record, it returns every time someone reads a durable-
execution vendor's landing page, and the evaluation gets redone.

### Functualize already implements durable execution

Not partially, and not as a stub. The mechanisms are in the tree:

- **Replay with memoised step records** — `_engine/workflow_walker.py` decides
  whether a step re-executes or reuses its recorded result.
- **Pinned branches and gate outcomes** — `_engine/frontier.py` decides what is
  reachable next.
- **Durable gates** — a workflow suspends at a human decision point and resumes
  later, from a record.
- **A code-version fence** — `graph_digest()` in
  `_engine/workflow_validation.py` (`:211`) refuses a resume when the workflow
  graph has changed under a suspended run, and names both digests when it
  refuses.

Adopting a durable-execution vendor therefore does not *add* a layer. It
**substitutes** one — because two systems cannot both own what "this step
already ran" means. That is the same one-owner-per-fact rule
[ADR-025](025-engine-owns-transition-meaning.md) settles for transitions, and
the same two-seams failure [ADR-022](022-storage-is-a-substrate-not-a-key-value-domain.md)
recorded for storage.

### Four findings, each independently disqualifying

1. **The document store does not go away.** Restate's state is per-Virtual-Object
   with a one-day default retention; DBOS's event and messaging primitives are
   keyed by workflow UUID and garbage-collected with the workflow rows. Neither
   can hold `fresh`, `scopes`, `runs` or `shell-history`. The end state is
   **two** durability systems, not one.
2. **There is no seam to install it into.** A plugin can install a substrate.
   Nothing installs a replay engine — and inventing that port recreates exactly
   the two-seams split brain ADR-022 was written to remove.
3. **Their version fence is coarser than ours.** DBOS orphans every in-flight
   workflow when its application version — a hash of the whole application —
   moves, mitigated by blue/green deployment, which is meaningless for a laptop
   CLI. `graph_digest()` moves only when the graph moves. Adopting either trades
   a good failure mode for a worse one.
4. **Neither can be core.** Restate needs a separate BUSL-licensed Rust server.
   DBOS pulls six dependencies including a binary Postgres driver and `greenlet`,
   against core's **four** (`pydantic`, `python-dotenv`, `jinja2`,
   `cryptography`); and its offline SQLite mode is documented as unusable in a
   distributed setting, which cancels the reason to adopt it. Functualize ships
   a standalone offline binary — that is what the distribution is for.

### What was taken instead

DBOS's guarantee that a state change and its durability record commit in one
database transaction is exactly the shape the buffering runtime transaction
adopts. It is cited as **independent evidence for a design decision**, which is
worth more than the integration and costs nothing.

## Decision

**Storage is pluggable. Execution is not. No port is defined for a
durable-execution provider.**

A plugin may supply *where records live* and *what durability guarantees the
backend makes*. No plugin may supply *what it means for a step to have run*.

### The general rule this establishes

> Any future proposal that introduces a **second way for a workflow to be
> durable** is the ADR-022 mistake one layer up, however good the vendor is.

The test is not "is this vendor good" — several are. It is "would this create a
second owner for step completion". If yes, it is refused on that ground alone,
before any evaluation of quality, cost or ergonomics.

### What remains open, deliberately

- **A backend with stronger guarantees is welcome** and needs no new port. That
  is the whole point of a declared capability record: a store that offers
  cross-aggregate atomicity says so, and features that need it become
  selectable.
- **Borrowing a design** from a durable-execution system is encouraged, as the
  transaction shape above already does. Reading their engineering is not the
  same as delegating to their runtime.
- This ADR does not say the current replay implementation is finished. It says
  that improving it happens **in `_engine`**.

## Consequences

### Positive

- **One owner for "this step already ran."** The property the whole workflow
  feature rests on stays in one place.
- **Core stays at four dependencies** and the offline binary keeps working with
  no network at all.
- **The recurring proposal has an address.** The next time it arrives, this file
  is the answer, and the discussion starts from the four findings rather than
  from scratch.
- **The version fence stays graph-scoped**, which is the behaviour that makes
  resuming a suspended workflow across a code change safe rather than lossy.

### Negative

- **Functualize maintains its own durable execution**, including the hard parts:
  replay correctness, fence semantics, and every edge case a vendor would have
  absorbed. That cost is real and ongoing, and it is accepted knowingly.
- **A user already running such a platform cannot consolidate.** They will run
  Functualize's durability alongside it.
- **This forecloses an integration that may become more attractive** as those
  products mature. Reopening is deliberately made explicit below rather than
  left implicit.

### Neutral

- Nothing changes in the code today. This ADR records a boundary on future
  proposals.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Adopt Restate as the execution backend | Mature durable execution; strong semantics | Separate BUSL-licensed Rust server; cannot be core; document store survives anyway | Cannot ship in an offline binary; two durability systems remain |
| Adopt DBOS | Python-native; Postgres-backed | Six dependencies incl. binary Postgres driver; application-hash version fence orphans in-flight workflows; offline mode unusable distributed | Trades a good failure mode for a worse one |
| Define a `DurableExecutionProvider` port and let either plug in | Keeps the option open; symmetric with storage | Creates the second seam ADR-022 removed; two owners for step completion; the port would have exactly one shape and no second implementation | The defect is the port itself, not the vendor behind it |
| Adopt one only for distributed deployments | Best tool per deployment | Two execution semantics to test, document and support; a workflow's meaning would depend on deployment | Multiplies the surface it was meant to reduce |

## What would reopen this

A vendor that can own **all four** record kinds — `fresh`, `scopes`, `runs`,
`shell-history` — with a graph-scoped version fence, in core's dependency budget,
working offline. That is not a near-term ask of any evaluated product; it is
written down so the bar is a specification rather than an impression, and so a
future proposal can be measured against it instead of re-litigating the four
findings.

Note that even then the decision would be *substitution*, not addition: the
existing replay machinery would be removed in the same change. A proposal that
leaves both running has not met this bar.
