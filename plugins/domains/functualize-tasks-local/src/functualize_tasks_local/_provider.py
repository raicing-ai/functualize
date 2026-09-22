"""Local TaskProvider, backed by the framework's own storage.

Every task lives in **one** substrate document, `tasks`, as a mapping from task
id to the task's fields. The document is the unit of storage because that is
what a substrate offers: *give me this document, put this document back, and
stop anyone else while I do both*.

**It used to hold a `StateBackend`** from the `functualize-state` plugin — a
backend-agnostic key-value protocol that `store-substrate`/T6 retired, because
such a protocol can only offer the intersection of every backend and is worth
least exactly where having a database is worth most (`contributor/adr/022`).

**Then it held `TaskDocument`, which was the same shape one level down**, and
`plugin-taxonomy`/T7 removed it. It offered `get`/`set`/`delete`/`keys` — the
retired protocol's own vocabulary — over a single document, with one consumer
and no seam. Three defects followed from the pretence, and all three are closed
by deleting it rather than by three fixes:

- **`list()` cost 1 + N substrate reads.** `keys()` read the whole document to
  enumerate ids, then each `get()` read the whole document again. It is now one
  read (AC-6).
- **A read-modify-write could not be made safe.** `set()` held `lock()` and then
  wrote with no `expect=`, so on a backend whose `lock()` is a no-op — which the
  port explicitly permits, and which an object store is — two concurrent writers
  both won and one task was lost. Mutations are now compare-and-swap with a
  bounded retry (AC-5).
- **A task was a JSON string inside a JSON document.** `_serialize_task`
  `json.dumps`ed each task into a *value* the substrate then encoded again, so
  `func builtin data show` rendered escaped JSON instead of task fields (AC-7).
  Tasks are now ordinary nested mappings.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, TypeVar

from functualize_tasks import TaskItem, TaskLink, TaskNotFoundError, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from functualize._types.protocols import Revision, StoreSubstrate

__all__ = ["LocalTaskProvider"]

#: The document every task lives in. One document, not one per task: a
#: substrate is not required to offer a key scan — only `read`, `write` and a
#: lock — so listing has to be a property of a document rather than of the key
#: space.
TASKS_KEY = "tasks"

#: How many times a losing compare-and-swap re-reads and tries again.
#:
#: Bounded rather than unbounded: contention on one document is expected to be
#: low (a person adding a task, an agent updating one), and a caller starved
#: past this many rounds is a symptom worth surfacing rather than a wait worth
#: extending. Eight is arbitrary and is the kind of number that should be
#: changed by measurement, not by argument.
_WRITE_ATTEMPTS = 8

_T = TypeVar("_T")


class LocalTaskProvider:
    """`TaskProvider` over one substrate document.

    Args:
        substrate_source: Called to get the storage in effect, **each time it is
            needed**, rather than being handed a substrate at construction.

            That is the whole of the ordering fix (AC-8). The provider is built
            during `APP_READY`, and reading `app.substrate` there *resolves and
            caches* the engine's substrate — after which a plugin installing a
            database is refused. Which plugin ran first decided a project's
            storage, and plugin order is the loader's topological sort with an
            **alphabetical** tiebreak, so it came down to the spelling of a
            plugin's name.

            Deferring the read removes the coupling instead of ordering it, and
            matches the engine's own design: it resolves lazily for exactly this
            reason.

            A `Callable` and not a Protocol on purpose. `.spec/CONSTITUTION.md`
            forbids implicit callable conventions **for ports**; this is not one
            — one consumer, no discovery, no registry — and the thing it returns
            *is* the port. A one-method interface with one implementation is the
            shape ADR-022 argues against on its own terms.
        key: The document name. A parameter only so a caller holding two
            isolated task lists in one substrate can say so.
    """

    __slots__ = ("_key", "_substrate_source")

    def __init__(
        self,
        substrate_source: Callable[[], StoreSubstrate],
        key: str = TASKS_KEY,
    ) -> None:
        self._substrate_source = substrate_source
        self._key = key

    # ── storage ──────────────────────────────────────────────────────────

    def _read(self) -> tuple[dict[str, Any], Revision | None]:
        """The task map and the revision it was read at.

        The two travel together because compare-and-swap cannot work if they can
        disagree — `Stored` exists to make that impossible, and unpacking it
        here keeps the rest of this class in plain dictionaries.

        ``None`` for the revision means the document has never been written.
        """
        stored = self._substrate_source().read(self._key)
        if stored is None:
            return {}, None
        tasks = stored.data.get("tasks")
        return (dict(tasks) if isinstance(tasks, dict) else {}), stored.revision

    def _mutate(self, change: Callable[[dict[str, Any]], _T]) -> _T:
        """Read, apply ``change``, and write it back — or retry.

        Held under :meth:`StoreSubstrate.lock` *and* written with ``expect=``,
        which is belt and braces on purpose: the lock is real on a filesystem
        and on SQLite, and the compare-and-swap is what survives a backend whose
        lock is a no-op. The port offers both because backends differ, and a
        caller that uses only one is safe only on half of them.

        ``change`` may raise — `TaskNotFoundError` does — and that propagates
        without a write, which is why the existence check lives inside it rather
        than in a separate read before it. Checking first and writing after is
        the race this method exists to remove.

        **One race this cannot close, and it is the port's, not ours.** When the
        document has never been written there is no revision, and
        ``write(..., expect=None)`` is *unconditional* — the port offers no way
        to say "expect this key to be absent". So two processes creating the
        very first task at the same moment can collide on a backend whose
        ``lock()`` does nothing. Every later write is safe, because by then
        there is a revision to compare. Bounded in practice: the document is
        created once, and ``lock()`` is real on both shipped substrates. Pinned
        by `test_the_very_first_write_cannot_be_compare_and_swapped`, and
        recorded as Q2 of `.spec/features/substrate-conformance/research.md` on
        `sdd/substrate-conformance` — it is precisely the question a substrate
        whose lock is a no-op has to answer.
        """
        substrate = self._substrate_source()
        for _ in range(_WRITE_ATTEMPTS):
            with substrate.lock(self._key):
                tasks, revision = self._read()
                result = change(tasks)
                if substrate.write(self._key, {"tasks": tasks}, expect=revision):
                    return result
        raise RuntimeError(
            f"could not write {self._key!r} after {_WRITE_ATTEMPTS} attempts; "
            f"another writer is winning every round"
        )

    # ── the task shape ───────────────────────────────────────────────────

    @staticmethod
    def _to_fields(task: TaskItem) -> dict[str, Any]:
        """A task as a mapping, not as a string.

        `func builtin data show` renders whatever the substrate holds, so a
        task encoded as JSON *inside* the document printed as an escaped blob.
        """
        fields: dict[str, Any] = {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "linked_to": None,
            "notes": task.notes,
            "creator": task.creator,
            "created_at": task.created_at,
        }
        if task.linked_to is not None:
            fields["linked_to"] = {
                "kind": task.linked_to.kind,
                "target": task.linked_to.target,
            }
        return fields

    @staticmethod
    def _from_fields(fields: dict[str, Any]) -> TaskItem:
        link = fields.get("linked_to")
        return TaskItem(
            id=fields["id"],
            title=fields["title"],
            status=TaskStatus(fields["status"]),
            linked_to=(
                TaskLink(kind=link["kind"], target=link["target"])
                if isinstance(link, dict)
                else None
            ),
            notes=fields.get("notes"),
            creator=fields.get("creator"),
            created_at=fields.get("created_at"),
        )

    @staticmethod
    def _require(tasks: dict[str, Any], task_id: str) -> dict[str, Any]:
        fields = tasks.get(task_id)
        if not isinstance(fields, dict):
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        return fields

    # ── TaskProvider ─────────────────────────────────────────────────────

    def add(self, title: str, linked_to: TaskLink | None = None) -> str:
        """Create a new task and return its generated unique ID."""
        task = TaskItem(
            id=uuid.uuid4().hex[:12],
            title=title,
            status=TaskStatus.PENDING,
            linked_to=linked_to,
            notes=None,
            creator=None,
            created_at=time.time(),
        )
        fields = self._to_fields(task)

        def _add(tasks: dict[str, Any]) -> str:
            tasks[task.id] = fields
            return task.id

        return self._mutate(_add)

    def list(
        self, status: TaskStatus | None = None, filter: str | None = None
    ) -> list[TaskItem]:
        """List tasks, optionally filtered by status or title substring.

        **One substrate read, whatever N is** (AC-6). Filtering happens here
        rather than in the substrate because a substrate holds documents and has
        no opinion about what is inside them.
        """
        tasks, _ = self._read()
        found: list[TaskItem] = []
        for fields in tasks.values():
            if not isinstance(fields, dict):
                continue
            task = self._from_fields(fields)
            if status is not None and task.status != status:
                continue
            if filter is not None and filter not in task.title:
                continue
            found.append(task)
        return found

    def update(
        self, task_id: str, status: TaskStatus | None = None, notes: str | None = None
    ) -> None:
        """Update a task's status and/or notes.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """

        def _update(tasks: dict[str, Any]) -> None:
            fields = dict(self._require(tasks, task_id))
            if status is not None:
                fields["status"] = status.value
            if notes is not None:
                fields["notes"] = notes
            tasks[task_id] = fields

        self._mutate(_update)

    def delete(self, task_id: str) -> None:
        """Delete a task by its ID.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """

        def _delete(tasks: dict[str, Any]) -> None:
            self._require(tasks, task_id)
            del tasks[task_id]

        self._mutate(_delete)

    def link(self, task_id: str, linked_to: TaskLink) -> None:
        """Associate a task with a job, workflow step, or job phase.

        Raises:
            TaskNotFoundError: If the task_id does not exist.
        """

        def _link(tasks: dict[str, Any]) -> None:
            fields = dict(self._require(tasks, task_id))
            fields["linked_to"] = {
                "kind": linked_to.kind,
                "target": linked_to.target,
            }
            tasks[task_id] = fields

        self._mutate(_link)
