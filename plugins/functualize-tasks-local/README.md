# functualize-tasks-local

> **Status: Published** — Independently installable from PyPI.

Local state-backed task storage plugin for functualize. Provides a `TaskProvider`
implementation that persists tasks as JSON blobs in the active `StateBackend`,
using keys prefixed with `tasks:`. Zero external dependencies beyond the
functualize workspace packages — if you have a state backend registered, this
plugin gives you a fully functional task queue with no additional infrastructure.

## Installation

```bash
pip install functualize-tasks-local
```

## Quick Start

```python
from functualize_state import InMemoryState
from functualize_tasks import TaskStatus
from functualize_tasks_local import LocalTaskProvider

# Create a provider backed by an in-memory state store
backend = InMemoryState()
provider = LocalTaskProvider(backend=backend)

# Add a task and retrieve it
task_id = provider.add("Deploy staging server")
tasks = provider.list(status=TaskStatus.PENDING)
print(tasks[0].title)  # "Deploy staging server"

# Update status and clean up
provider.update(task_id, status=TaskStatus.DONE)
provider.delete(task_id)
```

## Features

- **State-backed persistence** — delegates all storage to the active `StateBackend`, so tasks survive restarts when using a durable backend like SQLite
- **Automatic plugin registration** — registers via the `functualize.tasks_providers` entry point with name `"local"`, no manual wiring required
- **Full CRUD operations** — create, list, update, delete, and link tasks with filtering by status or title substring
- **Zero external dependencies** — only depends on `functualize-tasks` and `functualize-state` from the workspace
- **JSON serialization** — each task stored as a compact JSON blob under `tasks:{task_id}`, easily inspectable for debugging

## API Reference

Public classes exported by this plugin:

- `LocalTaskProvider` — `TaskProvider` implementation that stores tasks in a `StateBackend` with `tasks:` key prefix. Methods: `add()`, `list()`, `update()`, `delete()`, `link()`
- `LocalTasksPlugin` — Plugin entry point that resolves the active `StateBackend` from DI at boot and registers a `LocalTaskProvider` as the `TaskProvider` implementation

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-tasks-local/tests/ -v
```
