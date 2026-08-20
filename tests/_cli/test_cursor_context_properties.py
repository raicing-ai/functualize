"""Property-based tests for CursorContext parser (Properties 1, 2).

Tests parse_cursor_context from functualize._cli.cursor_context:
- Property 1: CursorContext mode is always valid
- Property 2: CursorContext structural invariants

# Feature: tui-smart-bar-and-modals, Task 1.2
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.completions.cursor_context import (
    CursorContext,
    parse_cursor_context,
)

# =============================================================================
# Strategies
# =============================================================================

# Strategy: arbitrary text strings for smart bar input
_text_strategy = st.text(min_size=0, max_size=100)

# Strategy: job name lists (non-empty, lowercase + underscores)
_job_names_strategy = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15),
    min_size=1,
    max_size=10,
)


@st.composite
def _text_and_cursor(draw: st.DrawFn) -> tuple[str, int]:
    """Generate a text string and a valid cursor position within it."""
    text = draw(_text_strategy)
    cursor_pos = draw(st.integers(min_value=0, max_value=len(text)))
    return text, cursor_pos


# =============================================================================
# Property 1: CursorContext mode is always valid
# =============================================================================


@pytest.mark.slow
class TestModeAlwaysValid:
    """Property 1: CursorContext mode is always valid.

    For any text string and cursor_pos in [0, len(text)], and any non-empty
    job_names list, the returned mode is always in {"command", "flag", "value"}.

    **Validates: Requirements 2.1**
    """

    @given(text_and_cursor=_text_and_cursor(), job_names=_job_names_strategy)
    def test_mode_always_in_valid_set(
        self,
        text_and_cursor: tuple[str, int],
        job_names: list[str],
    ) -> None:
        """For any input, mode is always one of the three valid modes.

        **Validates: Requirements 2.1**
        """
        text, cursor_pos = text_and_cursor
        result = parse_cursor_context(text, cursor_pos, job_names)

        assert isinstance(result, CursorContext)
        assert result.mode in {"command", "flag", "value"}, (
            f"Invalid mode '{result.mode}' for text={text!r}, "
            f"cursor_pos={cursor_pos}, job_names={job_names}"
        )


# =============================================================================
# Property 2: CursorContext structural invariants
# =============================================================================


@pytest.mark.slow
class TestStructuralInvariants:
    """Property 2: CursorContext structural invariants.

    For any CursorContext produced by parse_cursor_context:
    - When mode="value", both job_name and field_name are non-None
    - When mode="flag", job_name is non-None

    **Validates: Requirements 2.5, 2.6**
    """

    @given(text_and_cursor=_text_and_cursor(), job_names=_job_names_strategy)
    def test_value_mode_has_job_and_field(
        self,
        text_and_cursor: tuple[str, int],
        job_names: list[str],
    ) -> None:
        """When mode is "value", both job_name and field_name must be set.

        **Validates: Requirements 2.5, 2.6**
        """
        text, cursor_pos = text_and_cursor
        result = parse_cursor_context(text, cursor_pos, job_names)

        if result.mode == "value":
            assert result.job_name is not None, (
                f"mode='value' but job_name is None for text={text!r}, "
                f"cursor_pos={cursor_pos}, job_names={job_names}"
            )
            assert result.field_name is not None, (
                f"mode='value' but field_name is None for text={text!r}, "
                f"cursor_pos={cursor_pos}, job_names={job_names}"
            )

    @given(text_and_cursor=_text_and_cursor(), job_names=_job_names_strategy)
    def test_flag_mode_has_job_name(
        self,
        text_and_cursor: tuple[str, int],
        job_names: list[str],
    ) -> None:
        """When mode is "flag", job_name must be set.

        **Validates: Requirements 2.5, 2.6**
        """
        text, cursor_pos = text_and_cursor
        result = parse_cursor_context(text, cursor_pos, job_names)

        if result.mode == "flag":
            assert result.job_name is not None, (
                f"mode='flag' but job_name is None for text={text!r}, "
                f"cursor_pos={cursor_pos}, job_names={job_names}"
            )
