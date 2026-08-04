# functualize-state-sqlite Examples

Durable SQLite-backed state (WAL mode, stdlib-only).

| Directory | Demonstrates |
|-----------|--------------|
| [`persistent_counter/`](persistent_counter/) | `SQLiteStateBackend` as a `StateBackend`: values survive across processes; keys listing by prefix |

```bash
uv run pytest plugins/functualize-state-sqlite/examples/ -v
```
