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

**Which backends have real-service rows:** seven of the eight — the JSON filesystem, local
SQLite, AWS S3, Cloudflare R2, AWS DynamoDB, Turso/libSQL and Supabase Postgres.
**Cloudflare D1 does not**; it is the one column with no measured rows, and its reason is
stated rather than left blank.

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

Seven backends, plus Supabase Postgres as an eighth that was expected to stay unmeasured —
**it did not.** All eight columns carry measured cells except Cloudflare D1, which is the
one column this document still reports as unasked, with its reason.

| | filesystem | local SQLite | Cloudflare D1 | AWS S3 | Cloudflare R2 | AWS DynamoDB | Turso / libSQL | Supabase Postgres |
|---|---|---|---|---|---|---|---|---|
| **evidence level, every cell** | `measured (real service)` | `measured (real service)` | `NOT MEASURED` | `measured (real service)` | `measured (real service)` | `measured (real service)` | `measured (real service)` | `measured (real service)` |
| `cross_aggregate_atomicity` | no · real | **yes** · real | NOT MEASURED | no · real | no · real | **yes** · real | **yes** · real | **yes** · real |
| `fencing` | cross-process · real | cross-process · real | NOT MEASURED | cross-process · real | cross-process · real | cross-process · real | cross-process · real | cross-process · real |
| `multi_process` | yes · real | yes · real | NOT MEASURED | yes · real | yes · real | yes · real | yes · real | yes · real |
| `multi_machine` | no · real | no · real | NOT MEASURED | yes · real | yes · real | yes · real | yes · real | yes · real |
| `durable_outbox` | no · real | **yes** · real | NOT MEASURED | no · real | no · real | **yes** · real | **yes** · real | **yes** · real |
| `versioned_migrations` | no · real | no · real | NOT MEASURED | no · real | no · real | no · real | no · real | no · real |
| `interactive_transaction` | yes · real | yes · real | NOT MEASURED | no · real | no · real | no · real | **yes** · real | **yes** · real |
| `remote` | no · real | no · real | NOT MEASURED | yes · real | yes · real | yes · real | yes · real | yes · real |
| `max_document_bytes` | unbounded¹ · real | unbounded¹ · real | NOT MEASURED | unbounded¹ · real | unbounded¹ · real | **389 120** · real | unbounded¹ · real | unbounded¹ · real |
| `offline_capable` | yes · real | yes · real | NOT MEASURED | no · real | no · real | no · real | no · real | no · real |

¹ **"unbounded" means "nothing refused what was attempted"**, not "there is no limit". The
sizes walked were 4 MiB for the two local backends and 8 MiB for S3, R2, Turso and Supabase.
S3 documents a 5 GiB single-PUT limit; it is not in the cell because it was not measured.

**Count:** 80 cells. **70 measured**, all of them `measured (real service)` — and
**10 `NOT MEASURED`**, every one of them with its reason below. No cell is
`measured (emulator)` any more; the twenty AWS cells were until 2026-09-23, and what
changed is recorded under *Provenance*.

## Why the unmeasured column is unmeasured

Its reason is the text the probe itself emitted when it declined to run, transcribed
rather than composed. **One column remains**, and it is the `no credentials` cause rather
than the `client absent` one — the two are kept apart because they cost different things
to fix: a dependency decision versus a purchase. R2 and Supabase Postgres left this section
on 2026-09-23, when their credentials arrived; what each of them answered is under *What
was measured, and how*.

**Cloudflare D1** — `NOT MEASURED (no credentials)`. `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_D1_DATABASE_ID` and `CLOUDFLARE_API_TOKEN` are not set, so nothing was asked
of D1. The instrument is written and gated: `tests/substrate_probe/d1.py` reaches the REST
API over stdlib `urllib.request`, and it will record a latency distribution, walk the
documented 2 MB row cap and send `BEGIN` rather than cite it, the moment those three
variables exist. D1 has a free tier. *(The credentials have since been provisioned and D1
has been measured by hand; this column is re-stamped by a task of its own because the
`BEGIN` path needs repair first — see Q2.)*

**Turso / libSQL** has a cell in this section too, but not because it is unmeasured: its
**client** is the part a reader cannot recover from the file, so it is recorded here. See
*The client finding* below.

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

### Turso / libSQL, against the real service

Measured **2026-09-23** against a Turso Cloud database — org `viltohmyst`, group `default`,
region `aws-us-west-2`, database `fun25-substrate-probe` — from contabo (`vmi3464921`), with
the maintained client **`libsql` 0.1.11** and a database-scoped token:

```bash
set -a; . ~/.config/fun25/probe-tierc.env; set +a
uv run --with libsql --with "psycopg[binary]" pytest -q tests/substrate_probe/tier_c.py
# 5 passed, 1 skipped in 61.84s   (the skip is Supabase)
```

**One answer reversed, and it reversed because the client changed.** *Can a transaction stay
open across a Python decision?* now reads **yes** for Turso. The previous path drove
`libsql-client`,
which offered a `batch()` call and no transaction handle, so the code reasoned *the atomic
unit is one batched request, therefore nothing can be held open across a Python decision* —
the shape D1 genuinely has. That was an inference from a client's surface, not a measurement
of the service. The maintained client is `sqlite3`-shaped, and the probe now measures the
thing directly:

> `BEGIN` opened a unit (`in_transaction=True`), a read inside it returned `('0',)`, Python
> chose `'1'` from what it had read, the write was visible **inside the same unit** as
> `('1',)`, and a rollback restored `('0',)`.

*Can two keys be written so that either both land or neither does?* — and the outbox row that
follows from it — were re-derived the same way, from explicit transactions rather than from a
batch: two keys written in one unit with the second doomed by the primary key, and after the
rollback **the sibling row is gone (0 rows)**.

**The sharp edge, measured rather than assumed:** a failed statement does *not* roll the unit
back by itself. Commit anyway after the failure and the sibling survives — measured, 1 row.
The guarantee is real and it is the caller's to invoke, which is precisely the kind of thing a
port design has to know before it relies on it.

The lock's reach was measured as a compare-and-swap on a revision column: the stale `UPDATE`
matched **0** rows, the current one matched **1**. The two-process question used a real second
OS process, not a thread — it connected to the same URL, wrote through the same conditional,
and this process then read the value the child had committed. A `SELECT 1` round trip took
**615 ms** from this host to `aws-us-west-2`, which is the number a read-modify-write loop
pays per step and is six times S3's 105 ms from the same machine.

### The client finding, which is the durable half of this column

The probe previously imported **`libsql-client` 0.3.1** (last release 2024-05-03, upstream
archived). Against Turso Cloud it fails its Hrana WebSocket handshake —
`WSServerHandshakeError: 400, message='Invalid response status'` — **and then retries
forever**, so the column did not fail, it *hung*, and a `timeout` had to kill the run.

Two things a reader should take from that, both of which outlive the fix:

1. **It was a client finding and never a service finding.** The service answered and the
   credential authorised; only the abandoned client could not speak to them. Anyone reading
   that hang as "Turso is unreachable" would have drawn the opposite conclusion from the
   evidence — and a hang is exactly the failure that invites the wrong conclusion, because it
   produces no error to read.
2. **A probe run must terminate.** A measurement that never returns is worse than one that
   fails, because a failure is a result. Every remote call in `tier_c.py` is bounded and there
   is no retry loop anywhere in it.

Neither client is declared by any first-party manifest — a test reads the root
`pyproject.toml` and every `plugins/*/*/pyproject.toml` and asserts it. They arrive through
an ephemeral `uv run --with …` overlay, so the project does not depend on them. Note that the
operator's runner still overlays the *archived* client, so `PROBE_TIER_C=1
~/.config/fun25/run-probe.sh` will hang on this column until that one token is flipped; the
command above is the one that works today.

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

### Cloudflare R2, against the real service

The same module against a different endpoint, which is how the repo already reached the
emulator. This is the column that closes open question 1:

> Eight writers sent `PutObject` with `If-None-Match: *` for one absent key against
> Cloudflare R2. **1 won**, the rest were refused (`PreconditionFailed`), and the surviving
> object holds `writer-1` — the winner's own bytes.

Everything else follows the S3 column's shape, and was measured rather than borrowed from
it: the two-key answers are **no** — no operation in this API writes two keys as one unit,
so a state change and the record that it happened cannot commit together — and nothing can
be held open across a Python decision, because there is no begin/commit pair to hold. No
schema is carried either, so no version can be enforced: a JSON document and
`b'not json at all'` were both stored without complaint. The largest document attempted was
8 MiB and nothing refused it (unbounded¹); every operation crosses a socket (a `HeadBucket`
round trip took 197 ms); the store is addressed by an endpoint rather than by a path on this
disk; and with the network gone there is nothing left to read.

**R2's endpoint host is part of the answer, not a detail.** The one thing this column had
to prove for itself is that the entity answering is R2 and not something that speaks S3:
the endpoint is `…r2.cloudflarestorage.com`, the credential is scoped to one bucket, and
the run is the same code path that measured AWS S3 the same afternoon.

### Supabase Postgres, against the real service

The one path in the probe that had never executed before 2026-09-23 — it ran clean on its
first credentialed run, and every cell below is `measured (real service)`:

> A transaction was opened, a row inserted, the row read back inside it (visible), a Python
> decision taken, and the transaction rolled back — afterwards the table held no rows.

That single operation settles three cells at once, which is why it is quoted once and
referenced twice: yes, a transaction can be held open across a Python decision and the read
inside it was visible; yes, two keys can be committed as one unit; and yes, a state change
and the record that it happened go together — the rollback is what makes the atomicity a
measurement rather than a claim. A stale-revision `UPDATE` affected no rows, and the check
is the server's, so the fence is cross-process. Every operation crosses a socket — a
`SELECT 1` round trip took 121 ms on a session pooler — and the DSN is the address, so the
store is reachable from any process and any machine holding it. With the network gone there
is nothing to read, the largest document attempted was 8 MiB and nothing refused it
(unbounded¹), and no version can be enforced: Postgres has a schema, but nothing here
declares a *version* for it.

## Open questions

### Q1 — Is R2's conditional `PutObject` atomic under concurrent writers?

**Answered — yes, it is atomic.**

Measured **2026-09-23** against Cloudflare R2, bucket `fun25-substrate-probe`, endpoint
`85151233e9d4d06c5d388c37d2211bc2.r2.cloudflarestorage.com`: **eight writers sent
`PutObject` with `If-None-Match: *` for one absent key at once, and exactly one won.** The
other seven were refused (`PreconditionFailed`), and the surviving object holds the winner's
own body — `writer-1` in the run transcribed in *Provenance* below; **which** writer wins
varies between runs, the count does not. The precondition is evaluated by the service rather
than by a lock this process holds, so R2's conditional write is a real compare-and-swap: a
stale writer is refused by the service, not by anything this process holds.

It was closed by measurement rather than by S3's adjacency, which matters because the two
are easy to conflate: R2 speaks S3's API, and that is a statement about request shapes, not
about what a different vendor's engine does when writers collide. The S3 column beside it
was re-measured the same day and produced the same shape — one winner of eight — and that
agreement is a *finding about the two services*, not the evidence for either. **Anything
built on R2 that assumes a safe compare-and-swap is now assuming something measured.**

### Q2 — What is D1's absolute REST latency from a developer's machine?

**Unanswered, and still `NOT MEASURED` in the table above — but no longer for want of a
credential.** *(2026-09-23: `CLOUDFLARE_*` is provisioned and D1 has been asked by hand; the
column stays unasked because the probe's `BEGIN` request needs repair first, and the task
that repairs it also re-stamps this question. The reason text in the table is the module's
own and predates the credential.)*

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

The local columns and every `NOT MEASURED` reason need nothing at all:

```bash
uv run pytest -q tests/substrate_probe/
```

That must be green on a machine with no network, no Docker and no credentials — a
contributor with no cloud account sees skips, never failures.

**Five columns need credentials** — AWS S3, AWS DynamoDB, Cloudflare R2, Turso/libSQL and
Supabase Postgres, all `measured (real service)`. Cloudflare D1 is the one column with no
measured rows. Their provenance is below, together with the exact command each one was
produced by.

### Provenance of the two AWS columns

Measured **2026-09-23**, against the branch at `4ee9731`, by the operator's runner:

```console
$ ~/.config/fun25/run-probe.sh
5 passed, 2 skipped in 14.04s
```

The runner exports a least-privilege credential set and **unsets `AWS_ENDPOINT_URL`**, so
the run is stamped `measured (real service)` rather than emulator. The two skips are the
two by-design expectations: the "no emulator reachable" case and the R2 case — R2 no
longer skips, it has its own provenance below.

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

### Provenance of the R2 and Supabase columns

Both measured **2026-09-23**, against the branch at `dbaafb1`, in this worktree:

```console
$ for f in ~/.config/fun25/probe-aws.env ~/.config/fun25/probe-r2.env; do set -a; . "$f"; set +a; done
$ unset AWS_ENDPOINT_URL
$ uv run pytest -q tests/substrate_probe/s3.py
3 passed, 1 skipped in 14.62s

$ for f in ~/.config/fun25/*.env; do set -a; . "$f"; set +a; done
$ uv run --with libsql --with "psycopg[binary]" pytest -q tests/substrate_probe/tier_c.py
6 passed in 78.25s
```

`AWS_ENDPOINT_URL` is unset so the R2 cells are stamped `measured (real service)` rather
than emulator, and the two Tier C clients arrive through `uv run --with` rather than a
declaration (see *The client finding*). **Source the env files one file at a time**, as the
runner does: `set -a; . ~/.config/fun25/*.env; set +a` expands to several filenames and `.`
takes only the first, so the credentials never arrive and the run passes having measured
nothing.

| | Cloudflare R2 | Supabase Postgres |
|---|---|---|
| Endpoint / address | `85151233e9d4d06c5d388c37d2211bc2.r2.cloudflarestorage.com` (S3-compatible) | session-pooler DSN, project `functualize` |
| Resource | bucket `fun25-substrate-probe` | dedicated role `fun25_probe`, owning only its own schema — **not** the project's `postgres` role |
| Credential scope | token scoped to that one bucket, `Workers R2 Storage Bucket Item Write` (object read/write/list; no bucket admin); S3 keys derived as `access_key_id` = token id, secret = SHA-256 of its value | DSN for that role; IPv4 path via the pooler, since the direct host is IPv6-only on the free plan |
| Client | `boto3` 1.43.29 | `psycopg` 3.3.6 (through the overlay, undeclared by the project) |
| Command | the two lines above | the two lines above |

R2's ten cells came from the same code path that measured AWS S3, and the survivor in the
recorded race was `writer-1`. Supabase's path had never executed before this run: the cell
quoted under *Supabase Postgres, against the real service* is the whole of its atomicity
evidence, and it is a rollback rather than a claim.

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

Turso needs its credentials and the maintained client, neither of which the project
declares:

```bash
set -a; . ~/.config/fun25/probe-tierc.env; set +a
uv run --with libsql --with "psycopg[binary]" pytest -q tests/substrate_probe/tier_c.py
```

Use that rather than `PROBE_TIER_C=1 ~/.config/fun25/run-probe.sh`: the runner still
overlays the archived `libsql-client`, which hangs against Turso Cloud rather than failing.
A documented command that hangs is a trap, so the working one is written out here.

The one still-unmeasured column needs the variables declared in `.env.example`:
`CLOUDFLARE_*` for D1. R2's `FUNCTUALIZE_PROBE_R2_*`, Turso's `TURSO_*` and Supabase's
`SUPABASE_DB_URL` are likewise declared there and have since been provisioned; the two
Tier C clients still come through the overlay rather than a declaration.

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
