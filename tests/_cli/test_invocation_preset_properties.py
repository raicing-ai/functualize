"""Property-based tests for InvocationPreset (Properties 7, 13).

Tests get_recent_invocations from functualize._cli.invocation_preset:
- Property 7: Recent invocations are bounded and ordered
- Property 13: Invocation preset display text faithfulness

# Feature: tui-smart-bar-and-modals, Task 4.2
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.data.argument_history import ArgumentHistory
from functualize._cli.data.invocation_preset import get_recent_invocations

# =============================================================================
# Strategies
# =============================================================================

# Strategy: job names — lowercase letters and underscores
_job_name_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12
)

# Strategy: field names — valid Python identifiers (lowercase + underscore)
_field_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Strategy: field values — alphanumeric strings
_field_value_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20
)

# Strategy: limit — positive integers 1 to 10
_limit_strategy = st.integers(min_value=1, max_value=10)


@st.composite
def _history_with_jobs(draw: st.DrawFn) -> tuple[ArgumentHistory, list[str]]:
    """Generate an ArgumentHistory populated with multiple jobs and varying fields.

    Returns (history, job_names) where job_names is the list of jobs recorded.
    """
    # Generate 1-6 unique job names
    num_jobs = draw(st.integers(min_value=1, max_value=6))
    job_names = draw(
        st.lists(
            _job_name_strategy,
            min_size=num_jobs,
            max_size=num_jobs,
            unique=True,
        )
    )

    history = ArgumentHistory(_store={}, _max_entries=50, _path=None, _dirty=False)

    for job_name in job_names:
        # Each job gets 1-5 fields
        num_fields = draw(st.integers(min_value=1, max_value=5))
        field_names = draw(
            st.lists(
                _field_name_strategy,
                min_size=num_fields,
                max_size=num_fields,
                unique=True,
            )
        )
        for field_name in field_names:
            # Each field gets 1-3 recorded values
            num_values = draw(st.integers(min_value=1, max_value=3))
            values = draw(
                st.lists(
                    _field_value_strategy,
                    min_size=num_values,
                    max_size=num_values,
                )
            )
            for value in values:
                history.record(job_name, field_name, value)

    return history, job_names


@st.composite
def _history_with_extra_job_names(
    draw: st.DrawFn,
) -> tuple[ArgumentHistory, list[str], int]:
    """Generate history + job_names list (may include names not in history) + limit.

    The job_names list provided to get_recent_invocations may include jobs
    that have no history — result should still only contain jobs from the list.
    """
    history, recorded_jobs = draw(_history_with_jobs())

    # Optionally add extra job names that don't have history
    extra_jobs = draw(st.lists(_job_name_strategy, min_size=0, max_size=3, unique=True))
    # Filter out any that accidentally match recorded ones
    extra_jobs = [j for j in extra_jobs if j not in recorded_jobs]

    # The job_names argument is a subset or superset of recorded jobs
    include_recorded = draw(st.booleans())
    if include_recorded:
        job_names = recorded_jobs + extra_jobs
    else:
        # Only use a subset of recorded jobs
        subset = draw(
            st.lists(
                st.sampled_from(recorded_jobs),
                min_size=1,
                max_size=len(recorded_jobs),
                unique=True,
            )
        )
        job_names = subset + extra_jobs

    limit = draw(_limit_strategy)
    return history, job_names, limit


# =============================================================================
# Property 7: Recent invocations are bounded and ordered
# =============================================================================


@pytest.mark.slow
class TestRecentInvocationsBoundedAndOrdered:
    """Property 7: Recent invocations are bounded and ordered.

    For any history, job_names list, and limit value:
    - len(result) <= limit
    - All result items have job_name in the provided job_names list
    - Result is sorted by timestamp descending (most recent first)

    **Validates: Requirements 10.2, 10.3, 10.4**
    """

    @given(data=_history_with_extra_job_names())
    def test_result_length_bounded_by_limit(
        self, data: tuple[ArgumentHistory, list[str], int]
    ) -> None:
        """len(result) <= limit for any inputs.

        **Validates: Requirements 10.2**
        """
        history, job_names, limit = data
        result = get_recent_invocations(history, job_names, limit=limit)
        assert len(result) <= limit, (
            f"Result has {len(result)} items but limit is {limit}"
        )

    @given(data=_history_with_extra_job_names())
    def test_all_job_names_in_provided_list(
        self, data: tuple[ArgumentHistory, list[str], int]
    ) -> None:
        """All result items have job_name in the provided job_names list.

        **Validates: Requirements 10.4**
        """
        history, job_names, limit = data
        result = get_recent_invocations(history, job_names, limit=limit)
        for preset in result:
            assert preset.job_name in job_names, (
                f"Preset job_name {preset.job_name!r} not in "
                f"provided job_names {job_names!r}"
            )

    @given(data=_history_with_extra_job_names())
    def test_result_sorted_by_timestamp_descending(
        self, data: tuple[ArgumentHistory, list[str], int]
    ) -> None:
        """Result is sorted by timestamp in descending order.

        **Validates: Requirements 10.3**
        """
        history, job_names, limit = data
        result = get_recent_invocations(history, job_names, limit=limit)
        if len(result) >= 2:
            timestamps = [preset.timestamp for preset in result]
            for i in range(len(timestamps) - 1):
                assert timestamps[i] >= timestamps[i + 1], (
                    f"Timestamps not sorted descending: "
                    f"{timestamps[i]} < {timestamps[i + 1]} at index {i}"
                )


# =============================================================================
# Property 13: Invocation preset display text faithfulness
# =============================================================================


@pytest.mark.slow
class TestInvocationPresetDisplayTextFaithfulness:
    """Property 13: Invocation preset display text faithfulness.

    For any InvocationPreset in the result:
    - display_text contains job_name
    - display_text contains all values from kwargs

    **Validates: Requirements 10.5**
    """

    @given(data=_history_with_extra_job_names())
    def test_display_text_contains_job_name(
        self, data: tuple[ArgumentHistory, list[str], int]
    ) -> None:
        """display_text contains the job_name for every preset.

        **Validates: Requirements 10.5**
        """
        history, job_names, limit = data
        result = get_recent_invocations(history, job_names, limit=limit)
        for preset in result:
            assert preset.job_name in preset.display_text, (
                f"job_name {preset.job_name!r} not found in "
                f"display_text {preset.display_text!r}"
            )

    @given(data=_history_with_extra_job_names())
    def test_display_text_contains_all_kwargs_values(
        self, data: tuple[ArgumentHistory, list[str], int]
    ) -> None:
        """display_text contains all values from kwargs for every preset.

        **Validates: Requirements 10.5**
        """
        history, job_names, limit = data
        result = get_recent_invocations(history, job_names, limit=limit)
        for preset in result:
            for key, value in preset.kwargs.items():
                assert value in preset.display_text, (
                    f"kwargs value {value!r} for key {key!r} not found in "
                    f"display_text {preset.display_text!r}"
                )
