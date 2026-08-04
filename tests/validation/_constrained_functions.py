"""Helper module defining constrained functions for property tests.

This module deliberately does NOT use `from __future__ import annotations`
so that Annotated[T, Field(...)] annotations are eagerly evaluated. This
is required for `_build_validation_model()` which inspects param.annotation
via inspect.signature() — when annotations are PEP 563 strings, Field()
metadata cannot be extracted.

In production, job authors typically do not use `from __future__ import annotations`
in their job files, so this reflects real usage.
"""

from typing import Annotated

from pydantic import Field


def constrained_fn(
    name: Annotated[str, Field(min_length=2, max_length=10)],
    count: Annotated[int, Field(ge=1, le=50)],
) -> str:
    """A function with Field()-annotated params that define clear constraints."""
    return f"{name}:{count}"
