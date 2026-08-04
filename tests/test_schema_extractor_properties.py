"""Property-based tests for schema extraction correctness.

Tests Property 16 from the design document for the
layered-architecture-lazy-boot spec.

Property 16: For any Pydantic BaseModel subclass with fields of supported types
(str, int, bool, float, Enum subclasses, list[str], Optional variants), the
schema extractor SHALL produce a list[FieldDescriptor] where each field's name,
type, choices, default, required, and help correctly reflect the model's field
definitions.

# Feature: layered-architecture-lazy-boot, Property 16: Schema extraction correctness
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, Field

from functualize._discovery.schema_extractor import extract_field_descriptors

if TYPE_CHECKING:
    from functualize._types.descriptors import FieldDescriptor

# --- Supported field types ---

# The supported type strings the schema extractor should produce.
SUPPORTED_TYPES = ("str", "int", "bool", "float", "enum", "list[str]")


# --- Dynamic Enum generation ---


def _make_enum(name: str, members: list[str]) -> type[enum.Enum]:
    """Create a dynamic Enum class with string values."""
    return enum.Enum(name, {m: m for m in members})  # type: ignore[misc]


# --- Field specification dataclass for test generation ---


class FieldSpec:
    """Specification for a single Pydantic model field to be generated.

    This captures the "ground truth" for what the schema extractor should
    produce, alongside the annotation/default/description used to build
    the dynamic Pydantic model.
    """

    def __init__(
        self,
        name: str,
        type_str: str,
        annotation: Any,
        required: bool,
        default: Any,
        help_text: str,
        choices: list[str] | None,
        enum_class: type[enum.Enum] | None = None,
    ):
        self.name = name
        self.type_str = type_str
        self.annotation = annotation
        self.required = required
        self.default = default
        self.help_text = help_text
        self.choices = choices
        self.enum_class = enum_class


# --- Hypothesis strategies for generating field specifications ---


# Valid Python identifiers for field names (simple, lowercase, no clashes)
_field_name_strategy = st.from_regex(r"[a-z][a-z0-9]{0,9}", fullmatch=True)

# Help text strategy
_help_text_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Z")),
    min_size=0,
    max_size=50,
)


@st.composite
def str_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate a str-typed field specification."""
    name = draw(_field_name_strategy)
    required = draw(st.booleans())
    help_text = draw(_help_text_strategy)

    default = ... if required else draw(st.text(min_size=0, max_size=20))

    return FieldSpec(
        name=name,
        type_str="str",
        annotation=str,
        required=required,
        default=default,
        help_text=help_text,
        choices=None,
    )


@st.composite
def int_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate an int-typed field specification."""
    name = draw(_field_name_strategy)
    required = draw(st.booleans())
    help_text = draw(_help_text_strategy)

    default = ... if required else draw(st.integers(min_value=-1000, max_value=1000))

    return FieldSpec(
        name=name,
        type_str="int",
        annotation=int,
        required=required,
        default=default,
        help_text=help_text,
        choices=None,
    )


@st.composite
def float_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate a float-typed field specification."""
    name = draw(_field_name_strategy)
    required = draw(st.booleans())
    help_text = draw(_help_text_strategy)

    if required:
        default = ...
    else:
        default = draw(
            st.floats(
                min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
            )
        )

    return FieldSpec(
        name=name,
        type_str="float",
        annotation=float,
        required=required,
        default=default,
        help_text=help_text,
        choices=None,
    )


@st.composite
def bool_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate a bool-typed field specification."""
    name = draw(_field_name_strategy)
    required = draw(st.booleans())
    help_text = draw(_help_text_strategy)

    default = ... if required else draw(st.booleans())

    return FieldSpec(
        name=name,
        type_str="bool",
        annotation=bool,
        required=required,
        default=default,
        help_text=help_text,
        choices=None,
    )


# Counter for unique enum class names (avoids class name collisions)
_enum_counter = 0


@st.composite
def enum_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate an enum-typed field specification."""
    global _enum_counter
    _enum_counter += 1

    name = draw(_field_name_strategy)
    required = draw(st.booleans())
    help_text = draw(_help_text_strategy)

    # Generate enum members (at least 1 member, unique non-empty strings)
    members = draw(
        st.lists(
            st.from_regex(r"[a-z][a-z0-9]{0,9}", fullmatch=True),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    enum_class = _make_enum(f"DynEnum{_enum_counter}", members)
    choices = [str(m.value) for m in enum_class]

    default = ... if required else draw(st.sampled_from(list(enum_class)))

    return FieldSpec(
        name=name,
        type_str="enum",
        annotation=enum_class,
        required=required,
        default=default,
        help_text=help_text,
        choices=choices,
        enum_class=enum_class,
    )


@st.composite
def list_str_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate a list[str]-typed field specification."""
    name = draw(_field_name_strategy)
    required = draw(st.booleans())
    help_text = draw(_help_text_strategy)

    if required:
        default = ...
    else:
        # list fields with defaults use default_factory, which extracts as None
        default = ...  # Will use default_factory=list
        required = False

    return FieldSpec(
        name=name,
        type_str="list[str]",
        annotation=list[str],
        required=required,
        default=default,
        help_text=help_text,
        choices=None,
    )


@st.composite
def optional_str_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate an Optional[str] field specification (always optional)."""
    name = draw(_field_name_strategy)
    help_text = draw(_help_text_strategy)

    return FieldSpec(
        name=name,
        type_str="str",
        annotation=str | None,
        required=False,
        default=None,
        help_text=help_text,
        choices=None,
    )


@st.composite
def optional_int_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate an Optional[int] field specification (always optional)."""
    name = draw(_field_name_strategy)
    help_text = draw(_help_text_strategy)

    return FieldSpec(
        name=name,
        type_str="int",
        annotation=int | None,
        required=False,
        default=None,
        help_text=help_text,
        choices=None,
    )


@st.composite
def optional_enum_field_spec(draw: st.DrawFn) -> FieldSpec:
    """Generate an Optional[Enum] field specification (always optional)."""
    global _enum_counter
    _enum_counter += 1

    name = draw(_field_name_strategy)
    help_text = draw(_help_text_strategy)

    members = draw(
        st.lists(
            st.from_regex(r"[a-z][a-z0-9]{0,9}", fullmatch=True),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    enum_class = _make_enum(f"DynOptEnum{_enum_counter}", members)
    choices = [str(m.value) for m in enum_class]

    return FieldSpec(
        name=name,
        type_str="enum",
        annotation=enum_class | None,
        required=False,
        default=None,
        help_text=help_text,
        choices=choices,
        enum_class=enum_class,
    )


# Combined strategy for any supported field type
any_field_spec = st.one_of(
    str_field_spec(),
    int_field_spec(),
    float_field_spec(),
    bool_field_spec(),
    enum_field_spec(),
    list_str_field_spec(),
    optional_str_field_spec(),
    optional_int_field_spec(),
    optional_enum_field_spec(),
)


@st.composite
def model_field_specs(draw: st.DrawFn) -> list[FieldSpec]:
    """Generate a list of field specifications with unique names.

    Each spec represents a field to be added to a dynamically-created
    Pydantic BaseModel.
    """
    # Generate 1-6 field specs
    specs = draw(st.lists(any_field_spec, min_size=1, max_size=6))

    # Ensure unique field names by deduplicating
    seen_names: set[str] = set()
    unique_specs: list[FieldSpec] = []
    for spec in specs:
        if spec.name not in seen_names:
            seen_names.add(spec.name)
            unique_specs.append(spec)

    # Must have at least one field
    if not unique_specs:
        # Fallback: draw a single field spec
        fallback = draw(str_field_spec())
        unique_specs = [fallback]

    return unique_specs


# --- Dynamic Pydantic model creation ---

# Counter for unique model class names
_model_counter = 0


def _build_dynamic_model(specs: list[FieldSpec]) -> type[BaseModel]:
    """Build a dynamic Pydantic BaseModel from field specifications.

    Uses pydantic's create_model equivalent via type() + __annotations__.
    """
    global _model_counter
    _model_counter += 1

    # Build field definitions for Pydantic
    # Using the (annotation, FieldInfo) pattern for dynamic model creation
    from pydantic import create_model

    field_definitions: dict[str, Any] = {}

    for spec in specs:
        if spec.default is ...:
            if spec.type_str == "list[str]" and not spec.required:
                # list fields with default use default_factory
                field_definitions[spec.name] = (
                    spec.annotation,
                    Field(default_factory=list, description=spec.help_text),
                )
            else:
                # Required field (no default)
                field_definitions[spec.name] = (
                    spec.annotation,
                    Field(description=spec.help_text),
                )
        else:
            # Has a concrete default value
            field_definitions[spec.name] = (
                spec.annotation,
                Field(default=spec.default, description=spec.help_text),
            )

    model = create_model(
        f"DynamicModel{_model_counter}",
        **field_definitions,
    )

    return model


# --- Property test ---


# Feature: layered-architecture-lazy-boot, Property 16: Schema extraction correctness
class TestSchemaExtractionCorrectness:
    """Property 16: Schema extraction correctness.

    For any Pydantic BaseModel subclass with fields of supported types
    (str, int, bool, float, Enum subclasses, list[str], Optional variants),
    the schema extractor SHALL produce a list[FieldDescriptor] where each
    field's name, type, choices, default, required, and help correctly
    reflect the model's field definitions.

    **Validates: Requirements 16.2, 16.3, 16.4, 16.6**
    """

    @given(specs=model_field_specs())
    @settings(max_examples=100)
    def test_schema_extraction_produces_correct_field_descriptors(
        self, specs: list[FieldSpec]
    ):
        """Extracted FieldDescriptors correctly reflect model field definitions.

        # Feature: layered-architecture-lazy-boot, Property 16: Schema extraction correctness
        **Validates: Requirements 16.2, 16.3, 16.4, 16.6**
        """
        # Build the dynamic Pydantic model from specs
        model_class = _build_dynamic_model(specs)

        # Extract field descriptors
        result = extract_field_descriptors(model_class)

        # The number of extracted fields should match the number of specs
        assert len(result) == len(specs), (
            f"Expected {len(specs)} fields, got {len(result)}"
        )

        # Build a lookup by name for easy comparison
        result_by_name: dict[str, FieldDescriptor] = {f.name: f for f in result}

        for spec in specs:
            assert spec.name in result_by_name, (
                f"Field '{spec.name}' not found in extracted descriptors"
            )
            descriptor = result_by_name[spec.name]

            # Verify name
            assert descriptor.name == spec.name

            # Verify type mapping
            assert descriptor.type_annotation == spec.type_str, (
                f"Field '{spec.name}': expected type '{spec.type_str}', "
                f"got '{descriptor.type_annotation}'"
            )

            # Verify choices
            if spec.type_str == "enum":
                assert descriptor.choices is not None, (
                    f"Field '{spec.name}': enum field should have non-None choices"
                )
                assert len(descriptor.choices) > 0, (
                    f"Field '{spec.name}': enum field should have non-empty choices"
                )
                assert descriptor.choices == spec.choices, (
                    f"Field '{spec.name}': expected choices {spec.choices}, "
                    f"got {descriptor.choices}"
                )
            else:
                assert descriptor.choices is None, (
                    f"Field '{spec.name}': non-enum field should have None choices, "
                    f"got {descriptor.choices}"
                )

            # Verify required
            assert descriptor.required == spec.required, (
                f"Field '{spec.name}': expected required={spec.required}, "
                f"got required={descriptor.required}"
            )

            # Verify help text
            assert descriptor.description == spec.help_text, (
                f"Field '{spec.name}': expected help='{spec.help_text}', "
                f"got help='{descriptor.description}'"
            )

            # Verify default
            if spec.required:
                # Required fields: extract_field_descriptors returns None for default
                assert descriptor.default is None, (
                    f"Field '{spec.name}': required field should have None default, "
                    f"got {descriptor.default}"
                )
            elif spec.type_str == "list[str]" and spec.default is ...:
                # list fields with default_factory return None from extractor
                assert descriptor.default is None, (
                    f"Field '{spec.name}': list field with default_factory "
                    f"should have None default, got {descriptor.default}"
                )
            elif spec.default is None:
                # Optional fields with None default
                assert descriptor.default is None, (
                    f"Field '{spec.name}': expected default=None, "
                    f"got {descriptor.default}"
                )
            elif isinstance(spec.default, enum.Enum):
                # Enum defaults are returned as the enum instance
                assert descriptor.default == spec.default, (
                    f"Field '{spec.name}': expected enum default={spec.default}, "
                    f"got {descriptor.default}"
                )
            else:
                # Scalar defaults (str, int, float, bool)
                assert descriptor.default == spec.default, (
                    f"Field '{spec.name}': expected default={spec.default!r}, "
                    f"got {descriptor.default!r}"
                )

    @given(specs=model_field_specs())
    @settings(max_examples=100)
    def test_extracted_types_are_in_supported_set(self, specs: list[FieldSpec]):
        """All extracted type strings are in the set of supported types.

        # Feature: layered-architecture-lazy-boot, Property 16: Schema extraction correctness
        **Validates: Requirements 16.2**
        """
        model_class = _build_dynamic_model(specs)
        result = extract_field_descriptors(model_class)

        for descriptor in result:
            assert descriptor.type_annotation in SUPPORTED_TYPES, (
                f"Field '{descriptor.name}': type '{descriptor.type_annotation}' "
                f"not in supported types {SUPPORTED_TYPES}"
            )

    @given(specs=model_field_specs())
    @settings(max_examples=100)
    def test_enum_choices_invariant_holds(self, specs: list[FieldSpec]):
        """Enum/choices invariant: enum → non-empty choices, non-enum → None choices.

        # Feature: layered-architecture-lazy-boot, Property 16: Schema extraction correctness
        **Validates: Requirements 16.3**
        """
        model_class = _build_dynamic_model(specs)
        result = extract_field_descriptors(model_class)

        for descriptor in result:
            if descriptor.type_annotation == "enum":
                assert descriptor.choices is not None
                assert len(descriptor.choices) > 0
                assert all(isinstance(c, str) for c in descriptor.choices)
            else:
                assert descriptor.choices is None

    @given(specs=model_field_specs())
    @settings(max_examples=100)
    def test_optional_unwrapping_preserves_inner_type(self, specs: list[FieldSpec]):
        """Optional[T] and T | None annotations unwrap to inner type T.

        # Feature: layered-architecture-lazy-boot, Property 16: Schema extraction correctness
        **Validates: Requirements 16.6**
        """
        model_class = _build_dynamic_model(specs)
        result = extract_field_descriptors(model_class)
        result_by_name = {f.name: f for f in result}

        for spec in specs:
            descriptor = result_by_name[spec.name]
            # The type should match the expected type_str regardless of
            # whether the annotation was Optional[T] or T
            assert descriptor.type_annotation == spec.type_str, (
                f"Field '{spec.name}': Optional unwrapping should yield "
                f"type '{spec.type_str}', got '{descriptor.type_annotation}'"
            )
