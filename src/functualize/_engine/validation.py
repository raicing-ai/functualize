"""Delivery-agnostic argument validation for job functions.

Provides:
- unexpected_keyword_error(): decides whether a callable can accept a set of
  keyword arguments, without requiring the ones it is still missing
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
from collections.abc import Callable, Collection, Mapping
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from functualize._types.annotations import resolved_hints


def unexpected_keyword_error(
    function: Callable[..., Any],
    kwargs: Mapping[str, Any],
    *,
    also_accepts: Collection[str] = (),
) -> TypeError | None:
    """The ``TypeError`` calling ``function(**kwargs)`` would raise, or ``None``.

    Answers one question — *may the caller supply these keywords?* — and
    deliberately not the other one, *are all required arguments present?*
    ``Signature.bind_partial`` is exactly that split: it rejects a keyword the
    signature cannot accept, tolerates a parameter nothing has filled yet, and
    honours ``**kwargs`` by accepting anything.

    That split is what makes this usable *before* dependency injection has run.
    A job function's parameters are mostly capabilities the engine fills
    (``Log``, ``Stdout``) and ``FromJob`` results recorded by upstream steps;
    none exist at launch, so a completeness check there would reject every valid
    call. This is not an *exclusion* of DI parameters — they are ordinary
    declared parameters, and a caller has always been able to supply one
    explicitly, since the engine injects only names the caller did not provide.

    **The signature alone is not the acceptable set**, which is what
    ``also_accepts`` exists for. A job declaring ``config: Cfg`` is invoked as
    ``--city Tokyo``, and ``city`` is not a parameter of anything —
    ``_resolve_config_model`` *pops* each of the config model's field names out
    of ``call_kwargs`` and replaces them with the built model. A check that saw
    only the signature would refuse the CLI's own spelling of a documented flag.
    So the caller passes the names later stages will consume, and this stays the
    one place that decides, rather than growing a second opinion about it.

    ``bind_partial`` omits the ``fn()`` prefix that a real call's message
    carries, so it is added back here. Python owns the rule; this function owns
    the wording and the extra names, and its caller owns the timing.

    Args:
        function: The callable the keywords would be passed to.
        kwargs: The keyword arguments a caller supplied.
        also_accepts: Names that are legitimate even though the signature does
            not declare them, because a later stage consumes them — in practice
            the job's config-model field names. Must stay in step with what
            ``_resolve_config_model`` pops; the two are one decision.

    Returns:
        A ``TypeError`` worded as the real call would word it, or ``None`` when
        every keyword is acceptable.
    """
    candidates = (
        {name: value for name, value in kwargs.items() if name not in also_accepts}
        if also_accepts
        else kwargs
    )
    try:
        inspect.signature(function).bind_partial(**candidates)
    except TypeError as exc:
        name = getattr(function, "__name__", None) or repr(function)
        return TypeError(f"{name}() {exc}")
    return None


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
