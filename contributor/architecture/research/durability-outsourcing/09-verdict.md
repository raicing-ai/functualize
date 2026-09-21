# 09 — Verdict, and what would change it

## 1. The five verdicts

| # | System | As a **backend store** | As a **durability provider** |
|---|---|---|---|
| 1 | **Restate** | **No** — not a document store; 1-day default retention; no cross-key transaction | **No** — replaces an engine we have, requires `async` across the public API, inverts control, BUSL server, coarser version fence |
| 2 | **DBOS** | **No** — event/message tables are workflow-keyed and GC'd with the workflow | **No**, but on the strongest grounds of any candidate. Blocked by 6 new dependencies, no plugin seam, `pickle`, a coarser version fence, and a SQLite/Postgres split that cancels the benefit |
| 3 | **Cloudflare D1** | **Yes — the best technical fit evaluated.** Reachable from Python, atomic `batch`, needs no port change | n/a (level 1/2) |
| 4 | **"Cloudflare D2"** | **Does not exist.** The plausible intents are Durable Objects (unreachable without shipping a JavaScript Worker) and R2 (blocked: conditional-PUT atomicity undocumented) | n/a |
| 5 | **AWS S3** | **Yes, technically** — 5 of 6 port methods map unchanged; real CAS since 2024 | Level 1 and most of level 2. **Cannot** fix defect B3: no multi-key atomicity, stated by AWS |

## 2. The recommendation

**Do not outsource durability. Do fix level 2 on the substrates we already have. Then, if
and only if someone actually needs a network store, build D1.**

In order:

### Step 1 — repair, on what we have (do this regardless)

The four defects in
[`../runtime-persistence-engine-owned/03-the-four-defects.md`](../runtime-persistence-engine-owned/03-the-four-defects.md),
all of them level 2, all reproducible:

- **B1** — `scope-state/<id>` has no fence at all
  (`grep -c generation src/functualize/_primitives/scope_state_store.py` → **0**)
- **B2** — the one fenced write calls `substrate.write()` without `expect=`
  (`scope_store.py:250-266`)
- **B3** — no code path commits two documents together
- **B4** — two processes can hold the same generation

A remote substrate built on top of these inherits every one of them and adds 50 ms to each
occurrence.

### Step 2 — make the two port repairs this research found

Both are small, both are needed whether or not a remote backend is ever built
(`07-the-design.md` §6):

1. `Stored.revision: int` → opaque. Its own docstring already says "do not order it or do
   arithmetic on it. A filesystem derives one from the bytes, **a remote store from its own
   row version**" (`src/functualize/_types/protocols.py:748-752`). An S3 ETag is a string.
   Without this, S3 cannot be implemented at all.
2. Add `interactive_transaction`, `remote`, `max_document_bytes` and `offline_capable` to
   `StoreProfile`, with a boot-time `require()`. Without `offline_capable`, ADR-015's
   guarantee is enforced by nothing except the fact that nobody has written a remote
   substrate yet.

### Step 3 — record the decision

An ADR, one page, saying: *storage is pluggable, execution is not.* With the reasoning from
`07-the-design.md` §2 and a citation to DBOS's single-transaction checkpoint as
independent evidence for the `RuntimeTransaction` shape.

This matters because the proposal will come back. "Why don't we just use Temporal / DBOS /
Restate?" is a reasonable question that deserves a written answer rather than a
re-derivation. ADR-022 exists for exactly this reason — it says so in its own opening: *"It
is a reasonable-looking design and it is re-proposed easily, so this records why it is
retired rather than deferred."*

### Step 4 — only then, and only on demand: `functualize-store-d1`

Not S3, not R2. D1, because:

- it is the only candidate offering **atomic multi-document commit**, via `batch`
  ([D1 Database docs](https://developers.cloudflare.com/d1/worker-api/d1-database/));
- it is SQLite, so
  `plugins/functualize-state-sqlite/src/functualize_state_sqlite/substrate.py` (225 lines)
  is most of the work already written;
- it needs **no port change** — `revision` stays an integer;
- it is reachable from plain Python via a first-party SDK, with no Worker in the middle.

Declared profile: `cross_aggregate_atomicity=True`, `fencing="cross-process"`,
`multi_machine=True`, `interactive_transaction=False`, `remote=True`,
`max_document_bytes=2_000_000`, `offline_capable=False`.

### What not to do

- **Do not build an S3 substrate first.** It is the more famous option and the weaker one:
  it cannot fix B3, and it needs the revision-type change before it can exist.
- **Do not build R2** until Cloudflare states in writing that a conditional `PutObject`'s
  precondition check and commit are atomic against concurrent writers. They document
  strong read-after-write consistency, which is a different claim, and they explicitly
  *disclaim* the equivalent atomicity for `CopyObject`
  ([R2 extensions](https://developers.cloudflare.com/r2/api/s3/extensions/)).
  Compare-and-swap that is not atomic is not compare-and-swap.
- **Do not add a `DurableExecutionProvider` port** "so we can support Restate later." That
  is the ADR-022 mistake one layer up (`07-the-design.md` §2).

## 3. What would change this verdict

State the falsifiers, so this is an argument rather than a position.

| If this became true | The verdict that changes |
|---|---|
| **Users need workflows that resume on a different machine than they parked on** | D1 moves from step 4 to step 1. It is the only evaluated option with both cross-machine reach and multi-document atomicity. |
| **Users need durable timers** — "retry this in 6 hours" surviving a reboot, with nobody running | This is our single largest real gap (`02` §4) and neither a substrate nor a `StoreProfile` field fixes it. It needs a scheduler. DBOS's queue-plus-recovery-thread model becomes worth a serious second look. |
| **Functualize gains a long-running server deployment as a first-class surface** | The offline constraint stops binding for that surface, `async` stops being disqualifying, and Restate's economics change completely. |
| **Cloudflare documents R2's conditional-PUT atomicity** | R2 becomes viable — cheaper per operation than S3, free egress — for the *blob* half of a store, though still without multi-key atomicity. |
| **DBOS ships a stable 3.x with a lighter dependency tree and JSON-first serialisation** | The dependency and `pickle` objections in `04` §3.1 and §3.4 weaken. The missing plugin seam and the coarse version fence do not. |
| **We discover a cross-machine fencing bug our lease cannot express** | Restate's epoch-fenced partition leadership is genuinely stronger than a generation number in a document. Worth revisiting on the merits. |

## 4. Open questions this research could not settle

Listed because an unanswered question stated is worth more than a confident guess.

1. **Is R2's conditional `PutObject` atomic under concurrent writers?** The single most
   important unknown. A community thread asking exactly this returned 403 and no staff
   answer was retrievable. Resolvable by asking Cloudflare, or by a contention test.
2. **What is D1's REST latency in absolute terms** from a developer laptop? Only a relative
   "50-500 ms improvement" is published. Resolvable in an afternoon with a script.
3. **Does anything actually depend on `Stored.revision` being an `int`?** Cheap to settle:
   `grep -rn '\.revision' src/functualize plugins --include=*.py`.
4. **Can Cloudflare Workflows be driven from Python** for lifecycle operations (trigger /
   pause / resume / terminate)? Claimed as "programmatic/via API"; the endpoint schema was
   not verified. Only matters if the deployment-target idea in `03` §5 is ever pursued.
5. **What is DBOS's minimum supported Postgres version?** Undocumented. Only matters if
   the verdict on DBOS is ever revisited.

## 5. The one-sentence version

> Functualize already has a durable-execution engine; its defects are all one level below
> that, in transactional integrity; so the useful move is to fix level 2 and make the
> guarantee a declared, tested field — after which adding Cloudflare D1 is a 400-line
> plugin, and adopting Restate or DBOS is still a 3,716-line replacement that leaves the
> document store exactly where it was.
