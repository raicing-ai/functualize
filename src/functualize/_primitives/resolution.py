"""Resolution-chain utilities."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def first_non_none(*values: T | None) -> T | None:
    """Return the first argument that is not None, or None if all are None.

    Args:
        *values: Arbitrary positional arguments, some of which may be None.

    Returns:
        The first non-None value, or None if all arguments are None.
    """
    for value in values:
        if value is not None:
            return value
    return None
