"""Unit tests for `_is_cli_compatible_type()` rewrite.

# Feature: cli-unix-compatibility, Task 1.4

Tests that the rewritten `_is_cli_compatible_type()` correctly delegates
to `parse_annotation()` and classifies types accurately.

Requirements: 1.2, 1.3, 1.4, 1.7
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from functualize._cli.annotation_utils import parse_annotation


def _is_cli_compatible_type(annotation: object) -> bool:
    """Classify a type's CLI-compatibility via the annotation parser.

    The former ``adapters.cli._is_cli_compatible_type`` was a one-line delegate
    over ``parse_annotation``; it was removed with the typer adapter, so the
    delegate is inlined here (the logic under test is unchanged).
    """
    return parse_annotation(annotation).is_cli_compatible


from functualize.job import (  # noqa: E402
    Invoke,
    JobConfigView,
    JobContext,
    Log,
    Perf,
    Prompt,
    RunContext,
    State,
)

# =============================================================================
# Helpers
# =============================================================================


class Color(enum.Enum):
    """Test enum for Enum subclass tests."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class MyConfig(BaseModel):
    """Test BaseModel subclass for config parameter tests."""

    name: str = "default"
    count: int = 0


class _FakeArg:
    """Placeholder marker simulating Arg() for Annotated metadata tests.

    The real Arg class doesn't exist yet; this simulates arbitrary metadata
    on a DI type to verify DI classification wins regardless.
    """

    pass


# =============================================================================
# Test: Bare CLI-compatible types → True
# =============================================================================


class TestBareCLICompatibleTypes:
    """Bare types (str, int, float, bool, Path) should return True.

    **Validates: Requirements 1.2, 1.7**
    """

    @pytest.mark.parametrize(
        "annotation",
        [str, int, float, bool, Path],
        ids=["str", "int", "float", "bool", "Path"],
    )
    def test_bare_cli_types_are_compatible(self, annotation: type):
        assert _is_cli_compatible_type(annotation) is True


# =============================================================================
# Test: DI types → False
# =============================================================================


class TestDITypes:
    """DI types (RunContext, Log, Invoke, Prompt, Perf, State, etc.) → False.

    **Validates: Requirements 1.3, 1.7**
    """

    @pytest.mark.parametrize(
        "annotation",
        [RunContext, Log, Invoke, Prompt, Perf, State, JobContext, JobConfigView],
        ids=[
            "RunContext",
            "Log",
            "Invoke",
            "Prompt",
            "Perf",
            "State",
            "JobContext",
            "JobConfigView",
        ],
    )
    def test_di_types_are_not_compatible(self, annotation: type):
        assert _is_cli_compatible_type(annotation) is False


# =============================================================================
# Test: Annotated[str, Field(...)] → True
# =============================================================================


class TestAnnotatedWithField:
    """Annotated[T, Field(...)] where T is CLI-compatible → True.

    The rewritten function unwraps Annotated and classifies based on base type.

    **Validates: Requirements 1.2, 1.7**
    """

    def test_annotated_str_with_field(self):
        annotation = Annotated[str, Field(min_length=1)]
        assert _is_cli_compatible_type(annotation) is True

    def test_annotated_int_with_field(self):
        annotation = Annotated[int, Field(ge=0, le=100)]
        assert _is_cli_compatible_type(annotation) is True

    def test_annotated_float_with_field(self):
        annotation = Annotated[float, Field(gt=0.0)]
        assert _is_cli_compatible_type(annotation) is True

    def test_annotated_path_with_field(self):
        annotation = Annotated[Path, Field(description="output path")]
        assert _is_cli_compatible_type(annotation) is True


# =============================================================================
# Test: Annotated[RunContext, Arg()] → False (DI wins)
# =============================================================================


class TestAnnotatedDITypeWithMarker:
    """Annotated[DI_Type, <marker>] → False because DI classification wins.

    Even when a DI type is wrapped in Annotated with arbitrary metadata,
    the function must classify it as non-CLI-compatible.

    **Validates: Requirements 1.3, 1.4**
    """

    def test_annotated_runcontext_with_arg_marker(self):
        annotation = Annotated[RunContext, _FakeArg()]
        assert _is_cli_compatible_type(annotation) is False

    def test_annotated_log_with_metadata(self):
        annotation = Annotated[Log, "some_metadata"]
        assert _is_cli_compatible_type(annotation) is False

    def test_annotated_invoke_with_multiple_metadata(self):
        annotation = Annotated[Invoke, _FakeArg(), "extra"]
        assert _is_cli_compatible_type(annotation) is False


# =============================================================================
# Test: BaseModel subclass → False
# =============================================================================


class TestBaseModelSubclass:
    """BaseModel subclasses are config parameters, not CLI-compatible.

    **Validates: Requirements 1.4**
    """

    def test_basemodel_subclass_is_not_compatible(self):
        assert _is_cli_compatible_type(MyConfig) is False

    def test_annotated_basemodel_is_not_compatible(self):
        annotation = Annotated[MyConfig, Field(description="config")]
        assert _is_cli_compatible_type(annotation) is False


# =============================================================================
# Test: Enum subclass → True
# =============================================================================


class TestEnumSubclass:
    """Enum subclasses are CLI-compatible (Typer handles them natively).

    **Validates: Requirements 1.2, 1.7**
    """

    def test_enum_subclass_is_compatible(self):
        assert _is_cli_compatible_type(Color) is True

    def test_annotated_enum_with_field(self):
        annotation = Annotated[Color, Field(description="pick a color")]
        assert _is_cli_compatible_type(annotation) is True
