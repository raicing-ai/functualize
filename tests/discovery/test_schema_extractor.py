"""Unit tests for functualize.discovery.schema_extractor."""

from __future__ import annotations

from enum import Enum, StrEnum

import pytest
from pydantic import BaseModel, Field

from functualize._discovery.schema_extractor import extract_field_descriptors

# --- Test models ---


class Color(StrEnum):
    red = "red"
    green = "green"
    blue = "blue"


class Priority(int, Enum):
    low = 1
    medium = 2
    high = 3


class LargeEnum(StrEnum):
    """Enum with 7 members to test extraction of 5+ choices."""

    alpha = "alpha"
    beta = "beta"
    gamma = "gamma"
    delta = "delta"
    epsilon = "epsilon"
    zeta = "zeta"
    eta = "eta"


class FullConfig(BaseModel):
    """Config with all supported types."""

    name: str = Field(description="Your name")
    greeting: str = Field(default="Hello", description="Greeting prefix")
    age: int = Field(default=25, description="Your age")
    score: float = Field(default=0.0, description="Score")
    verbose: bool = Field(default=False, description="Verbose output")
    color: Color = Field(default=Color.green, description="Favorite color")
    priority: Priority = Field(default=Priority.medium, description="Priority")
    nickname: str | None = Field(default=None, description="Optional nickname")
    lucky_number: int | None = Field(default=None, description="Optional lucky number")
    tags: list[str] = Field(default_factory=list, description="Tags")
    scores: list[int] = Field(default_factory=list, description="Score list")


class EmptyConfig(BaseModel):
    """Empty model."""

    pass


class RequiredOnlyConfig(BaseModel):
    """All required fields."""

    name: str
    count: int
    flag: bool


class OptionalEnumConfig(BaseModel):
    """Optional enum field."""

    maybe_color: Color | None = Field(default=None, description="Optional color")


class OptionalUnwrapConfig(BaseModel):
    """Model testing Optional[int] and float | None unwrapping."""

    opt_int: int | None = Field(
        default=None, description="Optional int via typing.Optional"
    )
    nullable_float: float | None = Field(default=None, description="Float or none")


class LargeEnumConfig(BaseModel):
    """Model with an Enum that has 7 members."""

    status: LargeEnum = Field(default=LargeEnum.alpha, description="Status")


# --- Tests ---


class TestExtractFieldDescriptors:
    """Tests for extract_field_descriptors()."""

    def test_empty_model(self) -> None:
        fields = extract_field_descriptors(EmptyConfig)
        assert fields == []

    def test_required_fields(self) -> None:
        fields = extract_field_descriptors(RequiredOnlyConfig)
        assert len(fields) == 3
        for f in fields:
            assert f.required is True

    def test_str_type(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.type_annotation == "str"
        assert name_field.required is True
        assert name_field.choices is None
        assert name_field.description == "Your name"

    def test_str_with_default(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        greeting = next(f for f in fields if f.name == "greeting")
        assert greeting.type_annotation == "str"
        assert greeting.required is False
        assert greeting.default == "Hello"
        assert greeting.choices is None

    def test_int_type(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        age = next(f for f in fields if f.name == "age")
        assert age.type_annotation == "int"
        assert age.required is False
        assert age.default == 25
        assert age.choices is None

    def test_float_type(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        score = next(f for f in fields if f.name == "score")
        assert score.type_annotation == "float"
        assert score.required is False
        assert score.default == 0.0
        assert score.choices is None

    def test_bool_type(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        verbose = next(f for f in fields if f.name == "verbose")
        assert verbose.type_annotation == "bool"
        assert verbose.required is False
        assert verbose.default is False
        assert verbose.choices is None

    def test_str_enum_type(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        color = next(f for f in fields if f.name == "color")
        assert color.type_annotation == "enum"
        assert color.choices == ["red", "green", "blue"]
        assert color.default == Color.green
        assert color.required is False

    def test_int_enum_type(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        priority = next(f for f in fields if f.name == "priority")
        assert priority.type_annotation == "enum"
        assert priority.choices == ["1", "2", "3"]
        assert priority.default == Priority.medium
        assert priority.required is False

    def test_optional_str(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        nickname = next(f for f in fields if f.name == "nickname")
        assert nickname.type_annotation == "str"
        assert nickname.required is False
        assert nickname.default is None
        assert nickname.choices is None

    def test_optional_int(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        lucky = next(f for f in fields if f.name == "lucky_number")
        assert lucky.type_annotation == "int"
        assert lucky.required is False
        assert lucky.default is None
        assert lucky.choices is None

    def test_list_str(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        tags = next(f for f in fields if f.name == "tags")
        assert tags.type_annotation == "list[str]"
        assert tags.required is False
        assert tags.default is None  # default_factory → None
        assert tags.choices is None

    def test_list_int_maps_to_list_str(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        scores = next(f for f in fields if f.name == "scores")
        assert scores.type_annotation == "list[str]"
        assert scores.choices is None

    def test_optional_enum(self) -> None:
        fields = extract_field_descriptors(OptionalEnumConfig)
        maybe_color = fields[0]
        assert maybe_color.type_annotation == "enum"
        assert maybe_color.choices == ["red", "green", "blue"]
        assert maybe_color.required is False
        assert maybe_color.default is None

    def test_help_text_from_description(self) -> None:
        fields = extract_field_descriptors(FullConfig)
        age = next(f for f in fields if f.name == "age")
        assert age.description == "Your age"

    def test_help_text_empty_when_no_description(self) -> None:
        fields = extract_field_descriptors(RequiredOnlyConfig)
        name = next(f for f in fields if f.name == "name")
        assert name.description == ""

    def test_field_descriptor_invariant(self) -> None:
        """If type=='enum' then choices is non-empty list[str]; otherwise choices is None."""
        fields = extract_field_descriptors(FullConfig)
        for f in fields:
            if f.type_annotation == "enum":
                assert f.choices is not None
                assert len(f.choices) > 0
                assert all(isinstance(c, str) for c in f.choices)
            else:
                assert f.choices is None

    def test_exception_propagation(self) -> None:
        """model_json_schema() exceptions should propagate to caller."""
        with pytest.raises(AttributeError):
            extract_field_descriptors(int)  # type: ignore

    def test_large_enum_all_choices_extracted(self) -> None:
        """Enum with 7 members should have all 7 choices extracted."""
        fields = extract_field_descriptors(LargeEnumConfig)
        status = fields[0]
        assert status.type_annotation == "enum"
        assert status.choices == [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
        ]
        assert len(status.choices) == 7

    def test_optional_int_typing_syntax(self) -> None:
        """Optional[int] (typing.Optional syntax) should unwrap to type 'int'."""
        fields = extract_field_descriptors(OptionalUnwrapConfig)
        opt_int = next(f for f in fields if f.name == "opt_int")
        assert opt_int.type_annotation == "int"
        assert opt_int.required is False
        assert opt_int.default is None

    def test_float_or_none(self) -> None:
        """float | None should unwrap to type 'float'."""
        fields = extract_field_descriptors(OptionalUnwrapConfig)
        nullable_float = next(f for f in fields if f.name == "nullable_float")
        assert nullable_float.type_annotation == "float"
        assert nullable_float.required is False
        assert nullable_float.default is None


class TestFallbackToStr:
    """Test that unmappable annotations fall back to 'str'."""

    def test_unknown_type_falls_back(self) -> None:
        class WeirdConfig(BaseModel):
            data: dict[str, str] = Field(default_factory=dict, description="Data")

        fields = extract_field_descriptors(WeirdConfig)
        assert fields[0].type_annotation == "str"
        assert fields[0].choices is None
