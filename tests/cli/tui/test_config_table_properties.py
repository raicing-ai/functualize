"""Property-based tests for ConfigTablePanel row navigation (Property 12).

Property 12: Row navigation wraps
- Row navigation (j/k) wraps modulo R (j at row R-1 goes to row 0, k at row 0 goes to row R-1)

**Validates: Requirements 7.1, 7.2**

Note: Column navigation (h/l) has been removed — ConfigTablePanel now uses
cursor_type="row" (R4-AC1, R4-AC2, R4-AC3).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.panels.config_table import ConfigTablePanel

# =============================================================================
# Strategies
# =============================================================================


@st.composite
def _table_with_position(
    draw: st.DrawFn,
    min_rows: int = 1,
    max_rows: int = 20,
) -> tuple[ConfigTablePanel, int]:
    """Generate a ConfigTablePanel with R rows and a valid cursor position.

    Returns (panel, starting_row).
    The panel is created without mounting — internal state is set directly.
    """
    row_count = draw(st.integers(min_value=min_rows, max_value=max_rows))
    start_row = draw(st.integers(min_value=0, max_value=row_count - 1))

    panel = ConfigTablePanel.__new__(ConfigTablePanel)
    # Set internal state directly (avoid Textual mounting)
    panel._row_count = row_count
    panel._cursor_row = start_row
    panel._table = None  # No mounted DataTable — _sync_table_cursor is a no-op
    panel._fields = []

    return panel, start_row


@st.composite
def _navigation_sequence(draw: st.DrawFn) -> list[str]:
    """Generate a sequence of navigation actions (up/down only)."""
    length = draw(st.integers(min_value=1, max_value=50))
    actions = draw(
        st.lists(
            st.sampled_from(["down", "up"]),
            min_size=length,
            max_size=length,
        )
    )
    return actions


# =============================================================================
# Property 12: Row navigation wraps
# =============================================================================


@pytest.mark.slow
class TestRowNavigationProperty:
    """Property 12: Row navigation wraps modulo R."""

    @given(data=st.data())
    def test_cursor_down_wraps_modulo_r(self, data: st.DataObject) -> None:
        """action_cursor_down() at row r yields row (r+1) % R.

        **Validates: Requirements 7.1**
        """
        panel, start_row = data.draw(_table_with_position())
        r = panel._row_count

        panel.action_cursor_down()

        assert panel._cursor_row == (start_row + 1) % r

    @given(data=st.data())
    def test_cursor_up_wraps_modulo_r(self, data: st.DataObject) -> None:
        """action_cursor_up() at row r yields row (r-1) % R.

        **Validates: Requirements 7.2**
        """
        panel, start_row = data.draw(_table_with_position())
        r = panel._row_count

        panel.action_cursor_up()

        assert panel._cursor_row == (start_row - 1) % r

    @given(data=st.data())
    def test_cursor_down_r_times_returns_to_start(self, data: st.DataObject) -> None:
        """R consecutive action_cursor_down() calls return to starting row.

        **Validates: Requirements 7.1**
        """
        panel, start_row = data.draw(_table_with_position())
        r = panel._row_count

        for _ in range(r):
            panel.action_cursor_down()

        assert panel._cursor_row == start_row

    @given(data=st.data())
    def test_row_always_in_bounds_after_sequence(self, data: st.DataObject) -> None:
        """After any sequence of up/down, row is always in [0, R-1].

        **Validates: Requirements 7.1, 7.2**
        """
        panel, _ = data.draw(_table_with_position())
        sequence = data.draw(_navigation_sequence())

        for action in sequence:
            if action == "down":
                panel.action_cursor_down()
            elif action == "up":
                panel.action_cursor_up()

        assert 0 <= panel._cursor_row < panel._row_count
