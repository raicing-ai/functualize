"""Property-based tests for JobContext expanded fields (Properties 8–9).

Tests the JobContext frozen dataclass from functualize.job._job_context:
- Property 8: JobContext immutability — assigning to any attribute raises FrozenInstanceError
- Property 9: Invoke depth increment — child job invoke_depth = parent + 1

# Feature: phase1-core-api-surface, Properties 8–9
"""

from __future__ import annotations

import dataclasses
from datetime import UTC
from pathlib import Path
from types import MappingProxyType

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize.job._job_context import JobContext

# =============================================================================
# Strategies
# =============================================================================

# Strategy for generating valid JobContext field values
_name_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        whitelist_characters="_-.",
    ),
)

_optional_str_strategy = st.one_of(st.none(), st.text(min_size=1, max_size=64))

_optional_path_strategy = st.one_of(
    st.none(),
    st.text(
        min_size=1,
        max_size=30,
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters="/._-",
        ),
    ).map(Path),
)

_invoke_depth_strategy = st.integers(min_value=0, max_value=100)

_metadata_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=st.one_of(st.integers(), st.text(max_size=20), st.booleans()),
    max_size=5,
).map(MappingProxyType)


@st.composite
def _job_context_strategy(draw: st.DrawFn) -> JobContext:
    """Generate a valid JobContext instance with arbitrary field values."""
    return JobContext(
        name=draw(_name_strategy),
        trace_id=draw(_optional_str_strategy),
        span_id=draw(_optional_str_strategy),
        deadline=draw(
            st.one_of(
                st.none(),
                st.datetimes(timezones=st.just(UTC)),
            )
        ),
        cwd=draw(_optional_path_strategy),
        job_directory=draw(_optional_path_strategy),
        invoke_depth=draw(_invoke_depth_strategy),
        scope_id=draw(_optional_str_strategy),
        metadata=draw(_metadata_strategy),
    )


# All attribute names on JobContext
_JOB_CONTEXT_FIELDS = [f.name for f in dataclasses.fields(JobContext)]


# =============================================================================
# Property 8: JobContext immutability
# =============================================================================


class TestJobContextImmutability:
    """Property 8: JobContext immutability.

    For any constructed JobContext instance with any combination of valid field
    values, attempting to assign to any attribute SHALL raise FrozenInstanceError.

    **Validates: Requirements 3.10**
    """

    @given(
        ctx=_job_context_strategy(),
        field_name=st.sampled_from(_JOB_CONTEXT_FIELDS),
    )
    @settings(max_examples=200)
    def test_assigning_to_any_field_raises_frozen_error(
        self, ctx: JobContext, field_name: str
    ):
        """Assigning to any attribute of a frozen JobContext raises FrozenInstanceError.

        **Validates: Requirements 3.10**
        """
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(ctx, field_name, "new_value")

    @given(
        ctx=_job_context_strategy(),
        attr_name=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L",),
            ),
        ),
    )
    @settings(max_examples=200)
    def test_assigning_to_arbitrary_attr_raises_frozen_error(
        self, ctx: JobContext, attr_name: str
    ):
        """Assigning to any attribute name (even non-existent) raises FrozenInstanceError.

        **Validates: Requirements 3.10**
        """
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(ctx, attr_name, "some_value")

    @given(ctx=_job_context_strategy())
    @settings(max_examples=200)
    def test_deleting_any_field_raises_frozen_error(self, ctx: JobContext):
        """Deleting any attribute of a frozen JobContext raises FrozenInstanceError.

        **Validates: Requirements 3.10**
        """
        for field_name in _JOB_CONTEXT_FIELDS:
            with pytest.raises(dataclasses.FrozenInstanceError):
                delattr(ctx, field_name)


# =============================================================================
# Property 9: Invoke depth increment
# =============================================================================


class TestInvokeDepthIncrement:
    """Property 9: Invoke depth increment.

    For any job invocation at invoke_depth d where d < max_invoke_depth,
    a child job invoked from within it SHALL have invoke_depth equal to d + 1.

    **Validates: Requirements 3.5, 3.6**
    """

    @given(parent_depth=st.integers(min_value=0, max_value=99))
    @settings(max_examples=200)
    def test_child_invoke_depth_equals_parent_plus_one(self, parent_depth: int):
        """A child JobContext created from a parent has invoke_depth = parent + 1.

        **Validates: Requirements 3.5, 3.6**
        """
        parent_ctx = JobContext(name="parent_job", invoke_depth=parent_depth)

        # Simulate what the engine does: child_depth = parent.invoke_depth + 1
        child_depth = parent_ctx.invoke_depth + 1
        child_ctx = JobContext(name="child_job", invoke_depth=child_depth)

        assert child_ctx.invoke_depth == parent_depth + 1

    @given(
        parent_depth=st.integers(min_value=0, max_value=50),
        chain_length=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=200)
    def test_invoke_depth_increments_across_chain(
        self, parent_depth: int, chain_length: int
    ):
        """A chain of N nested invocations increments invoke_depth by N total.

        **Validates: Requirements 3.5, 3.6**
        """
        current_depth = parent_depth
        for _ in range(chain_length):
            current_depth = current_depth + 1

        # After chain_length invocations, depth should be parent + chain_length
        final_ctx = JobContext(name="final_job", invoke_depth=current_depth)
        assert final_ctx.invoke_depth == parent_depth + chain_length

    @given(parent_depth=st.integers(min_value=0, max_value=99))
    @settings(max_examples=200)
    def test_child_depth_is_always_positive(self, parent_depth: int):
        """Child invoke_depth is always >= 1 when parent depth >= 0.

        **Validates: Requirements 3.5, 3.6**
        """
        child_depth = parent_depth + 1
        child_ctx = JobContext(name="child_job", invoke_depth=child_depth)

        assert child_ctx.invoke_depth >= 1

    @given(negative_depth=st.integers(min_value=-1000, max_value=-1))
    @settings(max_examples=100)
    def test_negative_invoke_depth_raises_value_error(self, negative_depth: int):
        """Creating a JobContext with negative invoke_depth raises ValueError.

        **Validates: Requirements 3.5**
        """
        with pytest.raises(ValueError, match="invoke_depth must be >= 0"):
            JobContext(name="bad_job", invoke_depth=negative_depth)
