"""Error types for the hierarchy module."""

from __future__ import annotations


class ChildPathError(Exception):
    """Raised when a child project path is invalid."""

    pass


class NamespaceConflictError(Exception):
    """Raised when child project namespaces conflict."""

    pass


__all__ = [
    "ChildPathError",
    "NamespaceConflictError",
]
