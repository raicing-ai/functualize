"""Registered job internals for the execution engine.

Re-exports RegisteredJob from _types/descriptors for backward
compatibility with existing imports from this location.
"""

from __future__ import annotations

from functualize._types.descriptors import JobResult, RegisteredJob

__all__ = ["RegisteredJob", "JobResult"]
