"""Property-based tests for positional arg registration (Property 12).

Tests that create_job_command correctly registers Arg()-marked parameters as
positional (typer.Argument) and non-Arg CLI-compatible parameters as named
options, preserving signature order for positional arguments.

# Feature: cli-unix-compatibility, Property 12
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any

import click
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize.app.adapters.click_params import build_click_params
from functualize.job.markers import Arg


def _params_by_name(fn: Any) -> dict[str, click.Parameter]:
    return {p.name: p for p in build_click_params(fn, None)[0]}


# =============================================================================
# Strategies
# =============================================================================

# Strategy: valid Python identifiers for parameter names (avoiding reserved words)
_param_names = st.sampled_from(
    [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
        "iota",
        "kappa",
    ]
)

# Strategy: CLI-compatible base types
_cli_types = st.sampled_from([str, int, float, bool])

# Strategy: optional Arg marker metadata
_arg_help_text = st.one_of(st.none(), st.text(min_size=1, max_size=20))


@st.composite
def _param_spec(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a parameter specification: name, type, and whether it's Arg-marked."""
    name = draw(_param_names)
    base_type = draw(_cli_types)
    is_arg = draw(st.booleans())
    help_text = draw(_arg_help_text) if is_arg else None
    return {
        "name": name,
        "type": base_type,
        "is_arg": is_arg,
        "help": help_text,
    }


@st.composite
def _param_spec_list(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Generate a list of unique parameter specs (1-5 params).

    Ensures at least one Arg-marked and one non-Arg param for meaningful tests.
    Arg()-marked params are ordered before non-Arg params so that the resulting
    signature is valid (positional args before defaulted options). Non-Arg params
    always have a default value — matching Typer's convention for named options.
    """
    num_params = draw(st.integers(min_value=2, max_value=5))
    # Use distinct names by picking from the pool without replacement
    available_names = [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
        "iota",
        "kappa",
    ]
    chosen_names = draw(
        st.lists(
            st.sampled_from(available_names),
            min_size=num_params,
            max_size=num_params,
            unique=True,
        )
    )

    arg_specs: list[dict[str, Any]] = []
    option_specs: list[dict[str, Any]] = []

    for name in chosen_names:
        base_type = draw(_cli_types)
        is_arg = draw(st.booleans())
        help_text = draw(_arg_help_text) if is_arg else None
        spec = {
            "name": name,
            "type": base_type,
            "is_arg": is_arg,
            "help": help_text,
        }
        if is_arg:
            arg_specs.append(spec)
        else:
            option_specs.append(spec)

    # Ensure at least one Arg and one non-Arg
    if not arg_specs:
        # Convert the first option spec to an arg spec
        option_specs[0]["is_arg"] = True
        option_specs[0]["help"] = draw(_arg_help_text)
        arg_specs.append(option_specs.pop(0))
    if not option_specs:
        # Convert the last arg spec to an option spec
        arg_specs[-1]["is_arg"] = False
        arg_specs[-1]["help"] = None
        option_specs.append(arg_specs.pop(-1))

    # Positional args come first, then named options (with defaults)
    return arg_specs + option_specs


def _default_for_type(base_type: type) -> Any:
    """Return a sensible default value for a given CLI-compatible type."""
    defaults: dict[type, Any] = {
        str: "default",
        int: 0,
        float: 0.0,
        bool: False,
    }
    return defaults.get(base_type, "default")


def _build_function_from_specs(specs: list[dict[str, Any]]) -> Any:
    """Dynamically create a function from parameter specifications.

    Each spec dict has: name, type, is_arg, help.
    Builds a function with the corresponding annotated parameters.
    Non-Arg params are given default values (matching Typer option conventions).
    """
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    for spec in specs:
        name = spec["name"]
        base_type = spec["type"]

        if spec["is_arg"]:
            # Annotated[T, Arg(...)]
            annotation = Annotated[base_type, Arg(help=spec["help"])]  # type: ignore[valid-type]
            params.append(
                inspect.Parameter(
                    name=name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                )
            )
        else:
            # Plain type with a default — no Arg marker (named option)
            annotation = base_type
            params.append(
                inspect.Parameter(
                    name=name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                    default=_default_for_type(base_type),
                )
            )
        annotations[name] = annotation

    # Build the function dynamically
    sig = inspect.Signature(parameters=params)

    def _dynamic_fn(**kwargs: Any) -> None:
        pass

    _dynamic_fn.__signature__ = sig  # type: ignore[attr-defined]
    _dynamic_fn.__annotations__ = annotations
    _dynamic_fn.__name__ = "test_job"
    _dynamic_fn.__doc__ = "Dynamically generated test job."
    return _dynamic_fn


# =============================================================================
# Property 12: Positional Arg Registration
# =============================================================================


@pytest.mark.slow
class TestPositionalArgRegistration:
    """Property 12: Positional Arg Registration.

    For any function with Arg()-marked params, the CLI adapter registers those
    as positional (typer.Argument) and all non-Arg CLI params as named options.

    **Validates: Requirements 3.1, 3.4**
    """

    @given(specs=_param_spec_list())
    @settings(max_examples=200)
    def test_arg_marked_params_become_positional(self, specs: list[dict[str, Any]]):
        """Arg()-marked parameters are registered as positional click Arguments.

        **Validates: Requirements 3.1, 3.4**
        """
        fn = _build_function_from_specs(specs)
        params = _params_by_name(fn)
        arg_names = {s["name"] for s in specs if s["is_arg"]}

        for name in arg_names:
            assert name in params, f"Arg-marked param '{name}' missing from command"
            assert isinstance(params[name], click.Argument), (
                f"Arg-marked param '{name}' should be a click.Argument, "
                f"got {type(params[name]).__name__}"
            )

    @given(specs=_param_spec_list())
    @settings(max_examples=200)
    def test_non_arg_params_become_named_options(self, specs: list[dict[str, Any]]):
        """Non-Arg CLI-compatible parameters are NOT positional arguments.

        **Validates: Requirements 3.1, 3.4**
        """
        fn = _build_function_from_specs(specs)
        params = _params_by_name(fn)
        non_arg_names = {s["name"] for s in specs if not s["is_arg"]}

        for name in non_arg_names:
            assert name in params, f"Non-Arg param '{name}' missing from command"
            assert isinstance(params[name], click.Option), (
                f"Non-Arg param '{name}' should be a click.Option, "
                f"got {type(params[name]).__name__}"
            )

    @given(specs=_param_spec_list())
    @settings(max_examples=200)
    def test_positional_order_matches_signature_order(
        self, specs: list[dict[str, Any]]
    ):
        """Positional arguments appear in the same order as in the original signature.

        **Validates: Requirements 3.1, 3.4**
        """
        fn = _build_function_from_specs(specs)
        built = build_click_params(fn, None)[0]

        positional_names = [p.name for p in built if isinstance(p, click.Argument)]
        expected_positional = [s["name"] for s in specs if s["is_arg"]]

        assert positional_names == expected_positional, (
            f"Positional order mismatch: got {positional_names}, "
            f"expected {expected_positional}"
        )
