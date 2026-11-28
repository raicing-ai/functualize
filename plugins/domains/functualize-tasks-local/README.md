# functualize-tasks-local

> **Status: Published** — Independently installable from PyPI.

Local task storage for functualize. Provides a `TaskProvider` that keeps every
task in one `tasks` document in the app's own storage substrate — whichever
substrate the app selected at boot (`app.substrate`) — so tasks persist wherever
the rest of the project's state does. On the default filesystem substrate that
is `.functualize/tasks.json`. No infrastructure of its own.

## Installation

```bash
pip install functualize-tasks-local
```

## Quick Start

A to-do list that survives between processes. Make a project directory — the
`.functualize/` folder is what puts the substrate inside it — and save this as
`todo_local.py` there. It is the plugin's
[`examples/todo_local/todo_local.py`](examples/todo_local/todo_local.py),
unchanged.

```bash
mkdir -p todo-demo/.functualize
cd todo-demo
```

```python
"""A to-do list that outlives the process, kept in the app's own storage.

Every command below is a separate process. The list survives between them
because `LocalTaskProvider` keeps every task in one `tasks` document in the
substrate the app selected at boot (`app.substrate`); on the default filesystem
substrate that is `.functualize/tasks.json`. `LocalTasksPlugin` registers the
same provider over the same substrate, so this list and the plugin's are one.

    python todo_local.py add "Write the report"
    python todo_local.py done "Write"
    python todo_local.py list
"""

from __future__ import annotations

import sys

from functualize_tasks import TaskStatus
from functualize_tasks_local import LocalTaskProvider

from functualize.app import FunctualizeApp


def open_list(app: FunctualizeApp) -> LocalTaskProvider:
    """The task list stored in ``app``'s substrate."""
    return LocalTaskProvider(lambda: app.substrate)


def main(argv: list[str]) -> int:
    """Run one command against the list, then print the whole list."""
    tasks = open_list(FunctualizeApp("todo"))
    command, *rest = argv or ["list"]
    if command == "add" and rest:
        tasks.add(rest[0])
    elif command == "done" and rest:
        for task in tasks.list(status=TaskStatus.PENDING, filter=rest[0]):
            tasks.update(task.id, status=TaskStatus.DONE)
    elif command != "list":
        print(
            "usage: todo_local.py add TITLE | done TITLE-PART | list", file=sys.stderr
        )
        return 2
    for task in tasks.list():
        print(f"[{task.status.value}] {task.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Each command is a new process; the list is read back from the substrate every
time:

```bash
python todo_local.py add "Write the report"
python todo_local.py add "Review the report"
python todo_local.py done "Write"
python todo_local.py list
ls .functualize
```

Every command prints the list after it runs. The last two print the finished
list and the one document it is stored in:

```text
[done] Write the report
[pending] Review the report
tasks.json
tasks.json.lock
```

## Features

- **Stored in the app's substrate** — the provider asks the app for its
  substrate on every use, so tasks land in whatever storage boot selected and
  survive restarts; nothing about the storage is decided by this plugin
- **Automatic plugin registration** — registers via the `functualize.tasks_providers` entry point with name `"local"`; at `APP_READY` it provides a `LocalTaskProvider` over the app's substrate as the `TaskProvider`
- **Full CRUD operations** — create, list, update, delete, and link tasks with filtering by status or title substring
- **Safe concurrent writes** — every mutation is a compare-and-swap under the substrate's lock, retried a bounded number of times
- **Inspectable** — the `tasks` document maps each task id to plain fields (`title`, `status`, `linked_to`, …), not to an encoded string
- **One dependency** — only `functualize-tasks` (and functualize itself)

## API Reference

Public classes exported by this plugin:

- `LocalTaskProvider(substrate_source, key="tasks")` — `TaskProvider` over one substrate document. `substrate_source` is called on every use and returns the substrate to use, e.g. `lambda: app.substrate`. Methods: `add()`, `list()`, `update()`, `delete()`, `link()`
- `LocalTasksPlugin` — Plugin entry point: at `APP_READY` it registers a `LocalTaskProvider` over the app's substrate as the `TaskProvider` implementation

## Development

Run the plugin tests and the example:

```bash
uv run pytest plugins/domains/functualize-tasks-local/tests/ -v
uv run pytest plugins/domains/functualize-tasks-local/examples/ -v
```
