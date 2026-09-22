# 06 — Data model, state machines, transactions

**This chapter is closer to Design 1 than anything else in this folder**, and that is
deliberate: its normalization rule and transaction catalogue are the best part of that
proposal. The differences are (a) state machines come first, (b) `Attempt` exists,
(c) the ring cap is accounted for, (d) every guarantee is tied to a `StoreProfile`
field rather than asserted universally.

Read [`05-the-design.md`](05-the-design.md) first.

---

## 1. State machines, before any table

Design 1 specifies tables and then transactions. That order is backwards for this
codebase, because [`02-what-exists-today.md`](02-what-exists-today.md) §6 shows there
is no agreed answer to "which transitions are legal" — status is assigned in twelve
places, validated in none, across four vocabularies. A schema built on top of that
encodes the confusion in DDL.

### 1.1 Attempt

One execution of one job body. **This is new** — today it does not exist, and a retry
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

Terminal in every case. A retry never mutates a terminal attempt; it inserts the next
one. That is what makes "how many times did this fail before it worked" answerable,
which it is not today.

### 1.2 Run

The logical unit a user asked for. Holds one or more attempts.

```
  RUNNING ──► SUCCEEDED | FAILED | CANCELLED
```

The run's status is derived from its last attempt plus its cancellation flag. It is
stored anyway, because deriving it on every history query means joining every attempt.

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

Two things that table settles which the code currently leaves open:

- **A terminal scope is immutable.** Today `set_scope_status` will happily move a
  `completed` scope back to `running` (`scope_store.py:361-367` validates nothing).
- **Cancel requires the generation or an explicit force.** Today
  `app/_workflow_control.py:439` catches a failed claim and cancels anyway, unfenced.

`stalled`, `waiting`, `ready` and `abandoned` remain **derived for display only**
(`app/_workflow_view.py:217-242`) and are never stored. Keeping that split is
important: they are functions of the lease clock, and storing a clock-derived value is
how the lease bug in `lease.py`'s docstring gets reintroduced.

### 1.4 Input request (gates)

```
   OPEN ──► ACCEPTED ──► CONSUMED
     │
     ├──► CANCELLED
     └──► EXPIRED
```

Adopted from Design 2, with `CONSUMED` added. Today consumption is **not a write at
all** — `_service_gate` only reads the payload (`workflow_walker.py:703` →
`frontier.py:429-432`), and nothing ever marks it used. That is benign now, because a
replayed read is idempotent; it stops being benign the moment an agent, rather than a
human, can deposit a second candidate.

---

## 2. Schema

Names are conceptual; FUN-18 may shorten them. **Constraints and ownership are the
contract.**

### 2.1 Runtime identity

| Table | Essential fields | Invariants |
|---|---|---|
| `schema_migrations` | `version`, `checksum`, `applied_at` | one row per applied migration; checksum mismatch **refuses boot** |
| `namespaces` | `id`, `project_key`, `created_at` | unique `project_key`; every runtime row references it |

`schema_migrations` is the direct answer to
[`02-what-exists-today.md`](02-what-exists-today.md) §8.3. The repository already has
this pattern at `_config/vault.py:417` (`_SCHEMA_VERSION`) and `:727-730` (`_upgrade`)
— the substrate plugin simply never got one.

### 2.2 Runs and attempts

| Table | Essential fields | Invariants / indexes |
|---|---|---|
| `runs` | namespace, id, scope_id, parent_run_id, job, surface, status, args_hash, invoke_depth, started_at, ended_at | PK (namespace, id); indexes on (namespace, started_at desc), job, scope_id, parent_run_id |
| `run_attempts` | id, run_id, attempt_no, status, started_at, ended_at, failure_code, failure_detail JSON | unique (run_id, attempt_no); index (run_id, attempt_no) |
| `run_events` | run_id, seq, type, payload JSON, occurred_at | unique (run_id, seq); **append only** |

`args_hash` only — never argument values. Today `compute_args_hash` is already what
the run record stores (`executor.py:936-945`), and that is correct: arguments carry
secrets, and capturing them is a separate redaction and retention decision.

### 2.3 Workflow aggregate

| Table | Essential fields | Invariants / indexes |
|---|---|---|
| `workflow_scopes` | namespace, id, workflow, graph_digest, status, position, lease_owner, lease_expires_at, **lease_generation**, created_at, updated_at, terminal_at | PK (namespace, id); index (status) for resumable; index (lease_expires_at) |
| `workflow_steps` | scope_id, step_key, iteration, status, inputs JSON, result JSON, reusable, started_at, completed_at | unique (scope_id, step_key, iteration) |
| `workflow_branches` | scope_id, decision_key, chosen_target, chosen_at | unique (scope_id, decision_key); **immutable once written** |
| `scope_state` | scope_id, key, value JSON, version, updated_at | unique (scope_id, key); **every write carries the fence** |
| `scope_events` | scope_id, seq, type, payload JSON, occurred_at, run_id | unique (scope_id, seq); append only |

**`scope_state` is where B1 is fixed structurally.** Today it is a separate JSON
document with no generation column and no predicate. As a table with a fenced
predicate, the stale writer's `UPDATE` matches zero rows — it cannot be forgotten by a
future contributor, which is the same reasoning `_mutate`'s single fencing point
already uses (`scope_store.py:238-248`).

Lease fields stay **on `workflow_scopes`** rather than in a `leases` table: there is
exactly one current claim per aggregate, and every transition already conditions that
row. Design 1 reaches the same conclusion with the same reasoning, and it is right.

### 2.4 Interactions and effects

| Table | Essential fields | Invariants |
|---|---|---|
| `input_requests` | id, scope_id, gate_key, generation, status, schema JSON, prompt JSON, created_at, resolved_at | one OPEN request per (scope_id, gate_key, generation) |
| `input_candidates` | id, request_id, source, payload JSON, created_at | append only — a second candidate never overwrites the first |
| `outbox` | id, namespace, aggregate_type, aggregate_id, topic, payload JSON, idempotency_key, status, available_at, claimed_at, published_at, attempts, last_error | unique idempotency_key where present; index (status, available_at) |
| `artifact_refs` | id, run_id, scope_id, step_key, kind, uri, digest, size, media_type, created_at | metadata only — bytes live in a workspace provider |

`input_candidates` being append-only matters more than it looks. Today a second
`deposit_gate_payload` overwrites the first (`scope_store.py:602-611`), so a human
approval followed by an agent suggestion silently replaces the human's answer.

---

## 3. The JSON boundary

Adopted from Design 1 essentially unchanged, because it is correct.

**Columns** — anything used for identity, joins, ordering, filtering, retention,
ownership or a predicate: `status`, `position`, `parent_run_id`, every timestamp,
`seq`, `lease_generation`, `lease_owner`, `lease_expires_at`, job and workflow names,
`args_hash`, artifact `digest` / `uri` / `size`, and every outbox claim field.

**JSON** — genuinely opaque payloads whose shape belongs to someone else: step inputs
and return values, gate schemas, candidate payloads, event detail not used in a
predicate, provider metadata documented as opaque.

The test, stated as a rule a reviewer can apply: **if you would ever want an index on
it, it is a column.**

---

## 4. Transaction catalogue

A transaction surrounds a **transition**, never a job body. Everything in the right
column runs with no transaction open.

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

**`resume` is one transaction, and today it is two.** The deposit
(`app/_workflow_answer.py:228`) and the claim (`frontier.py:183`) are separate locked
writes in different call frames. Today's window is benign because consumption is a
read; with `CONSUMED` in the state machine it would not be, which is why they merge.

### Why never around a job body

Design 1 says this well and it is worth keeping verbatim in spirit: user code may
block, prompt, call a network, or run for hours. Holding a transaction across it holds
locks and connections, makes retries unsafe, and couples database availability to
arbitrary work duration. With `BEGIN IMMEDIATE` on SQLite it would also stop every
other writer in the database — see
[`02-what-exists-today.md`](02-what-exists-today.md) §8.1, where unrelated scopes
already block each other for 3.7 s under a much shorter hold.

---

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

Zero rows updated → `Conflict`, not an exception. Every authoritative write then
carries the held generation in its predicate:

```sql
UPDATE scope_state
   SET value = :value, version = version + 1, updated_at = :now
 WHERE scope_id = :scope AND key = :key
   AND (SELECT lease_generation FROM workflow_scopes
         WHERE namespace_id = :ns AND id = :scope) = :held_generation;
```

Three properties this buys that today's code does not have:

1. **B1 is structurally impossible** — state carries the predicate.
2. **B4 is structurally impossible** — the claim is one atomic statement, so two
   claimers cannot both emerge at generation N.
3. **The owner is implicitly checked**, because a losing claimer never receives
   generation N in the first place — which is a better fix than adding owner to
   `check_generation`, and it is why the repair wave's owner change is a stopgap.

`fencing="cross-process"` in the profile is exactly this property. A store that cannot
provide it says so.

---

## 6. Retention, including the cap nobody has costed

Today: `scopes` carries a **500-record ring cap applied on every write**, evicting
only terminal records (`scope_format.py:133,144,156-197`). A project whose 500 records
are all live stays over cap permanently. Per-scope events carry a second cap of 500
(`scope_format.py:153`, enforced `scope_store.py:418-421`).

Neither Design 1 nor Design 2 mentions either. Two consequences:

- **Migration.** Records already evicted are gone. The import must report what it
  found rather than implying completeness, and the cutover's "verify counts" step
  must compare against the source's *current* contents, not a user's expectation.
- **Target behaviour.** In a relational store the cap should become an explicit
  retention policy — age and count, applied to terminal rows by a maintenance
  operation — not an eviction that runs inside every write. Writing a step record
  should not be able to delete someone else's run.

Deletion rules:

- Live and blocked scopes are never evicted by a cap.
- Deleting a scope cascades state, steps, branches, input requests and scope events in
  one transaction.
- `artifact_refs` cascade the **reference**; the bytes follow workspace retention.
  A runtime database deletion must not silently delete a shared blob — Design 1 says
  this too and it is right.

---

## 7. Migration discipline

- Ordered, checksummed, idempotent at the runner level, serialized by a lock.
- Run during boot step 6.5, **before any job can execute** — which is now possible
  because selection happens before engine construction
  ([`05-the-design.md`](05-the-design.md) §4).
- A partially applied revision is a **boot refusal with repair steps**, never a
  silent continue.
- Tests start from every supported historical schema, not only an empty database.
- `create_all()` is acceptable only for a brand-new empty database. It is not an
  upgrade mechanism — which is precisely the defect
  `CREATE TABLE IF NOT EXISTS` produced in the current plugin.

---

Next: [`07-what-changes.md`](07-what-changes.md) — the file-by-file inventory.
