"""Unit tests for building job commands with Arg markers.

# Feature: cli-unix-compatibility, Task 4.5

Tests that the click-native builder registers Arg()-marked parameters as
positional click Arguments and non-Arg CLI params as named options.

Requirements: 3.1, 3.3, 3.6
"""

from __future__ import annotations

from typing import get_origin
from unittest.mock import MagicMock

import click
from click.testing import CliRunner

from functualize.app.adapters.click_params import (
    build_click_params,
    create_job_click_command,
)
from tests.cli._arg_marker_subjects import (
    mixed_positional_and_options,
    multi_positional,
    positional_with_default,
    required_positional_no_default,
    single_positional,
    variadic_positional,
)

runner = CliRunner()


def _command(name, fn, app=None):
    return create_job_click_command(name, fn, app=app)


def _params(fn):
    return {p.name: p for p in build_click_params(fn, None)[0]}


def _make_app_mock():
    """Create a minimal FunctualizeApp mock with a real execution engine."""
    from functualize._engine.executor import JobExecutionEngine
    from functualize._engine.middleware import ExecutionMiddlewareChain
    from functualize._events.bus import EventBus
    from functualize._events.hooks import HookRegistry
    from functualize._primitives.di import DIRegistry

    app_mock = MagicMock()
    app_mock._di_registry = DIRegistry()
    app_mock.event_bus = EventBus()
    app_mock.plugin_config_registry = MagicMock()
    app_mock.plugin_config_registry.get_all.return_value = {}

    engine = JobExecutionEngine(
        di_registry=app_mock._di_registry,
        event_bus=app_mock.event_bus,
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
    )
    app_mock._execution_engine = engine
    app_mock.execution_engine = engine
    return app_mock


class TestSinglePositionalArg:
    """Arg()-marked parameter becomes a positional click Argument.

    **Validates: Requirement 3.1**
    """

    def test_param_is_click_argument(self):
        param = _params(single_positional)["target"]
        assert isinstance(param, click.Argument)

    def test_param_type_is_base_type(self):
        assert repr(_params(single_positional)["target"].type) == "STRING"

    def test_cli_invocation_single_positional(self):
        cmd = _command("deploy", single_positional, app=_make_app_mock())
        result = runner.invoke(cmd, ["production"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


class TestMultiplePositionalArgs:
    """Multiple Arg()-marked params are registered in signature order.

    **Validates: Requirements 3.1, 3.3**
    """

    def test_order_preserved(self):
        names = [p.name for p in build_click_params(multi_positional, None)[0]]
        assert names == ["env", "region"]

    def test_both_are_arguments(self):
        params = _params(multi_positional)
        for name in ("env", "region"):
            assert isinstance(params[name], click.Argument), (
                f"Parameter '{name}' should be a click Argument"
            )

    def test_cli_invocation_multiple_positional(self):
        cmd = _command("deploy", multi_positional, app=_make_app_mock())
        result = runner.invoke(cmd, ["staging", "us-west-2"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


class TestVariadicPositionalArg:
    """Annotated[list[str], Arg()] becomes a variadic positional.

    **Validates: Requirement 3.3**
    """

    def test_param_is_argument(self):
        assert isinstance(_params(variadic_positional)["files"], click.Argument)

    def test_variadic_nargs(self):
        param = _params(variadic_positional)["files"]
        assert param.nargs == -1

    def test_cli_invocation_variadic(self):
        cmd = _command("process", variadic_positional, app=_make_app_mock())
        result = runner.invoke(cmd, ["file1.txt", "file2.txt", "file3.txt"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


class TestMixedPositionalAndOptions:
    """Arg()-marked params become positional; others remain named options.

    **Validates: Requirements 3.1, 3.3**
    """

    def test_positional_is_argument_and_others_are_options(self):
        params = _params(mixed_positional_and_options)
        assert isinstance(params["target"], click.Argument)
        assert isinstance(params["replicas"], click.Option)
        assert isinstance(params["verbose"], click.Option)

    def test_cli_invocation_mixed(self):
        cmd = _command("deploy", mixed_positional_and_options, app=_make_app_mock())
        result = runner.invoke(cmd, ["prod", "--replicas", "5", "--verbose"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_cli_positional_only(self):
        cmd = _command("deploy", mixed_positional_and_options, app=_make_app_mock())
        result = runner.invoke(cmd, ["staging"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


class TestMissingRequiredPositional:
    """Required positional arg (no default) produces CLI error when omitted.

    **Validates: Requirement 3.6**
    """

    def test_missing_required_positional_exits_with_error(self):
        cmd = _command("greet", required_positional_no_default, app=_make_app_mock())
        result = runner.invoke(cmd, [])
        assert result.exit_code != 0, "Should fail when required positional is missing"

    def test_error_message_mentions_argument(self):
        cmd = _command("greet", required_positional_no_default, app=_make_app_mock())
        result = runner.invoke(cmd, [])
        assert "missing" in result.output.lower() or "required" in result.output.lower()

    def test_positional_with_default_not_required(self):
        cmd = _command("deploy_env", positional_with_default, app=_make_app_mock())
        result = runner.invoke(cmd, [])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


def test_variadic_annotation_inner_type_is_list_origin():
    """Sanity: the subject really declares a list positional."""
    import inspect

    sig = inspect.signature(variadic_positional)
    ann = sig.parameters["files"].annotation
    # Annotated[list[str], Arg()] — unwrap to the list origin.
    from functualize._cli.annotation_utils import parse_annotation

    assert get_origin(parse_annotation(ann).base_type) is list
