"""Tasks domain protocol — TaskProvider.

Defines the protocol interface that task implementation plugins must satisfy.
The Tasks capability delegates all storage and retrieval operations to a
TaskProvider implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize_tasks._types import TaskItem, TaskLink, TaskStatus


@runtime_checkable
class TaskProvider(Protocol):
    """Protocol for task storage implementation plugins.

    Implementation plugins (e.g., local state-backed, remote service) must
    satisfy this protocol. The Tasks capability delegates all CRUD operations
    to the active TaskProvider.
    """

    def add(self, title: str, linked_to: TaskLink | None = None) -> str:
        """Create a new task and return its generated unique ID.

        Args:
            title: Human-readable title for the task.
            linked_to: Optional link associating the task with a job,
                       workflow step, or job phase.

        Returns:
            The unique identifier of the newly created task.
        """
        ...

    def list(
        self, status: TaskStatus | None = None, filter: str | None = None
    ) -> list[TaskItem]:
        """List tasks, optionally filtered by status or title substring.

        Args:
            status: If provided, return only tasks matching this status.
            filter: If provided, return only tasks whose title contains
                    this substring.

        Returns:
            A list of matching TaskItem instances.
        """
        ...

    def update(
        self, task_id: str, status: TaskStatus | None = None, notes: str | None = None
    ) -> None:
        """Update a task's status and/or notes.

        Args:
            task_id: The unique identifier of the task to update.
            status: If provided, the new status to set.
            notes: If provided, the new notes to set.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        ...

    def delete(self, task_id: str) -> None:
        """Delete a task by its ID.

        Args:
            task_id: The unique identifier of the task to delete.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        ...

    def link(self, task_id: str, linked_to: TaskLink) -> None:
        """Associate a task with a job, workflow step, or job phase.

        Args:
            task_id: The unique identifier of the task to link.
            linked_to: The link specifying the kind and target.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        ...
