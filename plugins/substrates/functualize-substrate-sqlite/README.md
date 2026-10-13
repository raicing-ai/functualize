# functualize-substrate-sqlite

> **Status: Published** — Independently installable from PyPI.

A relational runtime store for a functualize project, in one local SQLite file —
plus the key-value substrate that sits on the same file.

Installing this plugin does not change where anything is stored. It registers
one URL scheme, `sqlite`, and configuration selects it: with nothing configured
every project keeps using the document store, exactly as it did before the
plugin was installed.

Zero external dependencies beyond the standard library's `sqlite3`.

## Installation

```bash
pip install functualize-substrate-sqlite
```

## Selecting the store

```toml
[runtime_store]
url = "sqlite:"
```

| `url` | The file |
|---|---|
| `sqlite:` | the project's own `state.db` |
| `sqlite:///var/lib/myapp/state.db` | that absolute path |
| `sqlite:data/state.db` | relative to the project root |

`sqlite://host/…` is refused: SQLite is a local file, and a URL naming a host
asks for something this store cannot honour.

`sqlite:` puts `state.db` where the filesystem substrate puts a project's
freshness record — `.functualize/state.db` in a declared project, otherwise the
XDG cache, keyed by project id. Both backends ask `resolve_fresh_location` the
same question, so they cannot disagree about where a project's state lives.

The former `[plugin.substrate-sqlite] db_path` setting is gone: the location is
part of the URL.

**The database is local.** Its profile declares `multi_machine=False`: the file
is a path on this host, reachable from every process on it and from nothing
outside it. What SQLite buys over the file substrate is one lock across every
document and a real compare-and-swap, not reach.

Selected, the store is prepared at boot step 6.5 and hands boot both the
relational store for runtime truth and a `SQLiteSubstrate` on the same file, so
the freshness record and shell history live beside runtime truth instead of
falling back to the filesystem. A selected store that cannot open, migrate or
pass its health check **aborts boot**, uncaught: nothing comes up on documents
instead, and no weaker store is substituted.

With nothing configured there is one refusal, and it is not a fallback: if a
`state.db` already holds runtime data this project would otherwise stop seeing,
boot stops and says so, with the remedy in the message.

## What it stores

Relational tables, one per entity the runtime ports speak:

| | |
|---|---|
| `runs`, `run_attempts`, `run_events` | execution records and what happened in them |
| `workflow_scopes`, `workflow_steps`, `workflow_branches` | the walk, its steps and its branches |
| `scope_state`, `scope_events` | a scope's own state, and its event log |
| `input_requests`, `input_candidates` | a prompt and the answers offered |
| `outbox`, `artifact_refs` | what must be delivered, and what a run produced |
| `namespaces`, `schema_migrations`, `runtime_cutover` | the namespace boundary, applied revisions, and the marker below |

`SQLiteSubstrate` adds a `documents` table beside them, one row per key-value
document — the freshness record, shell history, and for now the run log the
engine still writes there. See [The marker](#the-marker-which-store-owns-this-files-runtime-data)
for what that coexistence means.

That substrate is deliberately a document store rather than a second relational
model. [ADR-022](https://github.com/raicing-ai/functualize/blob/master/contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md)
records why: a backend-agnostic *key-value* protocol can only offer the
intersection of every backend, which is worth least exactly where having a real
database is worth most. The port is `read`, `write`, `lock`, `clear`, `delete`,
`describe` over whole documents.

What SQLite buys over a file, given that shape:

| | |
|---|---|
| `revision` + `revision + 1` in one statement | real compare-and-swap, so `write(expect=)` can refuse a stale write |
| `INSERT … ON CONFLICT DO UPDATE` | atomic upsert, with no read-then-write window |
| `BEGIN IMMEDIATE` | **one lock across every document** — the lock-order inversion the filesystem substrate cannot close |
| WAL journal mode | readers are not blocked by a writer |

## The marker: which store owns this file's runtime data

Runtime truth used to live in `documents['runs']` and `documents['scopes']`,
and it still can: a file may be **pre-relational** (created by the document
store, its runtime documents not yet imported) or **born relational** (created
by this store, which has never held legacy runtime documents). A guard that
reads only "`documents` holds runtime keys, and there is no marker" cannot tell
those two apart, and it refused every `sqlite:` project on its second boot.
`runtime_cutover` therefore records the provenance, and the guard reads it.

One row, written once per file, in the frozen revision `0001`:

| `source` | Written by | `imported_at` | `source_digest` | `backup_path` |
|---|---|---|---|---|
| `documents` | the importer | import time, ISO-8601 UTC | the importer's digest of the legacy runtime rows | the backup's path, **non-NULL** |
| `born-relational` | `prepare`, the first time it opens a file holding no legacy runtime documents | that moment, ISO-8601 UTC | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` = `sha256(repr([]))` | **NULL** — there is nothing to back up |

`prepare` orders its work `migrate` → construct the substrate → the conditional
insert → the guard → the store, and the insert is one statement in one batch
under `BEGIN IMMEDIATE`, so two processes cannot both claim the birth.

The guard, read after that insert. **Precedence, top to bottom; the first row
that matches decides:**

| # | State of the file | Outcome |
|---|---|---|
| G-1 | more than one marker row, or a `source` that is neither value above, or a row breaking its own line of the table above (`documents` with NULL `backup_path` or a digest that is not 64 hex digits; `born-relational` with a non-NULL `backup_path` or a digest other than the constant; an `imported_at` that does not parse as ISO-8601) | **refuse** `CutoverMarkerInvalid`, naming the path, the offending row and both remedies: restore the backup, or delete the row and run `functualize-sqlite-import --db <path>`, which then decides |
| G-2 | exactly one valid marker, of either source | **boot**, whatever `documents` holds. Legacy runtime keys beside a marker are expected in both cases: after an import the source rows are retained (the backup *and* the table), and on a born-relational file the run log keeps writing `documents['runs']` until the engine moves that write onto the relational store |
| G-3 | no marker, and legacy runtime keys present | **refuse** `LegacyImportRequired`, naming `functualize-sqlite-import --db <path>` — unchanged, and still the only way in for such a file |
| G-4 | no marker, no legacy runtime keys | unreachable after the insert; if it is ever observed it is a defect, so it refuses with `CutoverMarkerInvalid` rather than booting unmarked |

Both refusals are `RuntimeStoreSelectionError`s, so boot aborts and nothing
falls back to the document store.

The importer and the with-nothing-configured probe read the same marker, so a
file cannot be relational to one and not to the other:
`functualize-sqlite-import` on a `born-relational` file exits **0**, changes
nothing and reports "born relational; nothing to import" — otherwise it would
import the run log's own `documents['runs']` as if it were legacy. The
with-nothing-configured probe counts a file with any valid marker as relational,
and its message then names no import command.

**One limitation is accepted.** A framework *older than this marker*, writing
into a born-relational file, puts its runtime documents into `documents`. The
marker boots that file anyway (G-2), and those documents are neither imported
nor read: out of contract, and undetected. Several framework versions sharing
one store file is unsupported before release, and a branch-era file created
before the marker existed (born relational, unmarked) is refused (G-3) — it is
not a shipped state.

## API

The package exports seven names: `SQLiteSubstratePlugin` (the plugin object),
`SqliteRuntimeStoreFactory` (the factory it registers under the scheme
`sqlite`), `SqliteRuntimeStore` (the relational store boot builds from it),
`SQLiteSubstrate`, the two refusals `LegacyImportRequired` and
`CutoverMarkerInvalid`, and the store's `SQLITE_PROFILE`.

- **`SQLiteSubstrate`** — the `StoreSubstrate` implementation. Construct it with
  a path if you want to read or write documents directly:

  ```python
  from functualize_substrate_sqlite import SQLiteSubstrate

  substrate = SQLiteSubstrate("state.db")
  stored = substrate.read("my-key")
  substrate.write(
      "my-key",
      {"count": (stored.data["count"] if stored else 0) + 1},
      expect=stored.revision if stored else None,
  )
  ```

  `write` returns `False` when `expect` no longer matches. That is an ordinary
  outcome, not an error: somebody wrote between your read and your write, so read
  again and retry.

- **`SQLiteSubstratePlugin`** — registers the factory and does nothing else.
  Installing it selects nothing; `[runtime_store] url = "sqlite:…"` does.

See [`examples/persistent_counter/`](examples/persistent_counter/) for the
read-modify-write loop in full.

### `functualize-sqlite-import`

The offline importer: it does not boot the application, it backs the file up
first, it verifies what it wrote, and it refuses the whole import if any record
is illegal. The documents stay authoritative until it succeeds.

```bash
functualize-sqlite-import --project . --dry-run   # read, check, report; write nothing
functualize-sqlite-import --db path/to/state.db   # the file, instead of the project's state.db
functualize-sqlite-import --resume                # finish an import whose marker exists
functualize-sqlite-import --rollback              # undo a recorded import; documents become authoritative again
```

## Development

```bash
uv run pytest plugins/substrates/functualize-substrate-sqlite/tests/ -v
uv build --package functualize-substrate-sqlite
```
