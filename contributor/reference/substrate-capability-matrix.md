# Substrate capability matrix

What seven storage backends **actually do**, measured by running operations against them
rather than by reading their documentation. The instrument is `tests/substrate_probe/`;
every cell below was produced by it on `spike/substrate-capability-probe` at `ecdcffd`,
2026-09-23 (FUN-25).

This exists because the alternative already failed once. `Stored.revision` was an `int`
for the whole life of the filesystem substrate — correct for a counter, wrong for
anything whose revision is an opaque string, and invisible until a remote backend is
attempted. It was found by reading S3's documentation and repaired in FUN-24. The
question this document answers is *what else is like that*, and the only way to find out
is to ask the backends.

**Nothing here is a vendor claim.** Where a vendor number exists and was not measured, the
cell says so rather than quoting it. A documented limit in a measured cell would make this
document exactly the thing it replaces.

## How to read a cell

Ten rows are the fields of the `StoreProfile` a future substrate port would have to
publish (`contributor/architecture/research/durability-outsourcing/07-the-design.md`
§3 — twelve attributes, minus the two that are labels). Each column is one backend.

Every cell carries an evidence level, and the level is uniform down each column — the
first row of the table states it in full, and each cell repeats it in short form:

| short | evidence level | means |
|---|---|---|
| `real` | `measured (real service)` | the operation ran against the actual service |
| `emu` | `measured (emulator)` | it ran against an emulator standing in for the service |
| `fake` | `measured (fake)` | it ran against an instrument that models a vendor constraint |
| — | `NOT MEASURED` | nobody asked; the reason is stated under the table |

**An emulator row may never back a shipped field.** `measured (emulator)` says a
stand-in behaved a certain way, which is evidence about the stand-in. Before any backend
here is proposed for shipping, its fields need `measured (real service)` rows.

**The three instruments are not columns.** `BatchOnlySqliteDriver`, `FakeObjectStore` and
`FakeItemStore` (`tests/substrate_probe/fakes.py`) model vendor constraints — a driver
with no `BEGIN`, a store with no atomicity across keys, a store with transactions — so
that code paths depending on those constraints can be exercised with no network. They
populate the `measured (fake)` level; they are never a backend's answer, and none of them
appears as a column below.

### The refusal rule: there is no fifth kind of measurement

Four levels, and a run that fits none of them is refused rather than filed under the
closest one. The case this rule was written for is real and cheap to hit: **an embedded
libSQL database file is not Turso.** The engine is genuinely libSQL, so `measured (fake)`
is wrong; nothing is emulating anything, so `measured (emulator)` is wrong; and the Turso
*service* — the network, its transaction semantics, its latency — was never reached, so
`measured (real service)` is wrong and would be the most damaging of the three.
`tests/substrate_probe/tier_c.py` therefore refuses to run at all without both a client
and an account, and a test asserts no route through it reaches a measured cell otherwise.
The same reasoning bars stdlib `sqlite3` from standing in for libSQL: that is the local
SQLite column, and it is already measured.

## The matrix

Seven backends, plus Supabase Postgres as an eighth that was expected to stay unmeasured
and did.

| | filesystem | local SQLite | Cloudflare D1 | AWS S3 | Cloudflare R2 | AWS DynamoDB | Turso / libSQL | Supabase Postgres |
|---|---|---|---|---|---|---|---|---|
| **evidence level, every cell** | `measured (real service)` | `measured (real service)` | `NOT MEASURED` | `measured (emulator)` | `NOT MEASURED` | `measured (emulator)` | `NOT MEASURED` | `NOT MEASURED` |
| `cross_aggregate_atomicity` | no · real | **yes** · real | NOT MEASURED | no · emu | NOT MEASURED | **yes** · emu | NOT MEASURED | NOT MEASURED |
| `fencing` | cross-process · real | cross-process · real | NOT MEASURED | cross-process · emu | NOT MEASURED | cross-process · emu | NOT MEASURED | NOT MEASURED |
| `multi_process` | yes · real | yes · real | NOT MEASURED | yes · emu | NOT MEASURED | yes · emu | NOT MEASURED | NOT MEASURED |
| `multi_machine` | no · real | no · real | NOT MEASURED | yes · emu | NOT MEASURED | yes · emu | NOT MEASURED | NOT MEASURED |
| `durable_outbox` | no · real | **yes** · real | NOT MEASURED | no · emu | NOT MEASURED | **yes** · emu | NOT MEASURED | NOT MEASURED |
| `versioned_migrations` | no · real | no · real | NOT MEASURED | no · emu | NOT MEASURED | no · emu | NOT MEASURED | NOT MEASURED |
| `interactive_transaction` | yes · real | yes · real | NOT MEASURED | no · emu | NOT MEASURED | no · emu | NOT MEASURED | NOT MEASURED |
| `remote` | no · real | no · real | NOT MEASURED | yes · emu | NOT MEASURED | yes · emu | NOT MEASURED | NOT MEASURED |
| `max_document_bytes` | unbounded¹ · real | unbounded¹ · real | NOT MEASURED | unbounded¹ · emu | NOT MEASURED | **389 120** · emu | NOT MEASURED | NOT MEASURED |
| `offline_capable` | yes · real | yes · real | NOT MEASURED | no · emu | NOT MEASURED | no · emu | NOT MEASURED | NOT MEASURED |

¹ **"unbounded" means "nothing refused what was attempted"**, not "there is no limit". The
sizes walked were 4 MiB for the two local backends and 8 MiB for S3. S3 documents a 5 GiB
single-PUT limit; it is not in the cell because it was not measured.

**Count:** 80 cells. **40 measured** — 20 `measured (real service)`, 20
`measured (emulator)` — and **40 `NOT MEASURED`**, every one of them with a reason below.

## Why each unmeasured column is unmeasured

Each reason is the text the probe itself emitted when it declined to run, transcribed
rather than composed. Two distinct causes appear, and they are kept apart because they
cost different things to fix: an absent *client* is a dependency decision, an absent
*account* is a purchase.

**Cloudflare D1** — `NOT MEASURED (no credentials)`. `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_D1_DATABASE_ID` and `CLOUDFLARE_API_TOKEN` are not set, so nothing was asked
of D1. The instrument is written and gated: `tests/substrate_probe/d1.py` reaches the REST
API over stdlib `urllib.request`, and it will record a latency distribution, walk the
documented 2 MB row cap and send `BEGIN` rather than cite it, the moment those three
variables exist. D1 has a free tier.

**Cloudflare R2** — `NOT MEASURED (no R2 credentials)`. `FUNCTUALIZE_PROBE_R2_ENDPOINT`,
`FUNCTUALIZE_PROBE_R2_ACCESS_KEY_ID` and `FUNCTUALIZE_PROBE_R2_SECRET_ACCESS_KEY` are not
set. R2 has no emulator, and the S3 column beside it is **not** a substitute: floci's
answer is floci's, and R2 speaks S3's API without thereby making S3's guarantees. This is
the column that leaves open question 1 open.

**Turso / libSQL** — `NOT MEASURED (client absent, no credentials)`. Both causes apply:
`import libsql_client` fails and no first-party package declares it, so installing it is a
dependency decision rather than a probe run; and `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN`
are unset. See the refusal rule above for why a local libSQL file would not close this.

**Supabase Postgres** — `NOT MEASURED (client absent, no credentials)`, the same pair:
`import psycopg` fails and is undeclared, and `SUPABASE_DB_URL` is unset. This column was
expected to stay unmeasured and did.

## What was measured, and how

Every measured cell is an operation performed on the backend. The observations below are
what the probe recorded; none is a restatement of a docstring.

### The two backends that ship today

`JsonFileSubstrate` and the SQLite substrate plugin are measured `real` because for them
the real service **is** this host — no account, no endpoint, no container. They are the
only backends in this document whose fields are currently eligible to back a shipping
decision, and the two rows that separate them are the two the port exists to distinguish:

- **Can two keys be written so that either both land or neither does?** A state write and
  its outbox row were sent as one unit with the second doomed by a payload JSON cannot
  carry. On the filesystem *"afterwards the state row is still there, so nothing rolled it
  back"*; on SQLite *"afterwards the state row is absent, so the unit rolled back"*.
- **How far does a lock reach?** A genuine second OS process was started. It waited
  **0.508 s** for the lock, then read the value this process had committed (`2`), wrote
  `3` carrying the revision it had just read — which landed — and had a second write
  carrying the *pre-write* revision refused. That is one measurement answering the lock's
  reach, the two-process question and the absence of a lost update.
- **Can a transaction stay open across a Python decision?** A read, a decision in Python
  and a write inside one unit, with the stored document carrying the decision — *"the
  shape D1 cannot express, and this backend can"*.
- **How large a document is accepted?** 4 MiB written and read back intact, nothing
  refused. The walk stopped at the first accepted size, not at a limit — hence
  "unbounded" as defined above.
- **Does it cross a network?** The round trip was performed with every socket refused, so
  the answer is a property of the run rather than an inference. That is also why these two
  backends satisfy the no-network, no-Docker, no-credentials requirement by construction.

### AWS DynamoDB, against the floci emulator

The reason DynamoDB is in this evaluation is `TransactWriteItems` — the one call among
these backends that writes two different keys as a unit. Its existence was established
first (the emulator implements it and cancels atomically); what the matrix rests on is the
guarantee **under contention**:

> Eight writers, each with its own client, raced one conditional key while carrying a
> sibling write in the same `TransactWriteItems`. **1 committed**, the rest were refused
> with `TransactionCanceledException`, and **0 losers left a sibling behind.**

A backend holding the call but not the guarantee would show up as several winners, or as
one winner and several orphans; a probe that raced a single key would see neither. That
one run is the evidence behind three cells.

The document size cell is a measurement, not the documented 400 KB: *"an item carrying
430 080 bytes was refused (`ValidationException`); 389 120 bytes was accepted immediately
before it, so the limit lies between them."*

Whether a transaction can be held open is read off the service's own API model rather than
a page: the client offers `ExecuteTransaction`, `TransactGetItems` and `TransactWriteItems`
and **no begin/commit pair**, so a transaction is one request carrying every item and
there is no handle to hold across a Python decision.

### AWS S3, against the floci emulator

The same race, asked of a conditional `PutObject` — and it is the same question open
question 1 asks of R2:

> Eight writers sent `PutObject` with `If-None-Match: *` for one absent key. **1 won**,
> the other seven were refused with `PreconditionFailed`, and the surviving object holds
> that writer's bytes.

Two winners would be a lost update in a system that believes it cannot have one, which is
precisely what a compare-and-swap built on this precondition would be trusting.

The multi-key answer is read off the API surface: *"of the 111 operations this API offers,
none writes two keys as one unit; the bulk call it does have, `DeleteObjects`, reports
per-key results, which is the opposite of all-or-nothing."* The outbox row follows from
that and is recorded as following from it rather than asserted twice — with no two-key
unit, a state change and the record that it happened cannot commit together.

## Open questions

### Q1 — Is R2's conditional `PutObject` atomic under concurrent writers?

**Unanswered. `NOT MEASURED (no R2 credentials)`.**

This is the largest open unknown the research identified, and it is unanswered for one
reason: nobody has an R2 bucket. The instrument exists, is proven, and runs against R2's
S3-compatible endpoint the moment `FUNCTUALIZE_PROBE_R2_*` is set — the S3 column above
was produced by the same code path.

It cannot be closed by inference. R2 speaks S3's API; that is a statement about request
shapes, not about what happens when eight writers arrive at once. The S3 result beside it
was measured against an emulator, so it is not even S3's own answer. **Anything built on
R2 that assumes a compare-and-swap is safe is assuming this, and this is not known.**
Cost to close: one R2 bucket, free tier.

### Q2 — What is D1's absolute REST latency from a developer's machine?

**Unanswered. `NOT MEASURED (no credentials)`.**

The research recorded a vendor changelog figure of "50–500 ms". That range is wide enough
to change the design — at the top of it, a 200-transition workflow that reads and writes
in a loop spends over a minute in transport — which is exactly why it needed measuring
rather than quoting. `tests/substrate_probe/d1.py` takes 25 timed round trips and reports
`n / min / median / p95 / max`, deliberately over stdlib `urllib.request` so that no client
library's pooling or retries sit inside the number. Cost to close: one D1 database, free
tier.

### Q3 — Does anything depend on `Stored.revision` being an `int`?

**Answered, and retired before the probe ran.** Transcribed from FUN-25's specification:

> - Before `7ba663c`: `revision: int` (`git show 7ba663c~1:…/protocols.py`, line 784).
> - Now: `Revision = NewType("Revision", str)` (`_types/protocols.py:764`).
> - Arithmetic/ordering census over `src/`, `plugins/`, `tests/`: the **only** two hits are
>   SQL text against the sqlite plugin's own `revision INTEGER` column, stringified at the
>   Python boundary (`…/functualize_substrate_sqlite/substrate.py:112`).
>
> **Nothing in Python orders a revision or does arithmetic on one.**

FUN-24 landed the repair, so this was answered at planning time by running the falsifier
rather than by probing. What the probe added instead is a regression guard
(`tests/primitives/test_substrate.py::test_a_revision_is_an_opaque_token` and its census
companion), so the property cannot silently un-land when the first remote substrate
arrives.

## Reproducing this

The two `real` columns and every `NOT MEASURED` reason need nothing at all:

```bash
uv run pytest -q tests/substrate_probe/
```

That must be green on a machine with no network, no Docker and no credentials — a
contributor with no cloud account sees skips, never failures.

The two `emu` columns need an emulator, and the endpoint must be named explicitly. The
probe will not go looking for something on a local port: a probe that adopts whatever
happens to hold a port is how a measurement ends up describing the wrong service.

```bash
docker run -d --name floci -p 4566:4566 floci/floci:latest
AWS_ENDPOINT_URL=http://localhost:4566 uv run pytest -q tests/substrate_probe/dynamodb.py
AWS_ENDPOINT_URL=http://localhost:4566 uv run pytest -q tests/substrate_probe/s3.py
```

The unmeasured columns need the variables declared in `.env.example`: `CLOUDFLARE_*` for
D1, `FUNCTUALIZE_PROBE_R2_*` for R2, `TURSO_*` for Turso and `SUPABASE_DB_URL` for
Supabase — the last two also needing a client that no first-party package currently
declares.

## What this does not say

- It does not say any backend is suitable. It says what each one did when asked.
- It does not upgrade an emulator result. Two of the four measured columns are emulator
  evidence, and the port decision that follows this needs real-service rows for whatever
  it proposes to ship.
- It does not cover the substrate port itself. The probe measures backends **directly**,
  through each one's own client, because measuring through an adapter would measure the
  adapter. The single exception is the two shipping backends, where the substrate is the
  backend.
