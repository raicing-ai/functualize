"""Local TaskProvider, backed by the framework's own storage.

Stores tasks as JSON under keys prefixed with ``tasks:``, inside one document
the project's :class:`StoreSubstrate` holds. Each task is a JSON-encoded dict
of all ``TaskItem`` fields.

**It used to hold a `StateBackend`** from the `functualize-state` plugin — a
backend-agnostic key-value protocol that `store-substrate`/T6 retired, because
such a protocol can only offer the intersection of every backend and is worth
least exactly where having a database is worth most (`contributor/adr/022`).

The four calls this provider makes — get, set, delete, keys — are now served by
:class:`TaskDocument`, which is that shape over one substrate document. The
gain is not that the code shrank: it is that tasks follow the project's
substrate, so a task written under SQLite is not invisible to a reader on the
filesystem.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING

from functualize_tasks import TaskItem, TaskLink, TaskNotFoundError, TaskStatus

if TYPE_CHECKING:
    from functualize._types.protocols import StoreSubstrate


#: The document every task lives in. One document, not one per task: the
#: provider lists by prefix, and a substrate is not required to offer a key
#: scan — only `read`, `write` and a lock.
TASKS_KEY = "tasks"


class TaskDocument:
    """Four key-value calls over one substrate document.

    Small on purpose. It is not a second storage vocabulary coming back: it has
    no protocol, no plugin seam and one consumer, and it exists because
    `LocalTaskProvider` wants a flat key space while the substrate stores whole
    documents.
    """

    __slots__ = ("_key", "_substrate")

    def __init__(self, substrate: StoreSubstrate, key: str = TASKS_KEY) -> None:
        self._substrate = substrate
        self._key = key

    def _load(self) -> dict[str, str]:
        stored = self._substrate.read(self._key)
        if stored is None:
            return {}
        entries = stored.data.get("tasks")
        return entries if isinstance(entries, dict) else {}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._load().get(key, default)

    def set(self, key: str, value: str) -> None:
        with self._substrate.lock(self._key):
            entries = self._load()
            entries[key] = value
            self._substrate.write(self._key, {"tasks": entries})

    def delete(self, key: str) -> None:
        with self._substrate.lock(self._key):
            entries = self._load()
            if entries.pop(key, None) is not None:
                self._substrate.write(self._key, {"tasks": entries})

    def keys(self, prefix: str = "") -> list[str]:
        """Keys, optionally narrowed to a prefix.

        The prefix is what made this a key-value store rather than a document:
        `LocalTaskProvider` lists by scanning `tasks:`. Filtering happens here
        rather than in the substrate because a substrate is not required to
        offer a key scan — only `read`, `write` and a lock.
        """
        return sorted(k for k in self._load() if k.startswith(prefix))


class LocalTaskProvider:
    """TaskProvider storing tasks under a ``tasks:`` prefix.

    Each task is stored as a JSON blob under the key ``tasks:{task_id}``.
    Listing operations scan all keys with the ``tasks:`` prefix and
    deserialize them for filtering.
    """

    PREFIX = "tasks:"

    def __init__(self, backend: TaskDocument) -> None:
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
