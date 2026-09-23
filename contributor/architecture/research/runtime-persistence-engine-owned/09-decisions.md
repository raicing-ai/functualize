# 09 — Decisions, rejections, and open questions

A reviewer should be able to attack this design from this page alone.

---

## 1. Decision register

| ID | Decision | Status | Where argued |
|---|---|---|---|
| D-1 | Repair B1–B4 before any migration reads legacy data | **needs maintainer sign-off** | [03](03-the-four-defects.md) |
| D-2 | The engine keeps ownership of transition meaning; stores own durability | **decided** — [ADR-025](../../../adr/025-engine-owns-transition-meaning.md) | [04](04-three-designs-compared.md) §4, [05](05-the-design.md) §3 |
| D-3 | No new peer layer; ports in `_types`, recorders in `_engine`, wiring in `_app` | **decided** — [ADR-026](../../../adr/026-persistence-ports-need-no-new-layer.md) | [05](05-the-design.md) §1 |
| D-4 | Move engine construction to after config resolution; pass the store as a constructor argument | **decided** — [ADR-027](../../../adr/027-engine-construction-moves-after-config.md) | [05](05-the-design.md) §4 |
| D-5 | Capability is a typed `StoreProfile`, checked at boot; unmet capability refuses | safe to proceed | [05](05-the-design.md) §2.1 |
| D-6 | `Attempt` is a first-class aggregate, distinct from `Run` | **still needs an ADR** — not covered by the 2026-09-23 approval; see §1.1 below | [06](06-data-model.md) §1.1 |
| D-7 | State machines are specified and enforced before the physical schema | safe to proceed | [06](06-data-model.md) §1 |
| D-8 | Outbox delivery is at-least-once with consumer dedup. No at-most-once claim | safe to proceed | §3 below |
| D-9 | `StoreSubstrate` survives for `fresh` and `shell-history`, and becomes public | **still open** — public-API decision, deferred out of FUN-17; see §1.1 below | [05](05-the-design.md) §6 |
| D-10 | The 500-record cap becomes an explicit retention policy, not a write-time eviction | safe to proceed | [06](06-data-model.md) §6 |
| D-11 | Offline import last, and it rejects illegal records | safe to proceed | [08](08-delivery-and-tests.md) |
| D-12 | No network SQL provider until FUN-22 names a database | safe to proceed | §4 below |
| D-13 | Storage is pluggable; execution is not. No port for a durable-execution provider | **decided** — [ADR-028](../../../adr/028-storage-is-pluggable-execution-is-not.md) | §3 below, [`../durability-outsourcing/07-the-design.md`](../durability-outsourcing/07-the-design.md) §2 |
| D-14 | `RuntimeTransaction` buffers commands and commits once, rather than streaming statements | safe to proceed | [05](05-the-design.md) §2.2 |
| D-15 | `Stored.revision` becomes an opaque token, not an `int` | safe to proceed | [02](02-what-exists-today.md) §9 |

### 1.1 ADR status — reconciled 2026-09-23

**Four ADRs landed, and they are not the four this section originally predicted.**

The earlier gloss read: *"D-2 and D-3 belong together (ownership and placement are one
question). D-4, D-6 and D-9 are separable."* That counts `D-2+D-3`, `D-4`, `D-6`, `D-9`.
The maintainer's approval on 2026-09-23 named **four ADRs as drawn in
`.spec/features/runtime-persistence-ports/plan.md`**, and that table lists **D-2, D-3,
D-4 and D-13**. The set actually written follows the approval:

| ADR | Decision | Note |
|---|---|---|
| [ADR-025](../../../adr/025-engine-owns-transition-meaning.md) | D-2 | ownership |
| [ADR-026](../../../adr/026-persistence-ports-need-no-new-layer.md) | D-3 | placement — **split out**, not merged with D-2 |
| [ADR-027](../../../adr/027-engine-construction-moves-after-config.md) | D-4 | boot behaviour |
| [ADR-028](../../../adr/028-storage-is-pluggable-execution-is-not.md) | D-13 | **newly ADR'd**; was "the same ADR as D-2" |

D-3 got its own file rather than sharing D-2's: ownership and placement turned out to
be separable arguments with different reopening conditions, and merging them would have
produced one ADR that two later proposals would both have to contradict. D-13 likewise
carries an argument (why no durable-execution port) that stands on its own and is the
most re-proposable idea in the area.

**Two decisions this approval does NOT cover, recorded here so the register does not
disagree with the plan:**

- **D-6 — `Attempt` as a first-class aggregate.** Still needs an ADR. It changes what
  `func builtin history` and the MCP history tools show a user when a run failed twice,
  so it is a public-output decision and it was not put to the maintainer on 2026-09-23.
  It does not block FUN-17: the `Attempt` type is defined as vocabulary in this wave and
  nothing renders it yet.
- **D-9 — `StoreSubstrate` becomes public.** Still open, and **deliberately not
  implemented in FUN-17** (`.spec/features/runtime-persistence-ports/contracts.md` §4,
  cleared on merge). Shipping the export as a side effect of a ports ticket would settle
  a public-API question by accident. The consequence survives and is known:
  `docs/guides/workflows.md` still instructs plugin authors to import
  `functualize._types.protocols.StoreSubstrate`, a private path.

**D-1** (repair B1–B4 first) is unchanged here and was satisfied out of band by the
repair that landed on master before this branch was rebased onto it.

---

## 2. What this design takes from the other two

Stated again here because a design that presents borrowed ideas as its own is hard to
review honestly.

**From Design 1** (`../runtime-persistence/`): capability as a first-class record; the
normalization rule and its bad-JSON-fields list; the transaction catalogue's shape;
the outbox pattern; workspace/artifact separation; the offline cutover with backup and
verification; the rejected-alternatives reasoning, most of which is reproduced in §3
because it is correct.

**From Design 2** (`.spec/scrutiny-reports/runtime-persistence-non-c4-review.md` §11
and Confluence 6258689): commands over CRUD; engine-owned transitions; no new peer
layer; `Attempt` as a separate aggregate; at-least-once only; the concrete SQLite
policy list.

**Original here:** the repair wave and its four reproductions; the construction-order
move; the typed profile replacing the uniform contract; the public-port export and the
public-store decision; the ring-cap accounting; the correction of Design 2's
"engine is complete at construction" argument.

---

## 3. Rejected alternatives

### Widen `StoreSubstrate` with query methods

**Rejected**, and this is not a new argument — it is
[ADR-022](../../../adr/022-storage-is-a-substrate-not-a-key-value-domain.md)'s, which
retired `StateBackend`/`ExecutionStore` for exactly this. Every domain query would
widen every backend, and callers would rediscover capabilities by `hasattr`. The ADR
records what that looked like in `functualize-mcp`: a four-branch probe where "which
of those four branches a given install took was not knowable".

### A `RuntimePersistenceProvider` family now (Design 1)

**Deferred, not rejected.** The objection is timing, not shape. The provider would own
lifecycle, writes, queries, migrations, admin, close and a repository family, and the
only backend at ship time is SQLite. Building a two-implementation abstraction against
one implementation is what ADR-022 warns about. Design 3's ports are a strict subset,
so widening later is additive.

### A bind-once `RuntimePersistenceHandle`

**Rejected in favour of moving construction.** The handle is a reasonable answer to a
real problem — the engine genuinely is built before its storage can exist
([`02-what-exists-today.md`](02-what-exists-today.md) §11). But nothing reads the
engine in that window, so the problem is removable rather than manageable. A
constructor argument fails at boot with a `TypeError`; a handle that was never bound
fails at first write, in a run, in production.

### Re-raise from the `APP_READY` hook loop to fix B2

**Rejected.** It would fix the symptom by changing what a hook means. `APP_READY` is a
general extension point and a telemetry plugin that throws must not kill the app.
Choosing storage is a boot decision with no safe default, so it belongs in a boot step
that is allowed to fail — not in a hook.

### Keep `run_log` / `walk_log` subscribers as the durable record

**Rejected**, agreeing with Design 1. The observer runs outside the authoritative
transaction, can fail independently, and cannot atomically persist the state change it
describes. Today this is not theoretical: `run_log.py:194` swallows the entire batched
flush, and `bus.py:404-409` swallows every subscriber exception, so a fenced refusal
is invisible to the walk that caused it.

### A transaction around a job body

**Rejected**, agreeing with Design 1. User code may block, prompt, call a network, or
run for hours. On SQLite it is worse than it looks: `BEGIN IMMEDIATE` locks the whole
database, and unrelated scopes already block each other for seconds under much shorter
holds ([`02`](02-what-exists-today.md) §8.1).

### Silent fallback from a configured store to documents

**Rejected**, agreeing with Design 1 — and note that this is not a future risk but a
present defect (B2). Defaulting to documents when *nothing* was configured remains
correct.

### Indefinite dual write during migration

**Rejected**, agreeing with Design 1. Two authorities need reconciliation and every
failure produces an ambiguous winner.

### At-most-once outbox delivery

**Rejected**, agreeing with Design 2 and against Design 1's wording. A crash after the
provider accepts and before the acknowledgement cannot distinguish delivered from not
delivered. Retrying duplicates; not retrying loses. The honest statements are
"at-least-once with possible duplicates", "at-most-once with possible loss", or
"effective-once with receiver idempotency" — and only the first is compatible with a
crash-safe outbox.

### Store artifact bytes in runtime rows

**Rejected**, agreeing with Design 1. Transaction size, retention, sharing and
streaming semantics all differ. Store an immutable reference and a digest.

### Outsource durable execution to Restate or DBOS

**Rejected**, and recorded here because it is the single most re-proposable idea in this
area. Evaluated in full in
[`../durability-outsourcing/`](../durability-outsourcing/README.md); the short form:

Functualize **already implements durable execution** — replay, memoised step records,
pinned branches, durable gates and a code-version fence, in `_engine/workflow_walker.py`
and `_engine/frontier.py`. Adopting Restate or DBOS does not add a layer; it substitutes
one, because two systems cannot both own what "this step already ran" means.

Four specific findings, each of which alone would be disqualifying:

1. **The document store does not go away.** Restate's state is per-Virtual-Object with a
   1-day default retention; DBOS's `set_event`/`send`/`recv` are keyed by workflow UUID
   and GC'd with the workflow rows. Neither can hold `fresh`, `scopes`, `runs` or
   `shell-history`. The end state is *two* durability systems.
2. **There is no seam.** A plugin can install a substrate (`EngineHost.substrate`,
   ADR-022). Nothing installs a replay engine, and inventing that port recreates exactly
   the two-seams split brain ADR-022 was written to remove.
3. **Their version fence is coarser than ours.** DBOS orphans every in-flight workflow
   when `application_version` — a hash of the whole application — moves, mitigated by
   blue/green deployment, which is meaningless for a laptop CLI. `graph_digest()`
   (`_engine/workflow_validation.py:212-222`) moves only when the graph moves, and when
   it refuses it names both digests. Adopting either trades a good failure mode for a
   bad one.
4. **Neither can be core.** Restate needs a separate BUSL-licensed Rust server; DBOS
   pulls six dependencies including `psycopg[binary]` and `greenlet` against core's
   four, and its offline (SQLite) mode is documented as unusable in a distributed
   setting — which cancels the reason to adopt it.

**What was taken instead:** DBOS's guarantee that a state change and its durability
record commit in one database transaction is exactly the `RuntimeTransaction` shape in
[`05`](05-the-design.md) §2.2. It is cited as independent evidence, which is worth more
than the integration and costs nothing.

The general rule this establishes: **storage is pluggable, execution is not.** Any
future proposal that introduces a second way for a workflow to be durable is the ADR-022
mistake one layer up, however good the vendor is.

---

## 4. Open questions for the maintainer

These are decisions this design deliberately does not make.

1. **Do the four public stores get deprecated or kept?** `ScopeStore`, `RunStore`,
   `FreshStore` and `ShellHistoryStore` are in `functualize.app.utils.__all__` and
   covered by `tests/test_public_api_surface.py`. Design 1 proposes to "move or
   delete" them without noting they are public. Recommended: deprecate `ScopeStore`
   and `RunStore` for one minor version; keep the other two.

2. **Is a `Run` with multiple `Attempt`s a breaking change to history output?**
   `func builtin history` and the MCP history tools render run records today. Adding
   attempts changes what "a run failed twice" looks like to a user.

3. **Which database for FUN-22?** Everything about Wave 7 is unknowable until this is
   answered, and it is the decision that would justify Design 1's provider family.

   *Since this was written, the candidates have been evaluated*
   ([`../durability-outsourcing/09-verdict.md`](../durability-outsourcing/09-verdict.md)).
   The recommendation is **Cloudflare D1**, not S3 and not R2: it is the only evaluated
   backend offering atomic multi-document commit (its `batch` is a real SQL transaction),
   it is SQLite so `plugins/functualize-state-sqlite/`'s 225-line substrate is most of
   the work, and it needs no change to the port. S3 has real compare-and-swap since 2024
   but AWS states there is "no way to make atomic updates across keys", so it cannot fix
   B3. R2 is blocked until Cloudflare documents whether a conditional `PutObject` is
   atomic under concurrent writers. This does not decide FUN-22; it narrows it.

4. **Does the outbox dispatcher run inline after commit, as a managed background
   component, or as a separate worker?** Design 1 lists this as open and it still is.
   It interacts with the single `JobExecutionEngine` path: a background dispatcher is
   a second thing that runs work.

5. **Does local workspace storage share one SQLite file with runtime?** Logical
   separation is decided ([`06`](06-data-model.md) §2.4); physical co-location is not.

6. **Is the repair wave acceptable as a `0.3.x` patch, or does it wait for `0.4.0`?**
   B1 changes behaviour a user could in principle depend on — a stale runner's state
   write currently succeeds. It is a bug fix, but it is an observable one.

---

## 5. How to argue against this design

The three places it is most likely wrong, restated from
[`04-three-designs-compared.md`](04-three-designs-compared.md) §7 so they are not
buried:

- **If FUN-22 names a database soon**, Design 1's provider family stops being
  premature, and the incremental route costs a refactor that could have been avoided.
- **The construction move** rests on a grep over one span in two functions.
  [`08`](08-delivery-and-tests.md) §"Wave 1" specifies the tripwire test that would
  turn it into a proof, and until that test exists the claim is weaker than it reads.
- **The repair wave delays the feature** by two to four weeks. If the maintainer
  judges B1–B4 tolerable in the interim, the sequencing argument weakens. The
  migration argument does not: a corrupt source stays corrupt, and Wave 6 is where
  that bill arrives.

And a fourth, found while evaluating the alternatives:

- **This design does not give us durable timers, and nothing in it ever will.** A
  workflow that should retry in six hours, with no process running in between, is
  outside every port here — a store cannot wake anything up. It is our largest genuine
  gap against Restate and DBOS
  ([`../durability-outsourcing/02-what-we-already-have.md`](../durability-outsourcing/02-what-we-already-have.md) §4),
  and it needs a scheduler, not a schema. **If that capability turns out to be
  required, the durable-execution rejection in §3 should be re-opened on its merits**
  rather than treated as settled — DBOS's queue-plus-recovery-thread model addresses
  exactly this and the rest of its objections are weaker than the timer argument is
  strong.

---

## 6. Provenance

Written after an independent adversarial assessment recorded at
`.spec/scrutiny-reports/runtime-persistence-independent-assessment.md`, which carries
the full findings list, the comparison matrix against both other designs, and the
`origin/master` supersession table.

Code baseline `feat/substrate-sqlite` @ `8d450ad`, every finding re-checked against
`origin/master` @ `8c06198`. The four reproductions in
[`03-the-four-defects.md`](03-the-four-defects.md) were executed, not reasoned about.

**Revised after the durability evaluation** in
[`../durability-outsourcing/`](../durability-outsourcing/README.md), which tested this
design against four external systems rather than against the other two proposals. Four
things changed here as a result — D-13 through D-15 above, the buffering correction to
the transaction port ([`05`](05-the-design.md) §2.2), the four new `StoreProfile` fields
([`05`](05-the-design.md) §2.1), and the `Stored.revision` finding
([`02`](02-what-exists-today.md) §9). The rest of the design survived the comparison
unchanged, and two of its choices — command-shaped writers and capability-as-data — were
independently vindicated by it.
