"""Functional tests for functualize-tasks domain SDK.

Tests the Tasks capability class, status transitions, MockTasks
operation recording, and event emission on state changes.
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_tasks import (
    TASKS_COMPLETED,
    TASKS_CREATED,
    TASKS_DELETED,
    TASKS_UPDATED,
    MockTasks,
    TaskLink,
    TaskNotFoundError,
    Tasks,
    TaskStatus,
)


class _CapturingEventBus:
    """Minimal event bus that records all emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_name: str, **payload: Any) -> None:
        self.events.append((event_name, payload))


class TestTaskCreation:
    """Tests for creating tasks via the Tasks capability."""

    def test_add_returns_unique_id(self):
        """Happy path: adding a task returns a non-empty string ID."""
        tasks = Tasks()
        task_id = tasks.add("Write tests")
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    def test_add_creates_task_with_pending_status(self):
        """Happy path: a newly added task has PENDING status."""
        tasks = Tasks()
        task_id = tasks.add("Deploy service")
        items = tasks.list()
        assert len(items) == 1
        assert items[0].id == task_id
        assert items[0].title == "Deploy service"
        assert items[0].status == TaskStatus.PENDING

    def test_add_with_link(self):
        """Happy path: task can be created with a link."""
        tasks = Tasks()
        link = TaskLink(kind="job", target="deploy")
        tasks.add("Run migrations", linked_to=link)
        items = tasks.list()
        assert items[0].linked_to == link


class TestStatusTransitions:
    """Tests for updating task status through transitions."""

    def test_transition_pending_to_in_progress(self):
        """Happy path: task status can transition from PENDING to IN_PROGRESS."""
        tasks = Tasks()
        task_id = tasks.add("Build")
        tasks.update(task_id, status=TaskStatus.IN_PROGRESS)
        items = tasks.list()
        assert items[0].status == TaskStatus.IN_PROGRESS

    def test_transition_to_done(self):
        """Happy path: task status can transition to DONE."""
        tasks = Tasks()
        task_id = tasks.add("Test")
        tasks.update(task_id, status=TaskStatus.DONE)
        items = tasks.list()
        assert items[0].status == TaskStatus.DONE

    def test_update_nonexistent_task_raises_task_not_found(self):
        """Error case: updating a nonexistent task raises TaskNotFoundError."""
        tasks = Tasks()
        with pytest.raises(TaskNotFoundError):
            tasks.update("nonexistent-id", status=TaskStatus.DONE)

    def test_delete_nonexistent_task_raises_task_not_found(self):
        """Error case: deleting a nonexistent task raises TaskNotFoundError."""
        tasks = Tasks()
        with pytest.raises(TaskNotFoundError):
            tasks.delete("nonexistent-id")


class TestMockTasksBehavior:
    """Tests for the MockTasks testing double — operation recording."""

    def test_mock_records_add_operations(self):
        """Happy path: MockTasks records add operations with result."""
        mock = MockTasks()
        task_id = mock.add("First task")
        assert len(mock.operations) == 1
        assert mock.operations[0].method == "add"
        assert mock.operations[0].args == ("First task",)
        assert mock.operations[0].result == task_id

    def test_mock_records_multiple_operation_types(self):
        """Happy path: MockTasks records mixed operations in order."""
        mock = MockTasks()
        task_id = mock.add("Task A")
        mock.list()
        mock.update(task_id, status=TaskStatus.IN_PROGRESS)
        assert len(mock.operations) == 3
        assert mock.adds[0].method == "add"
        assert mock.lists[0].method == "list"
        assert mock.updates[0].method == "update"

    def test_mock_reset_clears_operations(self):
        """Happy path: reset clears all recorded operations."""
        mock = MockTasks()
        mock.add("Task B")
        assert len(mock.operations) == 1
        mock.reset()
        assert len(mock.operations) == 0


class TestEventEmission:
    """Tests for event emission on state changes."""

    def test_add_emits_created_event(self):
        """Happy path: adding a task emits tasks.task.created."""
        bus = _CapturingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("Event test")
        assert len(bus.events) == 1
        event_name, payload = bus.events[0]
        assert event_name == TASKS_CREATED
        assert payload["task_id"] == task_id
        assert payload["title"] == "Event test"

    def test_update_status_emits_updated_event(self):
        """Happy path: changing status emits tasks.task.updated."""
        bus = _CapturingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("Status event")
        bus.events.clear()  # Clear the created event

        tasks.update(task_id, status=TaskStatus.IN_PROGRESS)
        assert len(bus.events) == 1
        event_name, payload = bus.events[0]
        assert event_name == TASKS_UPDATED
        assert payload["task_id"] == task_id
        assert payload["old_status"] == TaskStatus.PENDING.value
        assert payload["new_status"] == TaskStatus.IN_PROGRESS.value

    def test_transition_to_done_emits_completed_event(self):
        """Happy path: transitioning to DONE emits both updated and completed."""
        bus = _CapturingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("Complete me")
        bus.events.clear()

        tasks.update(task_id, status=TaskStatus.DONE)
        event_names = [name for name, _ in bus.events]
        assert TASKS_UPDATED in event_names
        assert TASKS_COMPLETED in event_names

    def test_delete_emits_deleted_event(self):
        """Happy path: deleting a task emits tasks.task.deleted."""
        bus = _CapturingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add("Delete me")
        bus.events.clear()

        tasks.delete(task_id)
        assert len(bus.events) == 1
        event_name, payload = bus.events[0]
        assert event_name == TASKS_DELETED
        assert payload["task_id"] == task_id
