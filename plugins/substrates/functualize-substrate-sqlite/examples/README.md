# functualize-substrate-sqlite Examples

Durable SQLite-backed state (WAL mode, stdlib-only).

| Directory | Demonstrates |
|-----------|--------------|
| [`persistent_counter/`](persistent_counter/) | `SQLiteSubstrate` read-modify-write: a count survives across processes, and a stale write is refused rather than applied |

```bash
uv run pytest plugins/substrates/functualize-substrate-sqlite/examples/ -v
```
