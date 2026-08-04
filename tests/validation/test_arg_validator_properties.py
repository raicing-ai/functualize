"""Property-based tests for ArgValidator (Properties 4, 5).

Tests the engine-level ArgValidator from functualize._engine.validation:
- Property 4: Validation Idempotence
- Property 5: Field-Only Opt-In

# Feature: cli-unix-compatibility, Task 2.2
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import Field

from functualize._engine.validation import ArgValidator

# =============================================================================
# Strategies
# =============================================================================

# Strategy for valid Python identifiers (parameter names)
_param_names = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Strategy for simple string values
_string_values = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"), blacklist_characters="\x00"
    ),
    min_size=1,
    max_size=30,
)

# Strategy for integer values
_int_values = st.integers(min_value=-1000, max_value=1000)

# Strategy for float values
_float_values = st.floats(
    min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# Strategy for bool values
_bool_values = st.booleans()

# Strategy for kwargs values (types that Pydantic can validate)
_kwargs_values = st.one_of(
    _string_values,
    _int_values,
    _float_values,
    _bool_values,
)


@st.composite
def _valid_kwargs_for_field_fn(draw: st.DrawFn) -> dict[str, Any]:
    """Generate kwargs that are valid for a function with Field-annotated params.

    Generates kwargs matching the signature of _field_function() below:
    - name: str (min_length=1, max_length=50)
    - count: int (ge=0, le=100)
    """
    name = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=50,
        )
    )
    count = draw(st.integers(min_value=0, max_value=100))
    return {"name": name, "count": count}


@st.composite
def _kwargs_dict(draw: st.DrawFn) -> dict[str, Any]:
    """Generate an arbitrary kwargs dict with simple values.

    Uses stable param names to ensure consistent function matching.
    """
    num_params = draw(st.integers(min_value=1, max_value=5))
    # Use a fixed set of param names to avoid collision issues
    available_names = ["alpha", "beta", "gamma", "delta", "epsilon"]
    names = available_names[:num_params]
    kwargs: dict[str, Any] = {}
    for name in names:
        kwargs[name] = draw(_kwargs_values)
    return kwargs


# =============================================================================
# Test Functions (used as subjects for validation)
# =============================================================================


def _field_function(
    name: Annotated[str, Field(min_length=1, max_length=50)],
    count: Annotated[int, Field(ge=0, le=100)],
) -> None:
    """A function with Field()-annotated params for testing validation."""


def _no_field_function(x: str, y: int, z: float) -> None:
    """A function with plain type annotations (no Field metadata)."""


def _bare_function(a, b, c):  # noqa: ANN001
    """A function with no annotations at all."""


def _mixed_function(
    validated: Annotated[str, Field(min_length=1)],
    plain: str,
    number: int,
) -> None:
    """A function with both Field-annotated and plain params."""


def _default_field_function(
    name: Annotated[str, Field(min_length=1, max_length=50)] = "default",
    count: Annotated[int, Field(ge=0, le=100)] = 5,
) -> None:
    """A function with Field-annotated params that have defaults."""


# =============================================================================
# Property 4: Validation Idempotence
# =============================================================================


@pytest.mark.slow
class TestValidationIdempotence:
    """Property 4: Validation Idempotence.

    For any valid kwargs, `validate(fn, validate(fn, k)) == validate(fn, k)`.
    Applying validation twice produces the same result as applying it once.

    **Validates: Requirements 2.2, 2.4**
    """

    @given(kwargs=_valid_kwargs_for_field_fn())
    @settings(max_examples=200)
    def test_double_validate_equals_single_validate(self, kwargs: dict[str, Any]):
        """Validating already-validated kwargs produces the same result.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()

        # First validation
        first_result = validator.validate(_field_function, kwargs)
        # Second validation on the output of the first
        second_result = validator.validate(_field_function, first_result)

        assert first_result == second_result, (
            f"Idempotence violated: first={first_result}, second={second_result}"
        )

    @given(
        name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=50,
        ),
        count=st.integers(min_value=0, max_value=100),
        extra_key=st.sampled_from(["extra", "debug", "verbose", "mode"]),
        extra_val=_kwargs_values,
    )
    @settings(max_examples=200)
    def test_idempotence_with_extra_kwargs(
        self,
        name: str,
        count: int,
        extra_key: str,
        extra_val: Any,
    ):
        """Idempotence holds when kwargs contain keys not in the function signature.

        Extra keys (not Field-annotated) pass through unchanged.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()
        kwargs = {"name": name, "count": count, extra_key: extra_val}

        first_result = validator.validate(_field_function, kwargs)
        second_result = validator.validate(_field_function, first_result)

        assert first_result == second_result, (
            f"Idempotence violated with extra keys: "
            f"first={first_result}, second={second_result}"
        )

    @given(kwargs=_valid_kwargs_for_field_fn())
    @settings(max_examples=200)
    def test_idempotence_with_defaults(self, kwargs: dict[str, Any]):
        """Idempotence holds for functions with default values on Field params.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()

        first_result = validator.validate(_default_field_function, kwargs)
        second_result = validator.validate(_default_field_function, first_result)

        assert first_result == second_result, (
            f"Idempotence violated with defaults: "
            f"first={first_result}, second={second_result}"
        )

    @given(
        validated_val=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=30,
        ),
        plain_val=_string_values,
        number_val=_int_values,
    )
    @settings(max_examples=200)
    def test_idempotence_with_mixed_function(
        self,
        validated_val: str,
        plain_val: str,
        number_val: int,
    ):
        """Idempotence holds for functions with both Field and plain params.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()
        kwargs = {"validated": validated_val, "plain": plain_val, "number": number_val}

        first_result = validator.validate(_mixed_function, kwargs)
        second_result = validator.validate(_mixed_function, first_result)

        assert first_result == second_result, (
            f"Idempotence violated for mixed function: "
            f"first={first_result}, second={second_result}"
        )


# =============================================================================
# Property 5: Field-Only Opt-In
# =============================================================================


@pytest.mark.slow
class TestFieldOnlyOptIn:
    """Property 5: Field-Only Opt-In.

    For any function without Field() metadata, `validate(fn, kwargs)` returns
    kwargs unchanged. Only parameters with explicit Field() annotations are
    validated by ArgValidator.

    **Validates: Requirements 2.2, 2.4**
    """

    @given(kwargs=_kwargs_dict())
    @settings(max_examples=200)
    def test_no_field_returns_kwargs_unchanged(self, kwargs: dict[str, Any]):
        """Functions with plain type annotations pass kwargs through unmodified.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()

        result = validator.validate(_no_field_function, kwargs)

        assert result == kwargs, (
            f"Expected pass-through for no-Field function: input={kwargs}, got={result}"
        )

    @given(kwargs=_kwargs_dict())
    @settings(max_examples=200)
    def test_bare_function_returns_kwargs_unchanged(self, kwargs: dict[str, Any]):
        """Functions with no annotations at all pass kwargs through unmodified.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()

        result = validator.validate(_bare_function, kwargs)

        assert result == kwargs, (
            f"Expected pass-through for bare function: input={kwargs}, got={result}"
        )

    @given(kwargs=_kwargs_dict())
    @settings(max_examples=200)
    def test_result_is_same_object_when_no_field(self, kwargs: dict[str, Any]):
        """When no Field() metadata exists, the returned dict IS the input dict.

        This tests the optimization: no copy is made when validation is skipped.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()

        result = validator.validate(_no_field_function, kwargs)

        assert result is kwargs, (
            "Expected same dict object when no Field metadata (no-copy optimization)"
        )

    @given(kwargs=_kwargs_dict())
    @settings(max_examples=200)
    def test_bare_function_result_is_same_object(self, kwargs: dict[str, Any]):
        """Bare functions (no annotations) return the exact same dict object.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()

        result = validator.validate(_bare_function, kwargs)

        assert result is kwargs, (
            "Expected same dict object for bare function (no-copy optimization)"
        )

    @given(
        plain_val=_string_values,
        number_val=_int_values,
    )
    @settings(max_examples=200)
    def test_non_field_params_pass_through_in_mixed_function(
        self,
        plain_val: str,
        number_val: int,
    ):
        """In a mixed function, non-Field params pass through without modification.

        Only the Field-annotated param is validated; plain params are untouched.

        **Validates: Requirements 2.2, 2.4**
        """
        validator = ArgValidator()
        kwargs = {"validated": "valid_text", "plain": plain_val, "number": number_val}

        result = validator.validate(_mixed_function, kwargs)

        # Non-Field params should be identical
        assert result["plain"] == plain_val, (
            f"Non-Field param 'plain' was modified: "
            f"expected={plain_val}, got={result['plain']}"
        )
        assert result["number"] == number_val, (
            f"Non-Field param 'number' was modified: "
            f"expected={number_val}, got={result['number']}"
        )
