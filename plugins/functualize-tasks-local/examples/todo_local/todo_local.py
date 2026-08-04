"""Tasks stored in a state backend via LocalTaskProvider.

Pairs the tasks domain with the state domain: tasks live wherever your
StateBackend does (in-memory here; SQLite in production). In a real app
`LocalTasksPlugin` wires this automatically at boot.
"""

from functualize_state.testing import InMemoryState
from functualize_tasks import Tasks, TaskStatus
from functualize_tasks_local import LocalTaskProvider

from functualize.job import RunContext


def checklist(rc: RunContext) -> int:
    """Create a checklist and report how many items remain open."""
    backend = InMemoryState()
    tasks = Tasks(_provider=LocalTaskProvider(backend))

    first = tasks.add("Write the report")
    tasks.add("Review the report")

    tasks.update(first, status=TaskStatus.DONE)

    open_items = [t for t in tasks.list() if t.status is not TaskStatus.DONE]
    rc.log(f"{len(open_items)} item(s) still open")
    return len(open_items)
