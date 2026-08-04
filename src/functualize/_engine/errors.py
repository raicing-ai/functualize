"""Execution engine errors.

Re-exports shared error types from _types for backward compatibility.
"""

from __future__ import annotations

from functualize._types.errors import JobNotFoundError, RecursionLimitError

__all__ = ["JobNotFoundError", "RecursionLimitError"]
