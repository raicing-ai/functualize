"""Property tests for JobBrowserPanel selection correctness.

**Property 4: Selection Correctness** — JobSelected.job_name always matches
the job at cursor position.

Generates random job lists and random cursor positions. Verifies:
- action_select_job() posts JobSelected with the correct job.name from
  _jobs[_cursor_row]
- action_select_job() is a no-op when _jobs is empty

**Validates: Requirements 2.5**
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.panels.job_browser import JobBrowserPanel
from functualize._types.descriptors import JobDescriptor

# =============================================================================
# Strategies
# =============================================================================

_job_name = st.builds(
    lambda first, rest: first + rest,
    st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
    st.text(
        st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
        min_size=2,
        max_size=12,
    ),
)

_job_group = st.one_of(st.none(), _job_name)

_job_docstring = st.one_of(
    st.none(),
    st.text(
        st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=0,
        max_size=60,
    ),
)

_job_descriptor = st.builds(
    lambda name, group, docstring: JobDescriptor(
        name=name,
        group=group,
        docstring=docstring,
    ),
    name=_job_name,
    group=_job_group,
    docstring=_job_docstring,
)

# Non-empty job list (1..50) for selection tests
_nonempty_job_list = st.lists(_job_descriptor, min_size=1, max_size=50)


# =============================================================================
# Helpers
# =============================================================================


def _build_panel(jobs: list[JobDescriptor]) -> JobBrowserPanel:
    """Build a JobBrowserPanel with jobs set (no mounted DataTable).

    Goes through the real `set_jobs`, which is safe without a table —
    `_populate_table` no-ops while `_table is None`. Assigning `_jobs`
    directly leaves `_filtered_jobs` empty, and selection reads the filtered
    list, so every selection silently became a no-op.
    """
    panel = JobBrowserPanel(id="selection-test-panel")
    panel.set_jobs(list(jobs))
    return panel


# =============================================================================
# Property 4: Selection Correctness
# =============================================================================


@pytest.mark.slow
class TestSelectionCorrectness:
    """Property 4: Selection Correctness — JobSelected.job_name always matches
    the job at cursor position.

    **Validates: Requirements 2.5**
    """

    @given(
        jobs=_nonempty_job_list,
        cursor_pos=st.data(),
    )
    def test_select_job_posts_correct_name(
        self, jobs: list[JobDescriptor], cursor_pos: st.DataObject
    ) -> None:
        """action_select_job() posts JobSelected with job.name from _jobs[_cursor_row].

        **Validates: Requirements 2.5**
        """
        panel = _build_panel(jobs)
        # Draw a valid cursor position for this specific job list
        pos = cursor_pos.draw(st.integers(min_value=0, max_value=len(jobs) - 1))
        panel._cursor_row = pos

        captured_messages: list[JobBrowserPanel.JobSelected] = []

        with patch.object(
            panel, "post_message", side_effect=lambda msg: captured_messages.append(msg)
        ):
            panel.action_select_job()

        assert len(captured_messages) == 1, (
            f"Expected exactly 1 message posted, got {len(captured_messages)} "
            f"(cursor_pos={pos}, jobs_len={len(jobs)})"
        )
        msg = captured_messages[0]
        assert isinstance(msg, JobBrowserPanel.JobSelected), (
            f"Expected JobSelected message, got {type(msg).__name__}"
        )
        assert msg.job_name == jobs[pos].name, (
            f"JobSelected.job_name={msg.job_name!r} does not match "
            f"_jobs[{pos}].name={jobs[pos].name!r}"
        )

    @given(jobs=_nonempty_job_list)
    def test_select_job_uses_cursor_row_not_fixed_index(
        self, jobs: list[JobDescriptor]
    ) -> None:
        """After navigating, selection reflects updated cursor position.

        Navigate to a random position via action_cursor_down, then select.
        The posted message must match the job at the current _cursor_row.

        **Validates: Requirements 2.5**
        """
        panel = _build_panel(jobs)

        # Navigate to the last row via wrapping
        for _ in range(len(jobs) - 1):
            panel.action_cursor_down()

        expected_pos = panel._cursor_row
        captured_messages: list[JobBrowserPanel.JobSelected] = []

        with patch.object(
            panel, "post_message", side_effect=lambda msg: captured_messages.append(msg)
        ):
            panel.action_select_job()

        assert len(captured_messages) == 1
        assert captured_messages[0].job_name == jobs[expected_pos].name, (
            f"After navigating to row {expected_pos}, "
            f"JobSelected.job_name={captured_messages[0].job_name!r} "
            f"but expected {jobs[expected_pos].name!r}"
        )

    @given(moves=st.lists(st.sampled_from(["down", "up"]), min_size=0, max_size=50))
    def test_select_job_noop_when_empty(self, moves: list[str]) -> None:
        """action_select_job() is a no-op when _jobs is empty.

        No message should be posted regardless of cursor operations.

        **Validates: Requirements 2.5**
        """
        panel = _build_panel([])

        # Apply random cursor moves (all should be no-ops on empty list)
        for move in moves:
            if move == "down":
                panel.action_cursor_down()
            else:
                panel.action_cursor_up()

        captured_messages: list[JobBrowserPanel.JobSelected] = []

        with patch.object(
            panel, "post_message", side_effect=lambda msg: captured_messages.append(msg)
        ):
            panel.action_select_job()

        assert len(captured_messages) == 0, (
            f"Expected no messages for empty job list, "
            f"got {len(captured_messages)} messages"
        )
