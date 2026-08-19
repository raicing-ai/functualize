"""Property-based tests for tasks-local prefix storage.

Property 26: Tasks-local stores with tasks: prefix

For any task stored via functualize-tasks-local, the underlying StateBackend
SHALL contain a key starting with `tasks:` for that task's data. No keys
without the `tasks:` prefix SHALL be created by any task operation.

**Validates: Requirements 14.1, 26.2**
"""

from __future__ import annotations

from functualize_state.testing import InMemoryState
from functualize_tasks import TaskLink, TaskStatus
from functualize_tasks_local import LocalTaskProvider
from hypothesis import given
from hypothesis import strategies as st

# --- Strategies ---

# Strategy for task titles (non-empty printable strings)
task_titles = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
)

# Strategy for TaskStatus values
task_statuses = st.sampled_from(list(TaskStatus))

# Strategy for optional TaskLink
task_link_kinds = st.sampled_from(["job", "workflow_step", "job_phase"])
task_links = st.one_of(
    st.none(),
    st.builds(
        TaskLink,
        kind=task_link_kinds,
        target=st.text(
            min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))
        ),
    ),
)

# Strategy for optional notes
task_notes = st.one_of(st.none(), st.text(min_size=1, max_size=200))


PREFIX = "tasks:"


class TestTasksLocalPrefixStorage:
    """Property 26: Tasks-local stores with tasks: prefix.

    For any task stored via functualize-tasks-local, the underlying StateBackend
    SHALL contain a key starting with `tasks:` for that task's data. No keys
    without the prefix SHALL be created.

    **Validates: Requirements 14.1, 26.2**
    """

    @given(title=task_titles, linked_to=task_links)
    def test_add_stores_with_tasks_prefix(
        self, title: str, linked_to: TaskLink | None
    ) -> None:
        """Adding a task stores data under a key prefixed with `tasks:`.

        **Validates: Requirements 14.1, 26.2**
        """
        backend = InMemoryState()
        provider = LocalTaskProvider(backend=backend)

        provider.add(title, linked_to=linked_to)

        # The backend must have exactly one key, and it must start with tasks:
        all_keys = backend.keys()
        assert len(all_keys) == 1
        assert all_keys[0].startswith(PREFIX), (
            f"Expected key to start with '{PREFIX}', got '{all_keys[0]}'"
        )

    @given(titles=st.lists(task_titles, min_size=1, max_size=20))
    def test_all_stored_keys_have_tasks_prefix(self, titles: list[str]) -> None:
        """All keys stored by multiple add operations start with `tasks:`.

        **Validates: Requirements 14.1, 26.2**
        """
        backend = InMemoryState()
        provider = LocalTaskProvider(backend=backend)

        for title in titles:
            provider.add(title)

        all_keys = backend.keys()
        assert len(all_keys) == len(titles)
        for key in all_keys:
            assert key.startswith(PREFIX), (
                f"Expected key to start with '{PREFIX}', got '{key}'"
            )

    @given(title=task_titles, new_status=task_statuses, notes=task_notes)
    def test_update_preserves_tasks_prefix(
        self, title: str, new_status: TaskStatus, notes: str | None
    ) -> None:
        """After updating a task, all keys still have the `tasks:` prefix.

        **Validates: Requirements 14.1, 26.2**
        """
        backend = InMemoryState()
        provider = LocalTaskProvider(backend=backend)

        task_id = provider.add(title)
        provider.update(task_id, status=new_status, notes=notes)

        all_keys = backend.keys()
        assert len(all_keys) == 1
        for key in all_keys:
            assert key.startswith(PREFIX), (
                f"Expected key to start with '{PREFIX}', got '{key}'"
            )

    @given(title=task_titles)
    def test_delete_removes_prefixed_key(self, title: str) -> None:
        """Deleting a task removes the `tasks:`-prefixed key from the backend.

        **Validates: Requirements 14.1, 26.2**
        """
        backend = InMemoryState()
        provider = LocalTaskProvider(backend=backend)

        task_id = provider.add(title)

        # Verify key exists before deletion
        keys_before = backend.keys()
        assert len(keys_before) == 1
        assert keys_before[0].startswith(PREFIX)

        provider.delete(task_id)

        # After deletion, no keys remain
        keys_after = backend.keys()
        assert len(keys_after) == 0

    @given(title=task_titles, linked_to=task_links)
    def test_no_keys_without_prefix_created(
        self, title: str, linked_to: TaskLink | None
    ) -> None:
        """No keys without the `tasks:` prefix are ever created by task operations.

        **Validates: Requirements 14.1, 26.2**
        """
        backend = InMemoryState()
        provider = LocalTaskProvider(backend=backend)

        task_id = provider.add(title, linked_to=linked_to)

        # Perform update
        provider.update(task_id, status=TaskStatus.IN_PROGRESS, notes="some notes")

        # Check that ALL keys in the backend have the prefix
        all_keys = backend.keys()
        non_prefixed = [k for k in all_keys if not k.startswith(PREFIX)]
        assert non_prefixed == [], (
            f"Found keys without '{PREFIX}' prefix: {non_prefixed}"
        )

    @given(
        title=task_titles,
        link=st.builds(
            TaskLink,
            kind=task_link_kinds,
            target=st.text(
                min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))
            ),
        ),
    )
    def test_link_operation_preserves_prefix(self, title: str, link: TaskLink) -> None:
        """The link operation does not create keys outside the `tasks:` prefix.

        **Validates: Requirements 14.1, 26.2**
        """
        backend = InMemoryState()
        provider = LocalTaskProvider(backend=backend)

        task_id = provider.add(title)
        provider.link(task_id, link)

        all_keys = backend.keys()
        for key in all_keys:
            assert key.startswith(PREFIX), (
                f"Expected key to start with '{PREFIX}', got '{key}'"
            )
        # Still exactly one key for the task
        assert len(all_keys) == 1
