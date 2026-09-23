# Substrate capability matrix

What seven storage backends **actually do**, measured by running operations against them
rather than by reading their documentation. The instrument is `tests/substrate_probe/`;
every cell below was produced by it on `spike/substrate-capability-probe` (FUN-25). The
two local columns were measured 2026-09-23 at `ecdcffd`; the two AWS columns were
**re-measured against the real service** 2026-09-23 at `4ee9731`, in account
`131160053496`, `us-east-1` — see *Provenance* below.

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
here is proposed for shipping, its fields need `measured (real service)` rows. No column
in the table below currently carries emulator evidence — the AWS columns did until they
were re-measured against the real service — but the level is kept, and kept defined,
because the emulator path is still reproducible and the next backend measured through one
inherits this rule.

**Which backends have real-service rows:** the JSON filesystem, local SQLite, AWS S3 and
AWS DynamoDB. **Cloudflare R2, Cloudflare D1, Turso/libSQL and Supabase Postgres do
not** — they have no measured rows at all.

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
| **evidence level, every cell** | `measured (real service)` | `measured (real service)` | `NOT MEASURED` | `measured (real service)` | `NOT MEASURED` | `measured (real service)` | `NOT MEASURED` | `NOT MEASURED` |
| `cross_aggregate_atomicity` | no · real | **yes** · real | NOT MEASURED | no · real | NOT MEASURED | **yes** · real | NOT MEASURED | NOT MEASURED |
| `fencing` | cross-process · real | cross-process · real | NOT MEASURED | cross-process · real | NOT MEASURED | cross-process · real | NOT MEASURED | NOT MEASURED |
| `multi_process` | yes · real | yes · real | NOT MEASURED | yes · real | NOT MEASURED | yes · real | NOT MEASURED | NOT MEASURED |
| `multi_machine` | no · real | no · real | NOT MEASURED | yes · real | NOT MEASURED | yes · real | NOT MEASURED | NOT MEASURED |
| `durable_outbox` | no · real | **yes** · real | NOT MEASURED | no · real | NOT MEASURED | **yes** · real | NOT MEASURED | NOT MEASURED |
| `versioned_migrations` | no · real | no · real | NOT MEASURED | no · real | NOT MEASURED | no · real | NOT MEASURED | NOT MEASURED |
| `interactive_transaction` | yes · real | yes · real | NOT MEASURED | no · real | NOT MEASURED | no · real | NOT MEASURED | NOT MEASURED |
| `remote` | no · real | no · real | NOT MEASURED | yes · real | NOT MEASURED | yes · real | NOT MEASURED | NOT MEASURED |
| `max_document_bytes` | unbounded¹ · real | unbounded¹ · real | NOT MEASURED | unbounded¹ · real | NOT MEASURED | **389 120** · real | NOT MEASURED | NOT MEASURED |
| `offline_capable` | yes · real | yes · real | NOT MEASURED | no · real | NOT MEASURED | no · real | NOT MEASURED | NOT MEASURED |

¹ **"unbounded" means "nothing refused what was attempted"**, not "there is no limit". The
sizes walked were 4 MiB for the two local backends and 8 MiB for S3. S3 documents a 5 GiB
single-PUT limit; it is not in the cell because it was not measured.

**Count:** 80 cells. **40 measured**, all of them `measured (real service)` — and
**40 `NOT MEASURED`**, every one of them with a reason below. No cell is
`measured (emulator)` any more; the twenty AWS cells were until 2026-09-23, and what
changed is recorded under *Provenance*.

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
set. R2 has no emulator, and the S3 column beside it is **not** a substitute — neither
before nor after the re-measurement. The emulator's answer was the emulator's; AWS S3's
answer is AWS S3's; and R2 speaks S3's API without thereby making S3's guarantees. This
is the column that leaves open question 1 open.

**Turso / libSQL** — `NOT MEASURED (no credentials)`. `TURSO_DATABASE_URL` and
`TURSO_AUTH_TOKEN` are unset, so nothing was asked of Turso; the reason quoted is what a run
emits with the client on the path and the account absent, which is the runner's configuration
(a bare host emits `client absent` beside `no credentials` for the same column). Everything
about the **client** is a decision rather than a blocker:

| | |
|---|---|
| Client the measurement path drives | `libsql-client` **0.3.1** — `create_client_sync` / `execute` / `batch` / `close` |
| Upstream status | **archived** — last release 0.3.1 (2024-05-03); the repository points at `tursodatabase/libsql-python` |
| Maintained path instead | `libsql` **0.1.11** — `sqlite3`-style, **no `batch()`**, so adopting it means rewriting `tier_c.py`'s measurement path |
| Declared by a first-party manifest | **no** — the root `pyproject.toml` and every `plugins/*/*/pyproject.toml` are silent; a test asserts it |
| How to run it when the account exists | `PROBE_TIER_C=1 ~/.config/fun25/run-probe.sh`, which adds both Tier C clients as an ephemeral `uv run --with libsql-client --with "psycopg[binary]"` overlay |

So the client half of this column's gap is **not** "not installable here"; it is "not declared
by the project, runnable through the operator's overlay". That is deliberate and was decided on
2026-09-23: declaring an archived client would commit the repository to it, and switching to the
maintained one would put an untested measurement path in charge of a measurement. **If the
archived client cannot hold a session against Turso Cloud, that is a client finding to report
rather than a reason to switch unilaterally.** What this column is still waiting on is the
account. See the refusal rule above for why a local libSQL file would not close it either.

**Supabase Postgres** — `NOT MEASURED (no credentials)`, quoted under the same configuration.
`SUPABASE_DB_URL` is unset, and that is the whole of what stands between this column and a
measurement: `psycopg` arrives through the same overlay and is likewise undeclared by every
first-party manifest, so the only thing left to buy is the database. This column was expected
to stay unmeasured and did.

## What was measured, and how

Every measured cell is an operation performed on the backend. The observations below are
what the probe recorded; none is a restatement of a docstring.

### The two backends that ship today

`JsonFileSubstrate` and the SQLite substrate plugin are measured `real` because for them
the real service **is** this host — no account, no endpoint, no container. They are the
only backends in this document that ship today, and the two rows that separate them are
the two the port exists to distinguish:

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

### AWS DynamoDB, against the real service

The reason DynamoDB is in this evaluation is `TransactWriteItems` — the one call among
these backends that writes two different keys as a unit. Its existence was established
first against an emulator; what the matrix rests on is the guarantee **under contention**,
measured against AWS itself:

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

### AWS S3, against the real service

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

It cannot be closed by inference, and the S3 column beside it now makes that easier to
get wrong rather than harder. Since 2026-09-23 that column is a real measurement of AWS
S3 — but it is a measurement of **S3**. R2 speaks S3's API, and that is a statement about
request shapes, not about what happens inside a different vendor's storage engine when
eight writers arrive at once. A borrowed answer here would be the most plausible mistake
this document could invite. **Anything built on R2 that assumes a compare-and-swap is
safe is assuming this, and this is not known.** Cost to close: one R2 bucket, free tier.

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

The two AWS columns need credentials. They are `measured (real service)` and were
produced by the runner described under *Provenance* below.

### Provenance of the two AWS columns

Measured **2026-09-23**, against the branch at `4ee9731`, by the operator's runner:

```console
$ ~/.config/fun25/run-probe.sh
5 passed, 2 skipped in 14.04s
```

The runner exports a least-privilege credential set and **unsets `AWS_ENDPOINT_URL`**, so
the run is stamped `measured (real service)` rather than emulator. The two skips are the
two by-design expectations: the "no emulator reachable" case and the R2 case.

| | |
|---|---|
| Account | `131160053496`, region `us-east-1` |
| S3 bucket | `fun25-substrate-probe-131160053496` — public access blocked, 7-day object lifecycle |
| DynamoDB table | `fun25-substrate-probe` — `pk` S HASH, `PAY_PER_REQUEST` |
| IAM | user `fun25-substrate-probe`, policy `Fun25SubstrateProbeAccess` — that bucket, that table, and `table/fun25-probe-*`; nothing else in the account is reachable |
| Command | `~/.config/fun25/run-probe.sh` (equivalently: export the credentials, unset `AWS_ENDPOINT_URL`, `uv run pytest -q tests/substrate_probe/s3.py tests/substrate_probe/dynamodb.py`) |

**What the emulator got right, and the one thing it could not tell you.** Before this run
both AWS columns were `measured (emulator)` against floci 2.1.0, and **all twenty values
were identical** — the contention results, the `ValidationException` at 430 080 bytes, the
389 120-byte item accepted below it, every boolean. That is a real endorsement of the
emulator for these ten questions, and it is worth recording because it was not knowable in
advance.

What changed is the evidence behind one row. A `HeadBucket` round trip took **5 ms**
against floci and **105 ms** against S3; `DescribeTable` took **8 ms** and **104 ms**. The
`remote` cell's answer (`yes`) was right either way, but its consequence — *a
read-modify-write loop pays this per step* — is a twenty-fold different number, and a
200-transition workflow is the difference between one second and twenty-one. **An emulator
cannot measure latency**, and no amount of agreement on the other nine rows would have
revealed that.

### Two things to know before re-running this

Both were found by the operator during the credential run. Neither is repaired here:
each is a trade-off with an operator-visible consequence rather than a defect, and
changing either would alter the code path the measurements above came from.

1. **`FUNCTUALIZE_PROBE_DDB_TABLE` is inert under pytest, and the transient table is a
   feature as much as an accident.** The root `tests/conftest.py::_isolate_home` fixture
   strips every `FUNCTUALIZE_*` variable, and `dynamodb.py::_table()` reads the variable
   at call time rather than at import — so each pytest run creates and deletes its own
   `fun25-probe-<hex>` table, and the declared `fun25-substrate-probe` table is used only
   by runs outside pytest. That is why the IAM policy also grants `CreateTable` /
   `DeleteTable` on `table/fun25-probe-*`. Honouring the declared table would be *safe*
   — every item is already keyed with a per-run `uuid4` prefix — but it would trade
   per-run table isolation and automatic cleanup (the module has no item-level cleanup
   path) for symmetry with S3 and a narrower policy. That is a decision with an IAM
   consequence, not a bug fix.
2. **S3 and DynamoDB resolve their target at different times, and the asymmetry is
   visible.** `s3.py` reads `FUNCTUALIZE_PROBE_S3_BUCKET` at *import*, before the
   stripping fixture runs, so the declared bucket **is** honoured under pytest.
   `dynamodb.py` resolves per call, so the fixture wins. If the declared table should be
   honoured too, the read has to move to import time the same way — that is the shape of
   the change, and it is out of scope for this document.

The **emulator path is still supported and still reproducible** — it is how the AWS
columns were first measured, and how anyone without an account can exercise the same code.
The endpoint must be named explicitly: the probe will not go looking for something on a
local port, because a probe that adopts whatever happens to hold a port is how a
measurement ends up describing the wrong service.

```bash
docker run -d --name floci -p 4566:4566 floci/floci:latest
AWS_ENDPOINT_URL=http://localhost:4566 uv run pytest -q tests/substrate_probe/dynamodb.py
AWS_ENDPOINT_URL=http://localhost:4566 uv run pytest -q tests/substrate_probe/s3.py
```

Anything measured that way is `measured (emulator)` and may not back a shipped field. The
probe stamps the level from the environment, so this is not a matter of remembering to
write it down.

The unmeasured columns need the variables declared in `.env.example`: `CLOUDFLARE_*` for
D1, `FUNCTUALIZE_PROBE_R2_*` for R2, `TURSO_*` for Turso and `SUPABASE_DB_URL` for
Supabase — the last two also needing a client that no first-party package currently
declares.

## What this does not say

- It does not say any backend is suitable. It says what each one did when asked.
- It does not upgrade an emulator result. The AWS columns are real-service rows because
  the probe was re-run against AWS, not because anyone decided the emulator had been
  close enough — and it *was* close enough, which is a fact about floci rather than a
  licence to skip the real run.
- It does not cover the substrate port itself. The probe measures backends **directly**,
  through each one's own client, because measuring through an adapter would measure the
  adapter. The single exception is the two shipping backends, where the substrate is the
  backend.
