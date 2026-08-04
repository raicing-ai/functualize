# functualize-tasks

> **Status: Published** — Independently installable from PyPI.

Tasks Domain SDK for the functualize framework. Provides a task management capability
that acts as a mutable planning scratchpad within job execution — create, list, update,
delete, and link tasks with structured event emission on every mutation. Storage is
delegated to pluggable `TaskProvider` implementations, making the capability
backend-agnostic.

## Installation

```bash
pip install functualize-tasks
```

## Quick Start

```python
from functualize_tasks import Tasks, TaskStatus, TaskLink

tasks = Tasks()

# Create tasks
task_id = tasks.add("Run database migration")
tasks.add("Deploy service", linked_to=TaskLink(kind="job", target="deploy"))

# Update status
tasks.update(task_id, status=TaskStatus.IN_PROGRESS)
tasks.update(task_id, status=TaskStatus.DONE, notes="Migration complete")

# List and filter
pending = tasks.list(status=TaskStatus.PENDING)
all_tasks = tasks.list(filter="service")
```

## Features

- **CRUD task management** — add, list, update, delete, and link tasks with a clean method-call API
- **Event-driven mutations** — every state change emits structured events (`tasks.task.created`, `tasks.task.updated`, `tasks.task.completed`, `tasks.task.deleted`) via a duck-typed EventBus
- **Pluggable storage** — implement the `TaskProvider` protocol to back tasks with any persistence layer (in-memory, SQLite, remote service)
- **Rich data model** — `TaskItem` with status enum (`PENDING`, `IN_PROGRESS`, `DONE`, `SKIPPED`, `BLOCKED`), optional `TaskLink` to associate tasks with jobs or workflow steps
- **Testing double included** — `MockTasks` captures all operations for assertion while executing against a real in-memory provider
- **Type-safe** — fully typed with PEP 561 `py.typed` marker for mypy/pyright support

## API Reference

Public classes, types, and constants exported by this plugin:

### Capability

- `Tasks` — Main capability class providing `add()`, `list()`, `update()`, `delete()`, and `link()` methods

### Protocols

- `TaskProvider` — Runtime-checkable protocol that storage backends must implement

### Types

- `TaskItem` — Frozen dataclass representing a task (id, title, status, linked_to, notes, creator, created_at)
- `TaskLink` — Frozen dataclass specifying a link kind and target
- `TaskStatus` — String enum with values: `PENDING`, `IN_PROGRESS`, `DONE`, `SKIPPED`, `BLOCKED`

### Errors

- `TaskNotFound` — Raised when an operation targets a non-existent task ID

### Event Constants

- `TASKS_CREATED` — `"tasks.task.created"`
- `TASKS_UPDATED` — `"tasks.task.updated"`
- `TASKS_COMPLETED` — `"tasks.task.completed"`
- `TASKS_DELETED` — `"tasks.task.deleted"`

### Testing

- `MockTasks` — Operation-capturing testing double with `operations`, `adds`, `updates`, `deletes`, `links` properties
- `MockTaskOperation` — Frozen dataclass recording a single captured method call (method, args, kwargs, result)

### Metadata

- `domain_metadata` — `DomainMetadata` instance describing the tasks domain SDK

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-tasks/tests/ -v
```
