# FUN-19 — The SQLite runtime provider, legacy migration, and the tiered conformance suite

**Status:** specified against the approved shape; **three decisions open** (§7). Do not execute
the waves those decisions gate until they are answered (`tasks.md` names which).

**Shape authority:** SD/12583004 *"Shape Intent — Store Substrate and Relational SQLite Runtime
Provider"*, v1, `Authority: Approved` (read live 2026-10-05). Surfaces S-1 … S-8, obligations
I-1 … I-9 and experiments E-1 … E-6 below carry that page's numbering. `plan.md` → `## Alignment`
names them in the page's words.

## Goal

The first real RuntimeStore, and the tiered suite every later backend must pass.

## Why

SQLite is the reference implementation: it is the only backend that is both transactional and
offline-capable, which makes it the one that can be the default. The conformance suite written
here is what makes FUN-22 cheap.

## Acceptance criteria

These are **gates run at authoring time**, with each task's file scope equal to the gate's hit set.
Wording is FUN-19's own (read live 2026-10-05, *Revised 2026-09-21*), unchanged.

1. SqliteRuntimeStore declares cross_aggregate_atomicity=True, fencing='cross-process',
   offline_capable=True, and passes the tier each field gates.
2. The BASELINE conformance tier passes for every store including DocumentRuntimeStore. A store
   that declares a capability False does not run that capability's tier and cannot be selected by
   a feature needing it.
3. Legacy migration is OFFLINE with backup and verification. No indefinite dual write (rejected as
   RP-7).
4. Migration REFUSES illegal records rather than importing them — which is why FUN-24 comes first.
5. BatchOnlySqliteDriver from FUN-25 runs against this store in Tier A and passes, proving the
   transaction buffers.

## 1. Behaviour, by surface

Each row is what a user, operator or plugin author observes. The *Gate* column is the executable
check; `tasks.md` owns where it lives.

| Surface | Behaviour | Gate |
|---|---|---|
| **S-1** selecting the provider | The runtime store is chosen by one configuration value read at boot step 6.5. Installing `functualize-substrate-sqlite` **registers** a store under the scheme `sqlite`; it no longer changes where anything is stored. With the plugin installed and nothing configured, runtime truth, freshness and shell history stay where the document store puts them — unless §7 D-3 applies. | boot with plugin installed + no config → `DocumentRuntimeStore`; with `sqlite` configured → `SqliteRuntimeStore`; on `func` cold, `func` warm and `boot_static` |
| **S-2** selected but cannot start | A configured scheme whose store cannot be built, migrated or health-checked **aborts boot** with a named error. Nothing falls back to documents. A configured scheme no installed plugin registers is the same refusal. Nothing configured → documents, as today. | E-1 on all three boot paths |
| **S-3** capability refusal | A configuration that requires a capability the selected store declares `False` refuses at boot with `RuntimeStoreCapabilityError` naming the store, the field and the config key. Already landed for the document store (FUN-17 T13); this ticket makes it apply to the SQLite store too. | refusal test over both profiles |
| **S-4** schema migrations | On `prepare`, before any job runs: an empty database becomes version 1 in one unit; a second boot is a no-op; a checksum mismatch, a gap, or a database ahead of the code refuses boot with repair steps. Forward only. | migration tier (I-9 included) |
| **S-5** legacy import | An explicit, offline command — it does not boot the app — copies the legacy `documents(key, payload, revision)` runtime documents into the relational schema by the seven steps the shape quotes from 08. Illegal records (judged by FUN-18's transition tables) are refused and listed. The report states that the 500-record cap may already have evicted terminal records. A failure at any step leaves the legacy table authoritative and untouched. Freshness and shell-history keys are not runtime truth and stay in `documents` (I-8). With `sqlite` selected and un-imported legacy runtime documents present, boot refuses and names the command (shape Q-4). | E-4, E-5 |
| **S-6** inspectable data | Every runtime entity of I-1 is a row in a named table; `sqlite3 <db> "SELECT status, count(*) FROM workflow_scopes GROUP BY 1"` answers without decoding JSON. | baseline reads + a raw-SQL test |
| **S-7** honest docs and naming | No file in the plugin claims multi-machine reach (`substrate.py:20-22` does today). Package description, README and the plugin's own `version` agree (`pyproject.toml` says `0.4.0`, `_plugin.py:48` says `0.2.0`). `multi_machine=False` is the statement. | `rg -n "different machines" plugins/` returns nothing; version-agreement test |
| **S-8** conformance suite | BASELINE runs against every store; each capability tier runs only when the profile declares it. The suite takes a store factory, so a third-party backend can run it (scope of "third-party": §7 D-2). | AC-1, AC-2 |

### The SQLite profile (AC-1, shape *Profiles* table, 05 §2.1)

| Field | Value | Why it is true |
|---|---|---|
| `cross_aggregate_atomicity` | `True` | one `BEGIN IMMEDIATE … COMMIT` (or one `batch`) per transaction |
| `fencing` | `"cross-process"` | the conditional `UPDATE … lease_generation` of data model §5 |
| `multi_process` | `True` | one file, WAL, bounded busy timeout |
| `multi_machine` | `False` | a local file (S-7) |
| `durable_outbox` | `True` | an `outbox` row commits in the transition's unit (data-model §4). **Recording only** — the dispatcher is FUN-21's, so this tier tests that intents land with their transition and survive a crash either side of commit, never dispatch |
| `versioned_migrations` | `True` | S-4 |
| `interactive_transaction` | `False` | the store issues writes only as one batch, so it never needs one — and AC-5 proves it. The matrix measures local SQLite `yes` (`contributor/reference/substrate-capability-matrix.md:85`); this is the store's promise, under-declared and never over-declared — `DOCUMENT_PROFILE`'s own rule (`_primitives/document_store.py:156-157`) |
| `remote` | `False` | |
| `max_document_bytes` | `None` | the matrix's local-SQLite row; "nothing refused what was attempted", not "no limit" |
| `offline_capable` | `True` | AC-1 |

`interactive_transaction=False` is a deliberate spec choice: the store's write path is batch-only so
that AC-5 is a property of the shipped code, not of a test double. The shape delegates these three
fields to the spec.

## 2. Internal obligations (from the shape, binding)

I-1 schema tables · I-2 *"if you would ever want an index on it, it is a column"* · I-3 fencing by
one conditional update, `Conflict` as a value · I-4 the transaction buffers and commits once ·
I-5 SQLite policy (`foreign_keys=ON` per connection, WAL only for files, busy timeout →
**retryable** error, `BEGIN IMMEDIATE` on claim/CAS, no independent `:memory:` connections in
tests) · I-6 fault injection between every write + two-process stale writer · I-7 AC-5 ·
I-8 the SQLite work lives in the plugin and `substrate.py`'s behaviour is unchanged · I-9
`create_all()` only for an empty database. **I-8's "no framework file changes" does not survive
contact with S-1** — see `plan.md` → *Findings* F-2 and §7 D-1.

## 3. What AC-5 means, concretely

`BatchOnlySqliteDriver` is a test instrument (`tests/substrate_probe/fakes.py:92`): in-memory SQLite
behind a D1-shaped surface — `execute`, `batch`, `read(key)` over its own `documents` table, and a
`transaction()` that raises `NoInteractiveTransactionError`. "Tier A" is FUN-25's module of that
name, `tests/substrate_probe/tier_a.py`.

The store therefore speaks to SQLite through a **driver seam** whose whole surface is
`batch(statements)` and `query(sql, params)`; the shipped local driver implements `batch` as
`BEGIN IMMEDIATE … COMMIT`. AC-5 passes when a `SqliteRuntimeStore` constructed over a
`BatchOnlySqliteDriver` runs the BASELINE tier green from `tier_a.py`. The instrument gains one
read-only method, `query(sql, params) -> list[tuple]`, because its only read today is a
`documents` key lookup; that is a change under `tests/`, never to its refusal. Any store code path
that needs an interactive transaction then fails the gate by raising — which is the proof that the
transaction buffers.

## 4. Experiments (shape E-1 … E-6) as gates

| # | Gate | Fails when |
|---|---|---|
| E-1 | `sqlite` configured, `prepare()` made to raise (unwritable path; a doctored `0001` checksum) → boot fails with a named error on `func` cold, `func` warm and `boot_static` | any path comes up on documents |
| E-2 | two OS processes claim one scope; the loser writes `scope_state` with its old generation | the write lands, or the live value is lost |
| E-3 | a fault raised between every statement of each Wave 3 transition | any partial row survives |
| E-4 | legacy `documents` holding one `completed` scope with a live lease | it is imported, or the source changed |
| E-5 | the importer killed at each of the seven steps | a second authority exists afterwards |
| E-6 | AC-5 as in §3 | BASELINE is red over `BatchOnlySqliteDriver` |

## 5. Out of scope

Anything belonging to another wave. This initiative fails most plausibly by one ticket quietly
absorbing the next one's work — if you find yourself needing a later wave's deliverable, say so
rather than building it here. Named (shape *Non-goals*): rewiring workflow state, suspension and
lease fencing through the engine (FUN-20); the outbox **dispatcher** and gate evidence (FUN-21);
any network provider and `multi_machine=True` (FUN-22); workspace/AgentFS (FUN-23); the Design 1
provider family; widening `StoreSubstrate`; dual write; Restate/DBOS; artifact bytes in rows;
retention as a user command. Also out: importing the JSON documents under `.functualize/`
(shape M-2 = (a)); deprecating `ScopeStore`/`RunStore` (05 §6 — not in the shape, and
`.spec/CONSTITUTION.md` forbids deprecation shims pre-release).

## 6. Evidence baseline

Rebased 2026-10-05 onto `origin/master` @ `e8e3b867` (was `8c06198`, 35 commits behind; the rebase
replayed the branch's three commits without conflict). Every `path:line` in this package was
re-read at that commit. The research tree's citations are at `8d450ad`/`93ecd18` and are **not**
re-verified wholesale — `plan.md` → *Findings* lists the ones that proved stale.

## 7. Decisions open — put to the maintainer on MCH-149

| # | Decision | Recommendation | Gates |
|---|---|---|---|
| D-1 | Accept the bounded framework change S-1 needs (I-8 is falsified) | accept | tasks 1–4 |
| D-2 | How public the plugin-author contract is (export the persistence vocabulary; ship the suite in `functualize.testing`) | export both | tasks 4, 12, 13 |
| D-3 | Plugin installed, nothing configured, legacy SQLite runtime data present → refuse boot | refuse | tasks 3, 15 (the guard) |

Settled within the shape's delegated latitude (recorded here, reversible by the maintainer):
config key `runtime_store.url` with `sqlite:` / `documents:` schemes; import command
`functualize-sqlite-import`; retention applied once in `prepare()` after `migrate()`; the
migration runner lives in the plugin (`plan.md` → *Decisions taken*).
