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
| the suite | `functualize.testing.conformance` — `run_baseline(make_store)`, `run_capability_tiers(make_store)`; plain functions raising `AssertionError`, no pytest import (`functualize.testing` imports none today) |

With D-2 = (b) the first three rows land and the suite stays under `tests/conformance/`.
With D-2 = (c) only `RuntimeStoreFactory` and `StoreProfile` (07 Wave 1's original two) land.

`StoreSubstrate` / `Stored` public export (05 §6, H4) is **not** this ticket's; it is untouched.

## 5. Errors

| Error | Raised | Carries |
|---|---|---|
| `RuntimeStoreSelectionError` (new, `_types/errors.py`) | unknown scheme; two factories for one scheme; D-3 unselected data | scheme(s), claimant plugins, config key, the remedy sentence |
| `RuntimeStoreCapabilityError` (exists, `_types/errors.py:669`) | S-3 | store, field, config key, needed, actual |
| `MigrationRefused` (plugin) | checksum mismatch, gap, ledger ahead, partial revision | version, expected/actual checksum, repair steps |
| `LegacyImportRequired` (plugin, subclass of `RuntimeStoreSelectionError`) | `sqlite` selected, legacy runtime documents present, no cutover marker | db path, the import command line |
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

## 7. Schema

`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_schema/0001_runtime_schema.sql`
implements `contributor/reference/runtime-persistence-data-model.md` §2 (tables, constraints,
indexes), §5 (fencing statements) and §7 (migration discipline) — the frozen contract received
from `runtime-schema-migrations` (D3 = B). Each status `CHECK (status IN (…))` list equals the
state set of its machine in `_types/lifecycle.py`; a test asserts the equality so the two cannot
drift. Plus `runtime_cutover` (§6 above).

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
