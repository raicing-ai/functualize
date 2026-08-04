"""Unit tests for coerce_kwargs utility function.

Tests validate that Pydantic TypeAdapter is used to convert string values
to the Python types indicated by FieldDescriptor.type_annotation, and that
proper ValueError is raised on coercion failure.
"""

from pathlib import Path

import pytest

from functualize._types.descriptors import FieldDescriptor
from functualize.app.utils import coerce_kwargs


def _field(name: str, type_annotation: str, **kwargs) -> FieldDescriptor:
    """Helper to create a FieldDescriptor with minimal boilerplate."""
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=kwargs.get("default"),
        description=kwargs.get("description", ""),
        required=kwargs.get("required", True),
        choices=kwargs.get("choices"),
    )


class TestCoerceKwargsBasicTypes:
    """Test coercion of basic type annotations."""

    def test_str_passthrough(self):
        params = [_field("name", "str")]
        result = coerce_kwargs({"name": "hello"}, params)
        assert result == {"name": "hello"}

    def test_int_coercion(self):
        params = [_field("count", "int")]
        result = coerce_kwargs({"count": "42"}, params)
        assert result == {"count": 42}
        assert isinstance(result["count"], int)

    def test_float_coercion(self):
        params = [_field("rate", "float")]
        result = coerce_kwargs({"rate": "3.14"}, params)
        assert result == {"rate": 3.14}
        assert isinstance(result["rate"], float)

    def test_bool_true_values(self):
        params = [_field("verbose", "bool")]
        for value in ("true", "True", "1", "yes"):
            result = coerce_kwargs({"verbose": value}, params)
            assert result["verbose"] is True, f"Failed for value: {value}"

    def test_bool_false_values(self):
        params = [_field("verbose", "bool")]
        for value in ("false", "False", "0", "no"):
            result = coerce_kwargs({"verbose": value}, params)
            assert result["verbose"] is False, f"Failed for value: {value}"

    def test_path_coercion(self):
        params = [_field("output", "Path")]
        result = coerce_kwargs({"output": "/tmp/test"}, params)
        assert result == {"output": Path("/tmp/test")}
        assert isinstance(result["output"], Path)


class TestCoerceKwargsListTypes:
    """Test coercion of list type annotations."""

    def test_list_str_from_json(self):
        params = [_field("tags", "list[str]")]
        result = coerce_kwargs({"tags": '["a", "b", "c"]'}, params)
        assert result == {"tags": ["a", "b", "c"]}

    def test_list_int_from_json(self):
        params = [_field("ids", "list[int]")]
        result = coerce_kwargs({"ids": "[1, 2, 3]"}, params)
        assert result == {"ids": [1, 2, 3]}


class TestCoerceKwargsMultipleParams:
    """Test coercion with multiple parameters."""

    def test_multiple_different_types(self):
        params = [
            _field("name", "str"),
            _field("count", "int"),
            _field("verbose", "bool"),
        ]
        result = coerce_kwargs(
            {"name": "deploy", "count": "5", "verbose": "true"}, params
        )
        assert result == {"name": "deploy", "count": 5, "verbose": True}

    def test_unknown_keys_passed_through(self):
        params = [_field("name", "str")]
        result = coerce_kwargs({"name": "test", "unknown": "value"}, params)
        assert result == {"name": "test", "unknown": "value"}

    def test_empty_raw_dict(self):
        params = [_field("name", "str")]
        result = coerce_kwargs({}, params)
        assert result == {}


class TestCoerceKwargsErrors:
    """Test that ValueError is raised with correct message format."""

    def test_invalid_int_raises_valueerror(self):
        params = [_field("count", "int")]
        with pytest.raises(ValueError, match="Parameter 'count'"):
            coerce_kwargs({"count": "not_a_number"}, params)

    def test_invalid_int_error_includes_type(self):
        params = [_field("count", "int")]
        with pytest.raises(ValueError, match="cannot convert 'abc' to int"):
            coerce_kwargs({"count": "abc"}, params)

    def test_invalid_float_raises_valueerror(self):
        params = [_field("rate", "float")]
        with pytest.raises(ValueError, match="Parameter 'rate'"):
            coerce_kwargs({"rate": "not_a_float"}, params)

    def test_invalid_float_error_message_format(self):
        params = [_field("rate", "float")]
        with pytest.raises(
            ValueError, match="Parameter 'rate': cannot convert 'xyz' to float"
        ):
            coerce_kwargs({"rate": "xyz"}, params)

    def test_error_message_contains_parameter_name(self):
        params = [_field("my_param", "int")]
        with pytest.raises(ValueError) as exc_info:
            coerce_kwargs({"my_param": "bad"}, params)
        assert "my_param" in str(exc_info.value)

    def test_error_message_contains_expected_type(self):
        params = [_field("port", "int")]
        with pytest.raises(ValueError) as exc_info:
            coerce_kwargs({"port": "not_int"}, params)
        assert "int" in str(exc_info.value)
