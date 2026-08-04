# functualize-tasks-local Examples

The local task provider: stores tasks in any `StateBackend`, so task lists persist wherever your state does.

| Directory | Demonstrates |
|-----------|--------------|
| [`todo_local/`](todo_local/) | `LocalTaskProvider` wired to a state backend, driven through the `Tasks` capability |

```bash
uv run pytest plugins/functualize-tasks-local/examples/ -v
```
