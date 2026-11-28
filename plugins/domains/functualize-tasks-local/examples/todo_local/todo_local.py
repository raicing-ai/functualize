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
