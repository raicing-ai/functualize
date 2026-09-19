"""Functional tests for LocalTaskProvider.

Store and retrieve, list filtering, and the errors, over a real substrate in a
throwaway directory — not a double. The provider's whole job is to survive a
restart, and a double that cannot be restarted cannot show that.

`plugin-taxonomy`/T7 removed `TaskDocument`, the key-value facade these tests
used to build. The provider now takes a **callable** returning the substrate, so
that the substrate is read on use rather than at construction; here that
callable just hands back the one the fixture made.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from functualize_tasks import TaskLink, TaskNotFoundError, TaskStatus
from functualize_tasks_local import LocalTaskProvider

from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.protocols import StoreSubstrate

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from functualize._types.protocols import Stored


@pytest.fixture
def substrate(tmp_path: Path) -> JsonFileSubstrate:
    """Real storage in a throwaway directory."""
    return JsonFileSubstrate(tmp_path)


@pytest.fixture
def provider(substrate: JsonFileSubstrate) -> LocalTaskProvider:
    return LocalTaskProvider(lambda: substrate)


class TestStoreAndRetrieve:
    """Tests for adding and listing tasks."""

    def test_add_task_returns_id_and_persists(
        self, provider: LocalTaskProvider
    ) -> None:
        """Adding a task returns a unique ID and is retrievable via list."""
        task_id = provider.add("Deploy service")

        assert task_id is not None
        assert len(task_id) == 12  # uuid4 hex[:12]

        tasks = provider.list()
        assert len(tasks) == 1
        assert tasks[0].id == task_id
        assert tasks[0].title == "Deploy service"
        assert tasks[0].status == TaskStatus.PENDING

    def test_add_task_with_link(self, provider: LocalTaskProvider) -> None:
        """Adding a task with a TaskLink persists the link correctly."""
        link = TaskLink(kind="job", target="deploy-job")
        provider.add("Linked task", linked_to=link)

        tasks = provider.list()
        assert len(tasks) == 1
        assert tasks[0].linked_to is not None
        assert tasks[0].linked_to.kind == "job"
        assert tasks[0].linked_to.target == "deploy-job"


class TestListFiltering:
    """Tests for filtering tasks by status and title substring."""

    def test_filter_by_status(self, provider: LocalTaskProvider) -> None:
        """Listing with a status filter returns only matching tasks."""
        id1 = provider.add("Task A")
        id2 = provider.add("Task B")
        provider.update(id1, status=TaskStatus.DONE)

        pending = provider.list(status=TaskStatus.PENDING)
        done = provider.list(status=TaskStatus.DONE)

        assert len(pending) == 1
        assert pending[0].id == id2
        assert len(done) == 1
        assert done[0].id == id1

    def test_filter_by_title_substring(self, provider: LocalTaskProvider) -> None:
        """Listing with a filter string returns only tasks whose title contains it."""
        provider.add("Deploy service")
        provider.add("Run migrations")
        provider.add("Deploy database")

        results = provider.list(filter="Deploy")
        assert len(results) == 2
        titles = {t.title for t in results}
        assert titles == {"Deploy service", "Deploy database"}


class TestErrorHandling:
    """Tests for error cases and proper exception raising."""

    def test_update_nonexistent_task_raises(self, provider: LocalTaskProvider) -> None:
        """Updating a task that doesn't exist raises TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            provider.update("nonexistent-id", status=TaskStatus.DONE)

    def test_delete_nonexistent_task_raises(self, provider: LocalTaskProvider) -> None:
        """Deleting a task that doesn't exist raises TaskNotFoundError."""
        with pytest.raises(TaskNotFoundError):
            provider.delete("nonexistent-id")


class _NoLockSubstrate:
    """A real substrate with its mutual exclusion taken away.

    Not a mock: every call goes to a real `JsonFileSubstrate` underneath. Only
    `lock()` differs, and it differs in the way the **port explicitly permits** —
    :meth:`StoreSubstrate.lock` says it "may be a no-op for a backend that
    offers no mutual exclusion, which is why :meth:`write` takes ``expect`` and
    returns a bool".

    That sentence is the contract this double exists to test against. A caller
    that relies on the lock alone is correct on a filesystem and on SQLite and
    silently lossy on an object store — and an object store is what the next
    substrate is going to be. Monkeypatching the real class cannot express this:
    `JsonFileSubstrate` uses `__slots__`, and more to the point the subject is a
    *different kind of backend*, not a damaged one.

    Also counts reads, because "how many times did you ask storage" is the other
    thing these tests need to know and it is the same seam.
    """

    def __init__(self, inner: JsonFileSubstrate) -> None:
        self._inner = inner
        self.reads = 0
        self.on_read: Callable[[str], None] | None = None

    def read(self, key: str) -> Stored | None:
        self.reads += 1
        stored = self._inner.read(key)
        if self.on_read is not None:
            self.on_read(key)
        return stored

    def write(
        self, key: str, payload: dict[str, Any], *, expect: int | None = None
    ) -> bool:
        return self._inner.write(key, payload, expect=expect)

    @contextlib.contextmanager
    def lock(self, *keys: str) -> Iterator[None]:
        yield

    def clear(self, key: str) -> str | None:
        return self._inner.clear(key)

    def delete(self, key: str) -> bool:
        return self._inner.delete(key)

    def describe(self, key: str) -> str:
        return self._inner.describe(key)


def test_the_double_is_really_a_substrate(tmp_path: Path) -> None:
    """Guards the guard: a double that no longer satisfies the port would make
    every test below pass for the wrong reason."""
    assert isinstance(_NoLockSubstrate(JsonFileSubstrate(tmp_path)), StoreSubstrate)


class TestOneDocumentAndOneRead:
    """The shape `plugin-taxonomy`/T7 exists to establish."""

    def test_every_task_lives_in_the_one_tasks_document(
        self, provider: LocalTaskProvider, substrate: JsonFileSubstrate
    ) -> None:
        """AC-6's premise, and the replacement for the old `tasks:` prefix rule.

        The prefix was a convention over a faked key space. One document is a
        fact about storage: nothing else can be written without the substrate
        being asked for another key by name.
        """
        first = provider.add("one")
        second = provider.add("two")

        stored = substrate.read("tasks")
        assert stored is not None
        assert set(stored.data["tasks"]) == {first, second}

    def test_a_task_is_stored_as_fields_not_as_a_string(
        self, provider: LocalTaskProvider, substrate: JsonFileSubstrate
    ) -> None:
        """AC-7. A task used to be `json.dumps`ed into a value inside the
        document the substrate then encoded again, so `func builtin data show`
        rendered an escaped blob where a reader wanted a title."""
        task_id = provider.add("Deploy service")

        stored = substrate.read("tasks")
        assert stored is not None
        fields = stored.data["tasks"][task_id]
        assert isinstance(fields, dict), "a task must be data, not a string"
        assert fields["title"] == "Deploy service"

    def test_listing_costs_one_read_whatever_n_is(self, tmp_path: Path) -> None:
        """AC-6. It was `1 + N`: one read to enumerate the ids, then one more
        per id, each re-reading the whole document."""
        counting = _NoLockSubstrate(JsonFileSubstrate(tmp_path))
        provider = LocalTaskProvider(lambda: counting)
        for i in range(10):
            provider.add(f"task {i}")

        counting.reads = 0
        assert len(provider.list()) == 10
        assert counting.reads == 1, (
            f"list() of 10 tasks took {counting.reads} substrate reads"
        )


class TestConcurrentWritersOnANoOpLock:
    """AC-5. The data-loss bug, on the backend shape that exposes it."""

    def test_the_very_first_write_cannot_be_compare_and_swapped(
        self, tmp_path: Path
    ) -> None:
        """A known limitation of the **port**, pinned so it is not mistaken for
        a bug in this provider — and so it is not silently "fixed" by a change
        that only appears to work.

        `write(key, payload, expect=None)` is *unconditional*; `expect=` takes
        "the revision the caller last read". A document that has never been
        written has no revision, and the port offers no way to say **expect this
        key to be absent**. So the first writer to a fresh document cannot
        detect a second one, and on a backend whose `lock()` is a no-op the two
        can collide.

        Every later write is safe, which is what AC-5 asks for and what the test
        below asserts: `update` operates on a document that exists, so there is
        always a revision to compare.

        The residue is bounded in practice — the document is created once, and
        `lock()` is real on both shipped backends — but it is exactly the
        question a substrate whose lock does nothing has to answer, and it is
        recorded as Q2 of `.spec/features/substrate-conformance/research.md` on
        `sdd/substrate-conformance`.

        **This test asserts the limitation, not a guarantee.** If the port grows
        a way to express "create if absent" it should fail, and that failure is
        the signal to make `add` safe too.
        """
        substrate = _NoLockSubstrate(JsonFileSubstrate(tmp_path))
        a = LocalTaskProvider(lambda: substrate)
        b = LocalTaskProvider(lambda: substrate)

        interfered = False

        def interfere(key: str) -> None:
            nonlocal interfered
            if interfered:
                return
            interfered = True
            substrate.on_read = None
            b.add("from writer B")

        substrate.on_read = interfere
        try:
            a.add("from writer A")
        finally:
            substrate.on_read = None

        assert interfered, "the interleaving never happened; the test proves nothing"
        titles = {task.title for task in a.list()}
        assert titles == {"from writer A"}, (
            "the first-write race is no longer lossy — if the port gained a way "
            "to expect an absent key, `add` should now use it and this test "
            "should be replaced by the guarantee"
        )

    def test_an_interleaved_update_does_not_erase_the_other(
        self, tmp_path: Path
    ) -> None:
        """The interleaving the retry loop is for: B writes between A's read and
        A's write, so A's `expect=` is stale and A must re-read rather than
        overwrite."""
        substrate = _NoLockSubstrate(JsonFileSubstrate(tmp_path))
        provider = LocalTaskProvider(lambda: substrate)
        first = provider.add("A")
        second = provider.add("B")

        interfered = False

        def interfere(key: str) -> None:
            nonlocal interfered
            if interfered:
                return
            interfered = True
            # Another process updates the *other* task in the window between
            # this read and the write that follows it, so the revision the
            # caller is about to pass as `expect=` is already stale.
            substrate.on_read = None
            LocalTaskProvider(lambda: substrate).update(
                second, notes="written by the other process"
            )

        substrate.on_read = interfere
        try:
            provider.update(first, status=TaskStatus.DONE)
        finally:
            substrate.on_read = None

        by_id = {t.id: t for t in provider.list()}
        assert by_id[first].status == TaskStatus.DONE
        assert by_id[second].notes == "written by the other process", (
            "the retry overwrote the other writer instead of re-reading"
        )
