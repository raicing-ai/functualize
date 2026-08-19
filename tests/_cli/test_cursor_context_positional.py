# Feature: tui-architecture-v2, Property 12: CursorContext positional mode detection
"""Property-based tests for CursorContext positional mode detection.

Tests parse_cursor_context from functualize._cli.cursor_context:
- Property 12: For any job with N positional params and K completed non-flag tokens
  (K < N) where the partial doesn't start with "--", mode == "positional" with
  positional_index == K. When K >= N, mode falls back to "flag".

**Validates: Requirements 19.1, 19.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.completions.cursor_context import parse_cursor_context

# =============================================================================
# Strategies
# =============================================================================

# Job names: lowercase alpha identifiers (no hyphens to avoid flag confusion)
_job_name_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=10
)

# Positional token values: simple non-flag alphanumeric strings
_positional_token_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12
).filter(lambda s: not s.startswith("-"))

# Partial token being typed (non-flag, non-empty or empty)
_partial_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=0, max_size=8
).filter(lambda s: not s.startswith("-"))

# Number of positional params for the job
_n_positional_strategy = st.integers(min_value=1, max_value=5)


@st.composite
def _positional_underflow_scenario(
    draw: st.DrawFn,
) -> tuple[str, int, list[str], dict[str, int], int, int]:
    """Generate scenario where K < N (positional mode expected).

    Returns: (text, cursor_pos, job_names, positional_params, K, N)
    """
    job_name = draw(_job_name_strategy)
    n_positional = draw(_n_positional_strategy)

    # K must be < N (number of completed positional tokens)
    k = draw(st.integers(min_value=0, max_value=n_positional - 1))

    # Generate K completed positional tokens
    completed_tokens = draw(
        st.lists(_positional_token_strategy, min_size=k, max_size=k)
    )

    # Generate partial (what user is currently typing, non-flag)
    partial = draw(_partial_strategy)

    # Build the text: "job_name tok1 tok2 ... partial"
    parts = [job_name] + completed_tokens
    if partial:
        text = " ".join(parts) + " " + partial
        cursor_pos = len(text)
    else:
        # Trailing space means we're at position for next token
        text = " ".join(parts) + " "
        cursor_pos = len(text)

    job_names = [job_name]
    positional_params = {job_name: n_positional}

    return text, cursor_pos, job_names, positional_params, k, n_positional


@st.composite
def _positional_overflow_scenario(
    draw: st.DrawFn,
) -> tuple[str, int, list[str], dict[str, int], int, int]:
    """Generate scenario where K >= N (flag mode expected).

    Returns: (text, cursor_pos, job_names, positional_params, K, N)
    """
    job_name = draw(_job_name_strategy)
    n_positional = draw(_n_positional_strategy)

    # K must be >= N
    k = draw(st.integers(min_value=n_positional, max_value=n_positional + 3))

    # Generate K completed positional tokens
    completed_tokens = draw(
        st.lists(_positional_token_strategy, min_size=k, max_size=k)
    )

    # Generate partial (non-flag)
    partial = draw(_partial_strategy)

    # Build the text
    parts = [job_name] + completed_tokens
    if partial:
        text = " ".join(parts) + " " + partial
        cursor_pos = len(text)
    else:
        text = " ".join(parts) + " "
        cursor_pos = len(text)

    job_names = [job_name]
    positional_params = {job_name: n_positional}

    return text, cursor_pos, job_names, positional_params, k, n_positional


@st.composite
def _flag_partial_scenario(
    draw: st.DrawFn,
) -> tuple[str, int, list[str], dict[str, int]]:
    """Generate scenario where partial starts with '--' (flag mode forced).

    Returns: (text, cursor_pos, job_names, positional_params)
    """
    job_name = draw(_job_name_strategy)
    n_positional = draw(_n_positional_strategy)

    # Some completed positional tokens (fewer than N so positional would apply)
    k = draw(st.integers(min_value=0, max_value=max(0, n_positional - 1)))
    completed_tokens = draw(
        st.lists(_positional_token_strategy, min_size=k, max_size=k)
    )

    # Partial starts with "--"
    flag_suffix = draw(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8)
    )
    partial = "--" + flag_suffix

    # Build text
    parts = [job_name] + completed_tokens
    text = " ".join(parts) + " " + partial
    cursor_pos = len(text)

    job_names = [job_name]
    positional_params = {job_name: n_positional}

    return text, cursor_pos, job_names, positional_params


# =============================================================================
# Property 12: CursorContext positional mode detection
# =============================================================================


@pytest.mark.slow
class TestCursorContextPositionalMode:
    """Property 12: CursorContext positional mode detection.

    For any job with N defined positional parameters and K completed non-flag
    tokens after the job name (where K < N), and the current partial token does
    not start with "--", the CursorContext mode should be "positional" with
    positional_index = K. When K >= N, mode should fall back to "flag".

    **Validates: Requirements 19.1, 19.2**
    """

    @given(scenario=_positional_underflow_scenario())
    def test_positional_mode_when_k_less_than_n(
        self,
        scenario: tuple[str, int, list[str], dict[str, int], int, int],
    ) -> None:
        """When K < N non-flag tokens are completed, mode is 'positional' with index K.

        **Validates: Requirements 19.1**
        """
        text, cursor_pos, job_names, positional_params, k, n = scenario

        result = parse_cursor_context(text, cursor_pos, job_names, positional_params)

        assert result.mode == "positional", (
            f"Expected mode='positional' but got '{result.mode}' "
            f"for text={text!r}, cursor_pos={cursor_pos}, K={k}, N={n}"
        )
        assert result.positional_index == k, (
            f"Expected positional_index={k} but got {result.positional_index} "
            f"for text={text!r}, cursor_pos={cursor_pos}"
        )
        assert result.job_name == job_names[0], (
            f"Expected job_name={job_names[0]!r} but got {result.job_name!r}"
        )

    @given(scenario=_positional_overflow_scenario())
    def test_flag_mode_when_k_ge_n(
        self,
        scenario: tuple[str, int, list[str], dict[str, int], int, int],
    ) -> None:
        """When K >= N non-flag tokens are completed, mode falls back to 'flag'.

        **Validates: Requirements 19.2**
        """
        text, cursor_pos, job_names, positional_params, k, n = scenario

        result = parse_cursor_context(text, cursor_pos, job_names, positional_params)

        assert result.mode == "flag", (
            f"Expected mode='flag' but got '{result.mode}' "
            f"for text={text!r}, cursor_pos={cursor_pos}, K={k}, N={n}"
        )
        assert result.job_name == job_names[0], (
            f"Expected job_name={job_names[0]!r} but got {result.job_name!r}"
        )

    @given(scenario=_flag_partial_scenario())
    def test_flag_mode_when_partial_starts_with_dashes(
        self,
        scenario: tuple[str, int, list[str], dict[str, int]],
    ) -> None:
        """When partial starts with '--', mode is always 'flag' regardless of positional state.

        **Validates: Requirements 19.1, 19.2**
        """
        text, cursor_pos, job_names, positional_params = scenario

        result = parse_cursor_context(text, cursor_pos, job_names, positional_params)

        assert result.mode == "flag", (
            f"Expected mode='flag' but got '{result.mode}' "
            f"for text={text!r} (partial starts with '--')"
        )
        assert result.job_name == job_names[0], (
            f"Expected job_name={job_names[0]!r} but got {result.job_name!r}"
        )
