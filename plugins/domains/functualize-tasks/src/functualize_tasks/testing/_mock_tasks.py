"""MockTasks — operation-capturing testing double.

Provides a Tasks implementation for testing that captures all operations
(add, list, update, delete, link) for assertion. Backed by an in-memory
TaskProvider so operations actually execute, and all calls are recorded
in a queryable log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from functualize_tasks._tasks import Tasks, _InMemoryTaskProvider

if TYPE_CHECKING:
    from functualize_tasks._types import TaskItem, TaskLink, TaskStatus


@dataclass(frozen=True)
class MockTaskOperation:
    """A recorded operation on the MockTasks instance.

    Attributes:
        method: The method name that was called (e.g., "add", "list").
        args: Positional arguments as a tuple.
        kwargs: Keyword arguments as a dict.
        result: The return value of the operation (None for void methods).
    """

    method: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    result: Any = None


class MockTasks(Tasks):
    """Testing double for Tasks that captures all operations for assertion.

    Extends the Tasks capability with a real in-memory provider so that
    operations actually execute (add creates tasks, list returns them, etc.),
    while also recording every call in an operations log that tests can
    query and assert against.

    Example:
        >>> tasks = MockTasks()
        >>> task_id = tasks.add("Write tests")
        >>> tasks.update(task_id, status=TaskStatus.IN_PROGRESS)
        >>> assert len(tasks.operations) == 2
        >>> assert tasks.operations[0].method == "add"
        >>> assert tasks.operations[1].method == "update"
        >>> assert tasks.adds == [tasks.operations[0]]

    Args:
        None — uses an internal in-memory provider automatically.
    """

    def __init__(self) -> None:
        provider = _InMemoryTaskProvider()
        super().__init__(_provider=provider)
        self._operations: list[MockTaskOperation] = []

    @property
    def operations(self) -> list[MockTaskOperation]:
        """All recorded operations in call order."""
        return list(self._operations)

    @property
    def adds(self) -> list[MockTaskOperation]:
        """All recorded 'add' operations."""
        return [op for op in self._operations if op.method == "add"]

    @property
    def lists(self) -> list[MockTaskOperation]:
        """All recorded 'list' operations."""
        return [op for op in self._operations if op.method == "list"]

    @property
    def updates(self) -> list[MockTaskOperation]:
        """All recorded 'update' operations."""
        return [op for op in self._operations if op.method == "update"]

    @property
    def deletes(self) -> list[MockTaskOperation]:
        """All recorded 'delete' operations."""
        return [op for op in self._operations if op.method == "delete"]

    @property
    def links(self) -> list[MockTaskOperation]:
        """All recorded 'link' operations."""
        return [op for op in self._operations if op.method == "link"]

    def reset(self) -> None:
        """Clear all recorded operations."""
        self._operations.clear()

    def add(self, title: str, *, linked_to: TaskLink | None = None) -> str:
        """Create a task and record the operation."""
        result = super().add(title, linked_to=linked_to)
        self._operations.append(
            MockTaskOperation(
                method="add",
                args=(title,),
                kwargs={"linked_to": linked_to},
                result=result,
            )
        )
        return result

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        filter: str | None = None,
    ) -> list[TaskItem]:
        """List tasks and record the operation."""
        result = super().list(status=status, filter=filter)
        self._operations.append(
            MockTaskOperation(
                method="list",
                args=(),
                kwargs={"status": status, "filter": filter},
                result=result,
            )
        )
        return result

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        notes: str | None = None,
    ) -> None:
        """Update a task and record the operation."""
        super().update(task_id, status=status, notes=notes)
        self._operations.append(
            MockTaskOperation(
                method="update",
                args=(task_id,),
                kwargs={"status": status, "notes": notes},
                result=None,
            )
        )

    def delete(self, task_id: str) -> None:
        """Delete a task and record the operation."""
        super().delete(task_id)
        self._operations.append(
            MockTaskOperation(
                method="delete",
                args=(task_id,),
                kwargs={},
                result=None,
            )
        )

    def link(self, task_id: str, linked_to: TaskLink) -> None:
        """Link a task and record the operation."""
        super().link(task_id, linked_to=linked_to)
        self._operations.append(
            MockTaskOperation(
                method="link",
                args=(task_id,),
                kwargs={"linked_to": linked_to},
                result=None,
            )
        )
