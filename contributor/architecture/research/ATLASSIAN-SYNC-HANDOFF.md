# Handoff — finish the Jira and Confluence sync

**You need:** Jira write access **and** Confluence write access to
`raicing-ai.atlassian.net`. Both halves are in this document — Jobs 0–3 are **Jira**,
Job 4 is **Confluence**.

**Written:** 2026-09-21
**Why this exists:** the Atlassian MCP server disconnected partway through this work. All
repository and Git work is **done and verified**. Five jobs remain, and this document is
everything needed to finish them. It assumes you have no other context.

**Site:** `https://raicing-ai.atlassian.net`
**cloudId:** `269b32c5-52fe-4544-899b-18e225b3dc04`
**Confluence spaceId:** `163844` (space key `FUN`)
**Jira project:** `FUN`

---

## 0. Background in one page

Functualize is a Python job/workflow framework. An initiative (epic **FUN-16**) is
replacing its runtime persistence layer. Three competing designs existed; a fourth option
— outsourcing durability to Restate, DBOS, Cloudflare or AWS — was evaluated and rejected.

Two research packages were written into the repository (20 documents, 5,107 lines):

- `contributor/architecture/research/runtime-persistence-engine-owned/` — the design now
  proposed as canonical
- `contributor/architecture/research/durability-outsourcing/` — the evaluation of not
  building it

The headline finding: **Functualize already implements durable execution** (replay,
memoised step records, pinned branches, durable gates, a code-version fence). Its four
real defects are one level below that, in transactional integrity. So the plan repairs
that level rather than adopting someone else's engine.

### What is already done — do not redo any of it

| | |
|---|---|
| ✅ | Old canonical package (page `5308716`) **archived**: moved under new archive parent `5472849`, retitled `Archive — …(superseded)`, re-headed, index preserved. Page ID unchanged, so existing links still resolve. |
| ✅ | New Confluence parent **`6389761`** — *Runtime Persistence — Engine-Owned Design (Canonical)* |
| ✅ | New Confluence parent **`6422529`** — *Research — Outsourcing Durability: Restate, DBOS, Cloudflare, S3* |
| ✅ | **FUN-24** created — Wave 0, repair the four defects |
| ✅ | **FUN-25** created — Wave 0, six-backend capability probe |
| ✅ | 1 research branch + 9 ticket branches with worktrees and pre-loaded specs |

### What remains — your five jobs

| Job | System | What |
|---|---|---|
| **0** | Jira | Verify the state described above is real. Two issues were created just before the disconnect and have not been re-read since. |
| **1** | Jira | Replace one comment on FUN-25 — it is now materially misleading |
| **2** | Jira | Update FUN-17 → FUN-23 descriptions, and the FUN-16 epic |
| **3** | Jira | **Create the issue links.** The wave dependencies currently exist only as prose inside descriptions, so the board shows nine unordered tickets |
| **4** | Confluence | Publish 20 child pages |

Do them in that order. Job 0 is two calls; Job 1 is one.

---

## Job 0 — verify, before you change anything

The two issues below were created successfully (the API returned their keys), but the
connection dropped shortly afterwards and nothing has re-read them since. Confirm, and if
any is wrong, report it rather than working around it.

Call `getJiraIssue` for each with `fields: ["summary","status","parent","labels","priority"]`:

| Key | Expect |
|---|---|
| **FUN-24** | Summary *Repair the four runtime persistence defects before anything reads the legacy data*; Task; parent FUN-16; To Do; priority Highest; labels `defect`, `wave-0`, `persistence`, `substrate`, `north-star-1.0` |
| **FUN-25** | Summary *Substrate capability probe: measure StoreProfile empirically across six backends*; Task; parent FUN-16; To Do; priority Highest; labels include `spike`, `wave-0`, `conformance` |

Also confirm the three Confluence pages exist and are parented correctly
(`getConfluencePage`):

| Page | Expect |
|---|---|
| `5472849` | *Research Archive — Runtime Persistence (superseded 2026-09-21)*, child of `4816898` |
| `5308716` | *Archive — Runtime Persistence Architecture — Canonical Design Package (superseded)*, **child of `5472849`** |
| `6389761` / `6422529` | the two new parents, children of `4816898` |

**If FUN-24 or FUN-25 does not exist**, their full descriptions are not reproduced here —
say so in your report and stop rather than inventing them; they can be recovered from the
session that created them.

---

## Job 1 — replace comment `10013` on FUN-25

An earlier comment recommended an AWS emulator more strongly than the evidence supports,
and named LocalStack from a guess rather than from reading the tool. Replace it in place.

Use `addCommentToJiraIssue` with `issueIdOrKey: "FUN-25"`, `commentId: "10013"`,
`contentFormat: "markdown"`, and **exactly** this body:

<!-- BEGIN COMMENT BODY -->
```markdown
## Local testing strategy (2026-09-21, revised)

*An earlier version of this comment leaned on an AWS emulator harder than the evidence
warrants, and named LocalStack from a guess. This replaces it.*

### Three jobs, and the emulator only does the smallest one

| Job | Tool | Why not the others |
|---|---|---|
| Does **our code** handle profile-shape X? | **hand-written fakes**, ~80 lines each | no Docker, no credentials, every CI run |
| Does our **client** speak the real wire protocol? | **an emulator** | fakes bypass boto3 entirely, so they never catch a wrong kwarg, a malformed `TransactWriteItems`, auth/signature shape, or pagination |
| What does the service **actually guarantee** under concurrency? | **the real service, only** | a fake encodes *our* belief; an emulator encodes the *emulator author's* belief. This ticket exists to replace belief with measurement |

### Why D1 needs no emulator, and S3/DynamoDB do

**D1 is SQLite *minus* a capability** — no interactive transaction, atomic unit is one
`batch`. A restriction is faithfully simulatable by refusing to do the thing, so a ~50-line
`BatchOnlySqliteDriver` over stdlib `sqlite3` is not an approximation; it *is* the
constraint:

- never hands out a connection that survives a client-side decision;
- accepts only a list of `(sql, params)` and runs it inside one `BEGIN … COMMIT`;
- raises if anything opens a transaction explicitly.

It catches the whole bug class D1 catches — *this code assumed it could hold a transaction
open* — and it is the test that would have caught the streaming `RuntimeTransaction` design
before it was written down. **Tier A, permanently.**

S3 and DynamoDB are not restrictions on anything we have. They are different data models
with different failure taxonomies (ETags, 412 vs 409; `ConditionExpression`,
`TransactionCanceledException` with per-item cancellation reasons). Those need either a
hand-written fake (for our code) or the real service (for truth).

### On floci

[floci](https://github.com/floci-io/floci) is a free OSS AWS emulator positioned as a
drop-in replacement for LocalStack Community Edition, which sunsets March 2026. One
container on `:4566`, covers S3 and DynamoDB among 100+ services. Genuinely useful.

**Two caveats found by reading it:**

1. Its README **does not claim S3 conditional writes (`If-Match`/`If-None-Match`) or
   DynamoDB `TransactWriteItems`/`ConditionExpression`** — which are exactly the two
   features `fencing` and `cross_aggregate_atomicity` are measured from.
2. It self-describes as *"AWS-shaped services"* rather than parity, and reserves real
   Docker-backed execution for Lambda, RDS, Neptune and ECS — not S3 or DynamoDB.

So it is most likely to be silent or wrong on the exact two cells this ticket exists to
fill.

### Revised tiering

- **Tier A — required, every CI run, no Docker and no credentials.** Fakes for all four
  shapes, `BatchOnlySqliteDriver` among them.
- **Tier B — required once per backend for sign-off.** The real service. At our volume S3
  is roughly $1/month and DynamoDB on-demand is pennies.
- **An emulator is an optional developer convenience** between the two. It may never back
  a `StoreProfile` field.

### Task 1 of this ticket

**Point the probe at floci first.** Twenty minutes, and it answers whether floci implements
conditional writes and `TransactWriteItems` at all. That is not overhead — it *is* a probe
run, and it decides whether floci is usable for the wire-protocol job or only for the
boring parts.

### Evidence column on the results table

Every cell carries one of:

- `measured (real service)` — the only value that may back a shipped `StoreProfile` field
- `measured (emulator)` — fine for CI and shape conformance, never for sign-off
- `measured (fake)` — proves our code, proves nothing about the vendor
- `NOT MEASURED` — with the reason

**Acceptance criterion added:** every `StoreProfile` field on a shipped substrate is backed
by at least one `measured (real service)` row.
```
<!-- END COMMENT BODY -->

If `commentId 10013` no longer exists, post it as a **new** comment instead and say so in
your report.

---

## Job 2 — update FUN-17 through FUN-23

### Rules

1. **Fetch each issue first** (`getJiraIssue`, `fields: ["summary","description"]`,
   `responseContentFormat: "markdown"`).
2. **Preserve the existing `## Outcome` and `## Source` sections verbatim.** They carry
   product authority links that must survive. Do not rewrite them.
3. Append the revision block below. Where an existing section directly contradicts it
   (an old sequencing note, an old acceptance list), replace that section rather than
   leaving both.
4. Add the label `wave-N` matching the wave number, keeping all existing labels.
5. These are **Story** or **Task** types under epic **FUN-16** — do not change issue type
   or parent.

### The wave order, for reference

| Wave | Ticket | Branch |
|---|---|---|
| 0 | FUN-24 (done) | `fix/runtime-persistence-defects` |
| 0 ∥ | FUN-25 (done) | `spike/substrate-capability-probe` |
| 1 | **FUN-17** | `feat/runtime-persistence-ports` |
| 2 | **FUN-18** | `feat/runtime-schema-migrations` |
| 3 | **FUN-19** | `feat/sqlite-runtime-provider` |
| 4 | **FUN-20** | `feat/workflow-persistence-atomic` |
| 5 | **FUN-21** | `feat/gate-interactions-outbox` |
| 6 | **FUN-23** | `feat/workspace-persistence-split` |
| 7 | **FUN-22** | `feat/network-sql-provider` |

Note FUN-23 comes **before** FUN-22. That is deliberate: the network provider is last
because everything before it is what makes it a 400-line plugin rather than a rewrite.

### FUN-17 — Ports, StoreProfile, recorders, and the construction move

Set **Summary** to: `Ports, StoreProfile, recorders, and the construction move`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 1 of 7.** Branch: `feat/runtime-persistence-ports` (created, with specs pre-loaded).

**Goal.** Define the persistence ports and move engine construction to after config resolves.

**Why now.** The engine does not receive its storage — it goes and finds it, lazily, on first access (executor.py:1509-1527). That temporal coupling is what every defect downstream rests on. Moving construction to _app deletes the argument rather than winning it.

**Blocks:** FUN-18, FUN-19, FUN-20, FUN-21, FUN-22, FUN-23
**Runs in parallel with:** none — this is the wave everything else builds on

### Acceptance criteria

1. RuntimeTransaction ACCUMULATES commands and commits once on __exit__. It must be implementable over Cloudflare D1, which has no BEGIN.
2. A store declaring cross_aggregate_atomicity=False REFUSES a transaction spanning two aggregates. It never applies it in parts.
3. StoreProfile carries all ten fields including offline_capable, and boot REFUSES rather than degrading when a required capability is absent.
4. The lazy substrate property is gone. A tripwire test proves the engine receives its store and never discovers one.
5. The seven import-linter contracts still pass unchanged. No new layer.
6. claim() returns Claimed | Conflict. Losing a claim is an outcome, not an exception.

### Where the reasoning lives

- Repository: `.spec/features/runtime-persistence-ports/` on branch `feat/runtime-persistence-ports` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### FUN-18 — State machines, relational schema, and the migration contract

Set **Summary** to: `State machines, relational schema, and the migration contract`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 2 of 7.** Branch: `feat/runtime-schema-migrations` (created, with specs pre-loaded).

**Goal.** Specify the legal state transitions, then the tables that hold them.

**Why now.** 02-what-exists-today.md §6 found twelve status writers and no transition table. Specifying the machine before the schema is what stops the schema encoding an accident. Most of this data model is adopted from the archived Design 1, with credit.

**Blocks:** FUN-19
**Runs in parallel with:** none

### Acceptance criteria

1. Attempt, Run, Scope and InputRequest each have a written state machine with a legal-transition table.
2. An illegal transition raises IllegalTransition naming both states. It is not silently written.
3. The schema is one row per step, not one row per document — a D1 row caps at 2 MB and the scopes envelope grows without bound.
4. Migrations are versioned and forward-only, with a recorded schema version.
5. The 500-record cap becomes an explicit retention policy, not a write-time eviction.

### Where the reasoning lives

- Repository: `.spec/features/runtime-schema-migrations/` on branch `feat/runtime-schema-migrations` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### FUN-19 — The SQLite runtime provider, legacy migration, and the tiered conformance suite

Set **Summary** to: `The SQLite runtime provider, legacy migration, and the tiered conformance suite`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 3 of 7.** Branch: `feat/sqlite-runtime-provider` (created, with specs pre-loaded).

**Goal.** The first real RuntimeStore, and the tiered suite every later backend must pass.

**Why now.** SQLite is the reference implementation: it is the only backend that is both transactional and offline-capable, which makes it the one that can be the default. The conformance suite written here is what makes FUN-22 cheap.

**Blocks:** FUN-20, FUN-21, FUN-22, FUN-23
**Runs in parallel with:** none

### Acceptance criteria

1. SqliteRuntimeStore declares cross_aggregate_atomicity=True, fencing='cross-process', offline_capable=True, and passes the tier each field gates.
2. The BASELINE conformance tier passes for every store including DocumentRuntimeStore. A store that declares a capability False does not run that capability's tier and cannot be selected by a feature needing it.
3. Legacy migration is OFFLINE with backup and verification. No indefinite dual write (rejected as RP-7).
4. Migration REFUSES illegal records rather than importing them — which is why FUN-24 comes first.
5. BatchOnlySqliteDriver from FUN-25 runs against this store in Tier A and passes, proving the transaction buffers.

### Where the reasoning lives

- Repository: `.spec/features/sqlite-runtime-provider/` on branch `feat/sqlite-runtime-provider` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### FUN-20 — Workflow state, resume, and leases committed atomically

Set **Summary** to: `Workflow state, resume, and leases committed atomically`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 4 of 7.** Branch: `feat/workflow-persistence-atomic` (created, with specs pre-loaded).

**Goal.** One transition, one commit, one fence.

**Why now.** Defect B3: no code path commits two documents together, so scopes and scope-state can diverge. This is where that is structurally fixed rather than patched — the fence moves into the transaction predicate instead of being remembered at each call site.

**Blocks:** FUN-21
**Runs in parallel with:** none

### Acceptance criteria

1. A step record, its state change and its event commit as ONE unit or none of them do.
2. The fence is in the transaction predicate. A stale generation cannot commit from ANY process, and no call site has to remember to check.
3. A resumed walk in a fresh process sees its steps AND its variables. The split brain is unreachable by construction.
4. The B1 and B4 reproductions from FUN-24 still pass, now for a structural reason rather than a patched one.
5. A transaction NEVER wraps a job body, a prompt, an agent call or any network effect.

### Where the reasoning lives

- Repository: `.spec/features/workflow-persistence-atomic/` on branch `feat/workflow-persistence-atomic` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### FUN-21 — Gate interactions, evidence, and the transactional outbox

Set **Summary** to: `Gate interactions, evidence, and the transactional outbox`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 5 of 7.** Branch: `feat/gate-interactions-outbox` (created, with specs pre-loaded).

**Goal.** A human's answer and the effect it triggers cannot be separated by a crash.

**Why now.** A gate resolution that commits without its side effect, or a side effect that fires without its commit, are the two halves of the same bug. The outbox makes them one commit — the shape DBOS independently arrived at, cited as evidence in 09-decisions.md.

**Blocks:** none
**Runs in parallel with:** FUN-23

### Acceptance criteria

1. A gate resolution and its outbox row commit in ONE transaction.
2. Delivery is AT-LEAST-ONCE with consumer dedup. The documentation says so in those words — no at-most-once claim anywhere.
3. An undelivered effect survives a process kill and is delivered on the next start.
4. Evidence attached to a gate answer is stored by reference and digest, never as bytes in a runtime row.
5. A store declaring durable_outbox=False does not run the outbox tier and cannot be selected by a feature needing one.

### Where the reasoning lives

- Repository: `.spec/features/gate-interactions-outbox/` on branch `feat/gate-interactions-outbox` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### FUN-22 — Network providers and distributed resume

Set **Summary** to: `Network providers and distributed resume`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 7 of 7.** Branch: `feat/network-sql-provider` (created, with specs pre-loaded).

**Goal.** A workflow parks on one machine and resumes on another.

**Why now.** This is the capability the whole initiative exists to enable, and it is LAST because everything before it is what makes it a 400-line plugin instead of a rewrite. FUN-25 has already measured which backends can actually do it.

**Blocks:** none — this completes the initiative
**Runs in parallel with:** none

### Acceptance criteria

1. D1 FIRST. It is the only evaluated backend with atomic multi-document commit via batch, and it needs no port change.
2. The provider is a PLUGIN. `grep -rn 'cloudflare\|boto3' src/functualize/` stays at 0.
3. A workflow parked by process A on machine 1 resumes on machine 2, with the fence holding across both.
4. Declared profile values match FUN-25's MEASURED values, not the vendor documentation.
5. R2 is NOT implemented unless FUN-25 established that its conditional PutObject is atomic under concurrent writers.
6. The default store is unchanged and still offline-capable. ADR-015 holds.

### Where the reasoning lives

- Repository: `.spec/features/network-sql-provider/` on branch `feat/network-sql-provider` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### FUN-23 — Separate managed workspace persistence, and evaluate AgentFS

Set **Summary** to: `Separate managed workspace persistence, and evaluate AgentFS`

Append this to the description, after the existing `## Outcome` and `## Source` sections,
replacing any older "Objectives"/"Acceptance"/"Sequencing" sections that contradict it:

```markdown
---

## Revised 2026-09-21 — engine-owned design

**Wave 6 of 7.** Branch: `feat/workspace-persistence-split` (created, with specs pre-loaded).

**Goal.** Runtime truth and workspace bytes stop sharing a store.

**Why now.** A run record and a 400 MB artifact have different transaction sizes, retention, sharing and streaming semantics. Design 1 reached this conclusion too and it is adopted with credit.

**Blocks:** none
**Runs in parallel with:** FUN-21

### Acceptance criteria

1. Runtime rows store an immutable reference and a digest. They never store artifact bytes.
2. The workspace port is separate from RuntimeStore and may have a different backend.
3. Whether one SQLite file holds both is answered explicitly — logical separation is already decided, physical co-location is not.
4. The AgentFS evaluation ends in an ADR with a decision, not a survey.

### Where the reasoning lives

- Repository: `.spec/features/workspace-persistence-split/` on branch `feat/workspace-persistence-split` — BRIEFING.md,
  spec.md, plan.md, contracts.md, tasks.md with a valid wave graph
- Confluence: *Runtime Persistence — Engine-Owned Design (Canonical)* (page 6389761)

### Note on the superseded design

This ticket's original description cited the canonical design package at page 5308716.
That package is now **archived** — see page 5472849. Most of its data model was adopted
with credit; its sequencing and layer placement were not.
```

### Finally, update the epic FUN-16

Append to its description:

```markdown
---

## Revised 2026-09-21

The canonical design is now the **engine-owned design**
(Confluence page 6389761). The previous canonical package is archived (page 5472849).

**Two tickets were added:** FUN-24 (Wave 0 — repair four defects before anything reads the
legacy data) and FUN-25 (Wave 0 — measure StoreProfile against six backends).

**Wave order:** FUN-24 ∥ FUN-25 → FUN-17 → FUN-18 → FUN-19 → FUN-20 → FUN-21 → FUN-23 →
FUN-22.

**The decision this initiative now asks for:** *storage is pluggable; execution is not.*
A plugin may change where a step record is stored. A plugin may never change what it means
for a step to have run. This needs an ADR.

**What was evaluated and rejected:** outsourcing durability to Restate or DBOS. See
Confluence page 6422529. Functualize already implements durable execution; adopting
either would replace that engine, cost ~3,716 lines of blast radius, and still leave the
document store in place.
```

---

## Job 3 — create the issue links

**This is the gap that matters most.** Wave ordering is currently prose inside nine
descriptions. Nothing on the board expresses it, so a planner looking at the epic sees
nine tickets that all appear startable. They are not: FUN-24 blocks everything.

### First, discover the link types

Call `getIssueLinkTypes`. Instances differ. You are looking for the **Blocks** family
(usually inward *is blocked by* / outward *blocks*) and a **Relates** type. Use the exact
names that call returns — do not assume `"Blocks"` is spelled that way here.

### Then create these links with `createIssueLink`

**Hard dependencies — use the Blocks type.** Read `A -> B` as *A blocks B*:

| From | To | Why |
|---|---|---|
| FUN-24 | FUN-17 | a corrupt source stays corrupt; ports must not be built over unrepaired defects |
| FUN-17 | FUN-18 | the schema encodes the ports' state machines |
| FUN-18 | FUN-19 | the provider implements the schema |
| FUN-19 | FUN-20 | atomic workflow writes need a transactional store |
| FUN-20 | FUN-21 | the outbox commits alongside a workflow transition |
| FUN-19 | FUN-23 | the workspace split needs the runtime store to exist first |
| FUN-21 | FUN-22 | the network provider must pass the full conformance suite, outbox tier included |
| FUN-23 | FUN-22 | same |

**Soft dependencies — use the Relates type.** FUN-25 measures what the others assume:

| From | To | Why |
|---|---|---|
| FUN-25 | FUN-17 | supplies the measured `StoreProfile` field values |
| FUN-25 | FUN-19 | supplies the backend limits the schema must respect |
| FUN-25 | FUN-22 | decides which backends are worth implementing at all |

That is **8 blocking links and 3 relates**. FUN-24 and FUN-25 are the only two with no
inbound blocker — they are the two startable today, and they run in parallel.

### Priorities

FUN-24 and FUN-25 are already **Highest**. Suggested for the rest, as a judgment call the
maintainer may override:

| Tickets | Priority | Reason |
|---|---|---|
| FUN-17, FUN-18, FUN-19 | **High** | the critical path; nothing ships without them |
| FUN-20, FUN-21, FUN-23, FUN-22 | **Medium** | real work, but each is unblocked only after the path above |

### Labels

Every ticket gets a `wave-N` label matching its wave in the table above, **keeping all
existing labels**. FUN-24 and FUN-25 already carry `wave-0`.

---

## Job 4 — publish 20 Confluence child pages

Two batches. Work **sequentially**; do not parallelise. If you hit a rate limit, stop and
report exactly which titles completed.

### FIRST: check what already exists

A previous attempt died on a rate limit and *may* have created some children. Before
creating anything, list each parent's children and build a list of existing titles.

- Title already exists under its parent → `updateConfluencePage` on that page ID.
- Never create two pages with the same title under the same parent.

### Batch A → parentId `6389761`

Source dir:
`/home/ubuntu/orca/workspaces/functualize/feat-substrate-sqlite/contributor/architecture/research/runtime-persistence-engine-owned/`

| Page title | Source file |
|---|---|
| `00 — Start Here` | `README.md` |
| `01 — Orientation for a New Engineer` | `01-orientation.md` |
| `02 — What Exists Today` | `02-what-exists-today.md` |
| `03 — The Four Defects` | `03-the-four-defects.md` |
| `04 — Three Designs Compared` | `04-three-designs-compared.md` |
| `05 — The Design` | `05-the-design.md` |
| `06 — Data Model and Transactions` | `06-data-model.md` |
| `07 — What Changes` | `07-what-changes.md` |
| `08 — Delivery and Tests` | `08-delivery-and-tests.md` |
| `09 — Decisions` | `09-decisions.md` |

Header to prepend to each Batch A body (substitute the real filename):

```
> **Source of truth:** `contributor/architecture/research/runtime-persistence-engine-owned/<FILENAME>`
> Repository baseline `feat/substrate-sqlite` @ `8d450ad`. Edit the repository, then re-sync this page.
```

### Batch B → parentId `6422529`

Source dir:
`/home/ubuntu/orca/workspaces/functualize/feat-substrate-sqlite/contributor/architecture/research/durability-outsourcing/`

| Page title | Source file |
|---|---|
| `00 — Start Here` | `README.md` |
| `01 — The Question, Restated` | `01-the-question.md` |
| `02 — What We Already Have` | `02-what-we-already-have.md` |
| `03 — Restate` | `03-restate.md` |
| `04 — DBOS` | `04-dbos.md` |
| `05 — Cloudflare: D1, Durable Objects, R2, Workflows` | `05-cloudflare.md` |
| `06 — AWS S3` | `06-s3.md` |
| `07 — The Design: Where Each Abstraction Belongs` | `07-the-design.md` |
| `08 — Is It Cheap?` | `08-is-it-cheap.md` |
| `09 — Verdict` | `09-verdict.md` |

Header to prepend to each Batch B body (substitute the real filename):

```
> **Source of truth:** `contributor/architecture/research/durability-outsourcing/<FILENAME>`
> Research current as of 2026-09-21. External vendor facts carry inline source URLs; items
> marked "NOT FOUND" were deliberately not guessed.
```

### Rules for both batches

1. Use `createConfluencePage` with `contentFormat: "markdown"`, `spaceId: "163844"`.
2. **Body = the file's content, essentially VERBATIM.** Do not summarise, shorten, reword
   or "improve" anything. These documents are the deliverable. Preserve every table, code
   block, blockquote and heading.
3. Prepend the batch header, then a blank line, then the file content.
4. Strip the file's first line **only** if it is an H1 duplicating the page title (e.g.
   `# 04 — DBOS`) — Confluence renders the title already. Drop that one line, nothing else.
5. Rewrite **relative** markdown links only. `](01-orientation.md)` and
   `](../durability-outsourcing/06-s3.md)` will not resolve; replace each with italic text
   naming the document, e.g. `*(see 01 — Orientation for a New Engineer)*`. **Do not invent
   Confluence URLs.**
6. **Leave every `https://` link exactly as it is.** In Batch B especially, those are the
   research citations and are the most valuable content on the page.
7. Files run 82–460 lines. Send the whole file; do not truncate.
8. If a page fails with a **422 "data loss"** error, it means the existing content contains
   macros or smart links that markdown cannot represent. That only happens on *updates*.
   Switch that page to `contentFormat: "html"` — and call
   `getContentFormatGuide({toolName: "updateConfluencePage"})` first.
9. **Never** retry with mangled or shortened content, and never silently skip a page.

---

## Verification before you report done

- [ ] FUN-24 and FUN-25 exist, are Tasks under FUN-16, and are priority Highest
- [ ] Page `5308716` is titled `Archive — …(superseded)` and sits under `5472849`
- [ ] FUN-25 comment reads "revised" and mentions floci, not LocalStack-by-guess
- [ ] FUN-17–FUN-23 each carry a wave number, a branch name, and acceptance criteria
- [ ] FUN-16 carries the revision block
- [ ] 8 blocking links and 3 relates links exist; FUN-24 and FUN-25 are the only tickets
      with no inbound blocker
- [ ] every ticket carries a `wave-N` label and has kept its pre-existing labels
- [ ] Every ticket's original `## Outcome` and `## Source` sections are intact
- [ ] Parent `6389761` has exactly 10 children, titled `00 —` … `09 —`
- [ ] Parent `6422529` has exactly 10 children, titled `00 —` … `09 —`
- [ ] No duplicate titles under either parent
- [ ] Spot-check two Batch B pages: external `https://` citation links still present

## Report back

A table of every Jira issue touched and every Confluence page created or updated, with
IDs and URLs, plus **anything you could not do and why**. A gap you name is worth more
than a gap you paper over.
