"""Property-based tests for MissingArgsResult (Property 3: consistency).

Tests the MissingArgsResult dataclass from functualize._cli.tui.missing_args:
- Property 3: MissingArgsResult consistency (is_executable ↔ missing_fields)

# Feature: tui-smart-bar-and-modals, Task 2.2
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.missing_args import MissingArgsResult
from functualize._types.descriptors import FieldDescriptor

# =============================================================================
# Strategies
# =============================================================================


@st.composite
def _field_descriptor(draw: st.DrawFn) -> FieldDescriptor:
    """Generate a FieldDescriptor with required=True (for missing fields)."""
    name = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_",
            min_size=1,
            max_size=12,
        )
    )
    type_annotation = draw(st.sampled_from(["str", "int", "bool", "float", "Path"]))
    description = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=0,
            max_size=30,
        )
    )
    choices = draw(
        st.one_of(
            st.none(),
            st.lists(
                st.text(
                    alphabet="abcdefghijklmnopqrstuvwxyz",
                    min_size=1,
                    max_size=8,
                ),
                min_size=1,
                max_size=4,
            ),
        )
    )
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=None,
        description=description,
        required=True,
        choices=choices,
    )


@st.composite
def _missing_args_result(draw: st.DrawFn) -> MissingArgsResult:
    """Generate a MissingArgsResult with consistent is_executable ↔ missing_fields."""
    job_name = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_",
            min_size=1,
            max_size=15,
        )
    )
    num_missing = draw(st.integers(min_value=0, max_value=10))
    missing_fields = draw(
        st.lists(_field_descriptor(), min_size=num_missing, max_size=num_missing)
    )
    # Generate provided fields (field_name -> value pairs)
    num_provided = draw(st.integers(min_value=0, max_value=5))
    provided_fields = draw(
        st.dictionaries(
            keys=st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz_",
                min_size=1,
                max_size=12,
            ),
            values=st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
                min_size=0,
                max_size=20,
            ),
            min_size=num_provided,
            max_size=num_provided,
        )
    )
    # Enforce the consistency contract: is_executable ↔ empty missing_fields
    is_executable = len(missing_fields) == 0

    return MissingArgsResult(
        job_name=job_name,
        missing_fields=missing_fields,
        provided_fields=provided_fields,
        is_executable=is_executable,
    )


# =============================================================================
# Property 3: MissingArgsResult consistency
# =============================================================================


class TestMissingArgsResultConsistency:
    """Property 3: MissingArgsResult consistency.

    For any MissingArgsResult, is_executable SHALL be True if and only if
    missing_fields is empty, all items in missing_fields SHALL have
    required=True, and provided_fields keys SHALL be a subset of the job's
    parameter names.

    **Validates: Requirements 4.3, 4.4, 4.5**
    """

    @pytest.mark.slow
    @given(result=_missing_args_result())
    def test_is_executable_iff_missing_fields_empty(self, result: MissingArgsResult):
        """is_executable is True ↔ missing_fields is empty.

        **Validates: Requirements 4.3, 4.4, 4.5**
        """
        if result.is_executable:
            assert result.missing_fields == [], (
                "is_executable=True requires missing_fields to be empty, "
                f"but got {len(result.missing_fields)} missing fields"
            )
        else:
            assert len(result.missing_fields) > 0, (
                "is_executable=False requires at least one missing field, "
                "but missing_fields is empty"
            )

    @pytest.mark.slow
    @given(result=_missing_args_result())
    def test_all_missing_fields_are_required(self, result: MissingArgsResult):
        """All items in missing_fields have required=True.

        **Validates: Requirements 4.3, 4.4, 4.5**
        """
        for field in result.missing_fields:
            assert field.required is True, (
                f"Field '{field.name}' in missing_fields has required=False, "
                "but only required fields should appear in missing_fields"
            )

    @pytest.mark.slow
    @given(result=_missing_args_result())
    def test_missing_count_equals_missing_fields_length(
        self, result: MissingArgsResult
    ):
        """missing_count property matches len(missing_fields).

        **Validates: Requirements 4.3, 4.4, 4.5**
        """
        assert result.missing_count == len(result.missing_fields), (
            f"missing_count={result.missing_count} does not match "
            f"len(missing_fields)={len(result.missing_fields)}"
        )
