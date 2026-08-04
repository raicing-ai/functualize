"""Unit tests for the Tasks capability class.

Tests cover add, list, update, delete, link operations,
TaskNotFoundError raising, and event emission.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from functualize_tasks import (
    TaskItem,
    TaskLink,
    TaskNotFoundError,
    Tasks,
    TaskStatus,
)
from functualize_tasks._events import (
    TASKS_COMPLETED,
    TASKS_CREATED,
    TASKS_DELETED,
    TASKS_UPDATED,
)

# --- Helpers ---


class FakeEventBus:
    """Records all emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_name: str, **payload: Any) -> None:
        self.events[len(self.events) :] = [(event_name, payload)]


# --- Tests: add() ---


class TestTasksAdd:
    def test_add_returns_unique_id(self) -> None:
        tasks = Tasks()
        id1 = tasks.add("Task 1")
        id2 = tasks.add("Task 2")
        assert id1 != id2
        assert isinstance(id1, str)
        assert len(id1) > 0

    def test_add_with_linked_to(self) -> None:
        tasks = Tasks()
        link = TaskLink(kind="job", target="my_job")
        task_id = tasks.add("Linked task", linked_to=link)
        result = tasks.list()
        task = next(t for t in result if t.id == task_id)
        assert task.linked_to == link

    def test_add_emits_created_event(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        link = TaskLink(kind="workflow_step", target="step_1")
        task_id = tasks.add("My task", linked_to=link)

        assert len(bus.events) == 1
        event_name, payload = bus.events[0]
        assert event_name == TASKS_CREATED
        assert payload["task_id"] == task_id
        assert payload["title"] == "My task"
        assert payload["linked_to"] == link

    def test_add_emits_created_event_without_link(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("Simple task")

        assert len(bus.events) == 1
        _, payload = bus.events[0]
        assert payload["task_id"] == task_id
        assert payload["linked_to"] is None


# --- Tests: list() ---


class TestTasksList:
    def test_list_returns_all_tasks(self) -> None:
        tasks = Tasks()
        tasks.add("Task A")
        tasks.add("Task B")
        tasks.add("Task C")
        result = tasks.list()
        assert len(result) == 3

    def test_list_filter_by_status(self) -> None:
        tasks = Tasks()
        id1 = tasks.add("Pending task")
        id2 = tasks.add("Another task")
        tasks.update(id2, status=TaskStatus.DONE)

        pending = tasks.list(status=TaskStatus.PENDING)
        done = tasks.list(status=TaskStatus.DONE)
        assert len(pending) == 1
        assert pending[0].id == id1
        assert len(done) == 1
        assert done[0].id == id2

    def test_list_filter_by_title_substring(self) -> None:
        tasks = Tasks()
        tasks.add("Build feature")
        tasks.add("Write tests")
        tasks.add("Build tests")

        result = tasks.list(filter="Build")
        assert len(result) == 2
        assert all("Build" in t.title for t in result)

    def test_list_empty(self) -> None:
        tasks = Tasks()
        result = tasks.list()
        assert result == []


# --- Tests: update() ---


class TestTasksUpdate:
    def test_update_status(self) -> None:
        tasks = Tasks()
        task_id = tasks.add("My task")
        tasks.update(task_id, status=TaskStatus.IN_PROGRESS)

        result = tasks.list()
        task = next(t for t in result if t.id == task_id)
        assert task.status == TaskStatus.IN_PROGRESS

    def test_update_notes(self) -> None:
        tasks = Tasks()
        task_id = tasks.add("My task")
        tasks.update(task_id, notes="Some notes")

        result = tasks.list()
        task = next(t for t in result if t.id == task_id)
        assert task.notes == "Some notes"

    def test_update_nonexistent_raises_task_not_found(self) -> None:
        tasks = Tasks()
        with pytest.raises(TaskNotFoundError):
            tasks.update("nonexistent-id", status=TaskStatus.DONE)

    def test_update_emits_updated_event(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("My task")
        bus.events.clear()

        tasks.update(task_id, status=TaskStatus.IN_PROGRESS)

        assert len(bus.events) == 1
        event_name, payload = bus.events[0]
        assert event_name == TASKS_UPDATED
        assert payload["task_id"] == task_id
        assert payload["old_status"] == "pending"
        assert payload["new_status"] == "in_progress"

    def test_update_to_done_emits_completed_event(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("My task")
        bus.events.clear()

        tasks.update(task_id, status=TaskStatus.DONE)

        assert len(bus.events) == 2
        assert bus.events[0][0] == TASKS_UPDATED
        assert bus.events[1][0] == TASKS_COMPLETED
        assert bus.events[1][1]["task_id"] == task_id

    def test_update_same_status_no_event(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("My task")
        bus.events.clear()

        # Update with same status — no change, no event
        tasks.update(task_id, status=TaskStatus.PENDING)

        assert len(bus.events) == 0

    def test_update_notes_only_no_status_event(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("My task")
        bus.events.clear()

        tasks.update(task_id, notes="Just notes")

        # No status change, so no updated/completed events
        assert len(bus.events) == 0


# --- Tests: delete() ---


class TestTasksDelete:
    def test_delete_removes_task(self) -> None:
        tasks = Tasks()
        task_id = tasks.add("To delete")
        tasks.delete(task_id)
        result = tasks.list()
        assert len(result) == 0

    def test_delete_nonexistent_raises_task_not_found(self) -> None:
        tasks = Tasks()
        with pytest.raises(TaskNotFoundError):
            tasks.delete("nonexistent-id")

    def test_delete_emits_deleted_event(self) -> None:
        bus = FakeEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("My task")
        bus.events.clear()

        tasks.delete(task_id)

        assert len(bus.events) == 1
        event_name, payload = bus.events[0]
        assert event_name == TASKS_DELETED
        assert payload["task_id"] == task_id


# --- Tests: link() ---


class TestTasksLink:
    def test_link_associates_task(self) -> None:
        tasks = Tasks()
        task_id = tasks.add("Unlinked task")
        link = TaskLink(kind="job_phase", target="phase_1")
        tasks.link(task_id, link)

        result = tasks.list()
        task = next(t for t in result if t.id == task_id)
        assert task.linked_to == link

    def test_link_nonexistent_raises_task_not_found(self) -> None:
        tasks = Tasks()
        link = TaskLink(kind="job", target="my_job")
        with pytest.raises(TaskNotFoundError):
            tasks.link("nonexistent-id", link)


# --- Tests: no event bus ---


class TestTasksNoEventBus:
    def test_operations_work_without_event_bus(self) -> None:
        """All mutations work fine when no event bus is configured."""
        tasks = Tasks(_event_bus=None)
        task_id = tasks.add("No bus task")
        tasks.update(task_id, status=TaskStatus.DONE)
        tasks.delete(task_id)
        # No exception means success


# --- Tests: with external provider ---


class TestTasksWithProvider:
    def test_delegates_to_provider(self) -> None:
        provider = MagicMock()
        provider.add.return_value = "custom-id-123"
        provider.list.return_value = [
            TaskItem(id="custom-id-123", title="Test", status=TaskStatus.PENDING)
        ]

        tasks = Tasks(_provider=provider)
        result = tasks.add("Test")

        assert result == "custom-id-123"
        provider.add.assert_called_once_with("Test", None)
