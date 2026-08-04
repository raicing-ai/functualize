"""Local TaskProvider implementation backed by StateBackend.

Stores tasks as JSON in the active StateBackend using keys prefixed with
``tasks:``. Each task is stored under ``tasks:{task_id}`` as a JSON-encoded
dict containing all TaskItem fields.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING

from functualize_tasks import TaskItem, TaskLink, TaskNotFoundError, TaskStatus

if TYPE_CHECKING:
    from functualize_state import StateBackend


class LocalTaskProvider:
    """TaskProvider implementation using StateBackend with ``tasks:`` prefix.

    Each task is stored as a JSON blob under the key ``tasks:{task_id}``.
    Listing operations scan all keys with the ``tasks:`` prefix and
    deserialize them for filtering.
    """

    PREFIX = "tasks:"

    def __init__(self, backend: StateBackend) -> None:
        self._backend = backend

    def _task_key(self, task_id: str) -> str:
        """Return the full state key for a task ID."""
        return f"{self.PREFIX}{task_id}"

    def _serialize_task(self, task: TaskItem) -> str:
        """Serialize a TaskItem to JSON string."""
        data: dict = {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "linked_to": None,
            "notes": task.notes,
            "creator": task.creator,
            "created_at": task.created_at,
        }
        if task.linked_to is not None:
            data["linked_to"] = {
                "kind": task.linked_to.kind,
                "target": task.linked_to.target,
            }
        return json.dumps(data)

    def _deserialize_task(self, raw: str) -> TaskItem:
        """Deserialize a JSON string to a TaskItem."""
        data = json.loads(raw)
        linked_to = None
        if data.get("linked_to") is not None:
            linked_to = TaskLink(
                kind=data["linked_to"]["kind"],
                target=data["linked_to"]["target"],
            )
        return TaskItem(
            id=data["id"],
            title=data["title"],
            status=TaskStatus(data["status"]),
            linked_to=linked_to,
            notes=data.get("notes"),
            creator=data.get("creator"),
            created_at=data.get("created_at"),
        )

    def _get_task(self, task_id: str) -> TaskItem:
        """Retrieve a task by ID, raising TaskNotFoundError if it doesn't exist."""
        raw = self._backend.get(self._task_key(task_id))
        if raw is None:
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        return self._deserialize_task(raw)

    def add(self, title: str, linked_to: TaskLink | None = None) -> str:
        """Create a new task and return its generated unique ID."""
        task_id = uuid.uuid4().hex[:12]
        task = TaskItem(
            id=task_id,
            title=title,
            status=TaskStatus.PENDING,
            linked_to=linked_to,
            notes=None,
            creator=None,
            created_at=time.time(),
        )
        self._backend.set(self._task_key(task_id), self._serialize_task(task))
        return task_id

    def list(
        self, status: TaskStatus | None = None, filter: str | None = None
    ) -> list[TaskItem]:
        """List tasks, optionally filtered by status or title substring."""
        keys = self._backend.keys(self.PREFIX)
        tasks: list[TaskItem] = []
        for key in keys:
            raw = self._backend.get(key)
            if raw is None:
                continue
            task = self._deserialize_task(raw)
            if status is not None and task.status != status:
                continue
            if filter is not None and filter not in task.title:
                continue
            tasks.append(task)
        return tasks

    def update(
        self, task_id: str, status: TaskStatus | None = None, notes: str | None = None
    ) -> None:
        """Update a task's status and/or notes.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        task = self._get_task(task_id)
        # Build updated task (TaskItem is frozen, so we reconstruct)
        updated = TaskItem(
            id=task.id,
            title=task.title,
            status=status if status is not None else task.status,
            linked_to=task.linked_to,
            notes=notes if notes is not None else task.notes,
            creator=task.creator,
            created_at=task.created_at,
        )
        self._backend.set(self._task_key(task_id), self._serialize_task(updated))

    def delete(self, task_id: str) -> None:
        """Delete a task by its ID.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        # Verify existence first
        self._get_task(task_id)
        self._backend.delete(self._task_key(task_id))

    def link(self, task_id: str, linked_to: TaskLink) -> None:
        """Associate a task with a job, workflow step, or job phase.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """
        task = self._get_task(task_id)
        updated = TaskItem(
            id=task.id,
            title=task.title,
            status=task.status,
            linked_to=linked_to,
            notes=task.notes,
            creator=task.creator,
            created_at=task.created_at,
        )
        self._backend.set(self._task_key(task_id), self._serialize_task(updated))
