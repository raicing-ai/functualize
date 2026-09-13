"""Unit tests for extract_parameters_from_signature in _discovery/providers.

Tests cover:
- Basic typed parameters (str, int, float, bool)
- Parameters without annotations (default to "str")
- Default values and required detection
- Enum types with choices extraction
- RunContext and JobConfigView exclusion
- Generic types (list[str], dict[str, int])
- Optional types (T | None)
- self/cls exclusion
- Functions with no parameters
- Functions that raise on inspect.signature
"""

# NOTE: We intentionally do NOT use `from __future__ import annotations` here
# because it turns all annotations into strings, which defeats testing the
# runtime type inspection behavior of extract_parameters_from_signature.

import dataclasses
import enum
from pathlib import Path

import pytest

from functualize._discovery.providers import extract_parameters_from_signature
from functualize._types import FieldDescriptor


class Color(enum.Enum):
    """Test enum for choices extraction."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Priority(enum.IntEnum):
    """Test IntEnum for choices extraction."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


class TestBasicTypedParameters:
    """Test extraction of basic typed parameters."""

    def test_str_parameter(self) -> None:
        def job(name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert len(params) == 1
        assert params[0].name == "name"
        assert params[0].type_annotation == "str"
        assert params[0].required is True
        assert params[0].default is None
        assert params[0].choices is None

    def test_int_parameter(self) -> None:
        def job(count: int) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "int"

    def test_float_parameter(self) -> None:
        def job(rate: float) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "float"

    def test_bool_parameter(self) -> None:
        def job(verbose: bool) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "bool"

    def test_path_parameter(self) -> None:
        def job(output: Path) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "Path"

    def test_multiple_parameters(self) -> None:
        def job(name: str, count: int, verbose: bool = False) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert len(params) == 3
        assert params[0].name == "name"
        assert params[1].name == "count"
        assert params[2].name == "verbose"


class TestUntypedParameters:
    """Test extraction of parameters without type annotations."""

    def test_untyped_parameter_defaults_to_str(self) -> None:
        def job(name) -> None:  # noqa: ANN001
            pass

        params = extract_parameters_from_signature(job)
        assert len(params) == 1
        assert params[0].name == "name"
        assert params[0].type_annotation == "str"
        assert params[0].required is True

    def test_untyped_with_default(self) -> None:
        def job(count=5) -> None:  # noqa: ANN001
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "str"
        assert params[0].required is False
        assert params[0].default == 5

    def test_mixed_typed_and_untyped(self) -> None:
        def job(name: str, count, verbose: bool = False) -> None:  # noqa: ANN001
            pass

        params = extract_parameters_from_signature(job)
        assert len(params) == 3
        assert params[0].type_annotation == "str"
        assert params[1].type_annotation == "str"  # untyped defaults to str
        assert params[2].type_annotation == "bool"


class TestDefaultsAndRequired:
    """Test default value and required flag detection."""

    def test_no_default_is_required(self) -> None:
        def job(name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].required is True
        assert params[0].default is None

    def test_with_default_is_not_required(self) -> None:
        def job(name: str = "world") -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].required is False
        assert params[0].default == "world"

    def test_none_default(self) -> None:
        def job(name: str = None) -> None:  # type: ignore[assignment]
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].required is False
        assert params[0].default is None

    def test_bool_false_default(self) -> None:
        def job(verbose: bool = False) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].required is False
        assert params[0].default is False


class TestEnumChoices:
    """Enum detection, and *which spelling* `choices` holds.

    Member **values**, which is what `FieldDescriptor.choices` is documented to
    hold, what `_discovery/schema_extractor.py` emits for a config model's
    fields, what `_cli/introspect.py` reads them as, and what
    `app/adapters/click_params._EnumChoice` renders on the cold path.

    These cases used to assert member *names*, and that is the more interesting
    half of the story: the divergence was not un-tested, it was **tested in**.
    `_discovery/providers.py` was the only producer emitting names, so an app's
    warm boot offered `{RED|GREEN|BLUE}` while its own first run offered
    `{red|green|blue}` — the same program changing the value it accepted
    between run 1 and run 2. A test that pins one producer's output, rather
    than pinning two producers against each other, cannot see that.

    `test_the_cached_choices_match_what_click_renders` below is the version
    that can.
    """

    def test_enum_type_populates_choices(self) -> None:
        def job(color: Color) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "Color"
        assert params[0].choices == ["red", "green", "blue"]

    def test_int_enum_populates_choices(self) -> None:
        def job(priority: Priority) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "Priority"
        assert params[0].choices == ["1", "2", "3"]

    def test_enum_with_default(self) -> None:
        def job(color: Color = Color.RED) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].required is False
        assert params[0].default == Color.RED
        assert params[0].choices == ["red", "green", "blue"]

    def test_optional_enum_populates_choices(self) -> None:
        def job(color: Color | None = None) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].choices == ["red", "green", "blue"]

    def test_non_enum_has_no_choices(self) -> None:
        def job(name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].choices is None

    def test_the_cached_choices_match_what_click_renders(self) -> None:
        """The assertion the four above could not make on their own.

        Each of them pins *this* producer's output, so all four agreed with
        each other and with nothing else. This one compares the two producers
        that have to agree — the cached spellings and the ones the cold path
        hands to click — which is where the defect actually lived.
        """
        from functualize.app.adapters.click_params import _click_type_for

        def job(color: Color, priority: Priority) -> None:
            pass

        params = extract_parameters_from_signature(job)
        for param, enum_cls in zip(params, (Color, Priority), strict=True):
            click_type, _, _ = _click_type_for(enum_cls)
            assert param.choices == list(click_type.choices)


class TestExcludedParameters:
    """Test that framework-injected parameters are excluded."""

    def test_runcontext_excluded(self) -> None:
        # Create a fake RunContext class with the expected name
        class RunContext:
            pass

        def job(rc: RunContext, name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert len(params) == 1
        assert params[0].name == "name"

    def test_jobconfigview_excluded(self) -> None:
        class JobConfigView:
            pass

        def job(config: JobConfigView, name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert len(params) == 1
        assert params[0].name == "name"

    def test_self_excluded(self) -> None:
        class MyClass:
            def method(self, name: str) -> None:
                pass

        params = extract_parameters_from_signature(MyClass.method)
        assert len(params) == 1
        assert params[0].name == "name"

    def test_cls_excluded(self) -> None:
        class MyClass:
            @classmethod
            def method(cls, name: str) -> None:
                pass

        params = extract_parameters_from_signature(MyClass.method)
        assert len(params) == 1
        assert params[0].name == "name"


class TestGenericTypes:
    """Test extraction of generic types (list, dict, etc.)."""

    def test_list_str(self) -> None:
        def job(tags: list[str]) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "list[str]"

    def test_list_int(self) -> None:
        def job(ids: list[int]) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "list[int]"

    def test_dict_str_int(self) -> None:
        def job(data: dict[str, int]) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "dict[str, int]"


class TestOptionalTypes:
    """Test extraction of Optional/union types."""

    def test_str_or_none(self) -> None:
        def job(name: str | None = None) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "str | None"
        assert params[0].required is False

    def test_int_or_none(self) -> None:
        def job(count: int | None = None) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].type_annotation == "int | None"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_no_parameters(self) -> None:
        def job() -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params == []

    def test_only_runcontext(self) -> None:
        class RunContext:
            pass

        def job(rc: RunContext) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params == []

    def test_builtin_function_returns_empty(self) -> None:
        # Built-in functions may raise on signature inspection
        params = extract_parameters_from_signature(print)
        # print has parameters but they're valid - just verify no crash
        assert isinstance(params, list)

    def test_returns_frozen_fielddescriptors(self) -> None:
        def job(name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert isinstance(params[0], FieldDescriptor)
        # FieldDescriptor is frozen
        with pytest.raises(dataclasses.FrozenInstanceError):
            params[0].name = "other"  # type: ignore[misc]

    def test_description_is_empty_string(self) -> None:
        """Parameters always have empty description (docstring parsing not implemented)."""

        def job(name: str) -> None:
            """A job with a name parameter."""
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].description == ""


class TestCLIMarkers:
    """Extraction captures Arg()/Option()/Stdin() marker metadata."""

    def test_arg_marker_sets_positional(self) -> None:
        from typing import Annotated

        from functualize.job import Arg

        def job(target: Annotated[str, Arg(help="Deploy target")]) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].positional is True
        assert params[0].description == "Deploy target"
        assert params[0].is_stdin is False

    def test_option_marker_sets_short_flag(self) -> None:
        from typing import Annotated

        from functualize.job import Option

        def job(
            target: Annotated[str, Option("-t", "--target", help="Target")],
        ) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].short_flag == "-t"
        assert params[0].description == "Target"

    def test_stdin_marker_with_explicit_flag(self) -> None:
        from typing import Annotated

        from functualize.job import Stdin

        def job(data: Annotated[str, Stdin(flag="--data", help="Piped data")]) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].is_stdin is True
        assert params[0].stdin_flag == "--data"
        assert params[0].description == "Piped data"

    def test_stdin_marker_without_flag_derives_none(self) -> None:
        from typing import Annotated

        from functualize.job import Stdin

        def job(raw_input: Annotated[str, Stdin()]) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].is_stdin is True
        assert params[0].stdin_flag is None

    def test_plain_param_is_not_stdin(self) -> None:
        def job(name: str) -> None:
            pass

        params = extract_parameters_from_signature(job)
        assert params[0].is_stdin is False
        assert params[0].stdin_flag is None
