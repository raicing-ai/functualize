"""Test subject functions for test_arg_marker_unit.py.

This module intentionally does NOT use `from __future__ import annotations`
so that `Annotated[T, ...]` annotations remain as runtime objects (not strings).
This is required for create_job_command() to inspect Arg() markers at runtime.
"""

from typing import Annotated

from functualize.job.markers import Arg


def single_positional(target: Annotated[str, Arg(help="Deploy target")]):
    """Job with a single positional arg."""
    return target


def multi_positional(
    env: Annotated[str, Arg(help="Environment")],
    region: Annotated[str, Arg(help="AWS region")],
):
    """Job with multiple positional args."""
    return f"{env}/{region}"


def variadic_positional(files: Annotated[list[str], Arg(help="Files to process")]):
    """Job with a variadic positional arg."""
    return files


def mixed_positional_and_options(
    target: Annotated[str, Arg(help="Deploy target")],
    replicas: int = 3,
    verbose: bool = False,
):
    """Job with positional + named options."""
    return f"{target} r={replicas} v={verbose}"


def required_positional_no_default(
    name: Annotated[str, Arg(help="Name is required")],
):
    """Job with a required positional (no default)."""
    return name


def positional_with_default(
    env: Annotated[str, Arg(help="Environment")] = "dev",
):
    """Job with a positional that has a default."""
    return env
