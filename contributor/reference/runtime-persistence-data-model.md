# Runtime Persistence Data Model Reference

**Audience:** contributors working on runtime storage, the persistence ports, or workflow resumption.
**Status:** the state machines are the rule and the two stored writers enforce them; the normalized
tables and the SQL that will carry them are still the target.

Migrated from the data-model chapter of the `runtime-persistence-engine-owned` research study
(`06-data-model.md`, written 2026-09-24 at commit `93ecd18`). That research tree does not reach
`master` under the standing merge rule (`.spec/CONSTITUTION.md` § *VCS*; the 2026-09-22
`research-artifacts-cleared` decision), so the study's durable half lives here.

**How to read the tenses.** §1's machines are **landed**: the four tables with their absorbing and
evictable sets are data (`_types/lifecycle.py`, no logic), `_primitives/transitions.py` refuses a
pair no table carries, and both stored writers call it — `ScopeStore.set_scope_status` (`SCOPE`) and
`RunStore.close_run` (`RUN`). §2's tables and the SQL in §5 are the target: the names a normalized
schema will use, the DDL contract, and the retention statement's semantics. What FUN-17 landed is the
vocabulary and the ports that carry them (`_types/persistence.py`), the honest `StoreProfile` of
today's document backend (`_primitives/document_store.py`), and the first transition that goes
through the port — the walk's claim. FUN-18 landed the machines, the check and the retention policy;
FUN-19 owns the tables, the migration runner and the relational retention statement. Anything below
that reads as present tense has been re-read against the tree at `1a0a679`; a still-forward-looking
item says so.

## 1. State machines, before any table

Tables first and transactions second is the wrong order for this codebase: there was no agreed answer
to *which transitions are legal*. Measured at the ports merge (`03fbb64`), scope status was assigned
at **thirteen production call sites across five modules** and validated in none — four of the
thirteen through `DocumentRuntimeStore`, nine by reaching `ScopeStore.set_scope_status` directly —
in **five** vocabularies (`WalkState`, `TERMINAL_SCOPE_STATUSES`, `LIVE_STATUSES`/`TERMINAL_STATES`,
`_SCOPE_STATUS_FOR`, and the status literals in `_primitives/document_store.py`). A schema built on
top of that would have encoded the confusion in DDL.

It is answered now, and answered once. The four machines below are data in `_types/lifecycle.py`;
`_primitives/transitions.py` holds the refusal that reads them; the two writers that store a scope
status and a run status call it, and the SQL in §5 restates the tables rather than deciding them.
`tests/types/test_lifecycle_tables.py` keeps a table from naming a state its own vocabulary does not
have, and `tests/primitives/test_transitions.py` sweeps the whole product ``(states ∪ {None}) ×
states`` per machine rather than a hand-written list of moves.

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

**Δ from this chapter's own tables: the `attempt` machine has no stored writer.** `Attempt` is a
port value and `FinishAttempt` a command, but the document backend's `finish_attempt`
(`_primitives/document_store.py:464-465`) appends the command and writes no attempt row, and no run
record carries one. `ATTEMPT` is therefore enforced where the relational writer lands, and until then
it is exercised directly by `tests/primitives/test_transitions.py`.

### 1.2 Run

The logical unit a user asked for. Holds one or more attempts.

**Δ — the vocabulary is adopted, not invented.** The four-state line this chapter used to carry
(`RUNNING → SUCCEEDED | FAILED | CANCELLED`) is a *projection* of the stored set, not the set. The
run machine is `RunStatus` (`_types/enums.py`), adopted as-is; only its state set is derived from
that enum rather than declared here, lower-cased, because the lower-cased text is what the store
writes.

| From | To | Trigger |
|---|---|---|
| absent | `running` | start run |
| `running`, `blocked`, `skipped`, `unknown` | any state | whatever ends the run — `RunStore.close_run` |
| terminal — `success`, `failure`, `cancelled`, `timeout`, `refused` | — | refused: `IllegalTransition` |

A run opens at `running`, and every state that has not finished may move to **any** state: a run is
reported by what ends it, and the set it may end as is the whole vocabulary. `RunStatus.terminal` is
the absorbing set — one definition, because two copies of that set had already drifted apart once.

The run's status is derived from its last attempt plus its cancellation flag. It is stored anyway,
because deriving it on every history query means joining every attempt.

**Landed.** The machine's one call site is `RunStore.close_run` (`_primitives/run_store.py:259`),
which reads the current value inside the batch it is already writing — so the check audits the write
rather than a stale pre-read. Production writers are `_engine/executor.py`'s finished and failed
paths and `_primitives/document_store.py`'s close. A run the store never opened is ignored rather
than refused (the log is an observation, and a writer that crashed between opening and closing has
already said so), which is why the absent-record edge is not what saves that path.

### 1.3 Workflow scope

The aggregate every other row hangs off, and the status an operator reads to answer "what is this
run doing?". The machine is **landed** — `SCOPE` in `_types/lifecycle.py`, transcribed from this
section — and its one stored writer now refuses a pair the table does not carry.

```
   (absent) ──claim──► RUNNING ──suspend (gate)──► BLOCKED ──resume (gate)──► RUNNING
                         │  │
                         │  ├── complete_step reaching END ──────► COMPLETED
                         │  ├── complete_step, terminal failure ─► FAILED
                         │  ├── complete_step mid-walk ──────────► RUNNING   (self-edge)
                         │  └── cancel ──────────────────────────► CANCELLED
                         │
                         └── resume, from COMPLETED or FAILED: a retry, stamped RUNNING

   CANCELLED is absorbing — nothing leaves it.
   A completed scope's end-of-walk stamp fires twice, so COMPLETED ──► COMPLETED is a legal pair.
```

Legal transitions, exhaustively — the table `IllegalTransition` is raised against:

| From | To | Trigger | Guard |
|---|---|---|---|
| absent | RUNNING | `claim` writing a blank record, then the entry stamp | none |
| RUNNING | RUNNING | every entry's stamp (a resumed walk included), and `complete_step` mid-walk | holds current generation |
| RUNNING | BLOCKED | `suspend` at a gate the walk cannot resolve inline | holds current generation |
| RUNNING | COMPLETED | `complete_step` reaching END | holds current generation |
| RUNNING | FAILED | `complete_step` with a terminal failure | holds current generation |
| RUNNING \| BLOCKED | CANCELLED | `cancel` | holds current generation **or** explicit force |
| FAILED \| COMPLETED | RUNNING | `resume` — a retry re-enters the scope | `resume` refuses only `cancelled` |
| BLOCKED | RUNNING | `resume` | an ACCEPTED input request exists |
| COMPLETED | COMPLETED | the end-of-walk stamp, which fires twice | — |

Everything else is refused, and it is worth knowing exactly what "everything else" is, because four of
them used to be produced: every pair out of `CANCELLED` (5), the two unlisted self-edges
(`BLOCKED → BLOCKED`, `FAILED → FAILED`), the two from a closed scope into `CANCELLED` — `cancel`
refuses a non-live scope (`app/_workflow_control.py:401-405`), so `cancel` reaches only `RUNNING` and
`BLOCKED` — the two out of `COMPLETED` into `BLOCKED` and `FAILED`, and the four in the next
paragraph. A self-edge is legal only where the table lists one. The **Guard** column is the caller's,
not the store's: `set_scope_status` checks the pair and nothing else, and holding the generation is
what makes the lease arm true (§5).

**Four transitional edges were removed, not declared legal.** `blocked → completed`,
`blocked → failed`, `failed → completed` and `failed → blocked` each had a producer at `03fbb64`,
and each producer was a defect rather than a transition. The resumed branch of `FrontierWalk.start`
left the old status in place, so a walk that resumed and then finished wrote `COMPLETED` over a
record that still said `blocked` — and every removed pair was a trace of that one gap. Two more
producers went with them: `blocked → blocked`'s only observation was a direct test setup, because the
port-side scope-status writers in `_primitives/document_store.py` have no production caller at all and
the one production transaction call in that backend (`claim`) writes no status; and the
inline-resolved gate's write-ahead parked a live walk by stamping `BLOCKED` on its way to resolving
the gate. Decision **D2 = 1** is the fix — *every entry into a walk stamps `running`*, first entry or
resume — and the gate slot now goes through `record_gate`, which writes the gate without the
`BLOCKED` stamp.

**Two transitional edges remain, and they are marked as such.** `failed → running` and
`completed → running` carry `# TRANSITIONAL(workflow-persistence-atomic)` beside them in
`_types/lifecycle.py`: when that step lands, a retry may mint a fresh attempt instead of re-entering
the scope, and both edges go with it.

**Absorbing and evictable are different questions, and the old four-state diagram conflated them.**

| Set | Members | The question it answers |
|---|---|---|
| absorbing | `{cancelled}` | what `IllegalTransition` protects — nothing leaves it |
| evictable | `{completed, failed, cancelled}` — the document backend's `TERMINAL_SCOPE_STATUSES` | what a retention cap may drop (§6) |

They coincided under the four-state diagram, and D1 = A separated them: `completed → running` is
reachable through a plain `resume`, so a completed scope is evictable and is no longer absorbing.
`TERMINAL_SCOPE_STATUSES` is now *derived* from `SCOPE.evictable` rather than written out beside it,
and its comment says what the set means now — a cap may drop these, not "a scope can never leave
this" — because the second question is `SCOPE.absorbing`'s and only `cancelled` answers it. The name
is kept for its callers. "Terminal" is deliberately not used as a scope's word — it names the run
machine's absorbing set (§1.2), which is a different claim about a different row.

Two things that table settles which the code used to leave open, and where each stands:

- **A pair outside the table is refused at the write.** **Landed:** `ScopeStore.set_scope_status`
  (`_primitives/scope_store.py:415-421`) reads the current value inside the batch it is writing and
  assigns `require_transition(SCOPE, scope["status"], status)`, so a `completed` scope can only go to
  `completed` or back to `running` (the retry edge) — not to `failed`, `blocked` or `cancelled`.
  The lease predicate that makes the *generation* arm structural is still FUN-19's tables; what
  landed here is the pair rule.
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

**Δ — this status is derived, never stored.** In the document backend there is no request row: the
gate→`InputRequest` projection (`_primitives/document_store.py:394-419`) reads `consumed_at` for
`consumed`, a deposited payload for `accepted`, and `open` otherwise, and says so — `cancelled` and
`expired` have no document shape at all and arrive with the request table. So `INPUT_REQUEST` is
enforced where the relational writer lands, and until then it is exercised directly by
`tests/primitives/test_transitions.py`. What the `(None, "open")` edge means for a legacy record is
deliberate: absent is a state, so an unstatused gate record cannot jump to `consumed` without passing
through `open`.

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
| `schema_migrations` | `version INTEGER`, `name`, `checksum`, `applied_at` | PK `version`, append-only: one row per applied migration, its `checksum` = `sha256(sql)`; a mismatch **refuses boot** |
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
| `workflow_scopes` | namespace, id, workflow, graph_digest, status, position, lease_owner, lease_expires_at, **lease_generation** (`INTEGER NOT NULL DEFAULT 0`), created_at, updated_at, terminal_at | PK (namespace, id); index (status) for resumable; index (lease_expires_at). `terminal_at` is set when the scope enters an **evictable** status (D1) and cleared when a retry re-enters `running` — it is the only column that records when a scope stopped, so an age-based retention query has to use it |
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
| `input_requests` | id, scope_id, gate_key, generation, status, schema JSON, prompt JSON, created_at, resolved_at | PK `id`; partial unique (scope_id, gate_key, generation) `WHERE status = 'open'` — one OPEN request per gate per generation; the `status` column is `CHECK (status IN (…))` generated from §1.4 |
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

The scope document carries a **500-record ring cap applied on every write**, evicting only records
whose status is in the machine's *evictable* set (§1.3), and per-scope events carry a second cap of
500. A project whose 500 records are all live stays over cap permanently — the eviction is
deliberately allowed to miss rather than delete a live run, because a workflow parked at a gate is the
one record that must survive any amount of unrelated traffic.

**Δ — the three caps are one value now.** `SCOPES_LIMIT`, `EVENTS_PER_SCOPE_LIMIT`
(`_primitives/scope_format.py`) and `RUNS_LIMIT` (`_primitives/run_format.py`) each spelled `500` in
its own file; all three read one policy value, `_types/retention.py`'s
`RetentionPolicy(max_records=500, evictable_only=True, max_age=None)`, and a caller that wants a
smaller horizon constructs a policy rather than editing a constant. Which field each trim can read is
a property of the document backend, and the module states it: `scope_format._trim` reads
`max_records` and `evictable_only`; `run_format._trim` reads `max_records` only, because a run log
evicts oldest-first by ULID and carries no status clause to filter on; `max_age` is read by neither,
because a scope record has no creation timestamp and the run log orders by id rather than by clock.
`max_age` is in the shape because the relational statement applies it, and one shape for the policy
beats a second type over there.

The per-**run** event depth is the one cap that is not policy-derived: `EVENTS_PER_RUN_LIMIT` stays a
constant `200`, because it is a depth rather than a record count. `max_records` reaches the
scope-record ring and the run-log ring through their trims and the per-scope event ring through
`EVENTS_PER_SCOPE_LIMIT`.

**Landed consequence worth stating: an evicted scope cannot be retried.** `completed` is evictable
and `resume` accepts a completed scope (D1 = A), so a project that evicts one loses the retry with it
— `resume` answers `workflow_not_found`, the same answer a scope that never existed gets. Nothing
marks the difference, and this chapter records it rather than pretending the cap is lossless.

Two more consequences:

- **Migration.** Records already evicted are gone. An import must report what it found rather than
  implying completeness, and a cutover's "verify counts" step must compare against the source's
  *current* contents, not a user's expectation.
- **Target behaviour.** In a relational store the cap becomes an explicit retention policy — age and
  count, applied to evictable rows by a maintenance operation — not an eviction that runs inside
  every write. Writing a step record should not be able to delete someone else's run. Concretely: the
  statement deletes evictable `workflow_scopes` rows and terminal `runs` rows beyond the count or
  older than `max_age` (using the scope's `terminal_at`), cascading children; it never touches a
  `running` or `blocked` scope, and never runs inside a step write. It is `sqlite-runtime-provider`'s
  (D3 = B), which is why the policy carries `max_age` before anything reads it.

Deletion rules:

- Live and blocked scopes are never evicted by a cap.
- Deleting a scope cascades state, steps, branches, input requests and scope events in one transaction.
- `artifact_refs` cascade the **reference**; the bytes follow workspace retention. A runtime database
  deletion must not silently delete a shared blob.

## 7. Migration discipline

- Ordered, checksummed, idempotent at the runner level, serialized by a lock. A revision is
  `(version: int, name: str, sql: str)` and its checksum is `sha256(sql)`.
- Each revision applies in its own transaction — or its own batch, on a substrate with no `BEGIN` —
  with its `schema_migrations` row written in the same unit, so a crash leaves either both or neither.
- **Forward-only.** No down migration exists, and the recorded version is `max(version)` in
  `schema_migrations`; a rollback is a new forward revision.
- Run during boot step 6.5, **before any job can execute** — which is possible because selection now
  happens before engine construction (ADR-027, landed).
- A partially applied revision is a **boot refusal with repair steps**, never a silent continue.
- Tests start from every supported historical schema, not only an empty database.
- `create_all()` is acceptable only for a brand-new empty database. It is not an upgrade mechanism —
  which is precisely the defect `CREATE TABLE IF NOT EXISTS` produced in the substrate plugin.
- Revision `0001` is the one that creates the schema; every later revision is an ordered upgrade, and
  the runner **refuses** on a checksum mismatch, a gap in the sequence, or a database ahead of the
  code — it never repairs by guessing.

**Forward-looking:** the document backend declares `versioned_migrations=False` and has no schema
version at all, so none of the above runs today. The runner arrives with FUN-19's tables, in the
relational provider (`sqlite-runtime-provider`), which owns the DDL, revision `0001` and the
relational retention statement. What this chapter keeps is the contract those have to satisfy — the
list above — and the tables in §2 that the DDL has to match.

## See also

- [`state-store.md`](state-store.md) §9 — the document store's honest profile, field by field.
- [`workflow-walker.md`](workflow-walker.md) §4 — a resumed walk says `running` for as long as it
  walks, and what that changes for `list_scopes` and `advanceable_scopes`.
- [`workflow-walker.md`](workflow-walker.md) §10 — what a walk refused at the door reports.
- [`substrate-capability-matrix.md`](substrate-capability-matrix.md) — the measurements the profile
  fields are read from.
- `contributor/adr/025-engine-owns-transition-meaning.md`, `026-persistence-ports-need-no-new-layer.md`,
  `027-engine-construction-moves-after-config.md`, `028-storage-is-pluggable-execution-is-not.md`.
