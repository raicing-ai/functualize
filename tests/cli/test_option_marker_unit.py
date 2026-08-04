"""Unit tests for short flag registration via Option marker.

# Feature: cli-unix-compatibility, Task 5.2

Tests that `create_job_command()` properly handles `Option()` markers by
registering short/long flag aliases, deriving long flags from param names,
combining with Field() for validation, and validating short flag format.

Requirements: 4.1, 4.2, 4.3, 4.5
"""

from typing import Annotated
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner
from pydantic import Field

from functualize.app.adapters.click_params import (
    _validate_short_flag,
    create_job_click_command,
)
from functualize.job.markers import Option

runner = CliRunner()


def _command(name, fn, app=None):
    """Build the click command for a job function under test."""
    return create_job_click_command(name, fn, app=app)


def _params(name, fn):
    return {p.name: p for p in _command(name, fn).params}


# =============================================================================
# Helper: Build a minimal app mock for tests that need engine execution
# =============================================================================


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


# =============================================================================
# Test subject functions — defined directly since this file does NOT use
# `from __future__ import annotations`, so Annotated types remain as runtime
# objects (not strings) and create_job_command can parse them.
# =============================================================================


def _deploy_both_flags(target: Annotated[str, Option("-t", "--target")]):
    """Job with both short and long flag specified."""
    return target


def _run_verbose(verbose: Annotated[bool, Option("-v")] = False):
    """Job with short flag only — long flag derived from param name 'verbose'."""
    return verbose


def _run_dry_run(dry_run: Annotated[bool, Option("-d")] = False):
    """Job with underscore param name — derives --dry-run."""
    return dry_run


def _deploy_validated(target: Annotated[str, Option("-t"), Field(min_length=3)]):
    """Job with Option + Field for validation."""
    return target


def _scale_validated(replicas: Annotated[int, Option("-n"), Field(ge=1)]):
    """Job with numeric Option + Field constraint."""
    return replicas


def _deploy_bad_short(target: Annotated[str, Option("-tt")]):
    """Job with invalid flag format — len('-tt') > 2, treated as long flag by Option."""
    return target


def _deploy_digit_short(count: Annotated[int, Option("-1")]):
    """Job with invalid short flag (digit) — len('-1') == 2, assigned as short."""
    return count


def _deploy_dash_only(target: Annotated[str, Option("-")]):
    """Job with invalid flag format — bare dash, treated as long flag by Option."""
    return target


# =============================================================================
# Test: Option("-t", "--target") registers both aliases
# =============================================================================


class TestOptionBothAliases:
    """Option("-t", "--target") should register both the short flag and long flag.

    **Validates: Requirement 4.1**
    """

    def test_param_registers_both_flags(self):
        """The 'target' param should carry both --target and -t."""
        param = _params("deploy", _deploy_both_flags)["target"]
        assert isinstance(param, click.Option)
        assert "--target" in param.opts
        assert "-t" in param.opts

    def test_param_type_is_base_type(self):
        """The 'target' param type should be unwrapped to STRING."""
        param = _params("deploy", _deploy_both_flags)["target"]
        assert repr(param.type) == "STRING"

    def test_short_flag_works_via_cli(self):
        """The short flag -t is accepted by the CLI."""
        cmd = _command("deploy", _deploy_both_flags, app=_make_app_mock())
        result = runner.invoke(cmd, ["-t", "production"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_long_flag_works_via_cli(self):
        """The long flag --target is accepted by the CLI."""
        cmd = _command("deploy", _deploy_both_flags, app=_make_app_mock())
        result = runner.invoke(cmd, ["--target", "staging"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


# =============================================================================
# Test: Option("-v") derives --verbose from param name
# =============================================================================


class TestOptionDerivedLongFlag:
    """Option("-v") without explicit long flag should derive --verbose from param name.

    **Validates: Requirement 4.2**
    """

    def test_short_flag_works(self):
        """The short flag -v is accepted by the CLI."""
        cmd = _command("run", _run_verbose, app=_make_app_mock())
        result = runner.invoke(cmd, ["-v"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_derived_long_flag_works(self):
        """The derived long flag --verbose is accepted by the CLI."""
        cmd = _command("run", _run_verbose, app=_make_app_mock())
        result = runner.invoke(cmd, ["--verbose"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_underscore_param_derives_dashed_long_flag(self):
        """Param 'dry_run' derives long flag --dry-run (underscores → dashes)."""
        cmd = _command("run", _run_dry_run, app=_make_app_mock())
        result = runner.invoke(cmd, ["--dry-run"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_underscore_param_short_flag_also_works(self):
        """Short flag -d for 'dry_run' param also works."""
        cmd = _command("run", _run_dry_run, app=_make_app_mock())
        result = runner.invoke(cmd, ["-d"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"


# =============================================================================
# Test: Option("-t") combined with Field() validates value
# =============================================================================


class TestOptionWithFieldValidation:
    """Option() combined with Field() should pass the value to the engine for validation.

    The CLI adapter passes the value through; the engine's ArgValidator
    enforces the Field constraints (min_length, ge, etc.).

    **Validates: Requirement 4.3**
    """

    def test_valid_string_value_passes(self):
        """A valid string (>= 3 chars) passes through to the engine."""
        cmd = _command("deploy", _deploy_validated, app=_make_app_mock())
        result = runner.invoke(cmd, ["-t", "production"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_short_string_fails_validation(self):
        """A string too short (< 3 chars) fails engine-level validation."""
        cmd = _command("deploy", _deploy_validated, app=_make_app_mock())
        # "ab" is less than min_length=3 — should fail validation in engine
        result = runner.invoke(cmd, ["-t", "ab"])
        assert result.exit_code != 0, "Should fail: 'ab' is shorter than min_length=3"

    def test_valid_int_value_passes(self):
        """A valid int (>= 1) passes through to the engine."""
        cmd = _command("scale", _scale_validated, app=_make_app_mock())
        result = runner.invoke(cmd, ["-n", "5"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_zero_int_fails_validation(self):
        """An int value of 0 fails engine-level validation (ge=1)."""
        cmd = _command("scale", _scale_validated, app=_make_app_mock())
        result = runner.invoke(cmd, ["-n", "0"])
        assert result.exit_code != 0, "Should fail: 0 violates ge=1 constraint"


# =============================================================================
# Test: Short flag format validation (single char only)
# =============================================================================


class TestShortFlagFormatValidation:
    """Short flags must be single dash + exactly one ASCII letter.

    **Validates: Requirement 4.5**
    """

    @pytest.mark.parametrize(
        "flag,expected",
        [
            ("-v", True),
            ("-t", True),
            ("-n", True),
            ("-A", True),
            ("-Z", True),
            ("-a", True),
        ],
        ids=["-v", "-t", "-n", "-A", "-Z", "-a"],
    )
    def test_valid_short_flags(self, flag: str, expected: bool):
        assert _validate_short_flag(flag) is expected

    @pytest.mark.parametrize(
        "flag",
        [
            "-vv",  # More than one char after dash
            "-1",  # Digit, not a letter
            "-",  # Just a dash
            "--long",  # Double dash (long flag format)
            "-ab",  # Multiple chars
            "",  # Empty string
            "v",  # No dash prefix
            "-!",  # Non-alphanumeric
            "- ",  # Space
        ],
        ids=["-vv", "-1", "-", "--long", "-ab", "empty", "no-dash", "-!", "-space"],
    )
    def test_invalid_short_flags(self, flag: str):
        assert _validate_short_flag(flag) is False

    def test_invalid_short_flag_raises_in_command_build(self):
        """Building the command should raise ValueError for digit short flags.

        Option("-1") has len == 2, so it's assigned as `short` by the marker,
        but _validate_short_flag rejects it because '1' is not a letter.
        """
        with pytest.raises(ValueError, match="Invalid short flag"):
            _command("deploy", _deploy_digit_short, app=None)

    def test_multi_char_flag_not_treated_as_short(self):
        """Option("-tt") has len > 2, so it's treated as long flag, not short.

        No ValueError is raised — the marker assigns it as the long flag.
        """
        # This should NOT raise — "-tt" is treated as long flag
        param = _params("deploy", _deploy_bad_short)["target"]
        assert isinstance(param, click.Option)
        assert "-tt" in param.opts
