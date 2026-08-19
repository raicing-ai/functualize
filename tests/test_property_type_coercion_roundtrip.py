"""Property-based tests for type coercion round-trip correctness (Property 4).

# Feature: codebase-restructure, Property 4: Type coercion round-trip correctness

**Validates: Requirements 8.2, 8.3**
"""

from __future__ import annotations

import json
import string
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._types.descriptors import FieldDescriptor
from functualize.app.utils import coerce_kwargs

# =============================================================================
# Strategies for generating FieldDescriptors with supported types
# =============================================================================

# Supported type annotations for coercion
_SUPPORTED_TYPES = ("str", "int", "float", "bool", "list[str]", "Path")

# Strategy: valid parameter names
_param_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda n: n not in ("self", "cls") and not n.startswith("__")
)


def _make_field(name: str, type_annotation: str) -> FieldDescriptor:
    """Create a FieldDescriptor for the given name and type."""
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=None,
        description=f"Test field for {type_annotation}",
        required=True,
        choices=None,
    )


# =============================================================================
# Strategies for generating valid values per type
# =============================================================================


@st.composite
def _valid_str_value(draw):
    """Generate a valid string value."""
    return draw(
        st.text(
            min_size=0,
            max_size=50,
            alphabet=st.characters(
                categories=("L", "N", "P", "S", "Z"),
                exclude_characters="\x00",
            ),
        )
    )


@st.composite
def _valid_int_value(draw):
    """Generate a valid integer value."""
    return draw(st.integers(min_value=-10_000, max_value=10_000))


@st.composite
def _valid_float_value(draw):
    """Generate a valid float value."""
    return draw(
        st.floats(
            allow_nan=False,
            allow_infinity=False,
            min_value=-1e6,
            max_value=1e6,
        )
    )


# Bool canonical forms that Pydantic accepts
_BOOL_TRUE_STRINGS = ("true", "True", "1", "yes")
_BOOL_FALSE_STRINGS = ("false", "False", "0", "no")


@st.composite
def _valid_bool_value(draw):
    """Generate a valid bool value (True or False)."""
    return draw(st.booleans())


@st.composite
def _valid_list_str_value(draw):
    """Generate a valid list[str] value."""
    items = draw(
        st.lists(
            st.text(
                min_size=0,
                max_size=20,
                alphabet=string.ascii_letters + string.digits + " _-",
            ),
            min_size=0,
            max_size=5,
        )
    )
    return items


@st.composite
def _valid_path_value(draw):
    """Generate a valid Path value."""
    # Generate path-like strings with forward slashes
    segments = draw(
        st.lists(
            st.from_regex(r"[a-zA-Z0-9_\-.]{1,12}", fullmatch=True),
            min_size=1,
            max_size=4,
        )
    )
    path_str = "/" + "/".join(segments)
    return Path(path_str)


# =============================================================================
# Combined strategy: (FieldDescriptor, value, string_representation)
# =============================================================================


@st.composite
def _typed_field_and_value(draw):
    """Generate a (FieldDescriptor, original_value, string_repr) tuple.

    The string_repr is what would be passed as CLI input, and coercing it
    back should produce the original value.
    """
    name = draw(_param_name_strategy)
    type_ann = draw(st.sampled_from(_SUPPORTED_TYPES))

    if type_ann == "str":
        value = draw(_valid_str_value())
        str_repr = value  # str round-trips as itself
    elif type_ann == "int":
        value = draw(_valid_int_value())
        str_repr = str(value)
    elif type_ann == "float":
        value = draw(_valid_float_value())
        str_repr = str(value)
    elif type_ann == "bool":
        value = draw(_valid_bool_value())
        # Use canonical str() form: "True" or "False"
        str_repr = str(value)
    elif type_ann == "list[str]":
        value = draw(_valid_list_str_value())
        str_repr = json.dumps(value)  # JSON-encoded
    elif type_ann == "Path":
        value = draw(_valid_path_value())
        str_repr = str(value)
    else:
        raise AssertionError(f"Unexpected type: {type_ann}")

    field = _make_field(name, type_ann)
    return (field, value, str_repr)


# =============================================================================
# Strategy for generating invalid strings per type
# =============================================================================


@st.composite
def _invalid_string_for_type(draw):
    """Generate a (FieldDescriptor, invalid_string) tuple where the string
    cannot be converted to the target type.
    """
    name = draw(_param_name_strategy)
    # Only use types where invalid strings are meaningful
    # (str accepts anything, so we exclude it)
    type_ann = draw(st.sampled_from(("int", "float", "bool", "list[str]")))

    if type_ann == "int":
        # Strings that are definitely not integers
        invalid = draw(
            st.sampled_from(
                [
                    "not_a_number",
                    "3.14",  # float string is not valid int
                    "abc",
                    "12.5",
                    "true",
                    "",
                    "1e5",
                    "0x1F",
                ]
            )
        )
    elif type_ann == "float":
        # Strings that are definitely not floats
        invalid = draw(
            st.sampled_from(
                [
                    "not_a_float",
                    "abc",
                    "twelve",
                    "",
                    "1.2.3",
                    "inf_bad",
                ]
            )
        )
    elif type_ann == "bool":
        # Strings that Pydantic does NOT accept as bool
        invalid = draw(
            st.sampled_from(
                [
                    "maybe",
                    "2",
                    "yep",
                    "nope",
                    "truthy",
                    "falsy",
                    "",
                    "none",
                ]
            )
        )
    elif type_ann == "list[str]":
        # Strings that are not valid JSON arrays
        invalid = draw(
            st.sampled_from(
                [
                    "not json",
                    '{"key": "val"}',  # object, not array
                    "[1, 2",  # incomplete
                    "plain text",
                    "123",
                    "",
                ]
            )
        )
    else:
        invalid = "definitely_invalid"

    field = _make_field(name, type_ann)
    return (field, invalid)


# =============================================================================
# Property 4: Type coercion round-trip correctness
# =============================================================================


class TestTypeCoercionRoundTripProperty:
    """Property 4: Type coercion round-trip correctness.

    For any FieldDescriptor with a supported type_annotation (str, int, float,
    bool, list[str], Path) and any valid Python value of that type,
    coerce_kwargs({name: str(value)}, [descriptor]) SHALL produce a dict where
    the value is equal to the original Python value.

    For any FieldDescriptor and a string that is not a valid representation of
    the target type, coerce_kwargs SHALL raise ValueError with a message
    containing the parameter name and expected type.

    **Validates: Requirements 8.2, 8.3**
    """

    @given(data=_typed_field_and_value())
    def test_valid_value_round_trip(
        self, data: tuple[FieldDescriptor, object, str]
    ) -> None:
        """str(value) → coerce → value preserves the original value.

        **Validates: Requirements 8.2**
        """
        field, original_value, str_repr = data

        result = coerce_kwargs({field.name: str_repr}, [field])

        assert field.name in result
        coerced = result[field.name]

        if field.type_annotation == "float":
            # Float comparison with tolerance for floating point repr
            assert isinstance(coerced, float)
            assert abs(coerced - original_value) < 1e-9, (
                f"Float round-trip failed: {original_value!r} -> "
                f"'{str_repr}' -> {coerced!r}"
            )
        elif field.type_annotation == "Path":
            # Path comparison via string normalization
            assert isinstance(coerced, Path)
            assert str(coerced) == str(original_value), (
                f"Path round-trip failed: {original_value!r} -> "
                f"'{str_repr}' -> {coerced!r}"
            )
        elif field.type_annotation == "bool":
            assert isinstance(coerced, bool)
            assert coerced == original_value, (
                f"Bool round-trip failed: {original_value!r} -> "
                f"'{str_repr}' -> {coerced!r}"
            )
        elif field.type_annotation == "list[str]":
            assert isinstance(coerced, list)
            assert coerced == original_value, (
                f"list[str] round-trip failed: {original_value!r} -> "
                f"'{str_repr}' -> {coerced!r}"
            )
        else:
            assert coerced == original_value, (
                f"Round-trip failed for {field.type_annotation}: "
                f"{original_value!r} -> '{str_repr}' -> {coerced!r}"
            )

    @given(data=_invalid_string_for_type())
    def test_invalid_value_raises_valueerror(
        self, data: tuple[FieldDescriptor, str]
    ) -> None:
        """Invalid strings raise ValueError with parameter name and expected type.

        **Validates: Requirements 8.3**
        """
        field, invalid_str = data

        try:
            coerce_kwargs({field.name: invalid_str}, [field])
            # If it didn't raise, that's a test failure —
            # the invalid string should not have been accepted
            raise AssertionError(
                f"Expected ValueError for type={field.type_annotation}, "
                f"value='{invalid_str}', param='{field.name}' but coercion succeeded"
            )
        except ValueError as exc:
            error_msg = str(exc)
            # Verify the error message contains the parameter name
            assert field.name in error_msg, (
                f"ValueError message should contain parameter name '{field.name}', "
                f"got: '{error_msg}'"
            )
            # Verify the error message contains the expected type
            assert field.type_annotation in error_msg, (
                f"ValueError message should contain type '{field.type_annotation}', "
                f"got: '{error_msg}'"
            )

    @given(data=_typed_field_and_value())
    def test_str_type_always_passes_through(
        self, data: tuple[FieldDescriptor, object, str]
    ) -> None:
        """String type coercion always returns the original string unchanged.

        **Validates: Requirements 8.2**
        """
        field, original_value, str_repr = data
        # Only test str type
        assume(field.type_annotation == "str")

        result = coerce_kwargs({field.name: str_repr}, [field])
        assert result[field.name] == str_repr
        assert isinstance(result[field.name], str)

    @given(name=_param_name_strategy, value=_valid_int_value())
    def test_int_round_trip_specific(self, name: str, value: int) -> None:
        """Integer round-trip: str(int_value) → coerce → int_value.

        **Validates: Requirements 8.2**
        """
        field = _make_field(name, "int")
        result = coerce_kwargs({name: str(value)}, [field])
        assert result[name] == value
        assert isinstance(result[name], int)

    @given(name=_param_name_strategy, value=_valid_float_value())
    def test_float_round_trip_specific(self, name: str, value: float) -> None:
        """Float round-trip: str(float_value) → coerce → float_value (within tolerance).

        **Validates: Requirements 8.2**
        """
        field = _make_field(name, "float")
        result = coerce_kwargs({name: str(value)}, [field])
        assert isinstance(result[name], float)
        assert abs(result[name] - value) < 1e-9

    @given(name=_param_name_strategy, value=st.booleans())
    def test_bool_round_trip_canonical(self, name: str, value: bool) -> None:
        """Bool round-trip with canonical str() forms ("True"/"False").

        Pydantic accepts "true"/"false"/"1"/"0"/"yes"/"no" — verify round-trip
        for canonical forms (str(True)="True", str(False)="False").

        **Validates: Requirements 8.2**
        """
        field = _make_field(name, "bool")
        # Canonical Python str(bool) produces "True" or "False"
        result = coerce_kwargs({name: str(value)}, [field])
        assert result[name] == value
        assert isinstance(result[name], bool)

    @given(
        name=_param_name_strategy,
        items=st.lists(
            st.text(
                min_size=0,
                max_size=20,
                alphabet=string.ascii_letters + string.digits + " _-",
            ),
            min_size=0,
            max_size=5,
        ),
    )
    def test_list_str_round_trip_json_encoded(
        self, name: str, items: list[str]
    ) -> None:
        """list[str] round-trip: JSON-encoded string → coerce → list[str].

        Values must be JSON-encoded (e.g., '["a", "b"]').

        **Validates: Requirements 8.2**
        """
        field = _make_field(name, "list[str]")
        json_str = json.dumps(items)
        result = coerce_kwargs({name: json_str}, [field])
        assert result[name] == items
        assert isinstance(result[name], list)

    @given(name=_param_name_strategy, path_value=_valid_path_value())
    def test_path_round_trip(self, name: str, path_value: Path) -> None:
        """Path round-trip: str(Path("/foo")) == "/foo" → coerce → Path("/foo").

        **Validates: Requirements 8.2**
        """
        field = _make_field(name, "Path")
        result = coerce_kwargs({name: str(path_value)}, [field])
        assert isinstance(result[name], Path)
        assert str(result[name]) == str(path_value)
