"""Annotation parsing utilities for CLI parameter classification.

Replaces the broken ``_is_cli_compatible_type()`` approach with a proper
``Annotated`` unwrapper that extracts base types, metadata markers, and
classifies parameters as DI, config, or CLI-compatible.

Public API:
- ``AnnotationInfo`` — frozen dataclass with parsed annotation details
- ``unwrap_annotated()`` — extract base type and metadata from Annotated[T, ...]
- ``parse_annotation()`` — full classification of a parameter annotation
- ``CLI_COMPATIBLE_TYPES`` — tuple of types that map to CLI options
"""

from __future__ import annotations

import enum
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args, get_origin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Types that Click can natively convert to CLI parameters.
CLI_COMPATIBLE_TYPES: tuple[type, ...] = (str, int, float, bool, Path)

#: DI capability type names that are injected by the execution engine.
#: Parameters with these types are stripped from CLI signatures.
_DI_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "RunContext",
        "Log",
        "Invoke",
        "Prompt",
        "Perf",
        "State",
        "JobContext",
        "JobConfigView",
    }
)


# ---------------------------------------------------------------------------
# AnnotationInfo dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnnotationInfo:
    """Parsed result of a parameter annotation.

    Fields:
        base_type: The underlying type after unwrapping Annotated (e.g. str, int).
            None if no annotation was provided.
        is_annotated: Whether an ``Annotated[T, ...]`` wrapper was present.
        cli_markers: List of CLI marker instances (Arg, Option, Stdin) found in metadata.
        field_metadata: Pydantic ``FieldInfo`` instance if present, else None.
        is_di_param: Whether this parameter should be injected via DI (not CLI-exposed).
        is_cli_compatible: Whether the base type can serve as a CLI parameter.
    """

    base_type: type | None
    is_annotated: bool
    cli_markers: list[Any] = field(default_factory=list)
    field_metadata: Any | None = None
    is_di_param: bool = False
    is_cli_compatible: bool = False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _is_provide_marker(obj: Any) -> bool:
    """Check if an object is a Provide DI qualifier marker.

    Uses class name matching to avoid importing from internal _primitives package.
    """
    return type(obj).__name__ == "Provide"


def _is_di_type(base_type: Any) -> bool:
    """Check if a type is a DI-registered capability type.

    Uses name-based matching against the known set of DI type names.
    """
    if not isinstance(base_type, type):
        return False
    return base_type.__name__ in _DI_TYPE_NAMES


def _is_basemodel_subclass(base_type: Any) -> bool:
    """Check if a type is a Pydantic BaseModel subclass (config parameter).

    Uses class name matching to avoid hard dependency on pydantic at import time.
    """
    if not isinstance(base_type, type):
        return False
    # Walk MRO to check for BaseModel without importing pydantic
    for cls in base_type.__mro__:
        if cls.__module__.startswith("pydantic") and cls.__name__ == "BaseModel":
            return True
    return False


def _is_field_info(obj: Any) -> bool:
    """Check if an object is a Pydantic FieldInfo instance."""
    return type(obj).__name__ == "FieldInfo" and type(obj).__module__.startswith(
        "pydantic"
    )


def _is_cli_marker(obj: Any) -> bool:
    """Check if an object is a CLI marker (Arg, Option, or Stdin)."""
    return type(obj).__name__ in ("Arg", "Option", "Stdin")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def unwrap_annotated(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    """Unwrap ``Annotated[T, ...]`` into ``(T, metadata_tuple)``.

    If the annotation is not ``Annotated``, returns ``(annotation, ())``.

    Args:
        annotation: A type annotation, possibly wrapped in ``Annotated[T, ...]``.

    Returns:
        A tuple of (base_type, metadata) where metadata is an empty tuple
        if the annotation was not Annotated.
    """
    from typing import Annotated

    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return args[0], args[1:]
    return annotation, ()


def parse_annotation(annotation: Any) -> AnnotationInfo:
    """Parse a function parameter annotation into structured classification info.

    Handles:
    - Bare types: ``str``, ``int``, ``MyEnum``
    - ``Annotated[str, Field(...)]``
    - ``Annotated[str, Arg(), Field(min_length=1)]``
    - ``Annotated[str, Option("-t"), Field(min_length=1)]``
    - ``Annotated[str, Stdin()]``
    - DI types: ``RunContext``, ``Log``, ``Invoke``, etc.
    - ``Annotated[T, Provide("qualifier")]`` — always DI
    - ``inspect.Parameter.empty`` (no annotation)
    - BaseModel subclasses (config parameters)

    Invariant: A parameter classified as DI is NEVER classified as CLI-compatible.

    Args:
        annotation: The annotation from ``inspect.Parameter.annotation``.

    Returns:
        An ``AnnotationInfo`` instance with all fields populated.
    """
    # Case 1: No annotation
    if annotation is inspect.Parameter.empty:
        return AnnotationInfo(
            base_type=None,
            is_annotated=False,
            cli_markers=[],
            field_metadata=None,
            is_di_param=False,
            is_cli_compatible=True,
        )

    # Case 2: Unwrap Annotated[T, ...] if present
    base_type, metadata = unwrap_annotated(annotation)
    is_annotated = len(metadata) > 0

    # Case 3: Check for Provide marker in metadata → always DI
    for meta in metadata:
        if _is_provide_marker(meta):
            return AnnotationInfo(
                base_type=base_type,
                is_annotated=is_annotated,
                cli_markers=[],
                field_metadata=None,
                is_di_param=True,
                is_cli_compatible=False,
            )

    # Case 4: Check if base type is a DI-registered type
    if _is_di_type(base_type):
        return AnnotationInfo(
            base_type=base_type,
            is_annotated=is_annotated,
            cli_markers=[],
            field_metadata=None,
            is_di_param=True,
            is_cli_compatible=False,
        )

    # Case 5: Check if base type is a BaseModel subclass (config parameter)
    if _is_basemodel_subclass(base_type):
        return AnnotationInfo(
            base_type=base_type,
            is_annotated=is_annotated,
            cli_markers=[],
            field_metadata=None,
            is_di_param=False,
            is_cli_compatible=False,
        )

    # Case 6: Extract CLI markers and Field metadata from metadata
    cli_markers = [m for m in metadata if _is_cli_marker(m)]
    field_meta = next((m for m in metadata if _is_field_info(m)), None)

    # Determine CLI compatibility from base type
    is_compatible = base_type in CLI_COMPATIBLE_TYPES or (
        isinstance(base_type, type) and issubclass(base_type, enum.Enum)
    )

    return AnnotationInfo(
        base_type=base_type,
        is_annotated=is_annotated,
        cli_markers=cli_markers,
        field_metadata=field_meta,
        is_di_param=False,
        is_cli_compatible=is_compatible,
    )
