# 05 — Cloudflare: D1, Durable Objects, R2, Workflows

## 0. First: there is no "Cloudflare D2"

It was asked about. It does not exist. A sweep of `developers.cloudflare.com`, the
Cloudflare blog and the product pages as of September 2026 finds no product, preview or
announcement under that name.

What exists in this space:

| Product | What it is |
|---|---|
| **D1** | managed SQLite, reachable over HTTP — §A |
| **R2** | S3-compatible object storage, zero egress fees — §C |
| **Durable Objects** | single-threaded keyed actors with attached SQLite storage — §B |
| **Workers KV** | eventually-consistent edge K/V (not evaluated: no CAS, wrong consistency) |
| **Workflows** | durable execution on Workers — §D |
| **Queues** | message queue (not evaluated: not a store) |
| **Hyperdrive** | a connection pooler in front of *your* external Postgres/MySQL. Not a Cloudflare database. Not evaluated. |

The two things "D2" most plausibly meant are **Durable Objects** and **R2**. Both are
covered below in full, so the question is answered either way.

---

## A. D1 — the best technical fit in this entire evaluation

### A.1 Why it is a serious candidate

Three properties, and each one matters:

1. **It is SQLite.** We already have a working SQLite substrate
   (`plugins/functualize-state-sqlite/src/functualize_state_sqlite/substrate.py`, 225
   lines). The schema and the SQL transfer directly.
2. **It is reachable from plain Python over HTTPS.** No Worker required. Cloudflare ships
   an official first-party Python SDK (`pip install cloudflare`):
   ```python
   client.d1.database.query(database_id=..., sql="SELECT ...", params=[...])
   ```
   ([Python SDK reference](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/raw/))
3. **Its `batch` is a real SQL transaction.** This is the headline:

   > "Batched statements are SQL transactions. If a statement in the sequence fails, then
   > an error is returned for that specific statement, and it **aborts or rolls back the
   > entire sequence**."
   > — [D1 Database docs](https://developers.cloudflare.com/d1/worker-api/d1-database/)

   **D1 can do the thing S3 cannot.** Defect B3 — no code path commits two documents
   together — is fixable on D1 and is not fixable on S3.

### A.2 Mapping `StoreSubstrate` onto D1

| Port method | D1 implementation | Works? |
|---|---|---|
| `read(key)` | `SELECT payload, revision FROM documents WHERE key = ?` | ✅ |
| `write(key, payload, expect=N)` | `UPDATE documents SET payload=?, revision=revision+1 WHERE key=? AND revision=?` → `False` when 0 rows changed | ✅ — identical to `substrate.py:135` today |
| `write(..., expect=None)` | `INSERT … ON CONFLICT DO UPDATE` | ✅ — identical to `substrate.py:128` |
| `lock(*keys)` | **no-op**; CAS carries the safety | ✅ (permitted by `protocols.py:842-845`) |
| `clear` / `delete` / `describe` | trivial SQL + a `d1://<database>` string | ✅ |
| *(new)* atomic multi-document commit | one `{"batch": [...]}` request | ✅ **and nothing else in this evaluation offers it** |

Unlike S3, `revision` can stay an integer — so D1 needs **no port change at all**.

### A.3 The constraint that shapes the design: no interactive transaction

D1 does not support `BEGIN` / `COMMIT` / `ROLLBACK` / `SAVEPOINT` held open across round
trips. The alpha migration guide literally instructs you to strip `BEGIN TRANSACTION` and
`COMMIT;` from imported SQL
([alpha-migration](https://developers.cloudflare.com/d1/platform/alpha-migration/)).

So **you cannot read, decide in Python, and then write, inside one transaction.**
Everything atomic must be expressible as a single `batch` payload sent in one request.

That is not a blocker — it is exactly why the port has `expect=`. The pattern is:

```
read  → decide in Python → send ONE batch whose every write carries `WHERE revision = ?`
                            → any row that moved makes its UPDATE affect 0 rows
                            → detect that, roll back, re-read, retry
```

which is optimistic concurrency control, which is what `write(expect=)` already is. **But
it does mean the `RuntimeTransaction` port in the existing design proposal
([`../runtime-persistence-engine-owned/05-the-design.md`](../runtime-persistence-engine-owned/05-the-design.md) §2.2)
cannot be a context manager that issues statements as you go** on a D1 backend — it has
to accumulate commands and flush once. Worth knowing before that port is frozen, and it
is an argument *for* the command-shaped writers that design already chose.

### A.4 Consistency: the Sessions API does not apply to us

D1 replicates reads across six regions asynchronously, and without the Sessions API "a
read replica may be arbitrarily out of date". The Sessions API fixes that with Lamport
bookmarks — but:

> "Sessions API is only available via the **D1 Worker Binding** and not yet available via
> the REST API."

Since a Python client can only use the REST API, **every query goes to the primary**. For
a CAS/lease workload that is the *simpler and safer* regime, not a downgrade — we get a
single-writer database with no replica lag to reason about. Worth stating explicitly so
nobody "improves" it later by adding replicas.

Relatedly: "each individual D1 database is inherently single-threaded, and processes
queries one at a time" ([FAQ](https://developers.cloudflare.com/d1/reference/faq/)) —
which caps write throughput and, for us, is a feature.

### A.5 Limits and cost

| Limit | Free | Paid |
|---|---|---|
| Max database size | 500 MB | 10 GB |
| Max SQL statement | 100 KB | 100 KB |
| Max row / string / BLOB | 2 MB | 2 MB |
| Max bound parameters per query | 100 | 100 |
| Max query duration | 30 s | 30 s |
| Time Travel restore window | 7 days | 30 days |

— [D1 limits](https://developers.cloudflare.com/d1/platform/limits/),
[Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/)

The **2 MB row cap** is the one to watch: our documents are whole JSON envelopes, and
`scopes` grows with every step record. The 500-record cap already in the design
([`../runtime-persistence-engine-owned/06-data-model.md`](../runtime-persistence-engine-owned/06-data-model.md) §retention)
exists partly for this reason; on D1 it becomes load-bearing. The real fix is one row per
step rather than one row per document — which is the schema the design already proposes.

**Cost** ([D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)): 25 billion
rows read and 50 million rows written per month included on the paid plan, then
$0.001/million read and $1.00/million written; storage $0.75/GB-month beyond 5 GB; **no
egress charge**. For our workload this is free in practice.

**Latency** is the cost. Cloudflare's own changelog quantifies an *improvement* of
"50-500 ms depending on request location and database location" after moving REST auth to
the edge — which tells you the prior baseline was worse than that. No absolute figure is
published. Expect one HTTPS round trip plus a possible internal hop to wherever the
primary lives.

### A.6 Offline

There is none. `wrangler dev` emulates D1 locally as a real SQLite file under
`.wrangler/state/v3/d1/…`, and a Python process could technically open that file — but it
exists only while a Node.js toolchain is running `workerd`, and Cloudflare documents it
nowhere as an integration point. For us it is not a story; a D1 plugin is online-only,
and ADR-015's offline guarantee means it can never be the default.

---

## B. Durable Objects — right idea, unreachable

Durable Objects are the closest thing in this evaluation to what a workflow scope *is*: a
named entity that is single-threaded, holds its own SQLite, and serialises everything
touching it.

> "Each Durable Object runs in exactly one location, in one single thread, at a time."
> — [Durable Objects: Easy, Fast, Correct](https://blog.cloudflare.com/durable-objects-easy-fast-correct-choose-three/)

Their **input gates** and **output gates** give transaction-like safety without explicit
locking, and writes auto-coalesce: "if you perform multiple `put()` or `delete()`
operations without `await`ing them … the operations are automatically grouped together and
stored atomically." The SQLite backend adds `ctx.storage.transactionSync()` and
point-in-time recovery to any moment in the past 30 days.

If you were designing our scope-lease mechanism from nothing on Cloudflare, one Durable
Object per scope would be the obvious answer, and it would be better than our lease.

**It is unreachable.**

> "Durable Objects do not receive requests directly from the Internet. Durable Objects
> receive requests from Workers or other Durable Objects."
> — [Get started](https://developers.cloudflare.com/durable-objects/get-started/)

Cloudflare's own Python SDK confirms it: the `durable_objects` resource exposes
`namespaces.list()` and `namespaces.objects.list()` — enumeration only. There is no way to
*call* an object.

Using Durable Objects therefore means **writing and deploying a JavaScript Worker as part
of Functualize**, versioning it alongside the Python package, and routing every store
operation through it. That is a second language and a second deployment artifact in a
project whose distribution story is one offline binary. It is not a substrate; it is a
service we would be operating.

Two further gaps: no fencing-token or generation primitive is documented (§B4 of the
research found none), and in-memory state does not survive eviction or hibernation —
"persist anything important to storage."

**Verdict: architecturally the best match in this document, and the least available.**

---

## C. R2 — S3's shape, with one unanswered question

R2 is S3-compatible object storage with **free egress** and materially different
per-operation pricing:

| | R2 | AWS S3 Standard |
|---|---|---|
| Storage | $0.015/GB-mo | $0.023/GB-mo |
| Class A (writes) | $4.50/million | $5.00/million |
| Class B (reads) | $0.36/million | $0.40/million |
| Egress | **$0** | charged |

— [R2 pricing](https://developers.cloudflare.com/r2/pricing/), [S3 pricing](https://aws.amazon.com/s3/pricing/)

Consistency is strong and explicitly documented: after a write "readers will immediately
see the latest object globally"; after a delete, reads "immediately return a 'does not
exist' error"
([R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/)).

Conditional writes are supported — and R2 is a *superset* of S3 here, accepting arrays of
ETags, weak ETags and the wildcard, where MinIO rejects the wildcard entirely
([S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)).

### The open question, and why it must not be glossed over

**Cloudflare does not document that a conditional `PutObject`'s precondition check and its
commit are atomic against concurrent writers.**

They document strong read-after-write consistency, which is a different statement. And for
`CopyObject` they explicitly *disclaim* the equivalent atomicity:

> "the time at which the source object is selected for copying, and the point in time when
> the destination object is committed to the bucket state are **not necessarily the
> same**."
> — [R2 API extensions](https://developers.cloudflare.com/r2/api/s3/extensions/)

A community thread asking precisely "are R2 conditional PutObject predicates atomic for
concurrent writers?" exists and its answer could not be retrieved.

Compare-and-swap that is not atomic is not compare-and-swap. **Until Cloudflare states
this in writing, R2 cannot be used for lease fencing.** It remains fine for content-
addressed immutable blobs, where no CAS is required.

Two further gaps relevant to us: bucket versioning is "completely unimplemented", and
object locking is unsupported — so ETag conditionals are the only concurrency lever there
is.

---

## D. Cloudflare Workflows — not addressable from Python

Durable execution on Workers: steps, retries, `step.sleep` up to **365 days**, pause for
external events, 100 MB–1 GB of persistent state per instance.

Feature-for-feature it is the closest thing here to our `FrontierWalk`, with the durable
timers we lack.

It is also **authored in JavaScript/TypeScript inside the Workers runtime**. No evidence
was found that step logic can be written in Python. Lifecycle control (trigger, pause,
resume, terminate) is described as available programmatically/via API, but the endpoint
schema was not verified.

So adopting Workflows means the same thing as adopting Durable Objects: our workflow logic
moves into JavaScript, deployed to Cloudflare. That is not an integration with
Functualize; it is a different product.

Completed-instance retention is 3 days free / 30 days paid, and billing for steps and
storage began 2026-08-10.

---

## E. The common verdict

| | As a backend store | Blocker |
|---|---|---|
| **D1** | **Yes — the best fit evaluated.** Real transactions via `batch`, reachable from Python, no port change needed | Online-only; 2 MB row cap; no interactive transaction |
| **Durable Objects** | No | Requires shipping and operating a JavaScript Worker |
| **R2** | Partially — fine for immutable blobs | Conditional-PUT atomicity is undocumented; no CAS guarantee, so no fencing |
| **Workflows** | N/A (level 3) | JavaScript-only authoring |
| **Workers KV** | No | Eventually consistent; no CAS |

**And the constraint that applies to all four:** none of them works offline. ADR-015 makes
the offline-complete binary the reason the binary exists. Every Cloudflare option is
therefore a plugin, chosen deliberately by an operator who has a network — never a
default, and never a replacement for the local substrate.

## Facts used, with sources

| Claim | Source |
|---|---|
| No product named D2 exists | swept `developers.cloudflare.com`, blog, product pages |
| D1 `batch` is a SQL transaction, rolls back as a unit | [D1 Database](https://developers.cloudflare.com/d1/worker-api/d1-database/) |
| No `BEGIN`/`COMMIT` | [alpha-migration](https://developers.cloudflare.com/d1/platform/alpha-migration/) |
| REST `/query` and `/raw`, bearer auth, params, batch | [D1 query API](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/query/) |
| Sessions API is Worker-binding-only | [read-replication](https://developers.cloudflare.com/d1/best-practices/read-replication/) |
| D1 limits (10 GB, 2 MB row, 100 params, 30 s) | [D1 limits](https://developers.cloudflare.com/d1/platform/limits/) |
| D1 pricing; Time Travel 7/30 days | [pricing](https://developers.cloudflare.com/d1/platform/pricing/), [time-travel](https://developers.cloudflare.com/d1/reference/time-travel/) |
| REST latency improved "50-500 ms" | [changelog](https://developers.cloudflare.com/changelog/2025-05-30-d1-rest-api-latency/) |
| DOs are single-threaded; input/output gates; write coalescing | [DO blog](https://blog.cloudflare.com/durable-objects-easy-fast-correct-choose-three/) |
| DOs unreachable from the internet directly | [get-started](https://developers.cloudflare.com/durable-objects/get-started/) |
| DO storage API, `transactionSync`, 30-day PITR, limits | [storage-api](https://developers.cloudflare.com/durable-objects/api/storage-api/), [limits](https://developers.cloudflare.com/durable-objects/platform/limits/) |
| Python SDK exposes DO namespaces only | [Python SDK](https://developers.cloudflare.com/api/python/resources/durable_objects/) |
| R2 strong consistency | [consistency](https://developers.cloudflare.com/r2/reference/consistency/) |
| R2 conditional headers supported; versioning/object-lock unimplemented | [S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/) |
| R2 `CopyObject` atomicity explicitly disclaimed | [extensions](https://developers.cloudflare.com/r2/api/s3/extensions/) |
| Workflows limits, retention, pricing start date | [limits](https://developers.cloudflare.com/workflows/reference/limits/), [pricing](https://developers.cloudflare.com/workflows/reference/pricing/) |
| `wrangler dev` stores D1 as a local SQLite file | [local-development](https://developers.cloudflare.com/d1/best-practices/local-development/) |

**Not established by the research:** whether R2's conditional `PutObject` is atomic under
concurrent writers (**the one that matters**); absolute D1 REST latency figures; a numeric
durability SLA for D1 or R2; any DO fencing-token primitive; whether Workflow steps can be
authored in Python; a GA/production-ready statement for Python Workers.
