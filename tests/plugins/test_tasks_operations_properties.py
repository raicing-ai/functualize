"""Property-based tests for Tasks operations.

Tests Properties 21–25 from the Phase 2–5 Domain SDKs design document.

Property 21: Tasks.add returns unique IDs — For any N calls to Tasks.add(title)
with arbitrary titles, all N returned IDs SHALL be distinct non-empty strings.

Property 22: Tasks.list status filtering — For any set of tasks with mixed
statuses and any target status S, Tasks.list(status=S) SHALL return only tasks
whose status equals S, and SHALL include all such tasks.

Property 23: Tasks.list title substring filtering — For any set of tasks and
any filter string F, Tasks.list(filter=F) SHALL return only tasks whose title
contains F as a substring, and SHALL include all such tasks.

Property 24: Tasks.update persists status change — For any existing task with
id I and any new status S, after Tasks.update(I, status=S), the task's status
SHALL equal S when retrieved.

Property 25: Tasks operations on non-existent IDs raise TaskNotFoundError — For any
task_id that does not exist in the store, Tasks.update(task_id, ...) and
Tasks.delete(task_id) SHALL raise TaskNotFoundError.

**Validates: Requirements 13.2, 13.3, 13.4, 13.5, 13.6**
"""

from __future__ import annotations

import pytest
from functualize_tasks import TaskNotFoundError, Tasks, TaskStatus
from hypothesis import assume, given
from hypothesis import strategies as st

# --- Strategies ---

# Strategy for task titles (non-empty printable strings)
task_titles = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
)

# Strategy for lists of task titles
task_title_lists = st.lists(task_titles, min_size=2, max_size=30)

# Strategy for TaskStatus values
task_statuses = st.sampled_from(list(TaskStatus))

# Strategy for non-existent task IDs (unlikely to collide with uuid4 hex)
non_existent_ids = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(categories=("L", "N")),
).filter(lambda s: len(s) < 32 or not all(c in "0123456789abcdef" for c in s))


# --- Property 21: Tasks.add returns unique IDs ---


class TestTasksAddReturnsUniqueIDs:
    """Property 21: Tasks.add returns unique IDs.

    For any N calls to Tasks.add(title) with arbitrary titles, all N returned
    IDs SHALL be distinct non-empty strings.

    **Validates: Requirements 13.2**
    """

    @given(titles=task_title_lists)
    def test_all_returned_ids_are_distinct(self, titles: list[str]) -> None:
        """All IDs returned by Tasks.add() are distinct non-empty strings.

        **Validates: Requirements 13.2**
        """
        tasks = Tasks()
        ids = [tasks.add(title) for title in titles]

        # All IDs must be non-empty strings
        for task_id in ids:
            assert isinstance(task_id, str)
            assert len(task_id) > 0

        # All IDs must be unique
        assert len(set(ids)) == len(ids), (
            f"Expected {len(ids)} unique IDs, got {len(set(ids))}"
        )

    @given(title=task_titles)
    def test_single_add_returns_non_empty_string(self, title: str) -> None:
        """A single Tasks.add() returns a non-empty string ID.

        **Validates: Requirements 13.2**
        """
        tasks = Tasks()
        task_id = tasks.add(title)
        assert isinstance(task_id, str)
        assert len(task_id) > 0


# --- Property 22: Tasks.list status filtering ---


class TestTasksListStatusFiltering:
    """Property 22: Tasks.list status filtering.

    For any set of tasks with mixed statuses and any target status S,
    Tasks.list(status=S) SHALL return only tasks whose status equals S,
    and SHALL include all such tasks.

    **Validates: Requirements 13.3**
    """

    @given(
        titles=st.lists(task_titles, min_size=1, max_size=20),
        statuses_to_assign=st.lists(task_statuses, min_size=1, max_size=20),
        target_status=task_statuses,
    )
    def test_list_returns_only_matching_status(
        self,
        titles: list[str],
        statuses_to_assign: list[TaskStatus],
        target_status: TaskStatus,
    ) -> None:
        """Tasks.list(status=S) returns only tasks with status == S.

        **Validates: Requirements 13.3**
        """
        tasks = Tasks()

        # Create tasks and assign statuses
        task_ids: list[str] = []
        for i, title in enumerate(titles):
            task_id = tasks.add(title)
            task_ids.append(task_id)
            # Assign status from the statuses list (cycling if needed)
            assigned_status = statuses_to_assign[i % len(statuses_to_assign)]
            if assigned_status != TaskStatus.PENDING:
                tasks.update(task_id, status=assigned_status)

        # Filter by target status
        filtered = tasks.list(status=target_status)

        # All returned tasks must have the target status
        for task in filtered:
            assert task.status == target_status, (
                f"Expected status {target_status}, got {task.status}"
            )

    @given(
        titles=st.lists(task_titles, min_size=1, max_size=20),
        statuses_to_assign=st.lists(task_statuses, min_size=1, max_size=20),
        target_status=task_statuses,
    )
    def test_list_includes_all_matching_tasks(
        self,
        titles: list[str],
        statuses_to_assign: list[TaskStatus],
        target_status: TaskStatus,
    ) -> None:
        """Tasks.list(status=S) includes ALL tasks with status == S.

        **Validates: Requirements 13.3**
        """
        tasks = Tasks()

        # Create tasks and track which ones should match
        expected_ids: set[str] = set()
        for i, title in enumerate(titles):
            task_id = tasks.add(title)
            assigned_status = statuses_to_assign[i % len(statuses_to_assign)]
            if assigned_status != TaskStatus.PENDING:
                tasks.update(task_id, status=assigned_status)

            # Determine the final status
            # New tasks start as PENDING; if we assign PENDING again it stays PENDING
            actual_final = statuses_to_assign[i % len(statuses_to_assign)]
            if (
                actual_final == target_status
                or target_status == TaskStatus.PENDING
                and actual_final == TaskStatus.PENDING
            ):
                expected_ids.add(task_id)

        # All tasks start as PENDING, so we need to recalculate
        # Let's just get the full list and check manually
        all_tasks = tasks.list()
        truly_matching_ids = {t.id for t in all_tasks if t.status == target_status}

        filtered = tasks.list(status=target_status)
        filtered_ids = {t.id for t in filtered}

        assert filtered_ids == truly_matching_ids


# --- Property 23: Tasks.list title substring filtering ---


class TestTasksListTitleSubstringFiltering:
    """Property 23: Tasks.list title substring filtering.

    For any set of tasks and any filter string F, Tasks.list(filter=F) SHALL
    return only tasks whose title contains F as a substring, and SHALL include
    all such tasks.

    **Validates: Requirements 13.4**
    """

    @given(
        titles=st.lists(task_titles, min_size=1, max_size=20),
        filter_str=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
    )
    def test_list_returns_only_titles_containing_filter(
        self,
        titles: list[str],
        filter_str: str,
    ) -> None:
        """Tasks.list(filter=F) returns only tasks whose title contains F.

        **Validates: Requirements 13.4**
        """
        tasks = Tasks()
        for title in titles:
            tasks.add(title)

        filtered = tasks.list(filter=filter_str)

        # All returned tasks must contain the filter substring
        for task in filtered:
            assert filter_str in task.title, (
                f"Task title {task.title!r} does not contain filter {filter_str!r}"
            )

    @given(
        titles=st.lists(task_titles, min_size=1, max_size=20),
        filter_str=st.text(
            min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))
        ),
    )
    def test_list_includes_all_titles_containing_filter(
        self,
        titles: list[str],
        filter_str: str,
    ) -> None:
        """Tasks.list(filter=F) includes ALL tasks whose title contains F.

        **Validates: Requirements 13.4**
        """
        tasks = Tasks()
        created_ids: list[str] = []
        for title in titles:
            created_ids.append(tasks.add(title))

        # Compute expected matching IDs
        expected_ids = {
            created_ids[i] for i, title in enumerate(titles) if filter_str in title
        }

        filtered = tasks.list(filter=filter_str)
        filtered_ids = {t.id for t in filtered}

        assert filtered_ids == expected_ids


# --- Property 24: Tasks.update persists status change ---


class TestTasksUpdatePersistsStatusChange:
    """Property 24: Tasks.update persists status change.

    For any existing task with id I and any new status S, after
    Tasks.update(I, status=S), the task's status SHALL equal S when retrieved.

    **Validates: Requirements 13.5**
    """

    @given(title=task_titles, new_status=task_statuses)
    def test_update_persists_status(self, title: str, new_status: TaskStatus) -> None:
        """After Tasks.update(id, status=S), the task's status equals S.

        **Validates: Requirements 13.5**
        """
        tasks = Tasks()
        task_id = tasks.add(title)
        tasks.update(task_id, status=new_status)

        all_tasks = tasks.list()
        task = next(t for t in all_tasks if t.id == task_id)
        assert task.status == new_status

    @given(
        title=task_titles,
        statuses=st.lists(task_statuses, min_size=2, max_size=10),
    )
    def test_sequential_updates_persist_last_status(
        self, title: str, statuses: list[TaskStatus]
    ) -> None:
        """After multiple status updates, the final status is the last one applied.

        **Validates: Requirements 13.5**
        """
        tasks = Tasks()
        task_id = tasks.add(title)

        for status in statuses:
            tasks.update(task_id, status=status)

        all_tasks = tasks.list()
        task = next(t for t in all_tasks if t.id == task_id)
        assert task.status == statuses[-1]


# --- Property 25: Tasks operations on non-existent IDs raise TaskNotFoundError ---


class TestTasksNonExistentIDRaisesTaskNotFoundError:
    """Property 25: Tasks operations on non-existent IDs raise TaskNotFoundError.

    For any task_id that does not exist in the store, Tasks.update(task_id, ...)
    and Tasks.delete(task_id) SHALL raise TaskNotFoundError.

    **Validates: Requirements 13.6**
    """

    @given(fake_id=non_existent_ids, status=task_statuses)
    def test_update_nonexistent_raises_task_not_found(
        self, fake_id: str, status: TaskStatus
    ) -> None:
        """Tasks.update() with a non-existent ID raises TaskNotFoundError.

        **Validates: Requirements 13.6**
        """
        tasks = Tasks()
        with pytest.raises(TaskNotFoundError):
            tasks.update(fake_id, status=status)

    @given(fake_id=non_existent_ids)
    def test_delete_nonexistent_raises_task_not_found(self, fake_id: str) -> None:
        """Tasks.delete() with a non-existent ID raises TaskNotFoundError.

        **Validates: Requirements 13.6**
        """
        tasks = Tasks()
        with pytest.raises(TaskNotFoundError):
            tasks.delete(fake_id)

    @given(
        titles=st.lists(task_titles, min_size=1, max_size=10),
        fake_id=non_existent_ids,
    )
    def test_update_nonexistent_id_among_existing_tasks(
        self, titles: list[str], fake_id: str
    ) -> None:
        """Even with existing tasks, update with non-existent ID raises TaskNotFoundError.

        **Validates: Requirements 13.6**
        """
        tasks = Tasks()
        existing_ids = {tasks.add(title) for title in titles}

        # Only test if fake_id doesn't accidentally collide
        assume(fake_id not in existing_ids)

        with pytest.raises(TaskNotFoundError):
            tasks.update(fake_id, status=TaskStatus.DONE)

    @given(
        titles=st.lists(task_titles, min_size=1, max_size=10),
        fake_id=non_existent_ids,
    )
    def test_delete_nonexistent_id_among_existing_tasks(
        self, titles: list[str], fake_id: str
    ) -> None:
        """Even with existing tasks, delete with non-existent ID raises TaskNotFoundError.

        **Validates: Requirements 13.6**
        """
        tasks = Tasks()
        existing_ids = {tasks.add(title) for title in titles}

        assume(fake_id not in existing_ids)

        with pytest.raises(TaskNotFoundError):
            tasks.delete(fake_id)
