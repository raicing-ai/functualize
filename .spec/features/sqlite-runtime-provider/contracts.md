# FUN-19 — Contracts

**Status:** specified. Items marked **(D-n)** follow the maintainer's answers (`spec.md` §7:
D-1 a, D-2 a, D-3 refuse), so each takes its recommended form.

An interface that changes without appearing here is the defect this file exists to prevent.

## 1. Configuration — the selection (S-1, S-2)

| Key | Values | Default | Read by |
|---|---|---|---|
| `runtime_store.url` | `documents:` · `sqlite:` (project default path, `<state dir>/state.db`, the plugin's existing `DEFAULT_DB_NAME`) · `sqlite:///abs/path.db` · `sqlite:relative/path.db` (relative to the project root) | unset → documents | `_app/store_selection.py`, boot step 6.5, both boot paths |

- Spelling is delegated latitude (shape *Delegated latitude*); the behaviour is not.
- A scheme no registered factory serves → `RuntimeStoreSelectionError` naming the scheme, the
  registered schemes and the key. Uncaught: boot aborts.
- `plugin.substrate-sqlite.db_path` (today's only plugin setting, `_plugin.py:133-155`) is
  **removed**: the location is part of the URL. No shim (`.spec/CONSTITUTION.md` → *Forbidden
  Patterns*: no backward-compat shims pre-release). Stating it in the release note is task 18.

## 2. Framework vocabulary added — `src/functualize/_types/persistence.py` (D-1)

```python
@dataclass(frozen=True)
class RuntimeStoreConfig:
    """What boot resolved for the store: the URL and where the project lives."""
    url: str                 # "documents:" when nothing is configured
    scheme: str              # the part before ":" — the registry key
    project_root: Path       # app.fresh_root, so relative paths cannot follow a chdir
    config_key: str = "runtime_store.url"

@dataclass(frozen=True)
class PreparedStore:
    """What a factory hands boot: the store, and the substrate for derived data."""
    store: RuntimeStore
    #: Where `fresh` and `shell-history` live when this store is selected; None → the
    #: project's default substrate. Lets one SQLite file carry both (I-8).
    substrate: StoreSubstrate | None

@runtime_checkable
class RuntimeStoreFactory(Protocol):
    scheme: str
    profile: StoreProfile    # declared before prepare, so a refusal needs no I/O

    def prepare(self, config: RuntimeStoreConfig) -> PreparedStore:
        """Open, migrate, health-check. Raise to abort boot; never degrade."""

    def unselected_data(self, project_root: Path) -> str | None:
        """A sentence naming runtime data this backend holds for the project, or None.
        Asked only when nothing is configured (D-3)."""
```

`StoreSubstrate` is imported under `TYPE_CHECKING` from `_types/protocols.py` (same layer). The
module stays logic-free (ADR-026's condition).

## 3. Plugin host — `PluginHost.register_runtime_store_factory` (D-1)

```python
# src/functualize/_types/host.py, PluginHost Protocol; implemented in _app/impl.py, app/core.py
def register_runtime_store_factory(self, factory: RuntimeStoreFactory) -> None: ...
```

- Called by boot itself first, on both paths, before plugins load:
  `app.register_runtime_store_factory(DocumentRuntimeStoreFactory(app))` (scheme `documents`,
  defined in `_app/store_selection.py`). An unset `runtime_store.url` reads as `documents:`.
- Then from a plugin's registration `__call__` (boot step 4), on both boot paths.
- Two factories for one scheme → `RuntimeStoreSelectionError` at step 6.5 naming both plugins
  (same "two claims refuse; neither wins" rule as `_resolve_substrate_claim`, `boot.py:268-303`).
- After step 6.5 → refused, as `install_substrate` / `offer_substrate` already are.
- `offer_substrate` and `install_substrate` **stay** (other plugins and tests use them); the SQLite
  plugin stops calling `offer_substrate`.

## 4. Public API — `functualize.plugin.__all__` (D-2)

Today the list carries no persistence name (checked: `SubstrateInstallError` is the only storage
symbol). `tests/test_public_api_surface.py` enforces the list.

| Recommendation (D-2 = a) | Added |
|---|---|
| the factory contract | `RuntimeStoreFactory`, `RuntimeStoreConfig`, `PreparedStore`, `StoreProfile`, `RuntimeStore`, `RuntimeTransaction` |
| what a store implements | the five writer and three reader protocols, and the command, outcome, view and query dataclasses of `_types/persistence.py.__all__` |
| errors | `RuntimeStoreCapabilityError`, `RuntimeStoreSelectionError`, `IllegalTransition` (`_types/errors.py:719`) |
| the suite | `functualize.testing.conformance` — `run_baseline(make_store)`, `run_capability_tiers(make_store, root=None, *, hooks=None)`, `capability_report(...)` and the hook types of §4a; plain functions raising `AssertionError`, no pytest import (`functualize.testing` imports none today) |

With D-2 = (b) the first three rows land and the suite stays under `tests/conformance/`.
With D-2 = (c) only `RuntimeStoreFactory` and `StoreProfile` (07 Wave 1's original two) land.

`StoreSubstrate` / `Stored` public export (05 §6, H4) is **not** this ticket's; it is untouched.

## 4a. The capability suite's harness hooks — `functualize.testing.conformance` (frozen 2026-10-06)

**Why it exists.** Some capabilities cannot be observed through the port. `durable_outbox` has a
writer (`EffectWriter`) and no reader, and `versioned_migrations` has no schema API. Atomicity at
the port can only fault *between commands*: a store that writes its documents one after another
passes the same check (`tests/conformance/test_capabilities.py`, the overclaiming-document-store
test, says so). The hooks give the **suite** a way in. They are **not** port surface:
`functualize._types.persistence.__all__` and `functualize.plugin.__all__` do not change.

### Signature

```python
# src/functualize/testing/conformance/hooks.py   (new; no pytest import, public names only)

class StatementFault(Exception):
    """Raised by a StatementFaults hook inside a commit; the tier catches exactly this."""

@runtime_checkable
class StatementFaults(Protocol):
    def make_store(self, root: Path, fault_at: int | None) -> RuntimeStore:
        """A store over `root`. Each commit raises StatementFault immediately before
        statement `fault_at` (0-based) of its atomic unit, after the first `fault_at`
        statements have executed *inside* that unit; None = never. A unit with ≤ fault_at
        statements commits normally — that is how the tier learns the unit's length."""

@dataclass(frozen=True)
class RecordedIntent:
    namespace: str
    topic: str
    payload: Any
    idempotency_key: str | None

@runtime_checkable
class OutboxProbe(Protocol):
    def pending(self, root: Path) -> Sequence[RecordedIntent]:
        """Committed, unpublished intents of the store over `root`, in commit order,
        read through a fresh handle — never through a store object a crashed process held."""

@runtime_checkable
class MigrationHarness(Protocol):
    latest_version: int
    #: schemas lay_down can produce; non-empty. SQLite: ("empty", "documents-only").
    historical: Sequence[str]
    #: damage `damage` can do; ⊇ {"checksum", "ahead"}, ⊇ {"gap"} once latest_version ≥ 2.
    #: SQLite: ("checksum", "ahead", "partial").
    refusals: Sequence[str]
    def lay_down(self, root: Path, schema: str) -> None: ...
    def damage(self, root: Path, refusal: str) -> None:
        """Damage the current-version store at `root` so the next open must refuse."""
    def version(self, root: Path) -> int: ...

@dataclass(frozen=True)
class HarnessHooks:
    statement_faults: StatementFaults | None = None
    outbox: OutboxProbe | None = None
    migrations: MigrationHarness | None = None

@dataclass(frozen=True)
class TierRun:
    name: str        # e.g. "cross_aggregate_atomicity=True" — the same string as today
    strength: str    # what was actually exercised, e.g. "statement faults at 7 positions"

@dataclass(frozen=True)
class CapabilityReport:
    runs: tuple[TierRun, ...]
    @property
    def names(self) -> tuple[str, ...]: ...

# src/functualize/testing/conformance/capabilities.py
def capability_report(make_store: MakeStore, root: Path | None = None,
                      *, hooks: HarnessHooks | None = None) -> CapabilityReport: ...
def run_capability_tiers(make_store: MakeStore, root: Path | None = None,
                         *, hooks: HarnessHooks | None = None) -> tuple[str, ...]:
    return capability_report(make_store, root, hooks=hooks).names    # unchanged return type
```

### Rules (each one is a gate in `tasks.md` task 13)

| # | Rule |
|---|---|
| H-1 | `run_capability_tiers(make_store, root=None)` with no hooks behaves as before for any store whose declared tiers need no hook. The document store's run list is `("fencing='cross-process'", "offline_capable=True")`. The second entry is new, from H-6, and is not a hook. |
| H-2 | A tier whose profile field switches it on and whose hook is `None` **raises `AssertionError`**, naming the field and the missing `HarnessHooks` attribute. Nothing becomes a skip. Which tier needs which hook: `cross_aggregate_atomicity=True` → `statement_faults`; `durable_outbox=True` → `outbox`; `versioned_migrations=True` → `migrations`. |
| H-3 | Atomicity with the hook: the 3-command, two-scope-plus-run unit is committed through `make_store(root, fault_at=k)` for k = 0, 1, … until a commit completes. Each faulted k must leave nothing, checked through a fault-free store. The completing commit must land the whole unit. At least one k must fault. The command-level faults and the part-way `IllegalTransition` refusal stay in the tier. Strength = `"statement faults at N positions + command faults at M"`, followed by the tier's observation limit: it reads the *outcome* through the ports, so a commit split into batches whose leading batch writes no port-visible row is not seen — that split is its own repair (MCH-156). |
| H-4 | Outbox: three child processes on one store directory. (i) Append an intent with a step, then `os._exit` **inside** the transaction (crash before commit): neither the intent nor the step is present. (ii) Append, let the block exit, then `os._exit` immediately (crash after commit): the intent is present **exactly once** with its payload intact, and so is the step. (iii) A unit that raises after appending: absent. Strength = `"crash before commit, crash after commit, raised unit"`. |
| H-5 | Migrations: for each `historical` schema, `lay_down` into a fresh directory → `make_store` opens it → `version == latest_version` → a claim and a read work → a reopen changes nothing. For each `refusals` entry: create a current store, close it, `damage`, then `make_store` must raise something other than `AssertionError`, with a non-empty message. The declared sets must meet H-5's minimums or the tier fails. Strength = `"N historical, M refusals"`. |
| H-6 | **New observable tier `offline_capable=True`** (AC-1 names the field; until now no tier gated it). BASELINE's first check runs with `socket.socket`, `socket.create_connection` and `socket.getaddrinfo` refusing, using the same technique as FUN-25's `_network_taken_away` (`tests/substrate_probe/fakes.py:59`), re-written in the library because `tests/` is not importable from `src/`. It needs no hook. Strength = `"baseline round trip, network refused"`. |
| H-7 | `fencing="cross-process"` is unchanged. Its strength reports honestly what it observes: `"stale write from a second OS process landed nothing"`. It cannot say which of the store's guards held it (the wave-4 verification removed only `_move`'s SQL fence and the tier stayed green). |

**Where SQLite's hooks live:** `tests/conformance/sqlite_hooks.py`. This is test code, and it uses
the plugin's constructors and private modules the way `tests/conformance/test_baseline.py` already
does. `statement_faults` wraps `LocalSqliteDriver` in a driver whose `batch` submits
`statements[:fault_at]` plus one statement that fails, all in **one** inner `batch`. The real
`BEGIN IMMEDIATE` unit therefore executes `fault_at` statements and then rolls back, which is the
all-or-nothing behaviour task 5 proved. The wrapper then raises `StatementFault`. The fault lands
inside the store's own unit; it is not simulated around it. No store attribute
is monkeypatched. `outbox` reads the `outbox` table over a fresh `sqlite3` connection. `migrations`
lays down `"empty"` (no file) and `"documents-only"` (the legacy `documents` table holding only a
`fresh`/`shell-history` key — runtime keys would rightly raise `LegacyImportRequired`). It damages
by editing the `schema_migrations` checksum, inserting a ledger row above the shipped set, and
dropping one table of `0001` while keeping its ledger row (`"partial"`).

**Exports added to `functualize.testing.conformance.__all__`:** `capability_report`,
`HarnessHooks`, `StatementFaults`, `StatementFault`, `OutboxProbe`, `RecordedIntent`,
`MigrationHarness`, `CapabilityReport`, `TierRun`. `tests/test_public_api_surface.py` covers
`functualize.testing` but not `.conformance`; task 13 adds the sub-package to it, so this surface
is enforced the way the rest of D-2's is.

## 5. Errors

| Error | Raised | Carries |
|---|---|---|
| `RuntimeStoreSelectionError` (new, `_types/errors.py`) | unknown scheme; two factories for one scheme; D-3 unselected data | scheme(s), claimant plugins, config key, the remedy sentence |
| `RuntimeStoreCapabilityError` (exists, `_types/errors.py:669`) | S-3 | store, field, config key, needed, actual |
| `MigrationRefused` (plugin) | checksum mismatch, gap, ledger ahead, partial revision | version, expected/actual checksum, repair steps |
| `LegacyImportRequired` (plugin, subclass of `RuntimeStoreSelectionError`) | `sqlite` selected, legacy runtime documents present, no cutover marker | db path, the import command line |
| `CutoverMarkerInvalid` (plugin, subclass of `RuntimeStoreSelectionError`) | §6a G-1 / G-4 — a degenerate or contradictory `runtime_cutover` | db path, the offending row, both remedies |
| `SqliteBusyError` (plugin, retryable) | busy timeout exhausted (I-5) | db path, timeout; `retryable = True` |
| `LegacyRecordRefused` (plugin, in the import report, not raised to boot) | AC-4 | key, record id, the illegal pair |

## 6. Command — `functualize-sqlite-import` (S-5)

Console script of `functualize-substrate-sqlite` (`[project.scripts]`). Does **not** boot the app.

```
functualize-sqlite-import [--project PATH] [--db PATH] [--dry-run] [--resume | --rollback]
exit 0   imported and verified; report printed; backup path printed
exit 3   refused records present — nothing imported, source untouched, report lists them
exit 4   verification failed — rolled back, source authoritative
exit 5   another import holds the migration lock
```

Spelling and exit numbers are delegated latitude; the seven steps, the refusal and "source stays
authoritative" are not. The cutover marker is a row in the target database
(`runtime_cutover(source, imported_at, source_digest, backup_path)`), written in step 5's unit.
Its provenance, and the guard that reads it, are §6a.

## 6a. Marker provenance and the boot guard (amended 2026-10-06)

**The defect this amends.** The guard used to be: refuse when "`documents` holds runtime keys and
no `runtime_cutover` row". That cannot tell a file **born relational** from one that is
**pre-relational**. With `sqlite` selected, the framework's run log still writes `documents['runs']`
into the same file through `SQLiteSubstrate` (`src/functualize/_primitives/run_store.py:244`).
And `prepare` had no step that recorded a fresh file's birth (`_factory.py:100-116`). So every
`sqlite:` project booted once and was refused on every later boot (reproduced on MCH-149 at
`46dc590f`).

**The marker gains a second provenance.** The table is frozen in revision `0001`, so no new
revision is needed: both values fit its columns as shipped.

| `source` | Written by | `imported_at` | `source_digest` | `backup_path` |
|---|---|---|---|---|
| `documents` (exists) | the importer, step 5's unit (§6) | import time, ISO-8601 UTC | the importer's digest of the legacy runtime rows | the backup's path, **non-NULL** |
| `born-relational` (new) | `prepare`, the first time it opens a file that holds no legacy runtime documents | that moment, ISO-8601 UTC | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` = `sha256(repr([]))`, the importer's own digest of a `documents` table holding no runtime rows | **NULL** — there is nothing to back up |

**How `prepare` writes it, race-free.** The order is `migrate` → construct `SQLiteSubstrate(path)`
→ the conditional insert → the guard → the store. The substrate's own DDL creates `documents`, so
the next statement is always valid; `substrate.py` stays unchanged. The insert is **one statement
in one batch**, so it runs under `BEGIN IMMEDIATE`:

```sql
INSERT INTO runtime_cutover (source, imported_at, source_digest, backup_path)
SELECT 'born-relational', :now, :born_digest, NULL
 WHERE NOT EXISTS (SELECT 1 FROM runtime_cutover)
   AND NOT EXISTS (SELECT 1 FROM documents WHERE <legacy runtime keys>);
```

Two processes opening a fresh file at once produce exactly one row. A file that already holds
legacy rows never gets one.

**The guard, read after the insert. Precedence, top to bottom; the first row that matches decides:**

| # | State of the file | Outcome |
|---|---|---|
| G-1 | more than one marker row, or a row whose `source` is neither value above, or a row whose columns break its own line of the table above (`documents` with NULL `backup_path` or a digest that is not 64 hex digits; `born-relational` with a non-NULL `backup_path` or a digest other than the constant; an `imported_at` that does not parse as ISO-8601) | **refuse**: `CutoverMarkerInvalid` (new, plugin, subclass of `RuntimeStoreSelectionError`). Names the path, the offending row and both remedies: restore the backup, or delete the row and run `functualize-sqlite-import --db <path>`, which then decides |
| G-2 | exactly one valid marker, of either source | **boot**, whatever `documents` holds. Legacy runtime keys beside a marker are expected in both cases. After an import, the source rows are retained (the backup *and* the table). On a born-relational file, the run log keeps writing `documents['runs']` until the durability residual lands |
| G-3 | no marker, and legacy runtime keys present | **refuse**: `LegacyImportRequired`, naming `functualize-sqlite-import --db <path>`. **Unchanged, and still the only way in for such a file** (§6: the refusal is not delegated latitude) |
| G-4 | no marker, no legacy runtime keys | unreachable after the insert. If it is observed, it is a defect: refuse with `CutoverMarkerInvalid` rather than boot unmarked |

**The importer and the D-3 probe read the same marker:**
- `functualize-sqlite-import` on a file whose marker is `born-relational` exits **0**, changes
  nothing, and reports "born relational; nothing to import". Otherwise it would import the run
  log's own `documents['runs']` as if it were legacy. Its existing `documents`-marker path (verify
  the recorded import) is unchanged.
- `unselected_data` (D-3, nothing configured) counts a file with any valid marker as relational.
  Its message then names no import command.

**Why here, and not by stopping the run log's legacy writes.** Moving the engine's run log and
scope writes onto the runtime port is the durability residual's own work
(`tests/integration/test_substrate_durability.py:54-57`, *"the workflow engine still mixes legacy
scope writes with the selected SQL store"*). It is an engine change and out of FUN-19's scope. The
marker records the one fact the guard was missing — when and how the file became relational. It
stays correct after the engine stops writing legacy documents, so nothing done here is undone
later.

**The one limitation accepted.** A framework *older than the marker*, writing into a
born-relational file, puts its runtime documents into `documents`. The marker then boots the file
anyway (G-2), and those documents are neither imported nor read. This is **out of contract,
undetected**. Several framework versions sharing one store file is unsupported before release
(`.spec/CONSTITUTION.md`: no backward-compatibility shims). The same holds for a branch-era file
created before this amendment (born relational, unmarked): it is refused (G-3), and is not a
shipped state.

## 7. Schema

`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/0001_runtime_schema.sql`
implements `contributor/reference/runtime-persistence-data-model.md` §2 (tables, constraints,
indexes), §5 (fencing statements) and §7 (migration discipline) — the frozen contract received
from `runtime-schema-migrations` (D3 = B). Each status `CHECK (status IN (…))` list equals the
state set of its machine in `_types/lifecycle.py`; a test asserts the equality so the two cannot
drift. Plus `runtime_cutover` (§6 and §6a above). Its two `source` values are §6a's, and need no new revision.

## 8. Import-linter contracts

The seven contracts (`pyproject.toml:346-466`) must pass **unchanged**. Every framework edit is in
`_types` (vocabulary) and `_app` (composition root); the plugin package sits outside every
contract's source modules. `uv run lint-imports` is a gate of tasks 1–4.

## 9. Backward compatibility — what breaks, for whom

| Who | Before | After | Falsifier |
|---|---|---|---|
| has `functualize-substrate-sqlite` installed, no config | all documents in `state.db` | documents on the filesystem — **or** a boot refusal when `state.db` holds runtime data (D-3) | E-1 variant: plugin installed, `state.db` with a scope, no config |
| relies on `plugin.substrate-sqlite.db_path` | honoured | ignored; use `runtime_store.url` | config test |
| a plugin calling `offer_substrate` | unchanged | unchanged | `tests/plugins/test_substrate_choice_is_not_hook_order.py` stays green |
| embeds `FunctualizeApp` without plugins | documents | documents | `boot_static` parity test |

The first row is the release-note item the shape's Q-3 calls for.
