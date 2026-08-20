"""Property-based tests for FieldDescriptor extraction from job functions (Property 3).

# Feature: codebase-restructure, Property 3: FieldDescriptor extraction from job functions

**Validates: Requirements 8.1**
"""

# NOTE: We intentionally do NOT use `from __future__ import annotations` here
# because it turns all annotations into strings, which defeats testing the
# runtime type inspection behavior of extract_parameters_from_signature.

import enum
import inspect
from pathlib import Path
from typing import Any, get_args, get_origin

from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.providers import extract_parameters_from_signature
from functualize._types import FieldDescriptor

# =============================================================================
# Type definitions for testing
# =============================================================================


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Priority(enum.Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class Status(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


# All available enum types for generation
_ENUM_TYPES = [Color, Priority, Status]

# Basic scalar types for annotation generation
_SCALAR_TYPES = [str, int, float, bool, Path]

# List element types
_LIST_ELEMENT_TYPES = [str, int, float, Path]

# =============================================================================
# Strategies for generating function parameters
# =============================================================================

# Python reserved keywords that cannot be used as parameter names
_PYTHON_KEYWORDS = frozenset(
    {
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    }
)

# Strategy: valid Python identifier names (for parameter names)
_param_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda n: (
        n not in ("self", "cls")
        and not n.startswith("__")
        and n not in _PYTHON_KEYWORDS
    )
)


# Strategy: type annotations
# We represent each annotation as (annotation_type, annotation_obj) tuples
@st.composite
def _annotation_strategy(draw):
    """Generate a random type annotation from the supported set."""
    choice = draw(st.sampled_from(["scalar", "list", "bool", "enum", "none"]))
    if choice == "scalar":
        return draw(st.sampled_from(_SCALAR_TYPES))
    elif choice == "list":
        element_type = draw(st.sampled_from(_LIST_ELEMENT_TYPES))
        return list[element_type]
    elif choice == "bool":
        return bool
    elif choice == "enum":
        return draw(st.sampled_from(_ENUM_TYPES))
    else:  # "none" means no annotation
        return inspect.Parameter.empty


# Strategy: default values matching a given annotation
@st.composite
def _default_for_annotation(draw, annotation):
    """Generate an appropriate default value for a given annotation, or no default."""
    has_default = draw(st.booleans())
    if not has_default:
        return inspect.Parameter.empty

    # Generate a value consistent with the type
    if annotation is inspect.Parameter.empty or annotation is str:
        return draw(st.text(min_size=0, max_size=20))
    elif annotation is int:
        return draw(st.integers(min_value=-1000, max_value=1000))
    elif annotation is float:
        return draw(
            st.floats(
                allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6
            )
        )
    elif annotation is bool:
        return draw(st.booleans())
    elif annotation is Path:
        return Path(
            draw(st.text(min_size=1, max_size=20).filter(lambda s: "\x00" not in s))
        )
    elif isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        members = list(annotation)
        return draw(st.sampled_from(members))
    elif get_origin(annotation) is list:
        # For list types, generate a small list of the element type
        args = get_args(annotation)
        elem_type = args[0] if args else str
        if elem_type is str:
            return draw(
                st.lists(st.text(min_size=0, max_size=10), min_size=0, max_size=3)
            )
        elif elem_type is int:
            return draw(
                st.lists(
                    st.integers(min_value=-100, max_value=100), min_size=0, max_size=3
                )
            )
        elif elem_type is float:
            return draw(
                st.lists(
                    st.floats(
                        allow_nan=False,
                        allow_infinity=False,
                        min_value=-100,
                        max_value=100,
                    ),
                    min_size=0,
                    max_size=3,
                )
            )
        elif elem_type is Path:
            return draw(
                st.lists(
                    st.text(min_size=1, max_size=10)
                    .filter(lambda s: "\x00" not in s)
                    .map(Path),
                    min_size=0,
                    max_size=3,
                )
            )
        return draw(st.lists(st.text(min_size=0, max_size=10), min_size=0, max_size=3))
    else:
        return draw(st.text(min_size=0, max_size=20))


# Strategy: a single parameter spec (name, annotation, default)
@st.composite
def _param_spec_strategy(draw):
    """Generate a single parameter specification: (name, annotation, default)."""
    name = draw(_param_name_strategy)
    annotation = draw(_annotation_strategy())
    default = draw(_default_for_annotation(annotation))
    return (name, annotation, default)


# Strategy: a list of parameter specs (with unique names)
@st.composite
def _params_list_strategy(draw):
    """Generate a list of parameter specs with unique names.

    Required params come before optional params to match Python syntax.
    """
    num_params = draw(st.integers(min_value=0, max_value=6))
    params = []
    used_names = set()

    for _ in range(num_params):
        name, annotation, default = draw(_param_spec_strategy())
        # Ensure unique names
        attempt = 0
        while name in used_names and attempt < 10:
            name = draw(_param_name_strategy)
            attempt += 1
        if name in used_names:
            continue
        used_names.add(name)
        params.append((name, annotation, default))

    # Sort: required params first, optional params after (Python syntax requirement)
    required = [(n, a, d) for n, a, d in params if d is inspect.Parameter.empty]
    optional = [(n, a, d) for n, a, d in params if d is not inspect.Parameter.empty]
    return required + optional


# =============================================================================
# Helper: dynamically create a function from parameter specs
# =============================================================================


def _make_function(param_specs: list[tuple[str, Any, Any]]) -> callable:
    """Create a real Python function with the specified parameter signature.

    Args:
        param_specs: List of (name, annotation, default) tuples.

    Returns:
        A callable with the specified signature.
    """
    params = []
    for name, annotation, default in param_specs:
        kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
        param = inspect.Parameter(
            name,
            kind=kind,
            default=default,
            annotation=annotation,
        )
        params.append(param)

    sig = inspect.Signature(params)

    # Create a function dynamically and attach the signature
    def generated_func(*args, **kwargs):
        pass

    generated_func.__signature__ = sig
    generated_func.__name__ = "generated_job"
    generated_func.__qualname__ = "generated_job"

    return generated_func


# =============================================================================
# Helper: compute expected type string for an annotation
# =============================================================================


def _expected_type_str(annotation: Any) -> str:
    """Compute the expected type_annotation string for a given annotation.

    Mirrors the logic of _annotation_to_type_str in providers.py.
    """
    if annotation is inspect.Parameter.empty:
        return "str"

    # Handle generic types like list[str]
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        if origin is list:
            if args:
                inner = _expected_type_str(args[0])
                return f"list[{inner}]"
            return "list"
        if origin is dict:
            if len(args) == 2:
                k = _expected_type_str(args[0])
                v = _expected_type_str(args[1])
                return f"dict[{k}, {v}]"
            return "dict"
        return str(annotation)

    # Handle types with __name__
    type_name = getattr(annotation, "__name__", None)
    if type_name:
        return type_name

    return str(annotation)


# =============================================================================
# Property 3: FieldDescriptor extraction from job functions
# =============================================================================


class TestFieldDescriptorExtractionProperty:
    """Property 3: FieldDescriptor extraction from job functions.

    For any Python function with type-annotated parameters (including
    combinations of required params, optional params with defaults, list[T]
    types, bool flags, and Enum choices), the resulting JobDescriptor.parameters
    SHALL contain a FieldDescriptor for each parameter with: correct name,
    type_annotation matching the annotation string, required=True iff no default
    exists, correct default value, and choices populated for Enum types.

    **Validates: Requirements 8.1**
    """

    @given(param_specs=_params_list_strategy())
    def test_correct_number_of_field_descriptors(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """extract_parameters_from_signature returns one FieldDescriptor per parameter.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        assert len(result) == len(param_specs)
        for fd in result:
            assert isinstance(fd, FieldDescriptor)

    @given(param_specs=_params_list_strategy())
    def test_correct_parameter_names(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """Each FieldDescriptor.name matches the corresponding parameter name.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        for i, (name, _, _) in enumerate(param_specs):
            assert result[i].name == name

    @given(param_specs=_params_list_strategy())
    def test_correct_type_annotations(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """Each FieldDescriptor.type_annotation matches the expected string for the annotation.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        for i, (_, annotation, _) in enumerate(param_specs):
            expected = _expected_type_str(annotation)
            assert result[i].type_annotation == expected, (
                f"Parameter '{param_specs[i][0]}': "
                f"expected type_annotation='{expected}', got '{result[i].type_annotation}'"
            )

    @given(param_specs=_params_list_strategy())
    def test_required_iff_no_default(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """FieldDescriptor.required is True iff the parameter has no default value.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        for i, (name, _, default) in enumerate(param_specs):
            has_default = default is not inspect.Parameter.empty
            expected_required = not has_default
            assert result[i].required == expected_required, (
                f"Parameter '{name}': "
                f"expected required={expected_required}, got required={result[i].required}"
            )

    @given(param_specs=_params_list_strategy())
    def test_correct_default_values(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """FieldDescriptor.default is the parameter default when present, else None.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        for i, (name, _, default) in enumerate(param_specs):
            if default is inspect.Parameter.empty:
                assert result[i].default is None, (
                    f"Parameter '{name}': expected default=None for required param, "
                    f"got default={result[i].default!r}"
                )
            else:
                assert result[i].default == default, (
                    f"Parameter '{name}': "
                    f"expected default={default!r}, got default={result[i].default!r}"
                )

    @given(param_specs=_params_list_strategy())
    def test_choices_populated_for_enum_types(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """FieldDescriptor.choices is populated with member names for Enum types, None otherwise.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        for i, (name, annotation, _) in enumerate(param_specs):
            if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
                expected_choices = [m.name for m in annotation]
                assert result[i].choices == expected_choices, (
                    f"Parameter '{name}': "
                    f"expected choices={expected_choices}, got choices={result[i].choices}"
                )
            else:
                assert result[i].choices is None, (
                    f"Parameter '{name}': "
                    f"expected choices=None for non-Enum type, got choices={result[i].choices}"
                )

    @given(param_specs=_params_list_strategy())
    def test_all_properties_hold_simultaneously(
        self, param_specs: list[tuple[str, Any, Any]]
    ) -> None:
        """All FieldDescriptor properties hold together for any generated function signature.

        This is the combined property test that verifies name, type_annotation,
        required, default, and choices all in one pass.

        **Validates: Requirements 8.1**
        """
        func = _make_function(param_specs)
        result = extract_parameters_from_signature(func)

        assert len(result) == len(param_specs)

        for i, (name, annotation, default) in enumerate(param_specs):
            fd = result[i]

            # Correct name
            assert fd.name == name

            # Correct type_annotation
            expected_type = _expected_type_str(annotation)
            assert fd.type_annotation == expected_type

            # Correct required
            has_default = default is not inspect.Parameter.empty
            assert fd.required == (not has_default)

            # Correct default
            if default is inspect.Parameter.empty:
                assert fd.default is None
            else:
                assert fd.default == default

            # Correct choices
            if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
                assert fd.choices == [m.name for m in annotation]
            else:
                assert fd.choices is None
