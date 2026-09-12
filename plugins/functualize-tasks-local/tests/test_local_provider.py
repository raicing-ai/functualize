"""Functional tests for LocalTaskProvider.

Tests local store/retrieve tasks, list filtering, and state persistence
via a TaskDocument on a temporary substrate.
"""

from __future__ import annotations

import pytest
from functualize_tasks import TaskLink, TaskNotFoundError, TaskStatus
from functualize_tasks_local import LocalTaskProvider
from functualize_tasks_local._provider import TaskDocument

from functualize._primitives.substrate import JsonFileSubstrate


@pytest.fixture
def backend(tmp_path) -> TaskDocument:
    """A real task store in a throwaway directory.

    `TaskDocument` went with `functualize-state` (`store-substrate`/T6). The
    replacement is the real thing rather than a second double: the provider's
    whole job is to survive a restart, and a double that cannot be restarted
    cannot show that.
    """
    return TaskDocument(JsonFileSubstrate(tmp_path))


@pytest.fixture
def provider(backend: TaskDocument) -> LocalTaskProvider:
    """Provide a LocalTaskProvider backed by TaskDocument."""
    return LocalTaskProvider(backend=backend)


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
