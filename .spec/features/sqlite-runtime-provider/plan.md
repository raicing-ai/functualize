# FUN-19 — Plan

**Status:** architecture gate **satisfied** (2026-10-05, at `e8e3b867`). Decisions answered
2026-10-05 10:16:48Z — **D-1 a, D-2 a, D-3 refuse** — so the AFTER below is the plan as approved.
`tasks.md` re-waved the same day so every wave is reachability-closed (see *Decisions taken*).

## Alignment

Shape: **SD/12583004** *"Shape Intent — Store Substrate and Relational SQLite Runtime Provider"*,
v1, `Status: Approved`, `Authority: Approved`, created 2026-10-05 08:57:33 UTC (read live this
run). MCH-149's `Shape intent` property points at it.

**In scope — the page's surfaces, in its words:**

| ID | Surface (page's name) | Page's behaviour sentence | Where this plan delivers it |
|---|---|---|---|
| S-1 | Selecting the SQLite runtime provider | "The selection is explicit configuration. Installing a plugin is no longer the selection." | tasks 1–3, 15 |
| S-2 | Boot when SQLite was selected and cannot start | "Boot fails loudly and does not fall back to files. With **nothing** configured, the document store remains the default." | tasks 3, 7, 15 (E-1) |
| S-3 | Capability refusal | "A feature that needs a capability the selected store declares `False` refuses at boot. It never degrades. The error names the store, the field and the config key." | task 3 (existing `check_required_capabilities`) |
| S-4 | Schema migrations at boot | "Versioned and transactional. They run before any job executes. A checksum mismatch or a partly applied revision refuses boot with repair steps." | tasks 6, 7, 13 |
| S-5 | Offline legacy migration from `documents(key, payload, revision)` | "An explicit, offline operation with backup and verification. It refuses illegal records. It reports what it could not see. A failed import leaves the source authoritative. There is no dual write." | tasks 16, 17 |
| S-6 | Inspectable data | "Core persisted entities can be inspected and queried with ordinary SQL." | tasks 6, 10 |
| S-7 | Honest documentation and naming | "Package, README and version names agree. Nothing claims that local SQLite proves multi-machine reachability." | task 18 |
| S-8 | Plugin-author contract: the tiered conformance suite | "Every store passes BASELINE. Each capability tier runs only when the profile declares that capability. A third-party backend gets the same suite." | tasks 12–14 (third-party reach: D-2) |

**Out of scope — the page's *Non-goals*, in its words:** "Rewiring workflow state,
suspension/resume and lease fencing through the engine" (FUN-20); "Gate interactions, evidence
persistence, the transactional outbox **dispatcher**" (FUN-21); "Any network or remote provider
(D1, Turso, Postgres, DynamoDB, S3); `multi_machine=True`" (FUN-22); "Workspace / AgentFS
persistence, and whether workspace shares the SQLite file" (FUN-23); "A
`RuntimePersistenceProvider` family with repositories, admin surface and a generalized query
object (Design 1)" (deferred); "Widening `StoreSubstrate` with query methods" (rejected); "Silent
fallback from a configured store to documents" (rejected); "Indefinite dual write; shadow reads
beyond temporary validation" (rejected); "A port for a durable-execution provider (Restate,
DBOS)" (rejected); "Storing artifact bytes in runtime rows" (rejected); "Retention maintenance
operation (age and count) as a user command" (not decided here).

**The page's settled calls this plan follows:** M-1/Q-1 (a) the importer ships here, legality from
FUN-18's tables, one legacy run → one attempt (`attempt_no = 1`); M-2/Q-2 (a) the SQLite
`documents` table only; M-3 (a) URI-scheme configuration resolved at boot step 6; Q-3 A, release
note; Q-4 A, explicit command and boot refuses with "run the migration".

## Retrieval performed (gate step 1)

| Tool | Addressed as | What it answered |
|---|---|---|
| zvec-grep 0.2.2 | index built this run at the worktree's absolute path (883 files, 13 851 entities, `local/potion-code-16m-v2`) | where Wave 3's "no framework changes" is argued (`research/…/07-what-changes.md:86-102`); the migration contract (`contributor/reference/runtime-persistence-data-model.md:472-495`); the TRANSITIONAL middle man (`_primitives/document_store.py:1107-1155`, `_app/boot.py:225-265`) |
| serena | project activated by absolute path | `SQLiteSubstrate` surface (9 methods); `functualize.plugin` exports no persistence symbol; `DOCUMENT_PROFILE` referenced only by `document_store.py` and `tests/core/test_store_capability_refusal.py`; `BatchOnlySqliteDriver` surface (`execute`, `batch`, `read`, `transaction` raising) |
| graphify 0.9.61 | `graphify extract . --code-only` rebuilt this run (10 235 nodes, 21 728 edges; the committed graph dated 2026-09-17 from another branch); `get_neighbors` with `project_path` = worktree | `_select_runtime_store` ← `boot_standard:1074`, `boot_static:633`; → `_resolve_substrate_claim`, `substrate_for_project`, `DocumentRuntimeStore`, `check_required_capabilities`; `SQLiteSubstratePlugin` → `SQLiteSubstrate` only |
| rg | worktree | counts and negatives below (each one run, not inferred) |

The rebuilt `graphify-out/graph.json` was **not** committed (it is a tracked file; regenerating it
is not this ticket's change).

Negatives verified by `rg` at `e8e3b867`: no `RuntimeStoreFactory`, `RuntimeStoreConfig`,
`store_selection` or `_runtime_store_factories` under `src/`, `plugins/`, `tests/`, `docs/`,
`contributor/reference`, `contributor/adr`; `"different machines"` still at
`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/substrate.py:20`;
no `tests/conformance/`.

## Codemaps read (gate step 2)

`contributor/architecture/codemaps/overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`,
`entry-points.md`. Two contradictions with the tree, recorded as findings: `modules.md:153`
describes `functualize-substrate-sqlite` as "SQLite-backed state persistence" — the same drift the
package description carries (S-7); and no codemap names the runtime-store port or boot step 6.5
at all, though both landed in FUN-17. Task 18 updates `modules.md` and `data-flow.md`.

## BEFORE (at `e8e3b867`)

```
 LAYER        MODULE (real path)                                   DEPENDS ON  →
 ───────────  ───────────────────────────────────────────────────  ─────────────────────────────
 plugin pkg   plugins/substrates/functualize-substrate-sqlite/
 (outside       functualize_substrate_sqlite/_plugin.py            → functualize.plugin (PUBLIC:
  contracts)      SQLiteSubstratePlugin.__call__                       SubstrateInstallError, PluginHost)
                    └─ app.offer_substrate(_choose_substrate)  ─┐   → .substrate
                functualize_substrate_sqlite/substrate.py        │   → functualize._types.errors   (private)
                  SQLiteSubstrate  documents(key,payload,rev)   │   → functualize._types.protocols (private)
                                                                │
 ════════════ boundary: plugin → framework via PluginHost ══════╪══════════════════════════════════
 _types/      src/functualize/_types/host.py   PluginHost       │   (stdlib only)
              src/functualize/_types/persistence.py             │   StoreProfile, RuntimeStore,
                                                                │   RuntimeTransaction, 5 writers,
                                                                │   3 readers, commands, views
              src/functualize/_types/lifecycle.py  (FUN-18 machines)
              src/functualize/_types/retention.py  RetentionPolicy
              src/functualize/_types/errors.py     RuntimeStoreCapabilityError, IllegalTransition
 _primitives/ src/functualize/_primitives/document_store.py     → _types.persistence, scope_store,
                DOCUMENT_PROFILE, DocumentRuntimeStore             run_store, scope_state_store
                (TRANSITIONAL middle man)                        
              src/functualize/_primitives/substrate.py          → _types.protocols
                JsonFileSubstrate, substrate_for_project
 _app/        src/functualize/_app/impl.py                      claims list app._substrate_claims
                offer_substrate / install_substrate  ◄──────────┘ (recorded at step 4)
              src/functualize/_app/boot.py  (2 298 lines)
                boot_standard:1074 ┐
                boot_static:633    ┴─► _select_runtime_store:225  (step 6.5)
                                         ├─ _resolve_substrate_claim  → calls the ONE offer
                                         ├─ substrate = override or substrate_for_project
                                         ├─ store = DocumentRuntimeStore(substrate)   ← always
                                         └─ check_required_capabilities(profile, {}) ← always {}
                                       ─► build_engine(app, runtime_store, substrate)
 _engine/     executor, frontier, workflow_walker, workflow_runner, workflow_orchestrator
                → _types.persistence only (RuntimeStore protocol)
 tests/       tests/substrate_probe/{fakes,tier_a}.py  BatchOnlySqliteDriver (instrument)
              tests/types/fixtures/runtime_store_conformance.py (mypy-only port check)
```

What it means for a user: installing the plugin **is** the selection, and it moves *every* document
— runtime truth, freshness, shell history — into one `documents` table of opaque JSON. Only one
runtime store can ever be built.

**Smells the BEFORE carries** (catalogue: `design-patterns-refactoring`, Refactoring.Guru):

| Smell | Where | Note |
|---|---|---|
| **Middle Man** | `DocumentRuntimeStore`, `_primitives/document_store.py:1107-1155` | declared, `# TRANSITIONAL(FUN-17/T7)` |
| **Speculative Generality** | `_required_capabilities` returns `{}` (`_app/boot.py:350-362`) | an empty hook; FUN-19 gives it its first entry only if a feature needs `multi_process` — none does yet, so it stays empty (surviving smell 3) |
| **Comments** (a comment that is false) | `substrate.py:20-22` "different machines"; `document_store.py:1107-1110` "FUN-19 removes it, and this file with it" | S-7; F-3 |
| hidden selection by side effect | `_plugin.py:59-60` `__call__` → `offer_substrate` | not a catalogue name; it is the S-1 defect itself (09 §3 "a present defect (B2)") |
| large module | `_app/boot.py` 2 298 lines | a module, not a class — the ~500-LOC rule governs classes; the AFTER does not grow it beyond the call swap |

## AFTER (recommended; D-1 = a, D-2 = a, D-3 = refuse)

```
 LAYER        MODULE (real path)                                   DEPENDS ON  →
 ───────────  ───────────────────────────────────────────────────  ─────────────────────────────
 plugin pkg   functualize_substrate_sqlite/  (plugins/substrates/functualize-substrate-sqlite/src/)
 (outside       _plugin.py     SQLiteSubstratePlugin.__call__      → functualize.plugin (PUBLIC)
  contracts)                     └─ app.register_runtime_store_factory(SqliteRuntimeStoreFactory())
                _factory.py    SqliteRuntimeStoreFactory           → functualize.plugin (PUBLIC)
                                 scheme="sqlite", profile=SQLITE_PROFILE
                                 prepare(): driver → migrate → legacy guard → retention → store
                                 unselected_data(): state.db with runtime keys? (D-3)
                _runtime_store.py  SqliteRuntimeStore (facade ≤150) + SQLITE_PROFILE
                                   readers + transaction() → _BufferedTransaction
                _transaction.py    _BufferedTransaction: writers append statements; __exit__ →
                                   driver.batch(all) once; nothing on error           (I-4)
                _workflow_sql.py   claim/complete/suspend/resume/cancel/state → SQL     (I-3)
                                   legality via functualize._types.lifecycle (FUN-18)
                _run_sql.py        start/finish attempt, run/scope events, inputs, outbox
                _readers.py        RunReader, WorkflowReader, InputReader over SQL
                _driver.py         SqlDriver Protocol {batch, query, close}
                                   LocalSqliteDriver: PRAGMA foreign_keys, WAL(file), busy→
                                   SqliteBusyError(retryable), batch = BEGIN IMMEDIATE…COMMIT (I-5)
                _migrations.py     Migration, migrate(driver, migrations), MigrationRefused
                _schema/0001_runtime_schema.sql                        (I-1, I-2, I-9)
                _retention.py      relational retention statement (D3 = B), called by prepare
                _legacy_import.py  the 7 steps, refusal, cap report    (S-5, AC-3, AC-4)
                _import_cli.py     console script functualize-sqlite-import (no app boot)
                substrate.py       SQLiteSubstrate — behaviour unchanged; docstring fixed (S-7)
                                   now serves only `fresh` + `shell-history` (PreparedStore.substrate)
 ════════════ boundary: plugin → framework via functualize.plugin (PUBLIC) only for new code ══
 public       src/functualize/plugin/__init__.py   re-exports the persistence vocabulary (D-2)
              src/functualize/testing/conformance/ run_baseline, run_capability_tiers (D-2)
                                                    → functualize.plugin (public only)
 _types/      _types/persistence.py  + RuntimeStoreConfig, PreparedStore, RuntimeStoreFactory
              _types/host.py         PluginHost + register_runtime_store_factory
              _types/errors.py       + RuntimeStoreSelectionError
 _primitives/ document_store.py      DocumentRuntimeStore stays, default store; marker reworded
 _app/        _app/impl.py, app/core.py   register_runtime_store_factory → app._runtime_store_factories
              _app/store_selection.py  (new, ≤200)  ◄── boot.py:_select_runtime_store delegates
                resolve runtime_store.url → RuntimeStoreConfig
                DocumentRuntimeStoreFactory(app) — registered by boot through the same host
                  method plugins use, before plugins load (scheme "documents")
                unset → [D-3: any factory.unselected_data()? → refuse] → read as "documents:"
                every scheme → factories[scheme] or refuse → prepare() UNCAUGHT → check capabilities
              _app/boot.py  _select_runtime_store body → store_selection.select(app) (both paths)
 _engine/     unchanged — still sees only the RuntimeStore protocol
 tests/       tests/conformance/  runs the suite for DocumentRuntimeStore + SqliteRuntimeStore
              tests/substrate_probe/tier_a.py  + AC-5 (SqliteRuntimeStore over BatchOnlySqliteDriver)
              tests/substrate_probe/fakes.py   BatchOnlySqliteDriver + query()  (read-only addition)
              plugins/substrates/functualize-substrate-sqlite/tests/  driver, migrations, import
```

**What crosses a boundary, and is it legal:** plugin → framework only through `functualize.plugin`
for every new module (the two existing private imports in `substrate.py` stay — not this ticket's).
`_app` → `_types`, `_primitives`, `_config` (composition root: legal). `_types` stays stdlib-only
(new names are dataclasses and a Protocol). `functualize.testing` → `functualize.plugin` (public →
public). No peer layer gains an import. The seven import-linter contracts are untouched;
`uv run lint-imports` is the gate.

## Iteration log (gate step 4) — candidates rejected

| Candidate | Why rejected | Smell it would have introduced |
|---|---|---|
| **A. The scaffold: `src/functualize/_primitives/sqlite_store.py`, `migrate_legacy.py`, `_primitives/migrations/`** | contradicts 07 Wave 3, shape I-8 and ADR-026's own reopen clause — *"A **second** runtime store whose implementation cannot live in `_primitives` — one carrying a driver, a connection pool and a migration runner"* (`contributor/adr/026-persistence-ports-need-no-new-layer.md:154-155`); puts dialect SQL in a layer contracted to import nothing internal but `_types` | **Divergent Change** on `_primitives` (generic stores + one dialect); makes the plugin a husk |
| **B. Pure plugin, zero framework edits (I-8 literal)** | S-1 cannot be met: there is no factory registry or selection key (`boot.py:231` *"A factory registry and `prepare()` proper … arrive with the backend plugins (FUN-19/FUN-22)"*), so the only way in is the existing `offer_substrate` — installation as selection, the defect S-1 removes | keeps the hidden-selection defect |
| **C. One `SqliteRuntimeStore` class (~700 lines, the research's estimate)** | over the CONSTITUTION's ~500-LOC god-object line — a **forbidden pattern**, therefore a blocker, not a compromise | **Large Class** |
| **D. Split per aggregate into three store classes behind a facade** | the facade would only forward — trades Large Class for **Middle Man** | Middle Man |
| **E. Migration runner generic in `_primitives/migrations/` (the received task text)** | one consumer until FUN-22 names a database (09 D-12); in-repo skill's *Rule of Three*; and a public export or a private import would be needed for the plugin to reach it | **Speculative Generality** |
| **Settled: split by *responsibility*** — facade, buffered transaction, SQL per aggregate, readers, driver, migrations | each module has one reason to change; the facade owns the profile, readers and transaction factory (real behaviour, not forwarding) | checked below |

Smells the settled AFTER **introduces**, checked: **Parallel Inheritance Hierarchies** — every
writer/reader port now has two implementations (document, SQLite), so a new command touches both
(surviving smell 1). **Shotgun Surgery** — adding a command touches `_types/persistence.py`, two
stores and the suite; this is the cost of a port with two implementations and the suite is what
catches a miss (folded into smell 1). No **Feature Envy**: SQL modules build statements from
commands they receive and own no engine logic — 05 §3's line *"a store implementation must never
contain the word 'resume' in a conditional"* is a review check on `_workflow_sql.py` (legality comes
from FUN-18's tables, not from a conditional here).

## Findings — where the shape, the canon and the code disagree

Reported to MCH-149 as findings, not reconciled quietly.

| # | Finding | Evidence | What this plan does |
|---|---|---|---|
| **F-1** | The shape's profile table gives `DocumentRuntimeStore` `fencing="process-local"`; the code and the canonical reference say `"cross-process"` | `_primitives/document_store.py:144` `fencing="cross-process"`; `contributor/reference/runtime-persistence-data-model.md` §5 *"`DOCUMENT_PROFILE` states this as `fencing="cross-process"`"*; the shape quotes 05 §2.1, written before FUN-24's CAS repair | follows the code; the shape page needs a one-cell correction |
| **F-2** | Shape I-8 / 07 Wave 3: *"Entirely inside the plugin. No framework file changes."* S-1 needs a selection key and a factory registry that FUN-17 did not ship (shape HY-4 falsified) | `_app/boot.py:229-233`; ADR-027 step 4 *"store factories registered by scheme"* (`027-…:84`) never landed; `rg RuntimeStoreFactory` → nothing in `src/` | D-1 |
| **F-3** | `DocumentRuntimeStore`'s marker says FUN-19 deletes it; the shape (S-2), AC-2 and 09 §3 keep it as the default | `_primitives/document_store.py:1107-1110` *"FUN-19 removes it, and this file with it"* | keeps it; task 18 rewords the marker to the true end state |
| **F-4** | The scaffold placed the store in `_primitives` | old `plan.md` *Files expected to change*; `tasks.md` 0.1 paths | candidate A rejected above |
| **F-5** | 08 puts the import in Wave 6 and also from JSON | `research/…/08-delivery-and-tests.md` *"Import moved from Wave 3 to Wave 6"* | the shape settled it (M-1 a, M-2 a); followed |
| **F-6** | FUN-19's Jira body still says *"behind the public provider family"* and cites archived pages 5308716, 5341407, 5341434, 5308781 and `research/runtime-persistence/…` paths that do not exist on this branch | FUN-19 read live 2026-10-05 (updated 09:33:30 UTC) | ignored as superseded by its own *Revised 2026-09-21* section and the shape |
| **F-7** | `BatchOnlySqliteDriver` can only read a `documents` key, so it cannot drive a relational store as shipped | `tests/substrate_probe/fakes.py:133-138` | adds a read-only `query()` to the instrument (tests only); `spec.md` §3 |
| **F-8** | The branch's commit `chore(fun-19): pre-load specs …` carries a tracker key in its subject | `.spec/CONSTITUTION.md` *Forbidden Patterns* — tracker keys in a commit message, PR title or body | the PR title and body must carry none; the squash subject replaces branch subjects |
| **F-9** | The research tree on this branch must not reach `master` | CONSTITUTION *"Research studies never reach `master`"*, the `research-artifacts-cleared` check | task 19 removes it before merge |

## Decisions taken within the shape's delegated latitude

Recorded so the maintainer can overrule them; none changes behaviour or scope.

- **The document store is selected through the registry too** (added 2026-10-05 with the
  re-wave). Boot registers a built-in `DocumentRuntimeStoreFactory` through
  `register_runtime_store_factory` before plugins load, and an unset key reads as `documents:`.
  Two reasons: it removes the "unset" special case from selection (one path for every scheme),
  and it gives the registration method and the factory protocol a production caller in wave 0, so
  tasks 1–3 prove reachability without waiting for the SQLite plugin. Behaviour is unchanged: unset
  still means documents (S-2), and a plugin that also claims `documents` is refused like any
  other duplicate scheme.

- Config key `runtime_store.url`; schemes `sqlite`, `documents` (shape: *"Key name, scheme name,
  alias"*).
- Import command `functualize-sqlite-import`, a console script that does not boot the app — so
  Q-4's "boot refuses and names the command" cannot lock the operator out of the command.
- Migration runner and retention live in the plugin (candidate E). The contract they satisfy is the
  frozen one in `contributor/reference/runtime-persistence-data-model.md` §6–§7; only the file
  location changed from the received text.
- Retention caller = `prepare()` after `migrate()` (received task 0.3's option (a)): outside any step
  write, bounded by `DEFAULT_RETENTION`, reachable on every boot.
- `interactive_transaction=False` on the SQLite profile (`spec.md` §1).

- **The capability suite's harness hooks** (route (a), decided on MCH-149 on 2026-10-06; signature
  authored here, frozen in contracts §4a). They are an optional keyword-only `hooks=` on
  `run_capability_tiers`, with the hook protocols owned by `functualize.testing.conformance` and
  not by the port. A declared tier whose hook is missing fails loudly. A new `offline_capable` tier
  closes the AC-1 gap. Smell check:
  - **Speculative Generality** was the risk for `MigrationHarness` and `OutboxProbe`, which have
    one implementation today (SQLite). It is rejected as a smell: `SQLITE_PROFILE` declares both
    capabilities `True` now, so each hook has a present consumer, the tier that must hold the
    declaration.
  - No **Middle Man**: the hooks construct or read, and never forward the port.

## Approach (3b — blast radius)

Call sites that change, by `rg`/serena at `e8e3b867`:

- `_select_runtime_store` — 2 callers (`boot.py:633`, `boot.py:1074`); its body moves to
  `_app/store_selection.py`; the signature `(app) -> tuple[RuntimeStore, StoreSubstrate]` is kept so
  neither caller changes.
- `check_required_capabilities` / `RequiredCapability` — imported by
  `tests/core/test_store_capability_refusal.py`; stay in `boot.py` (re-exported is a shim — not
  done).
- `PluginHost` — implemented by `_app/impl.py` and `app/core.py:374` (`offer_substrate`'s
  neighbours); the facade's executable-line budget (`tests/test_facade_loc_limits.py`) applies to
  `app/core.py`.
- `SQLiteSubstratePlugin` — referenced by its package `__init__`, its own tests, and
  `tests/substrate_probe/tier_a.py` (imports `SQLiteSubstrate`, which is unchanged).
- `functualize.plugin.__all__` — enforced by `tests/test_public_api_surface.py`.

## Files expected to change

Sizes measured with `wc -l` at `e8e3b867`; "new" sizes are estimates.

| File | Size | Change |
|---|---:|---|
| `src/functualize/_types/persistence.py` | 776 | +~60: `RuntimeStoreConfig`, `PreparedStore`, `RuntimeStoreFactory` |
| `src/functualize/_types/host.py` | — | +~10: `register_runtime_store_factory` |
| `src/functualize/_types/errors.py` | — | +~25: `RuntimeStoreSelectionError` |
| `src/functualize/_app/store_selection.py` | new | ~200 |
| `src/functualize/_app/boot.py` | 2 298 | ±~25: `_select_runtime_store` delegates |
| `src/functualize/_app/impl.py`, `src/functualize/app/core.py` | — | +~30: registration, refusal after selection |
| `src/functualize/plugin/__init__.py` | — | exports (D-2) |
| `src/functualize/testing/conformance/{__init__,baseline,capabilities}.py` | new | ~450 (D-2 a) |
| `src/functualize/_primitives/document_store.py` | 1 155 | marker rewording only |
| `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/` `_factory.py`, `_runtime_store.py`, `_transaction.py`, `_workflow_sql.py`, `_run_sql.py`, `_readers.py`, `_driver.py`, `_migrations.py`, `_retention.py`, `_legacy_import.py`, `_import_cli.py`, `_schema/0001_runtime_schema.sql` | new | ~2 000 total; **no module and no class over 500** |
| `…/_plugin.py` | 155 | rewrite of `__call__` and config: register the factory; no offer |
| `…/substrate.py` | 225 | docstring only (S-7) |
| `…/__init__.py`, `…/pyproject.toml`, `…/README.md` | — | exports, `[project.scripts]`, description, docs |
| `tests/conformance/`, `tests/app/test_store_selection.py`, `tests/substrate_probe/{fakes,tier_a}.py`, plugin tests | new/changed | gates |
| `contributor/architecture/codemaps/{modules,data-flow}.md`, `CHANGELOG.md`, `docs/` | — | S-7, release note |

## Surviving smells

1. **Parallel Inheritance Hierarchies** (with its Shotgun Surgery cost) — every port in
   `_types/persistence.py` has a document implementation (`_primitives/document_store.py`) and a
   SQLite one (`functualize_substrate_sqlite/_workflow_sql.py`, `_run_sql.py`, `_readers.py`).
   **Accepted**: it is what a port with two implementations is; collapsing it would mean one
   store. The conformance suite is the mitigation — a command added to one store and not the other
   fails BASELINE. Not on the forbidden list. **No maintainer review needed.**
2. **Middle Man** — `DocumentRuntimeStore` survives FUN-19 (F-3). Accepted for the same reason the
   shape keeps the document store as the default; its marker is reworded from "FUN-19 removes it"
   to its real end state. **Needs maintainer review: no** — the shape decided the store stays; the
   marker's end-state wording is the only open item and it is FUN-20's to settle when the engine
   stops needing the three document stores directly.
3. **Speculative Generality** — `_required_capabilities` stays `{}`: no shipped feature requires a
   capability the document store lacks. Accepted; giving it a fake entry to exercise the SQLite
   profile would be the config surface nobody asked for that its own docstring warns against.
   **No review.**
4. **`_types/persistence.py` grows to ~836 lines** — not a smell by the catalogue (no class over
   ~15 lines, zero logic), but ADR-026 says re-examine *"if a later feature adds to this module"*
   (`026-…:164-165`). Re-examined: the three additions are read with the port, so they stay.
   **Flagged to the maintainer** under D-1, since it is ADR-026's explicit condition.

The research's carried-forward **Large Class** (`SqliteRuntimeStore` ~700 lines) is **removed**,
not accepted: candidate C is rejected and the settled split keeps every class under 500.

## Design skills consulted

- [x] `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns/SKILL.md`): KISS,
  SRP, composition over inheritance, Rule of Three (decided candidate E).
- [x] `design-patterns-refactoring` (user-level skill in this session's listing; Refactoring.Guru
  catalogue, `cheatsheet.md` smell table and `glossary.md`): Middle Man, Large Class, Speculative
  Generality, Divergent Change, Shotgun Surgery, Parallel Inheritance Hierarchies, Feature Envy.
