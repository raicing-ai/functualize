"""Track work items through the Tasks capability.

Uses MockTasks (a real in-memory provider that also records operations)
so the example is self-contained; in a real app the framework injects a
`Tasks` capability backed by the installed provider.
"""

from functualize_tasks import TaskStatus
from functualize_tasks.testing import MockTasks

from functualize.job import RunContext


def plan_release(rc: RunContext) -> list[str]:
    """Create a small release checklist and complete the first item."""
    tasks = MockTasks()

    build_id = tasks.add("Build artifacts")
    tasks.add("Run smoke tests")
    tasks.add("Tag release")

    tasks.update(build_id, status=TaskStatus.DONE)
    rc.log("Build artifacts: done")

    remaining = [t.title for t in tasks.list() if t.status is not TaskStatus.DONE]
    rc.log(f"Remaining: {', '.join(remaining)}")
    return remaining
