# Runtime persistence — the engine-owned design

**Status:** proposal. Nothing here has shipped.
**Author stance:** independent; written after an adversarial assessment of the
existing proposal and of the code it describes.
**Code baseline:** `feat/substrate-sqlite` @ `8d450ad`, re-checked against
`origin/master` @ `8c06198`.
**Covers:** FUN-16 through FUN-23.

---

## What this folder is

This is a **second, complete design** for how Functualize should persist runtime
truth — runs, workflows, steps, job state, gates and events.

There is already a first design in
[`../runtime-persistence/`](../runtime-persistence/README.md). It is good work and
this folder does not replace it wholesale; it disagrees with its **sequencing**, its
**layer placement**, and one **factual claim about what the current code guarantees**.
There is also a third design, written by an independent reviewer, that lives on
Confluence. All three are compared side by side, with quoted snippets, in
[`04-three-designs-compared.md`](04-three-designs-compared.md).

If you only read one file, read that one.

**A fourth option was evaluated separately and rejected:** not building this at all, and
outsourcing durability to Restate, DBOS, Cloudflare or S3 instead. That lives in
[`../durability-outsourcing/`](../durability-outsourcing/README.md). It concluded that
Functualize already implements durable execution and that its defects are one level
below that — and it sent four corrections back into this folder, marked in
[`09-decisions.md`](09-decisions.md) §6.

## Who this is written for

**Someone who joined the team this week and has not read the codebase.** Every
document assumes that. Terms are defined the first time they appear, every claim
carries a `file:line` citation you can go and check, and
[`01-orientation.md`](01-orientation.md) exists purely so that the rest makes sense
to a newcomer.

If you have been here for a year, start at
[`04-three-designs-compared.md`](04-three-designs-compared.md) and skip 01–02.

## The argument in six sentences

1. Functualize keeps its runtime truth in five JSON documents behind a port called
   `StoreSubstrate`, and a plugin can swap that port for SQLite.
2. That port is a *document* abstraction, and the things the product now needs —
   relational queries, atomic multi-record transitions, an effects outbox, durable
   interactions, migrations — are not document operations.
3. So the first design proposes replacing it with a provider/repository/unit-of-work
   family in a new `_persistence` layer. That direction is right.
4. But **four correctness defects in the shipped code are currently corrupting the
   very data that design plans to migrate**, and one of them is widely believed to
   have been fixed and has not been ([`03-the-four-defects.md`](03-the-four-defects.md)).
5. And the first design's Wave 1 promises one semantic contract across a document
   adapter that provably cannot honour it.
6. This design fixes the data first, keeps transition ownership in the engine where
   the codebase already puts it, and earns the abstraction one backend at a time.

## Reading order

| # | Document | What it answers | Read if |
|---|---|---|---|
| 01 | [orientation.md](01-orientation.md) | What is Functualize, what is a scope, where does data live? | You are new |
| 02 | [what-exists-today.md](02-what-exists-today.md) | What does the code actually do right now? | Always |
| 03 | [the-four-defects.md](03-the-four-defects.md) | What is broken, proven by running it? | Always |
| 04 | [three-designs-compared.md](04-three-designs-compared.md) | How do the three proposals differ, and why this one? | Always |
| 05 | [the-design.md](05-the-design.md) | What exactly is being proposed? | Always |
| 06 | [data-model.md](06-data-model.md) | What are the tables, transactions and state machines? | Implementing |
| 07 | [what-changes.md](07-what-changes.md) | Which files change, by how much? | Estimating |
| 08 | [delivery-and-tests.md](08-delivery-and-tests.md) | In what order, and how is each step proven? | Planning |
| 09 | [decisions.md](09-decisions.md) | What was decided, rejected, and left open? | Reviewing |

## Status boundary

Everything in this folder describes a **target**. The only statements about shipped
behaviour are in 02 and 03, and each of those carries a citation or a reproduction
you can run yourself. Do not cite this folder as evidence that anything has been
built.

## Relationship to the other documents in this repository

| Document | Relationship |
|---|---|
| [`../runtime-persistence/`](../runtime-persistence/README.md) | The first design. Referenced and quoted throughout; disagreed with in 04 and 09. |
| [`../../codemaps/runtime-persistence.md`](../../codemaps/runtime-persistence.md) | The current/target codemap. Its "current" half agrees with 02. |
| `.spec/scrutiny-reports/runtime-persistence-non-c4-review.md` | An earlier adversarial review of the first design. Mostly agreed with; two of its findings are contradicted in 04. |
| `.spec/scrutiny-reports/runtime-persistence-independent-assessment.md` | The assessment this design came out of. 03 is its findings section, expanded. |
| [`../../../adr/022-storage-is-a-substrate-not-a-key-value-domain.md`](../../../adr/022-storage-is-a-substrate-not-a-key-value-domain.md) | The decision that produced today's `StoreSubstrate`. This design reopens it on its own stated terms, and 09 says exactly how. |
