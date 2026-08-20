"""Property-based tests for Task mutation event emission.

Tests Property 27 from the Phase 2–5 Domain SDKs design document.

Property 27: Task mutation event emission — For any task creation, the
capability SHALL emit `tasks.task.created` with `{task_id, title, linked_to}`.
For any status update, it SHALL emit `tasks.task.updated` with
`{task_id, old_status, new_status}`. When status becomes DONE, it SHALL
additionally emit `tasks.task.completed` with `{task_id}`. For any deletion,
it SHALL emit `tasks.task.deleted` with `{task_id}`.

**Validates: Requirements 15.1, 15.2, 15.3, 15.4**
"""

from __future__ import annotations

from typing import Any

from functualize_tasks import TaskLink, Tasks, TaskStatus
from functualize_tasks._events import (
    TASKS_COMPLETED,
    TASKS_CREATED,
    TASKS_DELETED,
    TASKS_UPDATED,
)
from hypothesis import assume, given
from hypothesis import strategies as st

# --- Helpers ---


class RecordingEventBus:
    """Records all emitted events for property assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_name: str, **payload: Any) -> None:
        self.events.append((event_name, payload))

    def clear(self) -> None:
        self.events.clear()


# --- Strategies ---

task_titles = st.text(min_size=1, max_size=100)

link_kinds = st.sampled_from(["job", "workflow_step", "job_phase"])

task_links = st.builds(
    TaskLink,
    kind=link_kinds,
    target=st.text(min_size=1, max_size=50),
)

optional_task_links = st.one_of(st.none(), task_links)

# All statuses except PENDING (since tasks start as PENDING, updating to PENDING
# is a no-op for the event system)
non_pending_statuses = st.sampled_from(
    [TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.SKIPPED, TaskStatus.BLOCKED]
)

# All valid task statuses
all_statuses = st.sampled_from(list(TaskStatus))


# --- Property 27a: Task creation emits tasks.task.created ---


class TestTaskCreatedEventEmission:
    """Property 27a: For any task creation, the capability SHALL emit
    `tasks.task.created` with `{task_id, title, linked_to}`.

    **Validates: Requirements 15.1**
    """

    @given(title=task_titles, linked_to=optional_task_links)
    def test_add_emits_created_event_with_correct_payload(
        self, title: str, linked_to: TaskLink | None
    ) -> None:
        """Tasks.add() emits tasks.task.created with task_id, title, and linked_to.

        **Validates: Requirements 15.1**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)

        task_id = tasks.add(title, linked_to=linked_to)

        # Exactly one event emitted
        assert len(bus.events) == 1
        event_name, payload = bus.events[0]

        # Event name is correct
        assert event_name == TASKS_CREATED

        # Payload contains required fields
        assert payload["task_id"] == task_id
        assert payload["title"] == title
        assert payload["linked_to"] == linked_to

    @given(titles=st.lists(task_titles, min_size=2, max_size=10))
    def test_each_add_emits_exactly_one_created_event(self, titles: list[str]) -> None:
        """Each Tasks.add() call emits exactly one created event.

        **Validates: Requirements 15.1**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)

        for title in titles:
            tasks.add(title)

        # One event per add call
        assert len(bus.events) == len(titles)
        # All events are TASKS_CREATED
        assert all(name == TASKS_CREATED for name, _ in bus.events)


# --- Property 27b: Task status update emits tasks.task.updated ---


class TestTaskUpdatedEventEmission:
    """Property 27b: For any status update, the capability SHALL emit
    `tasks.task.updated` with `{task_id, old_status, new_status}`.

    **Validates: Requirements 15.2**
    """

    @given(title=task_titles, new_status=non_pending_statuses)
    def test_update_emits_updated_event_with_status_change(
        self, title: str, new_status: TaskStatus
    ) -> None:
        """Tasks.update() with a status change emits tasks.task.updated.

        **Validates: Requirements 15.2**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        tasks.update(task_id, status=new_status)

        # Find the updated event
        updated_events = [(n, p) for n, p in bus.events if n == TASKS_UPDATED]
        assert len(updated_events) == 1

        _, payload = updated_events[0]
        assert payload["task_id"] == task_id
        assert payload["old_status"] == TaskStatus.PENDING.value
        assert payload["new_status"] == new_status.value

    @given(
        title=task_titles,
        first_status=st.sampled_from([TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED]),
        second_status=st.sampled_from([TaskStatus.SKIPPED, TaskStatus.DONE]),
    )
    def test_sequential_updates_emit_correct_old_and_new_status(
        self, title: str, first_status: TaskStatus, second_status: TaskStatus
    ) -> None:
        """Sequential status updates track old_status correctly.

        **Validates: Requirements 15.2**
        """
        assume(first_status != second_status)

        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        # First update: PENDING -> first_status
        tasks.update(task_id, status=first_status)
        # Second update: first_status -> second_status
        tasks.update(task_id, status=second_status)

        # Filter only updated events
        updated_events = [(n, p) for n, p in bus.events if n == TASKS_UPDATED]
        assert len(updated_events) == 2

        # First updated event: PENDING -> first_status
        _, first_payload = updated_events[0]
        assert first_payload["old_status"] == TaskStatus.PENDING.value
        assert first_payload["new_status"] == first_status.value

        # Second updated event: first_status -> second_status
        _, second_payload = updated_events[1]
        assert second_payload["old_status"] == first_status.value
        assert second_payload["new_status"] == second_status.value

    @given(title=task_titles)
    def test_update_same_status_does_not_emit_event(self, title: str) -> None:
        """Updating a task to its current status does NOT emit an event.

        **Validates: Requirements 15.2**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        # Update to same status (PENDING -> PENDING)
        tasks.update(task_id, status=TaskStatus.PENDING)

        # No events emitted since status didn't change
        assert len(bus.events) == 0


# --- Property 27c: Status transition to DONE also emits tasks.task.completed ---


class TestTaskCompletedEventEmission:
    """Property 27c: When status becomes DONE, the capability SHALL
    additionally emit `tasks.task.completed` with `{task_id}`.

    **Validates: Requirements 15.3**
    """

    @given(title=task_titles)
    def test_update_to_done_emits_completed_event(self, title: str) -> None:
        """Tasks.update(status=DONE) emits both updated and completed events.

        **Validates: Requirements 15.3**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        tasks.update(task_id, status=TaskStatus.DONE)

        # Should have two events: updated + completed
        event_names = [name for name, _ in bus.events]
        assert TASKS_UPDATED in event_names
        assert TASKS_COMPLETED in event_names

        # Completed event payload has task_id
        completed_events = [(n, p) for n, p in bus.events if n == TASKS_COMPLETED]
        assert len(completed_events) == 1
        _, payload = completed_events[0]
        assert payload["task_id"] == task_id

    @given(
        title=task_titles,
        intermediate_status=st.sampled_from(
            [TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.SKIPPED]
        ),
    )
    def test_update_to_non_done_does_not_emit_completed(
        self, title: str, intermediate_status: TaskStatus
    ) -> None:
        """Updating to a non-DONE status does NOT emit completed event.

        **Validates: Requirements 15.3**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        tasks.update(task_id, status=intermediate_status)

        # Should NOT have a completed event
        completed_events = [n for n, _ in bus.events if n == TASKS_COMPLETED]
        assert len(completed_events) == 0

    @given(title=task_titles)
    def test_completed_event_emitted_after_updated_event(self, title: str) -> None:
        """The completed event is emitted after the updated event (ordering).

        **Validates: Requirements 15.3**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        tasks.update(task_id, status=TaskStatus.DONE)

        # Find indices of updated and completed events
        updated_idx = next(
            i for i, (n, _) in enumerate(bus.events) if n == TASKS_UPDATED
        )
        completed_idx = next(
            i for i, (n, _) in enumerate(bus.events) if n == TASKS_COMPLETED
        )

        # Completed comes after updated
        assert completed_idx > updated_idx


# --- Property 27d: Task deletion emits tasks.task.deleted ---


class TestTaskDeletedEventEmission:
    """Property 27d: For any deletion, the capability SHALL emit
    `tasks.task.deleted` with `{task_id}`.

    **Validates: Requirements 15.4**
    """

    @given(title=task_titles)
    def test_delete_emits_deleted_event(self, title: str) -> None:
        """Tasks.delete() emits tasks.task.deleted with the task_id.

        **Validates: Requirements 15.4**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_id = tasks.add(title)
        bus.clear()

        tasks.delete(task_id)

        # Exactly one event emitted
        assert len(bus.events) == 1
        event_name, payload = bus.events[0]

        assert event_name == TASKS_DELETED
        assert payload["task_id"] == task_id

    @given(titles=st.lists(task_titles, min_size=2, max_size=5))
    def test_deleting_multiple_tasks_emits_one_event_each(
        self, titles: list[str]
    ) -> None:
        """Each delete() call emits exactly one deleted event.

        **Validates: Requirements 15.4**
        """
        bus = RecordingEventBus()
        tasks = Tasks(_event_bus=bus)
        task_ids = [tasks.add(title) for title in titles]
        bus.clear()

        for task_id in task_ids:
            tasks.delete(task_id)

        # One event per delete
        assert len(bus.events) == len(task_ids)
        # All are TASKS_DELETED
        assert all(name == TASKS_DELETED for name, _ in bus.events)
        # Each has the correct task_id
        emitted_ids = {p["task_id"] for _, p in bus.events}
        assert emitted_ids == set(task_ids)
