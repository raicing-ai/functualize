"""Property-based test for DI parameter exclusion (Property 9).

Tests that for any job function signature containing DI-annotated parameters
(RunContext, Log, Invoke, Prompt, Perf, State, JobContext, JobConfigView),
the resulting JobDescriptor.parameters contains none of these DI types.
Also tests that string annotations ("Log", "Invoke", etc.) are excluded.

Only CLI-compatible parameters SHALL remain in the extracted parameters.

**Validates: Requirements 7.1, 7.2, 7.3, 9.9**
"""

from __future__ import annotations

import types
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._discovery.providers import (
    _EXCLUDED_PARAM_TYPE_NAMES,
    extract_parameters_from_signature,
)

# --- DI type stubs (simulate the actual framework-injected types) ---

# Build stub classes for each excluded DI type name
_DI_STUB_CLASSES: dict[str, type] = {}
for _name in _EXCLUDED_PARAM_TYPE_NAMES:
    _DI_STUB_CLASSES[_name] = type(_name, (), {"__module__": "functualize.job"})


# --- Strategies ---

# Valid Python parameter names for CLI params
cli_param_names = st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True).filter(
    lambda s: s.isidentifier() and s not in ("self", "cls")
)

# CLI-compatible type annotations
cli_types = st.sampled_from([str, int, float, bool])

# DI type names (the ones that should always be excluded)
di_type_names = st.sampled_from(sorted(_EXCLUDED_PARAM_TYPE_NAMES))


@st.composite
def di_and_cli_params(
    draw: st.DrawFn,
) -> tuple[list[tuple[str, type]], list[tuple[str, Any]]]:
    """Generate a mix of DI-annotated params and CLI params.

    Returns:
        (di_params, cli_params) where:
        - di_params: list of (name, DI_stub_class) tuples
        - cli_params: list of (name, cli_type) tuples
    """
    # Generate 1-4 DI params
    num_di = draw(st.integers(min_value=1, max_value=4))
    di_names = draw(
        st.lists(cli_param_names, min_size=num_di, max_size=num_di, unique=True)
    )
    di_types_chosen = draw(st.lists(di_type_names, min_size=num_di, max_size=num_di))
    di_params = [
        (name, _DI_STUB_CLASSES[type_name])
        for name, type_name in zip(di_names, di_types_chosen, strict=True)
    ]

    # Generate 0-4 CLI params (names must not overlap with DI param names)
    remaining_names = draw(
        st.lists(
            cli_param_names.filter(lambda s: s not in {n for n, _ in di_params}),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )
    cli_type_list = draw(
        st.lists(
            cli_types, min_size=len(remaining_names), max_size=len(remaining_names)
        )
    )
    cli_params = list(zip(remaining_names, cli_type_list, strict=True))

    return di_params, cli_params


def _make_function_with_annotations(
    params: list[tuple[str, Any]],
) -> types.FunctionType:
    """Dynamically create a function with the given parameter annotations.

    Args:
        params: list of (param_name, annotation) tuples. Annotations can be
                type objects or strings (for string annotations).
    """
    # Build the parameter list and annotations dict
    param_names = [name for name, _ in params]
    annotations: dict[str, Any] = {}
    for name, ann in params:
        annotations[name] = ann
    annotations["return"] = None

    # Create function source dynamically
    params_str = ", ".join(param_names)
    func_code = f"def _generated_job({params_str}): pass"
    namespace: dict[str, Any] = {}
    exec(func_code, namespace)  # noqa: S102
    func = namespace["_generated_job"]
    func.__annotations__ = annotations
    return func


# --- Property 9: DI Parameter Exclusion ---


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=10000)
@given(data=di_and_cli_params())
def test_property_9_di_params_excluded_from_descriptor(
    data: tuple[list[tuple[str, type]], list[tuple[str, Any]]],
) -> None:
    """For any job function signature containing DI-annotated parameters
    (RunContext, Log, Invoke, Prompt, Perf, State, JobContext, JobConfigView),
    the resulting JobDescriptor.parameters SHALL contain none of these DI types.
    Only CLI-compatible parameters SHALL remain.

    **Validates: Requirements 7.1, 7.2, 7.3, 9.9**
    """
    di_params, cli_params = data

    # Interleave DI and CLI params in arbitrary order
    all_params = di_params + cli_params
    func = _make_function_with_annotations(all_params)

    # Extract parameters using the discovery pipeline
    extracted = extract_parameters_from_signature(func)

    # Property: no DI type names appear in extracted parameters
    extracted_names = {p.name for p in extracted}
    di_param_names = {name for name, _ in di_params}
    leaked_di_params = extracted_names & di_param_names
    assert not leaked_di_params, (
        f"DI parameters leaked into JobDescriptor.parameters: {leaked_di_params}. "
        f"DI types used: {[(n, t.__name__) for n, t in di_params]}. "
        f"All extracted: {[(p.name, p.type_annotation) for p in extracted]}"
    )

    # Property: no extracted parameter has a type_annotation matching a DI type name
    for param in extracted:
        assert param.type_annotation not in _EXCLUDED_PARAM_TYPE_NAMES, (
            f"Extracted parameter '{param.name}' has DI type annotation "
            f"'{param.type_annotation}' which should have been excluded"
        )

    # Property: all CLI params appear in the extracted parameters
    cli_param_names_set = {name for name, _ in cli_params}
    assert cli_param_names_set <= extracted_names, (
        f"CLI parameters missing from extracted result. "
        f"Expected: {cli_param_names_set}, Got: {extracted_names}. "
        f"Missing: {cli_param_names_set - extracted_names}"
    )


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=10000)
@given(di_type_name=di_type_names)
def test_property_9_string_annotations_excluded(
    di_type_name: str,
) -> None:
    """For any DI type referenced as a string annotation (e.g., "Log", "Invoke"),
    the resulting parameters SHALL still exclude that parameter.

    **Validates: Requirements 7.1, 7.2, 7.3, 9.9**
    """
    # Create a function with string annotation for the DI type
    all_params: list[tuple[str, Any]] = [
        ("injected", di_type_name),  # String annotation like "Log"
        ("name", str),  # CLI param
    ]
    func = _make_function_with_annotations(all_params)

    extracted = extract_parameters_from_signature(func)

    # Property: the string-annotated DI param is excluded
    extracted_names = {p.name for p in extracted}
    assert "injected" not in extracted_names, (
        f"String-annotated DI parameter 'injected' (annotation='{di_type_name}') "
        f"leaked into parameters. Extracted: {[(p.name, p.type_annotation) for p in extracted]}"
    )

    # Property: the CLI param "name" remains
    assert "name" in extracted_names, (
        f"CLI parameter 'name' was incorrectly excluded. "
        f"Extracted: {[(p.name, p.type_annotation) for p in extracted]}"
    )


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=10000)
@given(
    di_type_names_chosen=st.lists(di_type_names, min_size=1, max_size=8, unique=True)
)
def test_property_9_all_di_types_only_yields_empty_params(
    di_type_names_chosen: list[str],
) -> None:
    """For any function whose parameters are ALL DI-annotated types,
    the extracted parameters SHALL be empty.

    **Validates: Requirements 7.1, 7.2, 7.3, 9.9**
    """
    # Create a function where every param is a DI type
    all_params: list[tuple[str, Any]] = [
        (f"p{i}", _DI_STUB_CLASSES[type_name])
        for i, type_name in enumerate(di_type_names_chosen)
    ]
    func = _make_function_with_annotations(all_params)

    extracted = extract_parameters_from_signature(func)

    assert extracted == [], (
        f"Expected empty parameters when all params are DI types, "
        f"but got {len(extracted)} parameters: "
        f"{[(p.name, p.type_annotation) for p in extracted]}. "
        f"DI types used: {di_type_names_chosen}"
    )
