"""Property-based tests: task storage stays inside one document.

**Property 26, re-expressed.** It used to read *"for any task stored via
functualize-tasks-local, the underlying StateBackend SHALL contain a key
starting with `tasks:`; no keys without the prefix SHALL be created"*, and it
was checked against `TaskDocument.keys()`.

`plugin-taxonomy`/T7 deleted `TaskDocument`, so that wording no longer names
anything real — but the *intent* is worth keeping and is now cheaper to
guarantee. The prefix was a convention over a faked key space: `TaskDocument`
presented `get`/`set`/`delete`/`keys` over a single substrate document, and the
`tasks:` prefix existed so a flat key space could be pretended to.

The replacement property is stronger, because it is a fact about storage rather
than a convention over it:

    Every task operation touches exactly one substrate key, ``tasks``.

Nothing else can be written without the substrate being asked for another key by
name, which no code path does. The old form could be satisfied by a provider
that wrote `tasks:a`, `tasks:b` *and* `tasks-index`; this one cannot.

**Validates: Requirements 14.1, 26.2** (unchanged — the requirement is that task
storage is confined to its own namespace, not that the namespace is a prefix).
"""

from __future__ import annotations

import contextlib
from typing import Any

from functualize_tasks import TaskLink, TaskStatus
from functualize_tasks_local import LocalTaskProvider
from functualize_tasks_local._provider import TASKS_KEY
from hypothesis import given
from hypothesis import strategies as st

from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.protocols import StoreSubstrate


class _RecordingSubstrate:
    """A real substrate that remembers which keys were asked for.

    Real storage underneath — the provider's job is to survive a restart, and a
    double that cannot be restarted cannot show that. Only the bookkeeping is
    added.
    """

    def __init__(self, root: Any) -> None:
        self._inner = JsonFileSubstrate(root)
        self.keys_written: list[str] = []
        self.keys_read: list[str] = []

    def read(self, key: str) -> Any:
        self.keys_read.append(key)
        return self._inner.read(key)

    def write(self, key: str, payload: dict, *, expect: int | None = None) -> bool:
        self.keys_written.append(key)
        return self._inner.write(key, payload, expect=expect)

    @contextlib.contextmanager
    def lock(self, *keys: str) -> Any:
        with self._inner.lock(*keys):
            yield

    def clear(self, key: str) -> str | None:
        return self._inner.clear(key)

    def delete(self, key: str) -> bool:
        self.keys_written.append(key)
        return self._inner.delete(key)

    def describe(self, key: str) -> str:
        return self._inner.describe(key)

    # -- what the assertions ask --------------------------------------------

    @property
    def touched(self) -> set[str]:
        return set(self.keys_written) | set(self.keys_read)

    def tasks(self) -> dict[str, Any]:
        stored = self._inner.read(TASKS_KEY)
        return dict(stored.data.get("tasks", {})) if stored else {}


def _provider(tmpdir: Any) -> tuple[LocalTaskProvider, _RecordingSubstrate]:
    substrate = _RecordingSubstrate(tmpdir)
    return LocalTaskProvider(lambda: substrate), substrate


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


# --- Strategies ---

task_titles = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
)
task_statuses = st.sampled_from(list(TaskStatus))
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
task_notes = st.one_of(st.none(), st.text(min_size=1, max_size=200))


def test_the_double_is_really_a_substrate() -> None:
    """Guards the guard. A double that drifted out of the port would make every
    property below pass for the wrong reason."""
    assert isinstance(_RecordingSubstrate(_tmp()), StoreSubstrate)


class TestTaskStorageIsConfinedToOneDocument:
    """Property 26. One key, whatever the operation and whatever the input."""

    @given(title=task_titles, linked_to=task_links)
    def test_add_touches_only_the_tasks_document(
        self, title: str, linked_to: TaskLink | None
    ) -> None:
        provider, substrate = _provider(_tmp())

        provider.add(title, linked_to=linked_to)

        assert substrate.touched == {TASKS_KEY}
        assert len(substrate.tasks()) == 1

    @given(titles=st.lists(task_titles, min_size=1, max_size=20))
    def test_many_adds_still_touch_only_that_document(self, titles: list[str]) -> None:
        """The old form let the key space grow with N. This one cannot."""
        provider, substrate = _provider(_tmp())

        for title in titles:
            provider.add(title)

        assert substrate.touched == {TASKS_KEY}
        assert len(substrate.tasks()) == len(titles)

    @given(title=task_titles, new_status=task_statuses, notes=task_notes)
    def test_update_touches_only_the_tasks_document(
        self, title: str, new_status: TaskStatus, notes: str | None
    ) -> None:
        provider, substrate = _provider(_tmp())

        task_id = provider.add(title)
        provider.update(task_id, status=new_status, notes=notes)

        assert substrate.touched == {TASKS_KEY}
        assert len(substrate.tasks()) == 1

    @given(title=task_titles)
    def test_delete_empties_the_document_without_touching_another(
        self, title: str
    ) -> None:
        provider, substrate = _provider(_tmp())

        task_id = provider.add(title)
        assert len(substrate.tasks()) == 1

        provider.delete(task_id)

        assert substrate.touched == {TASKS_KEY}
        assert substrate.tasks() == {}

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
    def test_link_touches_only_the_tasks_document(
        self, title: str, link: TaskLink
    ) -> None:
        provider, substrate = _provider(_tmp())

        task_id = provider.add(title)
        provider.link(task_id, link)

        assert substrate.touched == {TASKS_KEY}
        stored = next(iter(substrate.tasks().values()))
        assert stored["linked_to"] == {"kind": link.kind, "target": link.target}

    @given(title=task_titles, linked_to=task_links)
    def test_a_full_lifecycle_never_reaches_a_second_key(
        self, title: str, linked_to: TaskLink | None
    ) -> None:
        """The original's closing property — "no keys without the prefix are
        ever created" — over every verb the provider has."""
        provider, substrate = _provider(_tmp())

        task_id = provider.add(title, linked_to=linked_to)
        provider.update(task_id, status=TaskStatus.IN_PROGRESS, notes="some notes")
        provider.list()
        provider.delete(task_id)

        assert substrate.touched == {TASKS_KEY}, (
            f"task operations reached {sorted(substrate.touched - {TASKS_KEY})}"
        )
