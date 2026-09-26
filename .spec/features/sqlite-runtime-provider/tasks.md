# FUN-19 — Tasks

Pre-loaded scaffold. **Refine against the code before executing.** Each task should be
1–3 files and completable in one context window.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.

- [ ] **1.1** SqliteRuntimeStore: connection lifecycle and close(), which the current substrate lacks
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **1.2** Schema creation and migration runner wiring
      *Files:* `src/functualize/_primitives/sqlite_store.py`
      *Depends on:* 1.1, 0.1. Calls 0.1's `migrate()` when the store opens (boot step 6.5, before
      any job runs — `contributor/reference/runtime-persistence-data-model.md` §7); this wiring is
      0.1's production call path, so the two close together (below).
- [ ] **2.1** The buffering transaction: accumulate commands, commit once
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **2.2** The writers, with the generation predicate in the WHERE clause
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **3.1** The question-shaped readers
      *Files:* `src/functualize/_primitives/sqlite_store.py`
- [ ] **4.1** The baseline conformance tier
      *Files:* `tests/conformance/test_baseline.py`
- [ ] **4.2** Capability tiers gated on profile fields
      *Files:* `tests/conformance/test_capabilities.py`
- [ ] **5.1** Offline legacy migration with backup, verification and refusal
      *Files:* `src/functualize/_primitives/migrate_legacy.py`
- [ ] **6.1** Run BatchOnlySqliteDriver against the store; prove the transaction buffers
      *Files:* `tests/conformance/`

## Received from `runtime-schema-migrations` (2026-09-26)

The maintainer decided (D3 = B on the runtime-schema wave) that the migration runner and the
relational retention statement are built here, next to the store and the wiring that make them
reachable, instead of in the schema wave where nothing could call them. Their contract is frozen
there: `.spec/features/runtime-schema-migrations/schema.md` §2 (tables), §4 (migration contract)
and §5 (retention) on `feat/runtime-schema-migrations`; after that branch merges, the durable copy
is `contributor/reference/runtime-persistence-data-model.md` §2, §6, §7. Both tasks also consume
that wave's vocabulary (`_types/lifecycle.py` machines, `_types/retention.py` `RetentionPolicy`),
so this branch rebases onto `master` after the schema wave merges and before 0.1 starts.

**Close-together pairs.** *Reachability precedes `[x]`*: 0.1 has no production caller until 1.2
wires it, and 0.2 has none until 0.3 does. Each pair sits in one wave, is built in the order
given, and both boxes are ticked on the second task's sabotage proof — never the first alone.

- [ ] **0.1** Migration runner and revision `0001` (was runtime-schema 5.1)
      *Depends on:* the schema wave merged (lifecycle machines for the `CHECK (status IN …)` lists).
      *Files:* `src/functualize/_primitives/migrations/__init__.py` (`Migration`,
      `MigrationTarget` Protocol, `MigrationRefused`), `src/functualize/_primitives/migrations/runner.py`
      (`migrate(target, migrations) -> int`), `src/functualize/_primitives/migrations/0001_runtime_schema.sql`,
      `tests/primitives/test_migrations.py`
      *Gate:* against stdlib `sqlite3`: empty database → version 1 with one `schema_migrations`
      row; a second run is a no-op; an edited `0001` (checksum mismatch) → `MigrationRefused`; a
      ledger ahead of the shipped set → refused; a gap → refused; every table and index in
      `schema.md` §2 exists (`sqlite_master`); each status `CHECK` list equals its machine's state
      set. The runner depends on the `MigrationTarget` Protocol, not on `sqlite3`, so a
      batch-only substrate (no `BEGIN`) can implement it.
      *Call path:* 1.2 (store open → `migrate`).
- [ ] **0.2** Relational retention statement (was runtime-schema 5.2)
      *Depends on:* 0.1; the schema wave's `RetentionPolicy`.
      *Files:* `src/functualize/_primitives/migrations/retention.py`, `tests/primitives/test_migrations.py`
      *Gate:* on a version-1 database holding 600 evictable and 10 `blocked` scopes (plus runs),
      applying `DEFAULT_RETENTION` leaves 500 evictable + 10 blocked, cascades their steps, state,
      branches, input requests and events, never touches a `running`/`blocked` scope, and never
      deletes an artifact blob (reference rows only).
      *Call path:* 0.3.
- [ ] **0.3** Retention caller — new; nothing in either package planned one
      *Depends on:* 0.2, 1.2.
      *Files:* decided by this package's architecture gate; the hit set of the chosen call path
      plus a test. Candidates, both outside any step write: (a) the store's open path, after
      `migrate()`, bounded by the policy; (b) the existing maintenance verb
      (`purge_scopes`, `app/_workflow_control.py`) routed through the store.
      *Gate:* a production path runs 0.2's statement; sabotage (remove the call) makes a test that
      over-fills the store fail; a step write never runs it.

## Task Dependency Graph

The received tasks shift the scaffold's graph by one wave: 1.2 now waits for 1.1 (the runner
needs a connection) and 2.1 onward move down one. Only the received tasks and 1.2 carry explicit
dependency sets; the rest of the scaffold's edges are still the wave chain it was pre-loaded with
and are refined by this package's own Plan phase.

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "1.1"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "0.1",
        "1.2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "0.2",
        "0.3",
        "2.1"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "2.2"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "3.1"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "4.1",
        "4.2"
      ]
    },
    {
      "id": 6,
      "tasks": [
        "5.1"
      ]
    },
    {
      "id": 7,
      "tasks": [
        "6.1"
      ]
    }
  ],
  "depends_on": {
    "0.1": [],
    "1.2": [
      "1.1",
      "0.1"
    ],
    "0.2": [
      "0.1"
    ],
    "0.3": [
      "0.2",
      "1.2"
    ]
  },
  "close_together": [
    [
      "0.1",
      "1.2"
    ],
    [
      "0.2",
      "0.3"
    ]
  ]
}
```
