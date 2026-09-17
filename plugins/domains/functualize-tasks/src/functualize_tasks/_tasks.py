"""Tasks capability class — mutable planning scratchpad.

The Tasks class provides methods to add, list, update, delete, and link
tasks. It delegates all storage operations to a TaskProvider and emits
structured events via a duck-typed EventBus on every mutation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Protocol

from functualize_tasks._errors import TaskNotFoundError
from functualize_tasks._events import (
    TASKS_COMPLETED,
    TASKS_CREATED,
    TASKS_DELETED,
    TASKS_UPDATED,
)
from functualize_tasks._types import TaskItem, TaskLink, TaskStatus

if TYPE_CHECKING:
    from functualize_tasks._protocols import TaskProvider


class _EventBus(Protocol):
    """Duck-typed EventBus — only requires an emit method."""

    def emit(self, event_name: str, **payload: Any) -> None: ...


class _InMemoryTaskProvider:
    """Simple in-memory TaskProvider used when no external provider is configured.

    Stores tasks in a dict keyed by task ID. Suitable for ephemeral use
    when no persistent TaskProvider plugin is installed.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskItem] = {}

    def add(self, title: str, linked_to: TaskLink | None = None) -> str:
        task_id = uuid.uuid4().hex
        task = TaskItem(
            id=task_id,
            title=title,
            status=TaskStatus.PENDING,
            linked_to=linked_to,
        )
        self._tasks[task_id] = task
        return task_id

    def list(
        self, status: TaskStatus | None = None, filter: str | None = None
    ) -> list[TaskItem]:
        results = list(self._tasks.values())
        if status is not None:
            results = [t for t in results if t.status == status]
        if filter is not None:
            results = [t for t in results if filter in t.title]
        return results

    def get(self, task_id: str) -> TaskItem | None:
        return self._tasks.get(task_id)

    def update(
        self, task_id: str, status: TaskStatus | None = None, notes: str | None = None
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found.")
        # Build updated task (frozen dataclass — must reconstruct)
        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
        if notes is not None:
            updates["notes"] = notes
        if updates:
            from dataclasses import asdict

            data = asdict(task)
            data.update(updates)
            self._tasks[task_id] = TaskItem(**data)

    def delete(self, task_id: str) -> None:
        if task_id not in self._tasks:
            raise TaskNotFoundError(f"Task '{task_id}' not found.")
        del self._tasks[task_id]

    def link(self, task_id: str, linked_to: TaskLink) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found.")
        from dataclasses import asdict

        data = asdict(task)
        data["linked_to"] = linked_to
        self._tasks[task_id] = TaskItem(**data)


class Tasks:
    """Task management capability — mutable planning scratchpad.

    Provides methods to create, list, update, delete, and link tasks.
    Delegates all storage to a TaskProvider implementation and emits
    structured events on every mutation via a duck-typed EventBus.

    Args:
        _provider: The TaskProvider implementation for persistence.
                   If None, an in-memory provider is used.
        _event_bus: Optional duck-typed EventBus with an emit(event_name, **payload)
                    method. If None, events are silently discarded.
    """

    def __init__(
        self,
        *,
        _provider: TaskProvider | None = None,
        _event_bus: _EventBus | None = None,
    ) -> None:
        self._provider: TaskProvider = (
            _provider if _provider is not None else _InMemoryTaskProvider()
        )  # type: ignore[assignment]
        self._event_bus = _event_bus

    def _emit(self, event_name: str, **payload: Any) -> None:
        """Emit an event if an event bus is available."""
        if self._event_bus is not None:
            self._event_bus.emit(event_name, **payload)

    def add(self, title: str, *, linked_to: TaskLink | None = None) -> str:
        """Create a new task and return its generated unique ID.

        Emits a ``tasks.task.created`` event with payload containing the
        task id, title, and linked_to.

        Args:
            title: Human-readable title for the task.
            linked_to: Optional link associating the task with a job,
                       workflow step, or job phase.

        Returns:
            The unique identifier of the newly created task.
        """
        task_id = self._provider.add(title, linked_to)
        self._emit(
            TASKS_CREATED,
            task_id=task_id,
            title=title,
            linked_to=linked_to,
        )
        return task_id

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        filter: str | None = None,
    ) -> list[TaskItem]:
        """List tasks, optionally filtered by status or title substring.

        Args:
            status: If provided, return only tasks matching this status.
            filter: If provided, return only tasks whose title contains
                    this substring.

        Returns:
            A list of matching TaskItem instances.
        """
        return self._provider.list(status, filter)

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        notes: str | None = None,
    ) -> None:
        """Update a task's status and/or notes.

        Emits ``tasks.task.updated`` when the status changes, and
        ``tasks.task.completed`` when the new status is DONE.

        Args:
            task_id: The unique identifier of the task to update.
            status: If provided, the new status to set.
            notes: If provided, the new notes to set.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        # Retrieve old status before updating (for event payload)
        old_tasks = self._provider.list()
        old_task = next((t for t in old_tasks if t.id == task_id), None)
        if old_task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found.")

        old_status = old_task.status

        self._provider.update(task_id, status, notes)

        # Emit updated event when status changes
        if status is not None and status != old_status:
            self._emit(
                TASKS_UPDATED,
                task_id=task_id,
                old_status=old_status.value,
                new_status=status.value,
            )
            # Emit completed event when transitioning to DONE
            if status == TaskStatus.DONE:
                self._emit(TASKS_COMPLETED, task_id=task_id)

    def delete(self, task_id: str) -> None:
        """Delete a task by its ID.

        Emits a ``tasks.task.deleted`` event with the task id.

        Args:
            task_id: The unique identifier of the task to delete.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        # Verify existence before delegating (requirement: raise immediately)
        old_tasks = self._provider.list()
        old_task = next((t for t in old_tasks if t.id == task_id), None)
        if old_task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found.")

        self._provider.delete(task_id)
        self._emit(TASKS_DELETED, task_id=task_id)

    def link(self, task_id: str, linked_to: TaskLink) -> None:
        """Associate a task with a job, workflow step, or job phase.

        Args:
            task_id: The unique identifier of the task to link.
            linked_to: The link specifying the kind and target.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        # Verify existence before delegating
        old_tasks = self._provider.list()
        old_task = next((t for t in old_tasks if t.id == task_id), None)
        if old_task is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found.")

        self._provider.link(task_id, linked_to)
