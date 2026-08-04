"""Property-based tests for PendingExecution (Properties 1, 2, 3).

Tests PendingExecution from functualize._cli.pending_execution:
- Property 1: Override precedence — effective_value returns override when set
- Property 2: Override consistency — has_override, override_count invariants
- Property 3: Set/clear symmetry — set then clear restores original effective_value

Under the SmartBar-as-CLI model there is no per-override
"target": overrides are written directly into ``pending.overrides`` and every
overridden field reports source ``"cli"``.

# Feature: tui-config-inspector, Task 1.2
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.data.pending_execution import PendingExecution
from functualize._config.chain import ResolvedValue

# =============================================================================
# Strategies
# =============================================================================

# Strategy: field names (non-empty, printable text — limited length for speed)
_field_name_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S"), exclude_characters="\x00"),
    min_size=1,
    max_size=30,
)

# Strategy: arbitrary values for config fields
_value_strategy = st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.text(max_size=50),
    st.booleans(),
    st.none(),
)

# Strategy: source types for ResolvedValue. "session" is no longer a live
# source under the SmartBar-as-CLI model (SessionOverlaySource removed).
_source_type_strategy = st.sampled_from(["cli", "env", "file", "remote", "default"])


@st.composite
def _resolved_value(draw: st.DrawFn) -> ResolvedValue:
    """Generate a random ResolvedValue."""
    return ResolvedValue(
        value=draw(_value_strategy),
        source_type=draw(_source_type_strategy),
        source_id=draw(st.text(min_size=1, max_size=20)),
        key=draw(_field_name_strategy),
        alternatives=[],
    )


@st.composite
def _pending_execution(draw: st.DrawFn) -> PendingExecution:
    """Generate a PendingExecution with random resolved_values and no overrides."""
    # Generate 1-10 unique field names
    field_names = draw(
        st.lists(
            _field_name_strategy,
            min_size=1,
            max_size=10,
            unique=True,
        )
    )
    resolved_values: dict[str, ResolvedValue] = {}
    for name in field_names:
        rv = draw(_resolved_value())
        # Ensure the key matches the field name
        resolved_values[name] = ResolvedValue(
            value=rv.value,
            source_type=rv.source_type,
            source_id=rv.source_id,
            key=name,
            alternatives=rv.alternatives,
        )

    return PendingExecution(
        job_name=draw(st.text(min_size=1, max_size=20)),
        resolved_values=resolved_values,
    )


@st.composite
def _pending_with_overrides(
    draw: st.DrawFn,
) -> tuple[PendingExecution, dict[str, Any]]:
    """Generate a PendingExecution with some overrides applied.

    Returns the PE and a dict of field -> override_value.
    """
    pe = draw(_pending_execution())
    field_names = list(pe.resolved_values.keys())

    # Pick a subset of fields to override
    fields_to_override = draw(
        st.lists(
            st.sampled_from(field_names),
            min_size=0,
            max_size=len(field_names),
            unique=True,
        )
    )

    applied_overrides: dict[str, Any] = {}
    for field in fields_to_override:
        value = draw(_value_strategy)
        pe.overrides[field] = value
        applied_overrides[field] = value

    return pe, applied_overrides


# =============================================================================
# Property 1: Override precedence
# =============================================================================


@pytest.mark.slow
class TestOverridePrecedence:
    """Property 1: Override precedence.

    For any field in both overrides and resolved_values,
    effective_value returns the override value.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """

    @given(data=st.data(), pe=_pending_execution())
    @settings(max_examples=200)
    def test_override_wins_over_resolved(
        self,
        data: st.DataObject,
        pe: PendingExecution,
    ) -> None:
        """When a field has an override, effective_value returns the override value.

        **Validates: Requirements 1.2, 1.3, 1.4**
        """
        # Pick a field and override it
        field = data.draw(st.sampled_from(list(pe.resolved_values.keys())))
        override_value = data.draw(_value_strategy)

        pe.overrides[field] = override_value

        assert pe.effective_value(field) == override_value

    @given(pe=_pending_execution())
    @settings(max_examples=200)
    def test_non_overridden_returns_resolved(
        self,
        pe: PendingExecution,
    ) -> None:
        """When a field has no override, effective_value returns resolved chain value.

        **Validates: Requirements 1.2, 1.3**
        """
        # No overrides set, all fields should return resolved value
        for field, rv in pe.resolved_values.items():
            assert pe.effective_value(field) == rv.value


# =============================================================================
# Property 2: Override consistency
# =============================================================================


@pytest.mark.slow
class TestOverrideConsistency:
    """Property 2: Override consistency.

    has_override(f) ↔ f in overrides,
    override_count == len(overrides).

    **Validates: Requirements 1.4, 1.5, 1.6, 1.7**
    """

    @given(pe_and_overrides=_pending_with_overrides())
    @settings(max_examples=200)
    def test_has_override_iff_in_overrides(
        self,
        pe_and_overrides: tuple[PendingExecution, dict[str, Any]],
    ) -> None:
        """has_override returns True iff field is in overrides dict.

        **Validates: Requirements 1.5, 1.6**
        """
        pe, applied = pe_and_overrides

        for field in pe.resolved_values:
            if field in applied:
                assert pe.has_override(field), (
                    f"Field {field!r} was overridden but has_override returned False"
                )
            else:
                assert not pe.has_override(field), (
                    f"Field {field!r} was not overridden but has_override returned True"
                )

    @given(pe_and_overrides=_pending_with_overrides())
    @settings(max_examples=200)
    def test_override_count_equals_len_overrides(
        self,
        pe_and_overrides: tuple[PendingExecution, dict[str, Any]],
    ) -> None:
        """override_count always equals len(overrides).

        **Validates: Requirements 1.7**
        """
        pe, applied = pe_and_overrides

        assert pe.override_count() == len(pe.overrides)
        assert pe.override_count() == len(applied)

    @given(pe_and_overrides=_pending_with_overrides())
    @settings(max_examples=200)
    def test_overridden_field_source_is_cli(
        self,
        pe_and_overrides: tuple[PendingExecution, dict[str, Any]],
    ) -> None:
        """Every overridden field reports source "cli"."""
        pe, applied = pe_and_overrides

        for field in applied:
            assert pe.effective_source(field) == "cli"


# =============================================================================
# Property 3: Set/clear symmetry
# =============================================================================


@pytest.mark.slow
class TestSetClearSymmetry:
    """Property 3: Set/clear symmetry.

    set_override followed by clear_override restores original effective_value.

    **Validates: Requirements 1.4, 1.5, 1.9**
    """

    @given(data=st.data(), pe=_pending_execution())
    @settings(max_examples=200)
    def test_clear_restores_resolved_value(
        self,
        data: st.DataObject,
        pe: PendingExecution,
    ) -> None:
        """After set_override then clear_override, effective_value returns the original resolved value.

        **Validates: Requirements 1.4, 1.5, 1.9**
        """
        field = data.draw(st.sampled_from(list(pe.resolved_values.keys())))
        original_value = pe.effective_value(field)

        # Apply override
        override_value = data.draw(_value_strategy)
        pe.overrides[field] = override_value

        # Confirm override takes effect
        assert pe.effective_value(field) == override_value

        # Clear override
        pe.clear_override(field)

        # Original value restored
        assert pe.effective_value(field) == original_value
        assert not pe.has_override(field)

    @given(data=st.data(), pe=_pending_execution())
    @settings(max_examples=200)
    def test_clear_reduces_override_count(
        self,
        data: st.DataObject,
        pe: PendingExecution,
    ) -> None:
        """set_override increases count, clear_override decreases it back.

        **Validates: Requirements 1.5, 1.7**
        """
        field = data.draw(st.sampled_from(list(pe.resolved_values.keys())))
        override_value = data.draw(_value_strategy)

        count_before = pe.override_count()
        pe.overrides[field] = override_value
        assert pe.override_count() == count_before + 1

        pe.clear_override(field)
        assert pe.override_count() == count_before
