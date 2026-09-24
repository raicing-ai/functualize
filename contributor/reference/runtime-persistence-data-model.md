# Runtime Persistence Data Model Reference

**Audience:** contributors working on runtime storage, the persistence ports, or workflow resumption.
**Status:** target model, with the landed vocabulary marked where it has landed.

Migrated from `contributor/architecture/research/runtime-persistence-engine-owned/06-data-model.md`
at commit `93ecd18` (2026-09-24). That research tree does not reach `master` under the standing
merge rule (`.spec/CONSTITUTION.md` § *VCS*; the 2026-09-22 `research-artifacts-cleared` decision),
so its durable half lives here.

**How to read the tenses.** §1's state machines, §2's tables and the SQL in §5 are the target: what
FUN-18 (names, normalized tables, `SqliteRuntimeStore`) and FUN-19 build. What FUN-17 landed is the
vocabulary and the ports that carry them (`_types/persistence.py`), the honest `StoreProfile` of
today's document backend (`_primitives/document_store.py`), and the first transition that goes
through the port — the walk's claim. Anything below that reads as present tense has been re-read
against the tree at `93ecd18`; a still-forward-looking item says so.

## 1. State machines, before any table

Tables first and transactions second is the wrong order for this codebase: there is no agreed answer
to *which transitions are legal*. Scope status is assigned in twelve places, validated in none,
across four vocabularies, so a schema built on top of that encodes the confusion in DDL.

### 1.1 Attempt

One execution of one job body. `Attempt` is new — there is no attempt record today, and a retry
overwrites in place.

```
                  ┌──────────┐
                  │ RUNNING  │◄── start_attempt
                  └────┬─────┘
          ┌────────────┼────────────┬──────────────┐
          ▼            ▼            ▼              ▼
     ┌─────────┐  ┌────────┐  ┌──────────┐  ┌───────────┐
     │SUCCEEDED│  │ FAILED │  │ SKIPPED  │  │ CANCELLED │
     └─────────┘  └───┬────┘  └──────────┘  └───────────┘
                      │ retryable, attempts remain
                      └──► a NEW attempt row, same run_id
```

Terminal in every case. A retry never mutates a terminal attempt; it inserts the next one. That is
what makes "how many times did this fail before it worked" answerable, which it is not today.

**Landed:** `StartAttempt` / `FinishAttempt` as commands and `Attempt` as an outcome
(`_types/persistence.py`), with a retry inserting the next attempt and never mutating a terminal
one. **Forward-looking:** nothing renders an attempt sequence yet — `Attempt` is vocabulary, and
what a twice-failed-then-succeeded run shows a user is D-6, which needs its own ADR.

### 1.2 Run

The logical unit a user asked for. Holds one or more attempts.

```
  RUNNING ──► SUCCEEDED | FAILED | CANCELLED
```

The run's status is derived from its last attempt plus its cancellation flag. It is stored anyway,
because deriving it on every history query means joining every attempt.

### 1.3 Workflow scope

```
                     claim
   (absent) ────► RUNNING ◄─────────────┐
                    │                    │ resume (new generation)
        ┌───────────┼──────────┐         │
        ▼           ▼          ▼         │
    COMPLETED    FAILED    BLOCKED ──────┘
        │           │          │
        └───────────┴──────────┴──► CANCELLED   (from any non-terminal state)
```

Legal transitions, exhaustively — this table is the artefact that does not exist today:

| From | To | Trigger | Guard |
|---|---|---|---|
| absent | RUNNING | `claim` | none |
| RUNNING | BLOCKED | `suspend` | holds current generation |
| RUNNING | COMPLETED | `complete_step` reaching END | holds current generation |
| RUNNING | FAILED | `complete_step` with a terminal failure | holds current generation |
| BLOCKED | RUNNING | `resume` | an ACCEPTED input request exists |
| RUNNING | RUNNING | `complete_step` mid-walk | holds current generation |
| any non-terminal | CANCELLED | `cancel` | holds current generation **or** explicit force |
| terminal | — | — | **refused** |

Two things that table settles which the code leaves open, and where each stands:

- **A terminal scope is immutable.** **Not yet true of the document backend:**
  `ScopeStore.set_scope_status` (`_primitives/scope_store.py:415-421`) writes the string it is given
  and validates nothing, so a `completed` scope can be moved back to `running`. The predicates that
  make this structural are FUN-19's tables.
- **Cancel requires the generation or an explicit force.** **Landed in behaviour (FUN-17/T16):** the
  cancel takes its claim with `force=True` and the claim is deliberately uncaught
  (`app/_workflow_control.py:421-437`), so a claim that fails propagates and the cancel is
  **refused** instead of writing a status the running walk's own `COMPLETED` then overwrites.
  `force` is what skips the hold (`_primitives/lease.py:222-226`), and cancelling is one of the two
  verbs allowed to use it — the other is an explicit `reclaim`.

`stalled`, `waiting`, `ready` and `abandoned` remain **derived for display only**
(`app/_workflow_view.py`) and are never stored. Keeping that split matters: they are functions of the
lease clock, and storing a clock-derived value is how the lease bug described in `_primitives/lease.py`
gets reintroduced.

### 1.4 Input request (gates)

```
   OPEN ──► ACCEPTED ──► CONSUMED
     │
     ├──► CANCELLED
     └──► EXPIRED
```

`CONSUMED` is the addition to the shape this is adopted from. On the live resume path, consumption
is still **not a write** — the gate payload is read and nothing marks it used — which is benign while
a replayed read is idempotent and stops being benign the moment an agent, rather than a human, can
deposit a second candidate. **Landed at the port:** `InputRequest.status` names `consumed`, the
input writer is append-only by contract, and the document backend's `resume` stamps `consumed_at`
and consumes in one unit (`_primitives/document_store.py:858-872`). **Forward-looking:** the walk's
own resume does not go through the port yet, and a second `deposit_gate_payload` still overwrites
the first (`_primitives/scope_store.py`, `deposit_gate_payload`) — the overwrite the append-only
`input_candidates` table below exists to remove.

## 2. Schema

Names are conceptual; FUN-18 may shorten them. **Constraints and ownership are the contract.**

### 2.1 Runtime identity

| Table | Essential fields | Invariants |
|---|---|---|
| `schema_migrations` | `version`, `checksum`, `applied_at` | one row per applied migration; checksum mismatch **refuses boot** |
| `namespaces` | `id`, `project_key`, `created_at` | unique `project_key`; every runtime row references it |

`schema_migrations` is the direct answer to a substrate whose schema is never versioned. The repository
already has this pattern — `_SCHEMA_VERSION` at `_config/vault.py:132` and `_upgrade` at `:727-783` —
and the substrate plugin never got one. `_primitives/document_store.py` declares
`versioned_migrations=False` accordingly, and says so in `DOCUMENT_PROFILE` rather than leaving it to
be discovered.

### 2.2 Runs and attempts

| Table | Essential fields | Invariants / indexes |
|---|---|---|
| `runs` | namespace, id, scope_id, parent_run_id, job, surface, status, args_hash, invoke_depth, started_at, ended_at | PK (namespace, id); indexes on (namespace, started_at desc), job, scope_id, parent_run_id |
| `run_attempts` | id, run_id, attempt_no, status, started_at, ended_at, failure_code, failure_detail JSON | unique (run_id, attempt_no); index (run_id, attempt_no) |
| `run_events` | run_id, seq, type, payload JSON, occurred_at | unique (run_id, seq); **append only** |

`args_hash` only — never argument values. The run record already stores `compute_args_hash` and that
is correct: arguments carry secrets, and capturing them is a separate redaction and retention
decision. `RunView`, `RunTree` and `RunQuery` (`_types/persistence.py`) are the reader side of this
group.

### 2.3 Workflow aggregate

| Table | Essential fields | Invariants / indexes |
|---|---|---|
| `workflow_scopes` | namespace, id, workflow, graph_digest, status, position, lease_owner, lease_expires_at, **lease_generation**, created_at, updated_at, terminal_at | PK (namespace, id); index (status) for resumable; index (lease_expires_at) |
| `workflow_steps` | scope_id, step_key, iteration, status, inputs JSON, result JSON, reusable, started_at, completed_at | unique (scope_id, step_key, iteration) |
| `workflow_branches` | scope_id, decision_key, chosen_target, chosen_at | unique (scope_id, decision_key); **immutable once written** |
| `scope_state` | scope_id, key, value JSON, version, updated_at | unique (scope_id, key); **every write carries the fence** |
| `scope_events` | scope_id, seq, type, payload JSON, occurred_at, run_id | unique (scope_id, seq); append only |

**`scope_state` is where a fenced write becomes structural.** Today it is a separate JSON document
with no generation column and no predicate; as a table whose predicate carries the held generation,
the stale writer's `UPDATE` matches zero rows and cannot be forgotten by a future contributor. That
is the same reasoning the document backend already uses at its single fencing point — one
`_mutate` seam, and `write(..., expect=revision)` on every write regardless of any local hold
(`_primitives/scope_store.py`).

Lease fields stay **on `workflow_scopes`** rather than in a `leases` table: there is exactly one
current claim per aggregate, and every transition already conditions that row.

### 2.4 Interactions and effects

| Table | Essential fields | Invariants |
|---|---|---|
| `input_requests` | id, scope_id, gate_key, generation, status, schema JSON, prompt JSON, created_at, resolved_at | one OPEN request per (scope_id, gate_key, generation) |
| `input_candidates` | id, request_id, source, payload JSON, created_at | append only — a second candidate never overwrites the first |
| `outbox` | id, namespace, aggregate_type, aggregate_id, topic, payload JSON, idempotency_key, status, available_at, claimed_at, published_at, attempts, last_error | unique idempotency_key where present; index (status, available_at) |
| `artifact_refs` | id, run_id, scope_id, step_key, kind, uri, digest, size, media_type, created_at | metadata only — bytes live in a workspace provider |

`input_candidates` being append-only matters more than it looks: a second deposit overwrites the
first today, so a human approval followed by an agent suggestion silently replaces the human's
answer.

**Landed at the port:** `InputRequest`, `InputWriter` and `EffectWriter` carry this shape, and
`EffectWriter` says plainly that recording the intent is all that happens inside the transaction —
claiming a row, calling the provider and acknowledging the result run outside it. The document
backend declares `durable_outbox=False`, so its `EffectWriter.append` **refuses with**
`NotImplementedError` (`_primitives/document_store.py:786`) rather than dropping an intent: a store
that declares no outbox does not get selected by a feature that needs one, and an unrecorded intent
is a side effect nobody can replay.

## 3. The JSON boundary

**Columns** — anything used for identity, joins, ordering, filtering, retention, ownership or a
predicate: `status`, `position`, `parent_run_id`, every timestamp, `seq`, `lease_generation`,
`lease_owner`, `lease_expires_at`, job and workflow names, `args_hash`, artifact
`digest` / `uri` / `size`, and every outbox claim field.

**JSON** — genuinely opaque payloads whose shape belongs to someone else: step inputs and return
values, gate schemas, candidate payloads, event detail not used in a predicate, provider metadata
documented as opaque.

The test, stated as a rule a reviewer can apply: **if you would ever want an index on it, it is a
column.**

## 4. Transaction catalogue

A transaction surrounds a **transition**, never a job body. Everything in the right column runs with
no transaction open.

| Transition | Commits atomically | Runs outside |
|---|---|---|
| start run | claim/ensure scope at a generation, insert run, insert attempt #1, start events | the job body |
| state batch | verify fence, upsert/delete state keys, optional state event | the caller's computation |
| complete step | step outcome, branch, position, scope status, scope events, outbox intents | notification and network delivery |
| finish attempt | attempt outcome, run outcome when terminal, final events, outbox intents | rendering, EventBus notification |
| suspend at gate | input request row, scope → BLOCKED, position, event | collecting the human or agent input |
| resume | consume ACCEPTED request, claim at a **new** generation, scope → RUNNING, resume event | the resumed body |
| cancel | scope → CANCELLED, terminal_at, event | anything observing it |
| lease renewal | conditional generation/owner update | — |
| dispatch effect | claim one outbox row | the provider call |
| acknowledge effect | published_at / last_error / next attempt | — |

**`resume` is one transition, and on the live path it is still two locked writes.** The deposit and
the claim sit in different call frames (`app/_workflow_answer.py`, `_engine/frontier.py`), with
`ScopeStore`'s lock taken twice. Today's window is benign because consumption is a read; with
`CONSUMED` in the state machine it would not be, which is why they merge. **Landed at the port:**
`ResumeWorkflow` is one command and the document backend's `resume` consumes the accepted request,
claims at the new generation, moves the scope to `RUNNING` and appends the event as one unit.
**Forward-looking:** `WorkflowRecorder().resumed` has no production caller, so the merge is FUN-20's
to wire.

### Why never around a job body

User code may block, prompt, call a network, or run for hours. Holding a transaction across it holds
locks and connections for that long, makes retries unsafe, and couples database availability to
arbitrary work duration. With `BEGIN IMMEDIATE` on SQLite it would also stop every other writer in
the database — the research measured unrelated scopes blocking each other for 3.7 s under a much
shorter hold. This rule is **landed** as the port's own contract: `RuntimeTransaction`'s docstring
states that a transaction never wraps a job body, a prompt, an agent call or any network effect.

## 5. Fencing

One conditional update, and the returned generation is the only authority:

```sql
UPDATE workflow_scopes
   SET lease_owner        = :runner,
       lease_expires_at   = :expiry,
       lease_generation   = lease_generation + 1
 WHERE namespace_id = :ns
   AND id           = :scope
   AND (lease_owner = :runner OR lease_expires_at <= :now)
RETURNING lease_generation;
```

Zero rows updated → `Conflict`, not an exception. Every authoritative write then carries the held
generation in its predicate:

```sql
UPDATE scope_state
   SET value = :value, version = version + 1, updated_at = :now
 WHERE scope_id = :scope AND key = :key
   AND (SELECT lease_generation FROM workflow_scopes
         WHERE namespace_id = :ns AND id = :scope) = :held_generation;
```

Three properties this buys that a best-effort scheme cannot give:

1. **A stale state write is structurally impossible** — state carries the predicate.
2. **Two claimers cannot both emerge at generation N** — the claim is one atomic statement.
3. **The owner is implicitly checked**, because a losing claimer never receives generation N in the
   first place. That is a better fix than adding owner to `check_generation`.

`fencing="cross-process"` in a profile is exactly this property. A store that cannot provide it says
so.

**Where this stands.** The measured rows of
[`substrate-capability-matrix.md`](substrate-capability-matrix.md) are the citation for each profile
value; nothing here re-derives them from vendor documentation. At `93ecd18` the fence is enforced by
`ScopeStore`'s compare-and-swap plus the lease read out of the loaded envelope, and the port carries
it as **values**: `Claimed` returns the generation a caller now holds, every scope-mutating command
carries the held generation, and losing a claim is `Conflict` — a value the caller branches on, never
an exception. `DOCUMENT_PROFILE` states this as `fencing="cross-process"`, `cross_aggregate_atomicity=False`.

One consequence of `Conflict` being a value is worth knowing before you read a refusal:
`Conflict` (`_types/persistence.py:337-346`) carries `scope_id`, `held_by` and `held_generation` and
**no expiry**, so a walk refused at the door names the holder and the generation but not *until
when*. [`workflow-walker.md`](workflow-walker.md) §10 records what that costs an operator and what
they can do instead.

## 6. Retention, including the cap nobody has costed

Today the scope document carries a **500-record ring cap applied on every write**, evicting only
terminal records (`SCOPES_LIMIT` at `_primitives/scope_format.py:144`), and per-scope events carry a
second cap of 500 (`EVENTS_PER_SCOPE_LIMIT` at `:153`). A project whose 500 records are all live
stays over cap permanently — the eviction is deliberately allowed to miss rather than delete a live
run.

Two consequences:

- **Migration.** Records already evicted are gone. An import must report what it found rather than
  implying completeness, and a cutover's "verify counts" step must compare against the source's
  *current* contents, not a user's expectation.
- **Target behaviour.** In a relational store the cap becomes an explicit retention policy — age and
  count, applied to terminal rows by a maintenance operation — not an eviction that runs inside every
  write. Writing a step record should not be able to delete someone else's run.

Deletion rules:

- Live and blocked scopes are never evicted by a cap.
- Deleting a scope cascades state, steps, branches, input requests and scope events in one transaction.
- `artifact_refs` cascade the **reference**; the bytes follow workspace retention. A runtime database
  deletion must not silently delete a shared blob.

## 7. Migration discipline

- Ordered, checksummed, idempotent at the runner level, serialized by a lock.
- Run during boot step 6.5, **before any job can execute** — which is possible because selection now
  happens before engine construction (ADR-027, landed).
- A partially applied revision is a **boot refusal with repair steps**, never a silent continue.
- Tests start from every supported historical schema, not only an empty database.
- `create_all()` is acceptable only for a brand-new empty database. It is not an upgrade mechanism —
  which is precisely the defect `CREATE TABLE IF NOT EXISTS` produced in the substrate plugin.

**Forward-looking:** the document backend declares `versioned_migrations=False` and has no schema
version at all, so none of the above runs today. The runner arrives with FUN-19's tables.

## See also

- [`state-store.md`](state-store.md) §9 — the document store's honest profile, field by field.
- [`workflow-walker.md`](workflow-walker.md) §10 — what a walk refused at the door reports.
- [`substrate-capability-matrix.md`](substrate-capability-matrix.md) — the measurements the profile
  fields are read from.
- `contributor/adr/025-engine-owns-transition-meaning.md`, `026-persistence-ports-need-no-new-layer.md`,
  `027-engine-construction-moves-after-config.md`, `028-storage-is-pluggable-execution-is-not.md`.
