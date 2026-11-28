# functualize-tasks-local Examples

The local task provider: tasks live in the app's own substrate, so a task list persists wherever the project's state does.

| Directory | Demonstrates |
|-----------|--------------|
| [`todo_local/`](todo_local/) | `LocalTaskProvider` over `FunctualizeApp(...).substrate`: a to-do list driven one process per command, persisting between them. The plugin README's Quick Start prints this file. |

```bash
uv run pytest plugins/domains/functualize-tasks-local/examples/ -v
```
