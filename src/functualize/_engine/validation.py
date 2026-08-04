"""Delivery-agnostic argument validation for job functions.

Provides:
- ArgValidator: validates function kwargs against Pydantic Field() constraints
- _build_validation_model(): introspects a function signature, extracts
  Field()-annotated params via Annotated unwrapping, and builds a dynamic
  Pydantic model with create_model()

Validation is engine-level — it runs identically for CLI, Lambda, HTTP, and MCP
adapters. When no Field() metadata is found, kwargs pass through unmodified.

Only imports from `_types/`, `_primitives/`, and stdlib (plus pydantic for models).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from functualize._types.annotations import resolved_hints


class ArgValidator:
    """Validates function call kwargs against Field() annotations.

    Caches dynamically-built Pydantic models keyed by id(function) so that
    repeated calls for the same function avoid re-introspection.
    """

    def __init__(self) -> None:
        self._model_cache: dict[int, type[BaseModel] | None] = {}

    def validate(
        self, function: Callable[..., Any], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate kwargs against Field-annotated parameters of function.

        Returns a new dict with validated (and possibly coerced) values merged
        back. Does NOT mutate the original kwargs dict.

        If the function has no Field() annotations, returns kwargs unchanged.
        Lets ValidationError propagate on failure — the caller handles it.
        """
        model_cls = self._get_or_build_model(function)
        if model_cls is None:
            return kwargs  # No Field annotations — pass through

        # Only validate params that have Field metadata
        validatable = {k: v for k, v in kwargs.items() if k in model_cls.model_fields}
        validated = model_cls.model_validate(validatable)

        # Merge validated values back (coercion may have changed types)
        result = dict(kwargs)
        result.update(validated.model_dump())
        return result

    def _get_or_build_model(
        self, function: Callable[..., Any]
    ) -> type[BaseModel] | None:
        """Retrieve cached model or build one for the function."""
        fn_id = id(function)
        if fn_id in self._model_cache:
            return self._model_cache[fn_id]
        model = _build_validation_model(function)
        self._model_cache[fn_id] = model
        return model


def _build_validation_model(
    function: Callable[..., Any],
) -> type[BaseModel] | None:
    """Introspect function signature, extract Field-annotated params,
    build a dynamic Pydantic model for validation.

    Returns None if no params have Field() metadata.
    """
    sig = inspect.signature(function)
    field_definitions: dict[str, Any] = {}
    # Under PEP 563 the annotation is the *string* "Annotated[int, Field(ge=0)]",
    # whose get_origin() is None — so every parameter would fall through the
    # `continue` below and the function would validate nothing at all, silently.
    hints = resolved_hints(function)

    for name, param in sig.parameters.items():
        annotation = hints.get(name, param.annotation)
        if annotation is inspect.Parameter.empty:
            continue

        # Unwrap Annotated[T, ...]
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            base_type = args[0]
            metadata = args[1:]
        else:
            continue  # No Annotated wrapper → no Field possible

        # Find FieldInfo in metadata
        field_info = next((m for m in metadata if isinstance(m, FieldInfo)), None)
        if field_info is None:
            continue  # No Field() → skip

        # Handle default values: if param has a default, propagate it to the field
        if param.default is not inspect.Parameter.empty:
            field_info.default = param.default

        field_definitions[name] = (base_type, field_info)

    if not field_definitions:
        return None

    return create_model(f"_Validate_{function.__name__}", **field_definitions)
