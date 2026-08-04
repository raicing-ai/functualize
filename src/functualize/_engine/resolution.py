"""Resolution plan for DI parameter resolution in job functions.

Provides:
- ParamBinding: frozen dataclass describing how a single parameter is resolved
- ResolutionPlan: frozen dataclass caching DI analysis for a function
- build_resolution_plan(): factory for creating plans from function signatures

Only imports from `_types/`, `_primitives/`, and stdlib.
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from typing import Any, get_type_hints

from functualize._primitives import Provide


@dataclass(frozen=True)
class ParamBinding:
    """How a single function parameter is resolved during DI.

    Attributes:
        name: Parameter name in the function signature.
        annotation: The resolved type annotation (unwrapped from Optional/Annotated).
        qualifier: Qualifier string from Provide("..."), or None.
        source: Resolution source — "di", "runcontext", "config", or "skip".
        has_default: Whether the parameter has a default value.
        is_optional: Whether the annotation is Optional[T] (i.e., T | None).
    """

    name: str
    annotation: type
    qualifier: str | None
    source: str  # "di", "runcontext", "config", "skip"
    has_default: bool
    is_optional: bool


@dataclass(frozen=True)
class ResolutionPlan:
    """Cached analysis of a function's DI requirements.

    Computed once per function (keyed by id(function)) and reused
    for all subsequent invocations. Avoids repeated inspect.signature() calls.

    Attributes:
        function_id: id(function) used as cache key.
        params: Tuple of ParamBinding entries for all resolvable parameters.
    """

    function_id: int
    params: tuple[ParamBinding, ...]


def _is_optional_type(annotation: Any) -> tuple[bool, type | None]:
    """Check if an annotation is Optional[T] (Union[T, None]).

    Returns:
        (is_optional, inner_type) — inner_type is T if Optional[T], else None.
    """
    import types as builtin_types

    origin = getattr(annotation, "__origin__", None)

    # typing.Union or types.UnionType (Python 3.10+ `X | Y`)
    if origin is typing.Union or isinstance(annotation, builtin_types.UnionType):
        args = typing.get_args(annotation)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and type(None) in args:
            return True, non_none_args[0]
    return False, None


def _extract_provide_qualifier(annotation: Any) -> tuple[type, str | None]:
    """Extract the base type and Provide qualifier from an Annotated type.

    For Annotated[T, Provide("qualifier")], returns (T, "qualifier").
    For plain types, returns (annotation, None).
    """
    if type(annotation).__name__ == "_AnnotatedAlias" or (
        hasattr(annotation, "__metadata__")
    ):
        args = typing.get_args(annotation)
        if len(args) >= 2:
            base_type = args[0]
            metadata = args[1:]
            for meta in metadata:
                if isinstance(meta, Provide):
                    return base_type, meta.qualifier
            return base_type, None

    return annotation, None


def build_resolution_plan(
    function: Any,
    registered_types: set[type],
    runcontext_type: type | None = None,
) -> ResolutionPlan:
    """Build a ResolutionPlan by analyzing a function's signature.

    Inspects the function's type annotations and classifies each parameter:
    - "runcontext": parameter annotated as RunContext
    - "di": parameter annotated with a type registered in the DI registry
    - "skip": parameter with no annotation, unregistered type, or 'self'

    Parameters annotated with Annotated[T, Provide("qualifier")] are detected
    and the qualifier is extracted.

    Optional[T] parameters (T | None) are handled: if T is registered,
    the parameter is resolved from DI; if T is not registered, it resolves
    to None rather than raising MissingProviderError.

    Args:
        function: The callable to analyze.
        registered_types: Set of types registered in the DIRegistry.
        runcontext_type: The RunContext class for detection (avoids circular import).

    Returns:
        A frozen ResolutionPlan for the function.
    """
    bindings: list[ParamBinding] = []

    sig = inspect.signature(function)

    # Use get_type_hints with include_extras=True to preserve Annotated metadata
    try:
        hints = get_type_hints(function, include_extras=True)
    except Exception:
        hints = {}

    for param_name, param in sig.parameters.items():
        # Skip 'self' and 'cls' parameters
        if param_name in ("self", "cls"):
            continue

        # Skip *args and **kwargs
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        has_default = param.default is not inspect.Parameter.empty
        annotation = hints.get(param_name, param.annotation)

        # No annotation → skip
        if annotation is inspect.Parameter.empty:
            bindings.append(
                ParamBinding(
                    name=param_name,
                    annotation=type(None),
                    qualifier=None,
                    source="skip",
                    has_default=has_default,
                    is_optional=False,
                )
            )
            continue

        # Handle string annotations (forward references)
        if isinstance(annotation, str):
            if runcontext_type is not None and annotation == "RunContext":
                bindings.append(
                    ParamBinding(
                        name=param_name,
                        annotation=runcontext_type,
                        qualifier=None,
                        source="runcontext",
                        has_default=has_default,
                        is_optional=False,
                    )
                )
            else:
                bindings.append(
                    ParamBinding(
                        name=param_name,
                        annotation=type(None),
                        qualifier=None,
                        source="skip",
                        has_default=has_default,
                        is_optional=False,
                    )
                )
            continue

        # Check for Optional[T] first
        is_optional, inner_type = _is_optional_type(annotation)
        if is_optional and inner_type is not None:
            base_type, qualifier = _extract_provide_qualifier(inner_type)

            # Check if inner type is RunContext
            if runcontext_type is not None and base_type is runcontext_type:
                bindings.append(
                    ParamBinding(
                        name=param_name,
                        annotation=base_type,
                        qualifier=qualifier,
                        source="runcontext",
                        has_default=has_default,
                        is_optional=True,
                    )
                )
                continue

            # Optional[T] is always classified as "di"
            bindings.append(
                ParamBinding(
                    name=param_name,
                    annotation=base_type,
                    qualifier=qualifier,
                    source="di",
                    has_default=has_default,
                    is_optional=True,
                )
            )
            continue

        # Extract Provide qualifier from Annotated[T, Provide("...")]
        base_type, qualifier = _extract_provide_qualifier(annotation)

        # Check if this is RunContext
        if runcontext_type is not None and base_type is runcontext_type:
            bindings.append(
                ParamBinding(
                    name=param_name,
                    annotation=base_type,
                    qualifier=qualifier,
                    source="runcontext",
                    has_default=has_default,
                    is_optional=False,
                )
            )
            continue

        # Check if type is registered in DI
        if base_type in registered_types or qualifier is not None:
            bindings.append(
                ParamBinding(
                    name=param_name,
                    annotation=base_type,
                    qualifier=qualifier,
                    source="di",
                    has_default=has_default,
                    is_optional=False,
                )
            )
        else:
            bindings.append(
                ParamBinding(
                    name=param_name,
                    annotation=base_type,
                    qualifier=qualifier,
                    source="skip",
                    has_default=has_default,
                    is_optional=False,
                )
            )

    return ResolutionPlan(
        function_id=id(function),
        params=tuple(bindings),
    )
