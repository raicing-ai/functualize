# FUN-19 — Tasks

Refined 2026-10-05 against `e8e3b867` and the approved shape SD/12583004. Each task is 1–3
production files plus its tests, and fits one context window.

**Wave ordering is binding:** never start a task in wave N+1 while wave N has unchecked tasks.
**Reachability precedes `[x]`:** name the production call path and prove it by breaking the call
and watching a test fail. **Commit before sabotaging.**

**Decisions answered** (maintainer, MCH-149, 2026-10-05 10:16:48Z): **D-1 a, D-2 a, D-3 refuse**
— all as recommended, so the tasks below carry the recommended shape.

**Every wave is reachability-closed** (revised 2026-10-05 after the first execute run returned
`WORKFLOW_AMBIGUOUS`). The previous graph put close-together pairs in different waves — task 1
(wave 0) closed with task 3 (wave 1), tasks 5 and 6 (wave 2) with task 7 (wave 3) — and task 2's
call path was task 15, four waves later. Under the binding wave rule a pair split across waves can
never be ticked: wave N cannot clear until its pair partner in N+1 proves reachability, and N+1
cannot start until N clears. Now each task's production call path is in **its own wave or an earlier
one**, and every close-together pair sits in one wave, built in `depends_on` order and ticked
together on the last member's sabotage proof. The rule itself, *reachability precedes `[x]`*, the
19 tasks, the decision gates and every acceptance gate are unchanged. The check that holds this,
run at authoring time, is at the foot of this file.

PLUGIN below means
`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/`, and
PLUGIN_TESTS means `plugins/substrates/functualize-substrate-sqlite/tests/`.

## Received from `runtime-schema-migrations` (2026-09-26) — where those tasks went

The maintainer decided (D3 = B) that the migration runner and the relational retention statement
are built here, next to the store that makes them reachable. Their contract is frozen in
`contributor/reference/runtime-persistence-data-model.md` §2 (tables), §6 (retention) and §7
(migrations) — on `master` since #61. The received file paths under `src/functualize/_primitives/`
are replaced by plugin paths (`plan.md` → *Iteration log*, candidate E); the gates are unchanged.

| Received | Now |
|---|---|
| 0.1 migration runner + revision `0001` | task 6 (closes with task 7) |
| 0.2 relational retention statement | task 11 |
| 0.3 retention caller | task 11 (caller = `prepare()`, option (a)) |

## Wave 0 — the selection seam, reachable through the built-in documents factory

- [x] **1** Factory vocabulary
      *Files:* `src/functualize/_types/persistence.py`, `src/functualize/_types/errors.py`,
      `tests/types/test_runtime_store_port.py`
      *Do:* add `RuntimeStoreConfig`, `PreparedStore`, `RuntimeStoreFactory` (contracts §2) and
      `RuntimeStoreSelectionError` (contracts §5). No logic.
      *Gate:* `uv run lint-imports` green (types import nothing internal); mypy accepts a minimal
      factory as `RuntimeStoreFactory`; `isinstance` refuses an object missing `prepare`.
      *Call path:* task 3, same wave — `_app/store_selection.py` builds a `RuntimeStoreConfig` and calls
      `factory.prepare` (closes together with 2 and 3).
- [x] **2** Host registration
      *Files:* `src/functualize/_types/host.py`, `src/functualize/_app/impl.py`,
      `src/functualize/app/core.py`
      *Do:* `register_runtime_store_factory` (contracts §3) storing into
      `app._runtime_store_factories`; refused once a store is selected, as `offer_substrate` is.
      Boot itself is its first production caller: task 3 registers the built-in documents factory
      **through this host method**, on both boot paths, before plugins load.
      *Gate:* registration after selection raises `SubstrateInstallError`-style refusal; two factories
      for one scheme are both kept (the refusal is task 3's); `tests/test_facade_loc_limits.py`
      green; `tests/types/test_plugin_host_port.py` green.
      *Call path:* `boot_standard` / `boot_static` → `app.register_runtime_store_factory(DocumentRuntimeStoreFactory(app))`
      (task 3, same wave); plugins join it in wave 1 (task 15). Closes together with 1 and 3.
- [x] **3** Store selection at step 6.5
      *Depends on:* 1, 2; D-3 for the guard.
      *Files:* `src/functualize/_app/store_selection.py` (new), `src/functualize/_app/boot.py`,
      `tests/app/test_store_selection.py`
      *Do:* `DocumentRuntimeStoreFactory(app)` (scheme `documents`, `DOCUMENT_PROFILE`; `prepare` =
      today's body: `_resolve_substrate_claim`, override or `substrate_for_project`,
      `DocumentRuntimeStore`), registered by boot through task 2's host method before plugins load.
      Resolve `runtime_store.url`; **unset is read as `documents:`** after the D-3 guard (any other
      factory's `unselected_data()` → `RuntimeStoreSelectionError`); then one path for every
      scheme: registry lookup (unknown scheme or two claimants → refuse) → `prepare()` **uncaught**
      → `check_required_capabilities`. Keep `_select_runtime_store(app) -> tuple[RuntimeStore,
      StoreSubstrate]` as the one call both boot paths make; its body delegates.
      *Gate:* unset → documents through the registered documents factory; `documents:` → the same;
      with a stub factory: `stub:` → stub store and its substrate; unknown
      scheme → refusal naming the key and the registered schemes; `prepare` raising → boot raises;
      on `boot_standard` **and** `boot_static`.
      *Sabotage:* (i) replace the delegate with today's body → the `stub:` test fails on both paths;
      (ii) drop boot's documents-factory registration → the unset/`documents:` tests fail on both
      paths. (ii) is task 2's proof; (i) closes 1 and 3. Tick 1, 2, 3 together.
      *Done (`1ebf364f`, 2026-10-05):* sabotage (i) — the delegate replaced by the pre-change
      body — failed 12 of 22 selection tests, every `stub:`, unknown-scheme, duplicate-claim
      and D-3 case, on `[static]` and `[standard]`; (ii) — boot's documents-factory
      registration dropped — failed 14 of 22, every unset and `documents:` case, on both
      paths. Restored by `git checkout`; 22/22 again. Also touched, beyond the listed files:
      `tests/types/fixtures/runtime_store_factory_conformance.py` (task 1's mypy gate, the
      pattern of the port's own fixture), `tests/types/test_plugin_host_port.py` (member pin
      12 → 13), `tests/test_facade_loc_limits.py` (budget 305 → 307, measured and recorded),
      `tests/core/test_store_capability_refusal.py` (its stand-in app now carries the
      registry boot builds).
- [x] **4** Public surface
      *Depends on:* 1.
      *Files:* `src/functualize/plugin/__init__.py`, `tests/test_public_api_surface.py`
      *Gate:* the surface test lists exactly contracts §4's additions for the answered D-2 option.
      *Call path:* none of its own — re-exports carry no executable path; the surface test is the gate.
      First importers: task 15 (wave 1) and task 12 (wave 4), which use only `functualize.plugin`.
      *Done (`1ebf364f`):* 35 names of `_types/persistence.py.__all__` plus
      `IllegalTransition`, `RuntimeStoreCapabilityError`, `RuntimeStoreSelectionError`;
      `tests/test_public_api_surface.py` pins exactly those 38. The suite row is tasks 12–13.

## Wave 1 — the SQLite store opens, reachable through the plugin

- [x] **5** Driver
      *Files:* `PLUGIN/_driver.py`, `PLUGIN_TESTS/test_driver.py`
      *Do:* `SqlDriver` Protocol `{batch, query, close}`; `LocalSqliteDriver`: one connection per
      thread, all closed by `close()`; `PRAGMA foreign_keys=ON` per connection; WAL only for a file;
      busy timeout → `SqliteBusyError(retryable=True)`; `batch` = `BEGIN IMMEDIATE … COMMIT`, all or
      nothing (I-5).
      *Gate:* foreign key violation refused; `:memory:` gets no WAL; a held write lock past the
      timeout raises `SqliteBusyError`, not `sqlite3.OperationalError`; a failing statement rolls the
      whole batch back; `close()` leaves no open connection (thread test).
      *Call path:* task 15 → task 3 → task 7's `prepare` → this driver, same wave (closes
      together with 6, 7, 15).
      *Done (`4563309f`, 2026-10-05):* every gate case in `test_driver.py` (FK refusal, WAL vs
      `:memory:`, held write lock → `SqliteBusyError` with `retryable is True` and not an
      `OperationalError`, whole-batch rollback, per-statement rowcounts, `close()` bringing 4
      threads' connections to 0, unopenable path failing at construction). Reachability is the
      group's sabotage (ii), under task 15.
- [x] **6** Migration runner and revision `0001` (was 0.1)
      *Files:* `PLUGIN/_migrations.py`, `PLUGIN/_schema/0001_runtime_schema.sql`,
      `PLUGIN_TESTS/test_migrations.py`
      *Do:* `Migration(version, name, sql)`, checksum `sha256(sql)`; `migrate(driver, migrations) -> int`
      applying each revision and its `schema_migrations` row in **one batch**; `MigrationRefused`.
      DDL = data model §2 plus `runtime_cutover` (contracts §7).
      *Gate (received, unchanged):* empty database → version 1 with one `schema_migrations` row; a
      second run is a no-op; an edited `0001` → `MigrationRefused`; a ledger ahead of the shipped
      set → refused; a gap → refused; every table and index of §2 exists (`sqlite_master`); each
      status `CHECK` list equals its machine's state set in `_types/lifecycle.py`. Runs against
      `LocalSqliteDriver`; the same runner over `BatchOnlySqliteDriver` is proven by task 14 (AC-5),
      in wave 4 — not a gate of this task, so nothing here waits on a later wave.
      *Call path:* task 15 → task 3 → task 7's `prepare` → `migrate`, same wave (closes together
      with 5, 7, 15).
      *Done (`4563309f`, 2026-10-05):* `test_migrations.py` covers every gate case, including the
      parametrized `CHECK`-list equality against `SCOPE`, `RUN`, `ATTEMPT` and `INPUT_REQUEST`, the
      no-ledger-with-runtime-tables refusal, a legacy `documents`-only database migrating, a failing
      revision leaving neither schema nor ledger, append-only triggers and scope-delete cascading
      the `artifact_refs` reference only.
- [x] **7** Store facade, profile, buffered transaction, factory
      *Depends on:* 3, 5, 6.
      *Call path:* task 15, same wave — the plugin registers this factory, selection calls `prepare`.
      *Files:* `PLUGIN/_runtime_store.py`, `PLUGIN/_transaction.py`, `PLUGIN/_factory.py`
      *Do:* `SQLITE_PROFILE` (`spec.md` §1 table); `SqliteRuntimeStore(driver)` with `transaction()`
      returning `_BufferedTransaction` (writers append statements; `__exit__` → one
      `driver.batch`; nothing on error); `SqliteRuntimeStoreFactory.prepare`: driver → `migrate`
      → legacy guard (`LegacyImportRequired` when `documents` holds runtime keys and no
      `runtime_cutover` row) → store. **Guard contract amended 2026-10-06 (contracts §6a):** the
      predicate above cannot tell a born-relational file from a pre-relational one, and the
      repair is task 20. This box stays ticked for what it proved; the guard is re-proven there; `PreparedStore.substrate` = `SQLiteSubstrate` on the same file.
      *Gate:* `prepare` on an empty path → version 1; a doctored checksum → `MigrationRefused` out of
      `prepare`; legacy runtime keys present → `LegacyImportRequired` naming
      `functualize-sqlite-import`; a raising writer inside `with store.transaction()` leaves zero
      rows.
      *Sabotage:* remove the `migrate()` call from `prepare` → the version-1 test **through boot with
      `sqlite:`** (task 15's harness) fails.
      *No class over 500 lines; the facade ≤150.*
      *Done (`4563309f`, 2026-10-05):* the facade is 80 lines; `prepare` closes the driver on every
      failure path. Hand-over item 1 checked: the factory returns a `SQLiteSubstrate` on the same
      file, never `None` (pinned by test). Sabotage — `migrate()` removed from `prepare` — failed 6
      of 19 selection tests: `test_sqlite_configured_selects_the_sqlite_store_migrated` and
      `test_a_doctored_checksum_aborts_boot_never_falling_back`, each on `boot_static`, `func`-cold
      and `func`-warm. Restored by `git checkout`; 81/81 again.
- [x] **15** The plugin registers instead of offering
      *Depends on:* 2, 3, 7.
      *Files:* `PLUGIN/_plugin.py`, `PLUGIN/__init__.py`, `PLUGIN_TESTS/test_plugin_selection.py`
      *Do:* `__call__` → `register_runtime_store_factory(SqliteRuntimeStoreFactory())`; delete the
      `offer_substrate` call, `_choose_substrate`, `_configured_path` and
      `plugin.substrate-sqlite.db_path` (no shim); `unselected_data` reports a `state.db` holding
      runtime keys (D-3).
      *Gate (E-1):* plugin installed + nothing configured → documents store, filesystem substrate;
      `runtime_store.url = "sqlite:"` → `SqliteRuntimeStore`; `prepare` sabotaged (unwritable
      path; doctored checksum) → boot fails on `func` cold, `func` warm and `boot_static`, never on
      documents. `tests/plugins/test_substrate_choice_is_not_hook_order.py` stays green.
      *Sabotage:* (i) restore the `offer_substrate` call → the "nothing configured → filesystem" test
      fails; (ii) drop the `register_runtime_store_factory` call → the `sqlite:` boot test fails with
      an unknown-scheme refusal. (ii) is the reachability proof for 5, 6, 7 and 15 — tick all four
      together.
      *Done (`4563309f`, 2026-10-05):* E-1 green on `boot_static`, `func`-cold and `func`-warm —
      including the real `func` entry refusing a doctored schema on cold and warm boot; the D-3
      refusal names `functualize-sqlite-import` and the remedy line; `unselected_data` also reports
      a relational `state.db`, and explicit `documents:` still starts fresh beside legacy SQLite
      data. `test_substrate_choice_is_not_hook_order.py` green (updated: storage is chosen by
      configuration, so every boot there writes `sqlite:`). Sabotage (i) — `offer_substrate`
      restored — failed 7 of 19 (every unconfigured-→-documents case on all three paths, plus the
      no-offer pin); (ii) — the registration dropped — failed 13 of 19, the `sqlite:` boot with
      `RuntimeStoreSelectionError: … names the scheme 'sqlite', which no registered runtime store
      serves (registered: documents)`. Both restored by `git checkout`; 81/81 again. (ii) is the
      proof that ticks 5, 6, 7 and 15 together.
      *Also touched, beyond the listed files* (installed-means-selected pins that had to become
      selected-means-selected): `PLUGIN_TESTS/test_sqlite_substrate.py`,
      `tests/_cli/test_shell_mode.py`, `tests/core/test_app_ready_and_shutdown.py` (its
      construction-failure escape now raises `OSError` out of `prepare`, not `SubstrateInstallError`
      out of a chooser), `tests/plugins/test_substrate_offer.py`,
      `tests/spec/test_a_substrate_plugin_loads_through_its_entry_point.py` (gains the cold/warm
      `func` refusal test),
      `tests/spec/test_disabled_is_honoured_by_the_builtin_commands.py`, and
      `tests/integration/test_substrate_durability.py`, which is `xfail(strict=True)` marked
      `TRANSITIONAL(sqlite-runtime-provider waves 2-3, tasks 8-10)` — its two workers select
      `sqlite:` now, and the selected store refuses every writer with `NotImplementedError` until
      the writer waves bind them, so the marker errors the moment that passes and must be removed
      with the re-pointed assertion then.

## Wave 2 — writers

- [x] **8** Workflow writers
      *Files:* `PLUGIN/_workflow_sql.py`, `PLUGIN_TESTS/test_workflow_sql.py`
      *Call path:* the selected store's `transaction().workflows` (wave 1) → `_BufferedTransaction` → here.
      *Sabotage:* unbind the workflow writer from `_BufferedTransaction` → a boot-selected `sqlite:`
      claim test fails.
      *Do:* `claim` (data model §5's conditional update; zero rows → `Conflict` value),
      `complete_step`, `suspend`, `resume`, `cancel`, `write_state` — every scope mutation carries
      the held generation in its predicate (I-3); every status move checked against FUN-18's table
      (`IllegalTransition`). Claim is the one writer that commits on the spot (as
      `ClaimWorkflow`'s docstring says) — one batch of one statement, then a read.
      *Gate:* stale generation → zero rows, live value survives; `cancelled` → `running`
      refused, while `completed` → `running` remains the lifecycle table's retry edge;
      `rg -n "resume" PLUGIN/_workflow_sql.py` shows no conditional on it (05 §3).
      *Done (`1eccab80`):* a stale generation is refused up front
      (`StaleGenerationError`), and a takeover between check and commit makes the staged
      writes match zero rows with the live value intact. `cancelled → running` raises
      `IllegalTransition`; a `completed` scope resumes at a new generation as the lifecycle
      table requires. `claim` sends one batch of one conditional UPSERT statement, then reads;
      a live competing holder receives `Conflict`. `rg -n "resume"` finds only the method,
      with no command-specific status branch. Unbinding `.workflows` in
      `BufferedTransaction` makes the boot-selected claim test fail with
      `NotImplementedError: SqliteRuntimeStore.workflows.claim`; restoration passes.
      Gate correction: the prior `completed → running refused` wording contradicted
      `_types/lifecycle.SCOPE` and the data model's retry edge. The UPSERT combines
      create-if-absent with the data model's conditional lease update in one statement.
- [x] **9** Run, input, event and effect writers
      *Files:* `PLUGIN/_run_sql.py`, `PLUGIN_TESTS/test_run_sql.py`
      *Call path / sabotage:* as task 8, through `transaction().runs`, `.inputs`, `.events`, `.effects`.
      *Gate:* attempt `(run_id, attempt_no)` unique; `run_events`/`scope_events` `seq` strictly
      increasing per owner; one OPEN input request per gate per generation; an `outbox` row commits
      only with its transition.
      *Done (`26de1a9c`, `98c12015`):* all four gate items have tests in `test_run_sql.py`; sabotage — each of
      `.runs`, `.inputs`, `.events`, `.effects` unbound in turn — fails
      `test_a_boot_selected_store_writes_runs_inputs_events_and_effects` with that writer's
      `NotImplementedError`, and restoration gives 124/124 plugin tests. A takeover between
      a fenced state write and commit drops both the stale write and its outbox intent;
      removing the outbox fence makes that regression test fail. Also touched beyond the listed files:
      `_transaction.py` (writers bound, the unit's pending view, the fence helpers),
      `_runtime_store.py` (owns the `default` namespace row; hands the transaction its driver),
      `test_runtime_store.py` (counts exclude the store's own namespace; the writer half of the
      "not yet built" test is gone because the writers are).

## Wave 3 — readers and retention

- [x] **10** Readers
      *Files:* `PLUGIN/_readers.py`, `PLUGIN_TESTS/test_readers.py`
      *Call path:* the selected store's `runs` / `workflows` / `inputs` attributes (wave 1), read by the
      engine; sabotage = bind a reader stub on the facade → the boot-selected read test fails.
      *Do:* `RunReader`, `WorkflowReader`, `InputReader` as SQL over the §2 tables; indexes used for
      `recent`, `resumable` (`EXPLAIN QUERY PLAN` names the index).
      *Gate:* S-6 raw-SQL test — a status count answered by `SELECT … GROUP BY status` with no JSON
      function.
      *Done:* SQL readers are bound on the selected store in `_runtime_store.py`; `EXPLAIN QUERY
      PLAN` names `runs_recent` and `workflow_scopes_status` for the reader queries. The raw SQL
      status-count test passes. After committing, replacing the run reader binding with a stub
      failed the boot-selected read test; restoring it passed.
- [x] **11** Relational retention and its caller (was 0.2 + 0.3)
      *Depends on:* 7, 8, 9.
      *Files:* `PLUGIN/_retention.py`, `PLUGIN/_factory.py`, `PLUGIN_TESTS/test_retention.py`
      *Gate (received, unchanged):* a version-1 database with 600 evictable and 10 `blocked` scopes
      (plus runs), after `DEFAULT_RETENTION`, holds 500 evictable + 10 blocked; steps, state,
      branches, input requests and events cascade; no `running`/`blocked` scope is touched; no
      artifact blob is deleted (reference rows only). A step write never runs it.
      *Call path:* `prepare()` after `migrate()`.
      *Sabotage:* remove the call from `prepare` → the over-filled-store test fails.
      *Done:* `prepare()` applies retention after migration. The seeded version-1 test trims 600
      completed scopes and runs to 500 each, keeps 10 blocked and one running scope, cascades
      child rows, preserves the artifact blob, and proves a step write does not trim. After
      committing, removing the `prepare()` call left 600 completed scopes and failed the gate;
      restoring it passed. The strict cross-process durability xfail in
      `tests/integration/test_substrate_durability.py` remains: its first worker reports the
      scope was taken before the gate, so binding readers did not make that engine path pass.
      The marker now names that remaining mixed engine persistence path.

## Wave 4 — the conformance suite (AC-1, AC-2, AC-5)

- [x] **12** BASELINE tier
      *Depends on:* 4, 7–10.
      *Files:* `src/functualize/testing/conformance/__init__.py`,
      `src/functualize/testing/conformance/baseline.py`, `tests/conformance/test_baseline.py`
      *Do:* 08's list — run tree and recent history; workflow transition and replay determinism;
      state batch and rollback; corrupt-data policy; event sequence monotonicity; close/reopen
      durability. Takes `make_store: Callable[[Path], RuntimeStore]`; imports only public names.
      *Call path:* this is a shipped test library (D-2 a), so its consumer *is* a test suite — its
      production surface is the public import `functualize.testing.conformance`, proven by
      `tests/conformance/` importing nothing private.
      *Gate (AC-2 first half):* green for `DocumentRuntimeStore` **and** `SqliteRuntimeStore`.
      *Done (`3dbc2266`):* six checks green over both stores (15 passed). Sabotage (i) SQLite
      `recent()` ordered oldest-first → only `run tree and recent history [sqlite]` red;
      (ii) a private import added to `baseline.py` → the import-surface test red. Deviation: the
      document store has no public constructor, so `tests/conformance/` reaches it by booting an
      app in a project directory and reading `app.execution_engine._runtime_store` — an attribute,
      not an import. Inputs are covered up to `suspend`/`open_for`/`awaiting`/`request`:
      `GateCandidate` is not public, so a third-party suite cannot append candidates.
- [x] **13** Capability tiers
      *Depends on:* 12.
      *Files (signature frozen in contracts §4a, 2026-10-06):*
      `src/functualize/testing/conformance/hooks.py` (new), `src/functualize/testing/conformance/capabilities.py`,
      `src/functualize/testing/conformance/__init__.py`, `tests/conformance/sqlite_hooks.py` (new),
      `tests/conformance/test_capabilities.py`, `tests/test_public_api_surface.py`. That is six files
      against the usual 1–3, on purpose: it is one public signature, and it does not split without
      leaving a surface that has no caller.
      *Do:* `HarnessHooks`, `StatementFaults`/`StatementFault`, `OutboxProbe`/`RecordedIntent`,
      `MigrationHarness`, `TierRun`/`CapabilityReport`, `capability_report`; a keyword-only `hooks=`
      on `run_capability_tiers` with an unchanged return type; tiers per rules H-1…H-7 —
      `cross_aggregate_atomicity` faults between every **statement** (E-3); `fencing ==
      "cross-process"` as now (E-2); `durable_outbox` crash before/after commit (recording only —
      the dispatcher is FUN-21's); `versioned_migrations` every historical schema plus each refusal
      (I-9); and the new `offline_capable=True` tier (H-6). SQLite's three hooks go in
      `tests/conformance/sqlite_hooks.py`. Remove the strict xfail and its `TRANSITIONAL` marker.
      *Gate (AC-1, AC-2 second half), as the profiles actually stand:*
      - **SQLite**, with its hooks, runs and passes all **five** tiers it declares. The report's
        strengths say statement-level atomicity, both outbox crash points, `N ≥ 2` historical
        schemas and `M ≥ 3` refusals, and the network refused.
      - **Document store**, no hooks, runs exactly `("fencing='cross-process'", "offline_capable=True")`
        and passes both. Its profile declares `cross_aggregate_atomicity`, `durable_outbox` and
        `versioned_migrations` `False`, so those three tiers do not run (AC-2).
      - **Chosen by the profile, not a list:** the document store re-declared with
        `cross_aggregate_atomicity=True` and no hooks runs that tier, which **fails** with H-2's
        missing-`statement_faults` message. That replaces today's assertion that it passes.
      - SQLite with `hooks=None` fails on H-2 for its first hook-needing tier and never skips it.
      - `functualize._types.persistence.__all__` and `functualize.plugin.__all__` are unchanged
        (`git diff` on both is empty); `functualize.testing.conformance.__all__` equals contracts
        §4a's list in the surface test.
      *Sabotage (each must turn its tier red; all of them tick 13):* (i) a unit that raised still
      commits → atomicity red; (ii) `SqliteRuntimeStore`'s commit split into two `batch` calls whose
      leading batch carries a **write the ports expose** (e.g. `statements[:2]` and
      `statements[2:]`) → the statement-fault tier red. The command-level check cannot see this; it
      is the reason for the hook. A split whose leading batch carries only the unit's first
      `workflow_steps` insert (`[:1]`) is **not** observable through the ports, so it is a
      documented limit of this tier rather than a second form of (ii): the tier names the limit in
      its docstring and in its strength, and the limit's repair is its own issue, MCH-156.
      (iii) the outbox `INSERT` staged in a separate batch after the step → the crash-after
      check red, or the crash-before check if the order is reversed; (iv) the migration runner's
      checksum comparison removed → the `"checksum"` refusal red; (v) a `socket.create_connection`
      call added to `prepare` → the offline tier red; (vi) fencing as today, all three guards
      removed → red.
      *Reported, not gated:* H-7 — the fencing tier observes the outcome, not which guard held it;
      likewise `cross_aggregate_atomicity` observes the two scopes' positions and the run count, so
      a split whose leading batch writes no port-visible row is a limit it reports (MCH-156).
      *Evidence (`cbe7f3a5`), not ticked:* `cross_aggregate_atomicity` and `fencing ==
      "cross-process"` (two OS processes, fork) pass on SQLite; sabotage — a faulted unit still
      committing → atomicity red (`('a1', None, 0)` left); the fence check and predicate removed →
      the cross-process tier red (`position='stale'` landed). Tiers are chosen by profile only
      (`tiers_for`), and declaring atomicity on the document store makes the tier run.
      *Evidence (`acfbd2b8`), not ticked — five of the six sabotage checks redden, (ii) does not:*
      each sabotage applied alone to a clean tree at `acfbd2b8`, then restored: (i) → `atomicity`
      red (`a fault after 1 command(s) left ('a1', None, 0)`); (iii) → `durable_outbox` red (`a
      crash inside the transaction left intents: [RecordedIntent(… idempotency_key='idem-a')]`);
      (iv) → `versioned_migrations` red (`damaged store (checksum) opened without refusing`);
      (v) → `offline_capable` red (`OSError: the network was taken away: create_connection
      refused`); (vi), all three fencing guards gone — `require_fence`'s raise, `fence_sql`'s
      predicate and `_move`'s own `AND lease_generation = ?` — → `fencing == "cross-process"` red
      (`the stale process's write landed: … position='stale' …`). **(ii) leaves the tier green:**
      `commit` split into `batch(self._statements[:1]) + batch(self._statements[1:])` → `1 passed`
      with strength `"statement faults at 5 positions + command faults at 4"`, and the same for the
      `[:-1]`/`[-1:]` split. The hook arms per `batch()` call, so the leading batch commits alone
      and the unit is left partially applied — but that batch holds one statement, the
      `workflow_steps` insert, while `position` is a `workflow_scopes` column the *next* statement
      writes and `runs.recent` is untouched, so `landed()` cannot see the partial commit. A split
      at `[:2]` **is** caught (`a fault before statement 2 left ('a1', None, 0)`), so the hole is
      exactly a leading batch that leaves no observable change. Closing it needs a decision this
      task's files do not carry: what the tier observes (no public port exposes a step row), or a
      unit boundary at the driver seam (there is none — `claim()` issues its own `batch()`). Left
      unchecked and reported to the issue.
      *Done (`7ec70ded`):* (ii) is restated above to the split the ports can see, and it reddens:
      with `commit` split at `statements[:2]` / `statements[2:]` (applied alone to a clean tree,
      then restored), `cross_aggregate_atomicity` fails — `AssertionError: a fault before
      statement 2 left ('a1', None, 0)` at `capabilities.py:192`. The split the earlier run used
      (`[:1]` / `[1:]`) still passes (`1 passed`) and reports `statement faults at 5 positions`
      against the intact unit's 6: its leading batch carries the unit's first `workflow_steps`
      insert alone, and no public port exposes a step row (`WorkflowReader` offers `workflow`,
      `resumable`, `events_after`), so `cross_aggregate_atomicity` reads nothing — and `commit()`'s
      own invariant, *"Send everything staged as one batch"* (`_transaction.py`), is **not** covered
      by this tier. The limit is stated where the tier is, in the form `cross_process_fencing`
      already uses: its docstring
      names the outcome it reads and the partial application it cannot see, and the published
      strength appends `"observed through the ports — a split whose leading batch writes no
      port-visible row is not seen"` (intact: `statement faults at 6 positions + command faults at
      4; …`), with the assertion in `test_capabilities.py` moved in the same change, and H-3 in
      contracts.md carrying the same limit. The limit's repair is its own issue (MCH-156), so the
      designer's intent for the hook is preserved there rather than narrowed here; the decision the
      earlier run asked for — restate the clause rather than widen the tier — is that issue plus
      this restatement.
      *History:* the earlier text said the document store runs "none of" the tiers. That was
      wrong once F-1's correction made its `fencing` `"cross-process"`, and it is restated above.
- [x] **14** AC-5 in Tier A
      *Depends on:* 12.
      *Files:* `tests/substrate_probe/fakes.py`, `tests/substrate_probe/tier_a.py`
      *Do:* add read-only `BatchOnlySqliteDriver.query(sql, params) -> list[tuple]`; drop nothing
      from its refusal. In `tier_a.py`, run BASELINE against `SqliteRuntimeStore(BatchOnlySqliteDriver())`.
      *Gate (AC-5, E-6):* green; then make `_BufferedTransaction` issue one statement through a
      driver transaction → `NoInteractiveTransactionError` turns it red.
      *Done (`b42a2add`):* `test_baseline_is_green_over_a_batch_only_driver` green; sabotage — the
      buffered transaction sends its first statement through `driver.transaction()` →
      `NoInteractiveTransactionError`, red. Deviation: the instrument also gains a no-op `close()`
      (the instance is the in-memory database; close/reopen durability needs the store to close
      and be rebuilt over it); `query()` refuses any statement that is not a read.

## Wave 5 — legacy import (AC-3, AC-4)

- [x] **16** The importer
      *Depends on:* 7–9, 13.
      *Call path:* task 17, same wave — the console script (closes together with 17).
      *Files:* `PLUGIN/_legacy_import.py`, `PLUGIN_TESTS/test_legacy_import.py`
      *Do:* the shape's seven steps — exclusive migration lock; snapshot + backup of the database
      file; import runtime keys into the schema in **one** unit, each legacy run as one attempt
      (`attempt_no = 1`, shape M-1); verify counts, identities, terminal/live status, state keys,
      sequence order, payload digests; write `runtime_cutover` in the import's unit; reopen
      through the read ports and verify semantically; keep the backup. Illegal record (FUN-18
      table, B4 symptom) → refuse the whole import and list it (AC-4). Report states that the
      500-record cap may already have evicted terminal records. `fresh` and `shell-history` keys
      stay in `documents`.
      *Gate (E-4, E-5, AC-3, AC-4):* legal fixture imports and verifies; a fixture with one
      `completed` scope holding a live lease is refused, listed, and the source file's digest is
      unchanged; killing at each of the seven steps either resumes or rolls back, and afterwards
      exactly one of {legacy authoritative, cutover marker present} holds; a second run is a no-op.
      *Done (`150931cf`):* `test_legacy_import.py` 14 passed — the legal fixture (written by the
      document store over `SQLiteSubstrate`, plus a legacy bare-payload deposit) imports and
      verifies; a `completed` scope with a live lease is refused and listed, the source file's
      sha256 unchanged, no backup kept; killed (`os._exit`) after each of the seven steps, steps
      1–2 leave the documents authoritative and 3–7 the marker, never both, and the next run
      finishes with `IMPORTED`; a second run writes nothing and adds no backup; a tampered row
      after step 3 fails verification and rolls back. Ticked with 17 on its entry-point sabotage.
      Deviations: three modules, not one — `_legacy_source.py` (read, judge, rows),
      `_legacy_import.py` (the steps), `_legacy_verify.py` (steps 4 and 6, undo) — to keep each
      under 500 lines; an identity already in the relational tables is a refused record (never
      overwritten); a legacy deposit with a payload and no candidate is carried as one accepted
      candidate from source `legacy-import`, counted in the report.
- [x] **17** The command
      *Depends on:* 16.
      *Files:* `PLUGIN/_import_cli.py`, `plugins/substrates/functualize-substrate-sqlite/pyproject.toml`,
      `PLUGIN_TESTS/test_import_cli.py`
      *Gate:* `functualize-sqlite-import --dry-run` changes nothing; exit codes per contracts §6; it
      runs while boot would refuse with `LegacyImportRequired`, and after it boot with
      `sqlite:` succeeds.
      *Call path:* the console-script entry point; sabotage = remove `[project.scripts]` → the
      subprocess test fails. That proof ticks 16 and 17 together.
      *Done (`150931cf`):* `test_import_cli.py` 8 passed, run through the installed console
      script: boot raises `LegacyImportRequired`, the script exits 0, boot with `sqlite:` then
      selects `SqliteRuntimeStore`; `--dry-run` leaves the file's sha256 unchanged; exits 2
      (`--resume` with nothing recorded), 3, 4, 5 as §6. Sabotage — `[project.scripts]` removed
      and the venv re-synced — fails 7 of 8 (the eighth calls `main()` in-process by design);
      restored, 154 passed.

## Wave 6 — the born-relational marker (contracts §6a)

- [x] **20** Marker provenance and the boot guard
      *Depends on:* 7, 15, 16, 17.
      *Call path:* task 15's plugin registration → selection → `prepare` (wave 1) for the insert
      and the guard; the `functualize-sqlite-import` console script (wave 5) for the importer's
      no-op.
      *Files:* `PLUGIN/_factory.py`, `PLUGIN/_legacy_import.py`, `PLUGIN/__init__.py`
      (export `CutoverMarkerInvalid`), `PLUGIN_TESTS/test_cutover_marker.py` (new).
      *Do:* contracts §6a, exactly:
      - in `prepare`: `migrate` → `SQLiteSubstrate(path)` → the one-statement conditional
        `born-relational` insert → the guard in G-1…G-4 order → store;
      - the importer's born-relational no-op;
      - `unselected_data` counting a valid marker as relational.
      No engine change, no new capability, no new schema revision, and no weakening of G-3.
      *Gate — the test matrix, each case a named test:*
      - **M-1** `fresh_file_boots_again_after_a_run`: a fresh `sqlite:` file → `prepare` writes one
        `born-relational` row with the §6a values → one run through the shipped boot path writes
        `documents['runs']` → a second `prepare` (and a second boot) **succeeds**; still exactly one
        marker row.
      - **M-2** `legacy_without_marker_is_still_refused`: a `documents` table holding runtime keys,
        no marker → `LegacyImportRequired` whose message names `functualize-sqlite-import --db
        <path>`; no marker row was written; the source digest is unchanged.
      - **M-3** `imported_marker_boots`: a `documents` marker from a real import, legacy rows
        retained → boots.
      - **M-4** `born_relational_marker_with_legacy_rows_boots`: G-2 precedence.
      - **M-5** `degenerate_markers_are_refused` (parametrised, one case per G-1 clause): two
        rows; an unknown `source`; `documents` with NULL `backup_path`; `documents` with a
        non-hex digest; `born-relational` with a non-NULL `backup_path`; `born-relational` with a
        digest other than the constant; an unparseable `imported_at` → each `CutoverMarkerInvalid`
        naming the row.
      - **M-6** `concurrent_first_prepare_writes_one_marker`: two OS processes `prepare` one fresh
        file → exactly one row, both boot.
      - **M-7** `import_on_a_born_relational_file_is_a_no_op`: exit 0, file digest unchanged,
        report says born relational.
      - **M-8** `unselected_data_on_a_born_relational_file_names_no_import`.
      - **M-9** the two-project shared-db shape of `tests/integration/test_substrate_durability.py`:
        project B is **not** refused with `LegacyImportRequired`. That module's strict xfail stays,
        on the scope-taken residual, which is not this task's.
      *Sabotage (tick on these):* (i) drop the conditional insert → M-1's first boot fails with
      G-4's `CutoverMarkerInvalid`; (ii) drop the insert's legacy-rows predicate → M-2 fails, because a
      legacy file gets marked and the import is bypassed; (iii) drop the importer's
      born-relational check → M-7 fails.
      *Also:* plugin suite green; `tests/conformance` green; tip-tier rule as task 19's.
      *Done (`ce77ca34`):* M-1…M-9 are named in `test_cutover_marker.py` (15 parametrized
      cases). The plugin suite passed 169 tests and `tests/conformance` passed 28. The boot path
      writes one marker on first open and the app's run log can then write `documents['runs']`
      without making the next boot refuse; a genuine legacy file still has no marker and raises
      `LegacyImportRequired`. A bounded retry handles two first-open processes racing the schema
      lock. Sabotage (i) removed the insert and M-1 failed on the **first** boot with G-4's
      `CutoverMarkerInvalid`; the earlier predicted second-boot error was incompatible with G-4,
      while the required red test holds. Sabotage (ii) removed only the legacy-rows predicate and
      M-2 failed `DID NOT RAISE LegacyImportRequired`. Sabotage (iii) removed the importer no-op
      and M-7 showed a new backup/import instead of "born relational; nothing to import". Each
      source file was restored to a clean tree; the three target tests then passed together.
      The old `test_runtime_store.py` fixture used an invalid marker; it now uses the valid
      `documents` columns required by §6a, while M-3 proves a real import marker.

## Wave 7 — honest docs and naming (S-7), release note

- [x] **18** Docs, naming, markers
      *Files:* `PLUGIN/substrate.py` (docstring only), `plugins/substrates/functualize-substrate-sqlite/README.md`,
      `CHANGELOG.md`; plus `contributor/architecture/codemaps/modules.md`, `data-flow.md`,
      `src/functualize/_primitives/document_store.py` (marker comment only), and the package
      description in its `pyproject.toml`
      *Gate:* `rg -n "different machines" plugins/ docs/` → nothing; a test asserts
      `SQLiteSubstratePlugin.version` equals the package version; the CHANGELOG entry states the
      boot-refusal behaviour change and the removed `db_path` key (shape Q-3); the TRANSITIONAL
      marker no longer says FUN-19 removes the store. The plugin README documents the final marker
      set from contracts §6a: the `documents` and `born-relational` provenances, the G-1…G-4
      precedence, and the accepted limitation.
      *Done (`88669e73`):* Every gate item measured green. A search for `different machines` over
      `plugins/` and `docs/` returns nothing — `substrate.py`'s bullet now says the file is local
      and that `multi_machine=False` declares it, and the bullet's doubly-wrong `(spec AC-3)`
      citation (AC-3 is the legacy import) went with the claim. `PLUGIN_TESTS/test_plugin_metadata.py`
      asserts `SQLiteSubstratePlugin.version` equals
      `importlib.metadata.version("functualize-substrate-sqlite")`; sabotaging the literal to `9.9.9`
      failed it (`assert '9.9.9' == '0.4.0'`), and the file was restored to a clean tree before the
      tick. The CHANGELOG entry states the boot-refusal behaviour change (a selected store that
      cannot open, migrate or pass its health check aborts boot, nothing falls back, and the
      with-nothing-configured case refuses rather than coming up on the document store with data
      unread) and the removed `[plugin.substrate-sqlite] db_path` key. Both markers over
      `DocumentRuntimeStore` (`:13-19`, `:1107-1113`) now describe the end state: with
      `runtime_store.url` unset the document store is what boot step 6.5 builds, so the class and
      its file stay. The README documents contracts §6a — both provenances with the
      `sha256(repr([]))` constant, `prepare`'s order and its single conditional insert under
      `BEGIN IMMEDIATE`, G-1…G-4 in order, the importer's born-relational no-op, the
      with-nothing-configured probe, and the accepted limitation. The plugin's 170 tests passed
      (169 before this task's test).
      *Deviation — the file set grew by four paths, each disclosed here:* the version-bearing
      `PLUGIN/_plugin.py`, whose literal said `0.2.0` against a package at `0.4.0`, so the gate's
      own test cannot pass without it (its `description` moved with it, and is user-visible in
      `func builtin plugins`); the new `PLUGIN_TESTS/test_plugin_metadata.py`; the
      `document_store.py` module docstring, which carried the same false claim as the marker three
      lines above it (F-3's fix is comment-only either way); and
      `docs/guides/{workflows,hosting,plugins,task-runner}.md`, which told readers to set the
      removed `db_path` key and to expect an installation to select storage — `plugins.md` listed
      the plugin twice and now lists it once. `contributor/architecture/boot-sequence.md` was left
      alone: it is off this task's file list and carries no `runtime_store` text at all, which is
      pre-existing drift.


## Wave 8 — pre-merge (not implementation)

- [x] **19** Clear the branch for merge
      *Files:* `.spec/STATUS.md` or `contributor/adr/031-*.md` (the factory registry and
      selection key are an ADR-027 follow-through — an ADR if the maintainer wants one),
      `contributor/reference/runtime-persistence-data-model.md` (tenses: §2 and §7 become landed),
      then `git rm -r contributor/architecture/research/` and, as the deletion-only **last**
      commit, `git rm -r .spec/features/sqlite-runtime-provider`.
      *Named repairs that clear this branch* (found by the tip-tier run at `b8591fa3`; both are
      done in task 13's write pass, and both must hold here):
      - **R-1 — selection survives a chain that cannot answer.** `_configured_url`
        (`src/functualize/_app/store_selection.py:112-118`, landed in `1ebf364f`, wave 0) calls
        `chain.resolve(...)` and catches only `MissingKeyError`. A resolution chain supplied as a
        bare `object()` therefore aborts boot. Fix the source with a duck-typed
        `getattr(chain, "resolve", None)` guard (no `resolve` → nothing configured). Do not wrap the
        call in `except AttributeError`, which would swallow a real chain's own error. Proof:
        `uv run pytest tests/core/test_property_constructor_defaulting.py --run-slow -q` → no failures
        (it was `8 failed, 1 passed`).
      - **R-2 — the entry-point test stops leaking its working directory.** The `project` fixture at
        `tests/spec/test_a_substrate_plugin_loads_through_its_entry_point.py:75-82` uses a raw
        `os.chdir(tmp_path)` with `finally`. Replace it with `monkeypatch.chdir(tmp_path)`. Proof:
        `uv run pytest tests/spec/test_a_substrate_plugin_loads_through_its_entry_point.py
        tests/test_integration.py -q -p no:randomly` → no failures (it was `21 failed, 14 passed`).
      - **Tip tier:** `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q` shows neither class.
        Any remaining failure is classified host or ambient, with an isolated passing re-run as
        evidence.
      *Gate:* `research-artifacts-cleared` and `spec-artifacts-cleared` green; two pushes per
      `.claude/rules/spec-workflow.md` → *Version control lifecycle*; PR title and body carry no
      tracker key (`.spec/CONSTITUTION.md` → *Forbidden Patterns*).
      *Done (`8565e34f`):* Both artifact gates are green and the pull request is open. The durable
      record went to `.spec/STATUS.md` — a row and a section — rather than a new
      `contributor/adr/031-*.md`: this task makes the ADR conditional on the maintainer wanting one,
      and the feature's decisions already live in ADR-022, ADR-026, ADR-027 and ADR-028, with the
      rest contract, which is the reference's job. The reference's §2 and §7 read as landed, and the
      header's tense map, §1's two enforcement clauses, §2's "names are conceptual" line and §6's
      retention paragraph moved with them because each stated the same pending work; all of it was
      checked against the shipped plugin (`_migrations.py`, `_factory.py`, `_retention.py`, the SQL
      writers), and everything FUN-20/21/4 owns stayed forward-looking. The two deletions are
      separate commits, research first and the feature tree last, over two pushes; the PR was opened
      after the second push so its head run sees both gates. The tick is the commit before the
      deletions, because it cannot ride inside a deletion-only commit and cannot follow the commit
      that removes the file. Checks at the head: full suite **12 157 passed / 1 630 skipped**, `ruff
      check` and `ruff format --check` clean, `mypy src/` clean, `lint-imports` **7 kept, 0 broken**,
      `mkdocs build --strict` clean; R-1 and R-2 were verified in task 18's acceptance run and were
      not re-implemented.

## Task Dependency Graph

Each wave is reachability-closed: every task's call path and every close-together partner is in
the same wave or an earlier one, and `depends_on` never points to a later wave. A close-together
group is built in `depends_on` order and ticked together on its last member's sabotage proof.

```json
{
  "waves": [
    {"id": 0, "tasks": ["1", "2", "3", "4"]},
    {"id": 1, "tasks": ["5", "6", "7", "15"]},
    {"id": 2, "tasks": ["8", "9"]},
    {"id": 3, "tasks": ["10", "11"]},
    {"id": 4, "tasks": ["12", "13", "14"]},
    {"id": 5, "tasks": ["16", "17"]},
    {"id": 6, "tasks": ["20"]},
    {"id": 7, "tasks": ["18"]},
    {"id": 8, "tasks": ["19"]}
  ],
  "depends_on": {
    "1": [],
    "2": [],
    "3": ["1", "2"],
    "4": ["1"],
    "5": [],
    "6": [],
    "7": ["3", "5", "6"],
    "15": ["2", "3", "7"],
    "8": ["7"],
    "9": ["7"],
    "10": ["8", "9"],
    "11": ["7", "8", "9"],
    "12": ["4", "7", "8", "9", "10"],
    "13": ["12"],
    "14": ["12"],
    "16": ["7", "8", "9", "13"],
    "17": ["16"],
    "20": ["7", "15", "16", "17"],
    "18": ["15", "17", "20"],
    "19": ["18"]
  },
  "call_path": {
    "1": "3", "2": "3", "3": "3", "4": null,
    "5": "15", "6": "15", "7": "15", "15": "15",
    "8": "15", "9": "15", "10": "15", "11": "7",
    "12": null, "13": null, "14": null,
    "16": "17", "17": "17", "20": "15", "18": null, "19": null
  },
  "close_together": [["1", "2", "3"], ["5", "6", "7", "15"], ["16", "17"]],
  "decision_gates": {"D-1": ["1", "2", "3", "4"], "D-2": ["4", "12", "13"], "D-3": ["3", "15"]},
  "decisions_answered": {"D-1": "a", "D-2": "a", "D-3": "refuse", "at": "2026-10-05T10:16:48Z"}
}
```

Consistency check, run at authoring time against the block above (any non-empty list fails):

```python
import json, re
g = json.loads(re.search(r"```json\n(.*?)\n```", open("tasks.md").read().rpartition("## Task " + "Dependency Graph")[2], re.S).group(1))
wave = {t: w["id"] for w in g["waves"] for t in w["tasks"]}
assert sorted(wave, key=int) == [str(i) for i in range(1, 21)]
late_deps   = [(t, d) for t, ds in g["depends_on"].items() for d in ds if wave[d] > wave[t]]
split_pairs = [p for p in g["close_together"] if len({wave[t] for t in p}) > 1]
late_paths  = [(t, c) for t, c in g["call_path"].items() if c and wave[c] > wave[t]]
print(late_deps, split_pairs, late_paths)   # -> [] [] []
```
