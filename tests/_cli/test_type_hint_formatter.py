"""Property-based tests for type hint formatting.

# Feature: tui-architecture-v2, Property 10: Type hint formatting from FieldDescriptor

Tests format_type_hint() from functualize._cli.tui.type_hint_formatter:
- Property 10: Type hint formatting from FieldDescriptor

**Validates: Requirements 14.1, 14.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.tui.type_hint_formatter import format_type_hint

# =============================================================================
# Strategies
# =============================================================================

# Known type annotations per Requirement 14.1
_SIMPLE_TYPES = ["str", "int", "float", "bool", "Path", "FilePath", "DirectoryPath"]

# Expected display mappings per the implementation
_DISPLAY_MAP = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "Path": "Path",
    "FilePath": "Path",
    "DirectoryPath": "Dir",
}

_LIST_INNER_TYPES = ["str", "int", "float", "bool", "Path"]

_simple_type_strategy = st.sampled_from(_SIMPLE_TYPES)

_list_type_strategy = st.sampled_from(_LIST_INNER_TYPES).map(lambda t: f"list[{t}]")

_type_annotation_strategy = st.one_of(_simple_type_strategy, _list_type_strategy)

# Constraint bounds: reasonable numeric values for ge, le, gt, lt
_bound_strategy = st.one_of(
    st.none(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(
        min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)

# Choices list for enum-style fields
_choices_strategy = st.one_of(
    st.none(),
    st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"), blacklist_characters="\n\r"
            ),
            min_size=1,
            max_size=10,
        ),
        min_size=1,
        max_size=6,
    ),
)


@st.composite
def _type_hint_inputs(draw: st.DrawFn) -> dict:
    """Generate valid inputs for format_type_hint."""
    type_annotation = draw(_type_annotation_strategy)
    choices = draw(_choices_strategy)

    # Only generate constraints for numeric types (int, float)
    if type_annotation in ("int", "float") and choices is None:
        # Pick either ge or gt (not both), and either le or lt (not both)
        use_ge = draw(st.booleans())
        use_le = draw(st.booleans())
        has_lower = draw(st.booleans())
        has_upper = draw(st.booleans())

        ge = None
        gt = None
        le = None
        lt = None

        if has_lower:
            val = draw(st.integers(min_value=-100, max_value=100))
            if use_ge:
                ge = val
            else:
                gt = val

        if has_upper:
            val = draw(st.integers(min_value=-100, max_value=100))
            if use_le:
                le = val
            else:
                lt = val
    else:
        ge = None
        gt = None
        le = None
        lt = None

    return {
        "type_annotation": type_annotation,
        "ge": ge,
        "le": le,
        "gt": gt,
        "lt": lt,
        "choices": choices,
    }


# =============================================================================
# Property 10: Type hint formatting from FieldDescriptor
# =============================================================================


@pytest.mark.slow
class TestTypeHintFormatting:
    """Property 10: Type hint formatting from FieldDescriptor.

    For any FieldDescriptor with a type_annotation string and optional
    constraint metadata (ge, le, gt, lt), the formatted type hint should
    correctly map the type to its display form and append constraint ranges
    using the correct bracket notation.

    **Validates: Requirements 14.1, 14.2**
    """

    @given(inputs=_type_hint_inputs())
    def test_result_length_is_at_least_fixed_width(self, inputs: dict) -> None:
        """Result is at least 12 characters (right-padded to fixed width).

        Per Req 14.5: right-padded with spaces when shorter than 12 chars.
        When content (type + constraint) exceeds 12 chars, the full content
        is preserved without truncation.
        """
        result = format_type_hint(
            inputs["type_annotation"],
            ge=inputs["ge"],
            le=inputs["le"],
            gt=inputs["gt"],
            lt=inputs["lt"],
            choices=inputs["choices"],
        )
        assert len(result) >= 12, (
            f"Expected at least 12 chars, got {len(result)} for {result!r}"
        )

    @given(inputs=_type_hint_inputs())
    def test_result_starts_with_correct_display_type(self, inputs: dict) -> None:
        """Result starts with the correct mapped display type (Req 14.1)."""
        result = format_type_hint(
            inputs["type_annotation"],
            ge=inputs["ge"],
            le=inputs["le"],
            gt=inputs["gt"],
            lt=inputs["lt"],
            choices=inputs["choices"],
        )
        stripped = result.rstrip()

        if inputs["choices"]:
            assert stripped.startswith("enum"), (
                f"Expected 'enum' prefix when choices provided, got: {result!r}"
            )
        elif inputs["type_annotation"].startswith("list["):
            assert stripped.startswith(inputs["type_annotation"]), (
                f"Expected '{inputs['type_annotation']}' prefix, got: {result!r}"
            )
        else:
            expected_display = _DISPLAY_MAP[inputs["type_annotation"]]
            assert stripped.startswith(expected_display), (
                f"Expected '{expected_display}' prefix for type '{inputs['type_annotation']}', got: {result!r}"
            )

    @given(inputs=_type_hint_inputs())
    def test_constraint_bracket_notation(self, inputs: dict) -> None:
        """Constraint ranges use correct bracket notation (Req 14.2).

        [N..M] for inclusive (ge/le), (N..M) for exclusive (gt/lt),
        mixed brackets for one inclusive and one exclusive.
        """
        result = format_type_hint(
            inputs["type_annotation"],
            ge=inputs["ge"],
            le=inputs["le"],
            gt=inputs["gt"],
            lt=inputs["lt"],
            choices=inputs["choices"],
        )
        stripped = result.rstrip()

        ge = inputs["ge"]
        gt = inputs["gt"]
        le = inputs["le"]
        lt = inputs["lt"]

        has_lower = ge is not None or gt is not None
        has_upper = le is not None or lt is not None

        if not has_lower and not has_upper:
            # No constraints — no constraint bracket notation in result
            # For list types, the "[" is part of the type name itself (e.g., "list[str]")
            # so we check that no ".." range separator exists
            assert ".." not in stripped, (
                f"No constraints, but range notation found in: {result!r}"
            )
        else:
            # Should contain constraint notation
            if has_lower and has_upper:
                # Both bounds present
                expected_open = "[" if ge is not None else "("
                expected_close = "]" if le is not None else ")"
                assert expected_open in stripped, (
                    f"Expected '{expected_open}' for lower bound in: {result!r}"
                )
                assert stripped.endswith(expected_close), (
                    f"Expected '{expected_close}' at end for upper bound in: {result!r}"
                )
                assert ".." in stripped, f"Expected '..' separator in: {result!r}"
            elif has_lower and not has_upper:
                # Only lower bound
                expected_open = "[" if ge is not None else "("
                assert expected_open in stripped, (
                    f"Expected '{expected_open}' for lower bound in: {result!r}"
                )
                assert stripped.endswith(")"), (
                    f"Expected ')' at end for open upper bound in: {result!r}"
                )
                assert ".." in stripped, f"Expected '..' separator in: {result!r}"
            elif not has_lower and has_upper:
                # Only upper bound
                expected_close = "]" if le is not None else ")"
                assert "(." in stripped or "(.." in stripped, (
                    f"Expected '(..' for open lower bound in: {result!r}"
                )
                assert stripped.endswith(expected_close), (
                    f"Expected '{expected_close}' at end for upper bound in: {result!r}"
                )
                assert ".." in stripped, f"Expected '..' separator in: {result!r}"

    @given(inputs=_type_hint_inputs())
    def test_choices_produce_enum_type(self, inputs: dict) -> None:
        """When choices are provided, the type displays as 'enum' (Req 14.1)."""
        result = format_type_hint(
            inputs["type_annotation"],
            ge=inputs["ge"],
            le=inputs["le"],
            gt=inputs["gt"],
            lt=inputs["lt"],
            choices=inputs["choices"],
        )
        stripped = result.rstrip()

        if inputs["choices"]:
            assert stripped == "enum", (
                f"Expected 'enum' when choices provided, got: {result!r}"
            )
        else:
            # When no choices, should not be "enum"
            assert not stripped.startswith("enum"), (
                f"Got 'enum' without choices for type '{inputs['type_annotation']}': {result!r}"
            )
