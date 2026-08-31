"""Unit tests for the lazy command wrapper construction module.

Post typer-removal, ``make_lazy_command`` returns a ``click.Command`` built from
cached ``FieldDescriptor`` metadata via
``click_params.build_click_params_from_descriptor``. These tests cover:

- Type mapping from ``FieldDescriptor.type_annotation`` to click types
- click parameter reconstruction (names, types, defaults, markers, stdin, variadic)
- Construction does NOT trigger module import
- Import failure at invocation time exits non-zero with error message
- Successful invocation delegates to the execution engine
- Docstring handling and the ``tty: TTY`` capability floor
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner
from pydantic import BaseModel

from functualize._discovery.lazy_wrapper import _detect_config_class
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize.app.adapters.click_params import (
    _resolve_type_string,
    build_click_params_from_descriptor,
)
from functualize.app.adapters.lazy_command import make_lazy_command


# Module-level Pydantic model for _detect_config_class tests
class _TestJobConfig(BaseModel):
    name: str = "test"
    count: int = 0


def _resolve_type_annotation(fd: FieldDescriptor) -> object:
    """Reconstruct the old resolver from the new primitives (enum → Choice)."""
    if fd.type_annotation == "enum" or fd.choices:
        return click.Choice(fd.choices or [])
    return _resolve_type_string(fd.type_annotation)


def _fd(
    name: str = "x",
    type_annotation: str = "str",
    *,
    default: object = None,
    required: bool = True,
    choices: list[str] | None = None,
    positional: bool = False,
    short_flag: str | None = None,
    is_stdin: bool = False,
    stdin_flag: str | None = None,
    description: str = "",
) -> FieldDescriptor:
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        choices=choices,
        default=default,
        required=required,
        description=description,
        positional=positional,
        short_flag=short_flag,
        is_stdin=is_stdin,
        stdin_flag=stdin_flag,
    )


def _ok_result(job_name: str):
    """A successful JobResult, for tests that mock the execution engine.

    The lazy command path routes its result through the same boundary handler
    the eager path uses, so a MagicMock standing in for a JobResult now reads
    as "the job raised" (`result.exception is not None` is true of any mock
    attribute). That routing is deliberate — cold and warm boot must agree on
    exit codes — so these doubles return a real result.
    """
    from functualize._engine.result import JobResult
    from functualize._types.enums import RunStatus

    return JobResult(
        status=RunStatus.SUCCESS,
        return_value=None,
        duration_ms=0.0,
        job_name=job_name,
    )


def _make_descriptor(
    name: str = "test_job",
    module_path: str = "test_module",
    config_fields: list[FieldDescriptor] | None = None,
    docstring: str | None = "Test docstring",
) -> JobDescriptor:
    return JobDescriptor(
        name=name,
        group=None,
        module_path=module_path,
        source_file="/tmp/test.py",
        source_mtime=1.0,
        content_hash="abc123",
        docstring=docstring,
        config_fields=config_fields or [],
        dependencies={},
    )


def _params(desc: JobDescriptor) -> dict[str, click.Parameter]:
    return {p.name: p for p in build_click_params_from_descriptor(desc)}


# --- Type resolution ------------------------------------------------------


class TestResolveTypeAnnotation:
    def test_str_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="str")) is str

    def test_int_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="int")) is int

    def test_bool_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="bool")) is bool

    def test_float_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="float")) is float

    def test_list_str_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="list[str]")) == list[str]

    def test_enum_type(self):
        result = _resolve_type_annotation(
            _fd(type_annotation="enum", choices=["a", "b", "c"])
        )
        assert isinstance(result, click.Choice)
        assert list(result.choices) == ["a", "b", "c"]

    def test_enum_with_empty_choices_fallback(self):
        result = _resolve_type_annotation(_fd(type_annotation="enum", choices=None))
        assert isinstance(result, click.Choice)
        assert list(result.choices) == []

    def test_unknown_type_falls_back_to_str(self):
        assert _resolve_type_annotation(_fd(type_annotation="unknown_type")) is str

    def test_path_type(self):
        from pathlib import Path

        assert _resolve_type_annotation(_fd(type_annotation="Path")) is Path

    def test_list_int_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="list[int]")) == list[int]

    def test_optional_int_type(self):
        assert _resolve_type_annotation(_fd(type_annotation="int | None")) == (
            int | None
        )

    def test_datetime_collapses_to_str(self):
        assert _resolve_type_annotation(_fd(type_annotation="datetime")) is str

    def test_dict_collapses_to_str(self):
        assert _resolve_type_annotation(_fd(type_annotation="dict[str, int]")) is str

    def test_enum_class_name_with_choices_is_choice(self):
        result = _resolve_type_annotation(
            _fd(type_annotation="Color", choices=["RED", "GREEN"])
        )
        assert isinstance(result, click.Choice)
        assert list(result.choices) == ["RED", "GREEN"]


# --- click parameter construction from descriptors ------------------------


class TestBuildClickParamsFromDescriptor:
    def test_empty_fields_produces_no_params(self):
        assert (
            build_click_params_from_descriptor(_make_descriptor(config_fields=[])) == []
        )

    def test_required_plain_field_is_positional_argument(self):
        # A required plain field renders as a positional argument (typer parity).
        params = _params(
            _make_descriptor(config_fields=[_fd("name", "str", required=True)])
        )
        p = params["name"]
        assert isinstance(p, click.Argument)
        assert p.required is True
        assert repr(p.type) == "STRING"

    def test_optional_field_is_option_with_default(self):
        params = _params(
            _make_descriptor(
                config_fields=[_fd("count", "int", default=42, required=False)]
            )
        )
        p = params["count"]
        assert isinstance(p, click.Option)
        assert p.opts == ["--count"]
        assert p.default == 42

    def test_optional_field_with_none_default(self):
        params = _params(
            _make_descriptor(
                config_fields=[_fd("value", "str", default=None, required=False)]
            )
        )
        assert params["value"].default is None

    def test_multiple_fields_preserve_order(self):
        desc = _make_descriptor(
            config_fields=[
                _fd("alpha", "str", required=True),
                _fd("beta", "int", default=10, required=False),
                _fd("gamma", "bool", default=False, required=False),
            ]
        )
        names = [p.name for p in build_click_params_from_descriptor(desc)]
        assert names == ["alpha", "beta", "gamma"]


# --- make_lazy_command ----------------------------------------------------


class TestMakeLazyCommand:
    def test_returns_click_command(self):
        cmd = make_lazy_command(_make_descriptor(), MagicMock())
        assert isinstance(cmd, click.Command)

    def test_construction_does_not_import_module(self):
        desc = _make_descriptor(module_path="nonexistent_module_xyz_12345")
        with patch("functualize._discovery.lazy_wrapper.importlib") as mock_importlib:
            make_lazy_command(desc, MagicMock())
        mock_importlib.import_module.assert_not_called()

    def test_docstring_set_from_descriptor(self):
        cmd = make_lazy_command(
            _make_descriptor(docstring="My custom docstring"), MagicMock()
        )
        assert cmd.help == "My custom docstring"

    def test_none_docstring_becomes_none_help(self):
        cmd = make_lazy_command(_make_descriptor(docstring=None), MagicMock())
        assert cmd.help is None

    def test_params_reflect_config_fields(self):
        desc = _make_descriptor(config_fields=[_fd("arg1", "str", required=True)])
        cmd = make_lazy_command(desc, MagicMock())
        assert "arg1" in {p.name for p in cmd.params}

    def test_command_name_override(self):
        cmd = make_lazy_command(
            _make_descriptor(name="deploy"), MagicMock(), command_name="ship"
        )
        assert cmd.name == "ship"

    def test_invocation_imports_module_and_delegates(self):
        """Standalone-adapter path: not registered → direct import + config detect."""
        desc = _make_descriptor(name="my_func", module_path="my.module")
        app = MagicMock()
        app.execution_engine.materialize_job.side_effect = KeyError("my_func")
        # The lazy path now hands its JobResult to the same boundary handler
        # the eager path uses, so a bare MagicMock result is no longer inert —
        # it reads as "the job raised". That routing is the point (cold and
        # warm must agree on exit codes), so the double becomes a real result.
        app.execution_engine.execute.return_value = _ok_result("my_func")
        mock_module = MagicMock()
        mock_func = MagicMock()
        mock_module.my_func = mock_func

        with patch(
            "functualize._discovery.lazy_wrapper.importlib.import_module",
            return_value=mock_module,
        ):
            cmd = make_lazy_command(desc, app)
            cmd.callback(key="value")  # type: ignore[misc]

        app.execution_engine.execute.assert_called_once()
        call_kwargs = app.execution_engine.execute.call_args
        assert call_kwargs.kwargs["job_name"] == "my_func"
        assert call_kwargs.kwargs["function"] is mock_func
        assert call_kwargs.kwargs["kwargs"] == {"key": "value"}

    def test_invocation_uses_engine_entry_when_registered(self):
        desc = _make_descriptor(name="my_func", module_path="my.module")
        app = MagicMock()
        entry = MagicMock()
        app.execution_engine.materialize_job.return_value = entry
        app.execution_engine.execute.return_value = _ok_result("my_func")

        with patch(
            "functualize._discovery.lazy_wrapper.importlib.import_module",
            side_effect=AssertionError("direct import must not run"),
        ):
            cmd = make_lazy_command(desc, app)
            cmd.callback(key="value")  # type: ignore[misc]

        app.execution_engine.materialize_job.assert_called_once_with("my_func")
        call_kwargs = app.execution_engine.execute.call_args
        assert call_kwargs.kwargs["function"] is entry.function
        assert call_kwargs.kwargs["config_class"] is entry.config_class

    def test_import_failure_prints_error_and_exits(self, capsys):
        desc = _make_descriptor(module_path="bad.module.path")
        app = MagicMock()
        app.execution_engine.materialize_job.side_effect = KeyError("test_job")
        cmd = make_lazy_command(desc, app)

        with (
            patch(
                "functualize._discovery.lazy_wrapper.importlib.import_module",
                side_effect=ModuleNotFoundError("No module named 'bad'"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd.callback()  # type: ignore[misc]

        assert exc_info.value.code == 1
        assert "bad.module.path" in capsys.readouterr().err

    def test_import_failure_on_syntax_error(self, capsys):
        desc = _make_descriptor(module_path="syntax.error.module")
        app = MagicMock()
        app.execution_engine.materialize_job.side_effect = KeyError("test_job")
        cmd = make_lazy_command(desc, app)

        with (
            patch(
                "functualize._discovery.lazy_wrapper.importlib.import_module",
                side_effect=SyntaxError("invalid syntax"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd.callback()  # type: ignore[misc]

        assert exc_info.value.code == 1
        assert "syntax.error.module" in capsys.readouterr().err


# --- _detect_config_class -------------------------------------------------


class TestDetectConfigClass:
    def test_detects_pydantic_model_parameter(self):
        def my_func(config: _TestJobConfig) -> None:
            pass

        assert _detect_config_class(my_func) is _TestJobConfig

    def test_returns_none_when_no_config(self):
        def simple_func(x: int, y: str) -> None:
            pass

        assert _detect_config_class(simple_func) is None

    def test_returns_none_for_base_model_itself(self):
        def func(model: BaseModel) -> None:
            pass

        assert _detect_config_class(func) is None

    def test_returns_none_for_unannotated_params(self):
        def func(x, y, z):
            pass

        assert _detect_config_class(func) is None


# --- Marker / stdin / variadic fidelity via click params ------------------


class TestMarkerFidelity:
    def test_positional_field_becomes_argument(self):
        params = _params(
            _make_descriptor(
                config_fields=[_fd("target", "str", required=True, positional=True)]
            )
        )
        p = params["target"]
        assert isinstance(p, click.Argument)
        assert p.required is True

    def test_positional_fields_ordered_before_options(self):
        desc = _make_descriptor(
            config_fields=[
                _fd("verbose", "bool", default=False, required=False),
                _fd("target", "str", required=True, positional=True),
            ]
        )
        names = [p.name for p in build_click_params_from_descriptor(desc)]
        # The positional argument precedes the option in declaration/list order.
        assert names == ["verbose", "target"]
        params = _params(desc)
        assert isinstance(params["target"], click.Argument)
        assert isinstance(params["verbose"], click.Option)

    def test_short_flag_field_becomes_option_with_both_flags(self):
        params = _params(
            _make_descriptor(
                config_fields=[
                    _fd(
                        "dry_run",
                        "bool",
                        default=False,
                        required=False,
                        short_flag="-d",
                    )
                ]
            )
        )
        p = params["dry_run"]
        assert isinstance(p, click.Option)
        assert p.is_flag is True
        assert p.default is False
        assert "--dry-run" in p.opts
        assert "-d" in p.opts

    def test_plain_option_keeps_default(self):
        params = _params(
            _make_descriptor(
                config_fields=[_fd("env", "str", default="dev", required=False)]
            )
        )
        p = params["env"]
        assert isinstance(p, click.Option)
        assert p.default == "dev"

    def test_short_flag_renders_in_help(self):
        desc = _make_descriptor(
            name="deploy",
            config_fields=[
                _fd(
                    "target",
                    "str",
                    required=True,
                    positional=True,
                    description="Deploy target",
                ),
                _fd("dry_run", "bool", default=False, required=False, short_flag="-d"),
            ],
        )
        cmd = make_lazy_command(desc, MagicMock())
        result = CliRunner().invoke(cmd, ["--help"])
        assert result.exit_code == 0
        assert "TARGET" in result.output
        assert "--dry-run" in result.output
        assert "-d" in result.output


class TestStdinFidelity:
    def test_stdin_field_becomes_optional_option(self):
        params = _params(
            _make_descriptor(
                config_fields=[
                    _fd(
                        "data", "str", required=True, is_stdin=True, stdin_flag="--data"
                    )
                ]
            )
        )
        p = params["data"]
        assert isinstance(p, click.Option)
        assert p.default is None
        assert "--data" in p.opts

    def test_stdin_flag_derived_from_name_when_absent(self):
        params = _params(
            _make_descriptor(
                config_fields=[_fd("raw_input", "str", required=True, is_stdin=True)]
            )
        )
        assert "--raw-input" in params["raw_input"].opts

    def test_explicit_stdin_flag_renders_in_help(self):
        desc = _make_descriptor(
            name="transform",
            config_fields=[
                _fd("payload", "str", required=True, is_stdin=True, stdin_flag="--data")
            ],
        )
        cmd = make_lazy_command(desc, MagicMock())
        result = CliRunner().invoke(cmd, ["--help"])
        assert result.exit_code == 0
        assert "--data" in result.output
        assert "--payload" not in result.output

    def test_stdin_roundtrips_through_serialization(self):
        field = _fd("data", "str", required=True, is_stdin=True, stdin_flag="--data")
        descriptor = _make_descriptor(config_fields=[field])
        restored = JobDescriptor.from_dict(descriptor.to_dict())
        rf = restored.config_fields[0]
        assert rf.is_stdin is True
        assert rf.stdin_flag == "--data"

    def test_legacy_field_dict_defaults_stdin_fields(self):
        legacy = {
            "name": "data",
            "type_annotation": "str",
            "choices": None,
            "default": "__REQUIRED__",
            "required": True,
            "description": "",
            "positional": False,
            "short_flag": None,
        }
        descriptor = _make_descriptor()
        data = descriptor.to_dict()
        data["config_fields"] = [legacy]
        restored = JobDescriptor.from_dict(data)
        rf = restored.config_fields[0]
        assert rf.is_stdin is False
        assert rf.stdin_flag is None


class TestRichTypes:
    def test_path_option_type(self):
        params = _params(
            _make_descriptor(
                config_fields=[
                    _fd("output", "Path", default=None, required=False, short_flag="-o")
                ]
            )
        )
        # click.types.convert_type(pathlib.Path) yields a param type named "Path".
        assert params["output"].type.name == "Path"

    def test_optional_int_option(self):
        params = _params(
            _make_descriptor(
                config_fields=[
                    _fd("retries", "int | None", default=None, required=False)
                ]
            )
        )
        assert repr(params["retries"].type) == "INT"

    def test_variadic_list_int_positional(self):
        params = _params(
            _make_descriptor(
                config_fields=[_fd("ids", "list[int]", required=True, positional=True)]
            )
        )
        p = params["ids"]
        assert isinstance(p, click.Argument)
        assert p.nargs == -1
        assert repr(p.type) == "INT"

    def test_variadic_renders_in_help(self):
        desc = _make_descriptor(
            name="collect",
            config_fields=[_fd("ids", "list[int]", required=True, positional=True)],
        )
        cmd = make_lazy_command(desc, MagicMock())
        result = CliRunner().invoke(cmd, ["--help"])
        assert result.exit_code == 0
        assert "IDS..." in result.output.replace(" ", "")


class TestCapabilityFloorRefusal:
    """A `tty: TTY` job invoked without a terminal is refused pre-flight."""

    def _tty_descriptor(self) -> JobDescriptor:
        import dataclasses

        return dataclasses.replace(_make_descriptor(name="editor"), requires_tty=True)

    def test_refuses_when_no_terminal(self, capsys) -> None:
        cmd = make_lazy_command(self._tty_descriptor(), MagicMock())

        with (
            patch(
                "functualize._engine.capabilities.tty.terminal_available",
                return_value=False,
            ),
            pytest.raises(SystemExit) as exc,
        ):
            cmd.callback()  # type: ignore[misc]

        assert exc.value.code == 1
