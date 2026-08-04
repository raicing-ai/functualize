"""Property tests for JobBrowserPanel cursor navigation bounds.

**Property 3: Cursor Bounds** — Cursor always stays in [0, row_count-1] range.

Generates random lists of JobDescriptors (length 0..50) and random sequences
of j/k keypresses. Verifies:
- _cursor_row always remains in [0, row_count - 1] (or 0 when empty)
- Wrapping: from last row, j goes to 0; from row 0, k goes to last row

**Validates: Requirements 2.4**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
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

_job_list = st.lists(_job_descriptor, min_size=0, max_size=50)

_cursor_moves = st.lists(st.sampled_from(["down", "up"]), min_size=1, max_size=100)


# =============================================================================
# Helpers
# =============================================================================


def _build_panel(jobs: list[JobDescriptor]) -> JobBrowserPanel:
    """Build a JobBrowserPanel with jobs set directly (no mounted DataTable)."""
    panel = JobBrowserPanel(id="cursor-test-panel")
    panel._jobs = list(jobs)
    panel._row_count = len(jobs)
    panel._cursor_row = 0
    return panel


# =============================================================================
# Property 3: Cursor Bounds
# =============================================================================


@pytest.mark.slow
class TestCursorNavigationBounds:
    """Property 3: Cursor Bounds — cursor always stays in [0, row_count-1].

    **Validates: Requirements 2.4**
    """

    @given(jobs=_job_list, moves=_cursor_moves)
    @settings(max_examples=200)
    def test_cursor_stays_in_bounds_after_random_moves(
        self, jobs: list[JobDescriptor], moves: list[str]
    ) -> None:
        """After any sequence of j/k moves, _cursor_row is in valid range.

        **Validates: Requirements 2.4**
        """
        panel = _build_panel(jobs)

        for move in moves:
            if move == "down":
                panel.action_cursor_down()
            else:
                panel.action_cursor_up()

            if panel._row_count == 0:
                assert panel._cursor_row == 0, (
                    f"Empty panel: _cursor_row should be 0, got {panel._cursor_row}"
                )
            else:
                assert 0 <= panel._cursor_row < panel._row_count, (
                    f"_cursor_row={panel._cursor_row} out of bounds "
                    f"[0, {panel._row_count - 1}] after move='{move}'"
                )

    @given(jobs=st.lists(_job_descriptor, min_size=1, max_size=50))
    @settings(max_examples=200)
    def test_cursor_wraps_from_last_to_first(self, jobs: list[JobDescriptor]) -> None:
        """From the last row, action_cursor_down wraps to row 0.

        **Validates: Requirements 2.4**
        """
        panel = _build_panel(jobs)
        # Move cursor to the last row
        panel._cursor_row = panel._row_count - 1

        panel.action_cursor_down()

        assert panel._cursor_row == 0, (
            f"Expected wrap to row 0, got _cursor_row={panel._cursor_row} "
            f"(row_count={panel._row_count})"
        )

    @given(jobs=st.lists(_job_descriptor, min_size=1, max_size=50))
    @settings(max_examples=200)
    def test_cursor_wraps_from_first_to_last(self, jobs: list[JobDescriptor]) -> None:
        """From row 0, action_cursor_up wraps to the last row.

        **Validates: Requirements 2.4**
        """
        panel = _build_panel(jobs)
        # Cursor starts at 0
        assert panel._cursor_row == 0

        panel.action_cursor_up()

        assert panel._cursor_row == panel._row_count - 1, (
            f"Expected wrap to row {panel._row_count - 1}, "
            f"got _cursor_row={panel._cursor_row}"
        )

    @given(moves=_cursor_moves)
    @settings(max_examples=100)
    def test_empty_list_cursor_stays_zero(self, moves: list[str]) -> None:
        """With empty job list, all cursor operations are no-ops (_cursor_row stays 0).

        **Validates: Requirements 2.4**
        """
        panel = _build_panel([])

        for move in moves:
            if move == "down":
                panel.action_cursor_down()
            else:
                panel.action_cursor_up()

            assert panel._cursor_row == 0, (
                f"Empty panel: _cursor_row should stay 0 after '{move}', "
                f"got {panel._cursor_row}"
            )
