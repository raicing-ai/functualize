# functualize-substrate-sqlite

> **Status: Published** — Independently installable from PyPI.

Keeps a functualize project's documents in a local SQLite database instead of in
JSON files. Install it and every store follows: the freshness ledger, workflow
scope records, the state inside them, the run log and shell history all move
together, because there is one decision and one object handed to all of them.

Zero external dependencies beyond the standard library's `sqlite3`.

## Installation

```bash
pip install functualize-substrate-sqlite
```

That is the whole setup. The plugin is discovered through its entry point and
installs itself during boot; nothing needs to be imported or configured.

## What it stores, and how

One table, one row per document:

```sql
CREATE TABLE documents (
  key TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL
);
```

That is deliberately a document store rather than a relational model of runs and
scopes. [ADR-022](https://github.com/raicing-ai/functualize/blob/master/contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md)
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

## Where the database goes

`.functualize/state.db` in a declared project; otherwise the XDG cache, keyed by
project id — the same question `resolve_fresh_location` answers for the
filesystem substrate, asked through the same call, so the two backends cannot
disagree about where a project's state lives.

Override it explicitly:

```toml
[plugin.substrate-sqlite]
db_path = "/var/lib/myapp/state.db"
```

## API

Two public names:

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

- **`SQLiteSubstratePlugin`** — the plugin object. It offers a
  `SQLiteSubstrate` at registration, which boot opens while selecting the store
  (after `plugin.substrate-sqlite.db_path` has resolved), and does nothing else.

See [`examples/persistent_counter/`](examples/persistent_counter/) for the
read-modify-write loop in full.

## Development

```bash
uv run pytest plugins/substrates/functualize-substrate-sqlite/tests/ -v
uv build --package functualize-substrate-sqlite
```
