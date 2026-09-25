# Runtime schema — internal types and tables

Source of truth for the tables this wave specifies. Adopted from
`contributor/reference/runtime-persistence-data-model.md` §1–§3, §6–§7 (on `master`), corrected
where the live code at `03fbb64` disagrees. Every correction is marked **Δ** with its evidence.
At clearing, the corrections migrate back into that reference document (task 6.1).

## 1. State machines

Each machine is a closed state set, a legal-transition table and a terminal set. A pair not in the
table is refused with `IllegalTransition(machine, current, target)`. A self-transition is legal
only where listed.

### 1.1 Scope (`ScopeStatus`: `running`, `blocked`, `completed`, `failed`, `cancelled`)

Stored values are the five raw strings `ScopeStore` writes today; `stalled`, `waiting`, `ready`,
`abandoned` stay derived for display (`app/_workflow_view.py`) and are never stored.

| From | To | Trigger | Status |
|---|---|---|---|
| absent | running | `ensure_scope` / `claim` (blank record is `running`, `scope_store.py:91`) | master |
| running | running | `complete_step` mid-walk; `FrontierWalk.start` on a fresh scope | master |
| running | blocked | `suspend` | master |
| running | completed | `complete_step` reaching END; `_close_scope` | master |
| running | failed | `_fail`; `_close_scope` | master |
| running | cancelled | `cancel` | master |
| blocked | running | `resume` (`ResumeWorkflow`) | master |
| blocked | cancelled | `cancel` | master |
| blocked | blocked | a resumed walk suspends again at a later gate (`frontier.py:444`) | **Δ** live |
| blocked | completed | resumed walk reaches END without writing `running` (`frontier.py:411`) | **Δ D2**, `TRANSITIONAL` |
| blocked | failed | resumed walk fails (`workflow_walker.py:1055`) | **Δ D2**, `TRANSITIONAL` |
| failed | running | retry of a failed scope (`resume_scope` refuses only `cancelled`, `_workflow_control.py:306`) | **Δ D1** |
| failed | completed / failed / blocked | a retried walk that never writes `running` — same cause as D2 | **Δ D1+D2**, `TRANSITIONAL` |
| completed, cancelled | anything | — | **refused** |

Terminal set: `{completed, cancelled}` if D1 is accepted; `{completed, failed, cancelled}` if not
(then the three `failed → *` rows are dropped and retry must mint a new scope).
`TERMINAL_SCOPE_STATUSES` (`scope_format.py:133`) is the **eviction** set, not the terminal set,
and keeps `failed` either way: a failed scope may be evicted by the cap without being immutable.

### 1.2 Run (`RunStatus`, `_types/enums.py:12` — adopted, not redefined)

| From | To |
|---|---|
| absent | `Running` |
| `Running`, `Blocked`, `Skipped`, `Unknown` | any `RunStatus` |
| `Success`, `Failure`, `Cancelled`, `Timeout`, `Refused` | — refused |

The terminal set is exactly `RunStatus.terminal` (`enums.py:46-76`). **Δ** master's four-state
run diagram is a projection of this, not a second vocabulary. The run log stores
`RunStatus.value.lower()` (`executor.py:1096,1108`; `run_store.py:229` opens at `running`), so the
check compares lower-cased values. Production writers of a run's status: `RunStore.close_run`
(`run_store.py:241`), reached from `executor.py:1096,1108` and `document_store.py:980`.

### 1.3 Attempt (`AttemptStatus`: `running`, `succeeded`, `failed`, `skipped`, `cancelled`)

| From | To |
|---|---|
| absent | running |
| running | succeeded, failed, skipped, cancelled |
| any terminal | — refused; a retry inserts attempt `n+1` |

No live stored writer at `03fbb64` beyond `_DocumentTransaction.finish_attempt`; the table is
enforced where the relational writer lands.

### 1.4 InputRequest (`InputRequestStatus`: `open`, `accepted`, `consumed`, `cancelled`, `expired`)

| From | To |
|---|---|
| absent | open |
| open | accepted, cancelled, expired |
| accepted | consumed |
| consumed, cancelled, expired | — refused |

**Δ** the document backend derives this status (`document_store.py:399-414`); nothing stores it
at `03fbb64`. The table is enforced by the relational writer (`gate-interactions-outbox`).

## 2. Relational schema v1 (migration `0001`)

One row per step, never one row per document: a D1 row caps at 2 MB and the scopes envelope grows
without bound. Every table carries `namespace_id` directly or through its parent's foreign key.
Timestamps are ISO-8601 UTC `TEXT`; statuses are `TEXT` with a `CHECK (status IN (...))` generated
from §1 (see plan.md → *Surviving smells*, primitive obsession).

| Table | Columns | Keys, constraints, indexes |
|---|---|---|
| `schema_migrations` | `version INTEGER`, `name TEXT`, `checksum TEXT`, `applied_at TEXT` | PK `version`; append only |
| `namespaces` | `id TEXT`, `project_key TEXT`, `created_at TEXT` | PK `id`; UNIQUE `project_key` |
| `runs` | `namespace_id`, `id`, `scope_id`, `parent_run_id`, `job`, `surface`, `status`, `args_hash`, `invoke_depth INTEGER`, `started_at`, `ended_at` | PK (`namespace_id`, `id`); IX (`namespace_id`, `started_at` DESC), (`job`), (`scope_id`), (`parent_run_id`) |
| `run_attempts` | `id`, `run_id`, `attempt_no INTEGER`, `status`, `started_at`, `ended_at`, `failure_code`, `failure_detail JSON` | UNIQUE (`run_id`, `attempt_no`); FK `run_id` ON DELETE CASCADE |
| `run_events` | `run_id`, `seq INTEGER`, `type`, `payload JSON`, `occurred_at` | UNIQUE (`run_id`, `seq`); append only; FK CASCADE |
| `workflow_scopes` | `namespace_id`, `id`, `workflow`, `graph_digest`, `status`, `position`, `lease_owner`, `lease_expires_at`, `lease_generation INTEGER NOT NULL DEFAULT 0`, `created_at`, `updated_at`, `terminal_at` | PK (`namespace_id`, `id`); IX (`status`), (`lease_expires_at`) |
| `workflow_steps` | `scope_id`, `step_key`, `iteration INTEGER`, `status`, `inputs JSON`, `result JSON`, `reusable INTEGER`, `started_at`, `completed_at` | UNIQUE (`scope_id`, `step_key`, `iteration`); FK CASCADE |
| `workflow_branches` | `scope_id`, `decision_key`, `chosen_target`, `chosen_at` | UNIQUE (`scope_id`, `decision_key`); immutable once written; FK CASCADE |
| `scope_state` | `scope_id`, `key`, `value JSON`, `version INTEGER`, `updated_at` | UNIQUE (`scope_id`, `key`); every write carries the fence predicate; FK CASCADE |
| `scope_events` | `scope_id`, `seq INTEGER`, `type`, `payload JSON`, `occurred_at`, `run_id` | UNIQUE (`scope_id`, `seq`); append only; FK CASCADE |
| `input_requests` | `id`, `scope_id`, `gate_key`, `generation INTEGER`, `status`, `schema JSON`, `prompt JSON`, `created_at`, `resolved_at` | PK `id`; partial UNIQUE (`scope_id`, `gate_key`, `generation`) WHERE `status = 'open'`; FK CASCADE |
| `input_candidates` | `id`, `request_id`, `source`, `payload JSON`, `created_at` | PK `id`; append only; FK CASCADE |
| `outbox` | `id`, `namespace_id`, `aggregate_type`, `aggregate_id`, `topic`, `payload JSON`, `idempotency_key`, `status`, `available_at`, `claimed_at`, `published_at`, `attempts INTEGER`, `last_error` | PK `id`; partial UNIQUE `idempotency_key` WHERE NOT NULL; IX (`status`, `available_at`) |
| `artifact_refs` | `id`, `run_id`, `scope_id`, `step_key`, `kind`, `uri`, `digest`, `size INTEGER`, `media_type`, `created_at` | PK `id`; metadata only — bytes live in the workspace provider; deleting a row never deletes a blob |

Lease fields stay on `workflow_scopes` (one current claim per aggregate). `args_hash` only — never
argument values.

## 3. The JSON boundary

**Column** if it is used for identity, joins, ordering, filtering, retention, ownership or a
predicate. **JSON** if its shape belongs to someone else (step inputs and results, gate schemas,
candidate payloads, event detail not used in a predicate). Reviewer's rule: *if you would ever
want an index on it, it is a column.*

## 4. Migration contract

- A migration is `(version: int, name: str, sql: str)`; `checksum = sha256(sql)`.
- Versions are contiguous from 1 and applied in order, each in its own transaction (or its own
  batch on a substrate with no `BEGIN`), with its `schema_migrations` row in the same unit.
- **Forward-only:** no down migration exists. The recorded version is `max(version)` in
  `schema_migrations`.
- **Refusals** (typed error, never a silent continue): a recorded checksum differs from the
  shipped one; the recorded version is ahead of the shipped set; a gap in recorded versions.
- `create_all()`-style `IF NOT EXISTS` DDL is allowed only inside migration `0001` against an
  empty database, never as an upgrade path.

## 5. Retention

`RetentionPolicy(max_records=500, terminal_only=True, max_age=None)` — one value.

- Document backend: `scope_format._trim` (`SCOPES_LIMIT`, `EVENTS_PER_SCOPE_LIMIT`) and
  `run_format._trim` (`RUNS_LIMIT`) read their counts from the policy; they still apply at write
  time because the document backend has no maintenance operation (decision D3).
- Relational: a maintenance statement deletes terminal `workflow_scopes` / `runs` rows beyond the
  count or older than `max_age`, cascading children, never a live or blocked scope, and never
  inside a step write.
