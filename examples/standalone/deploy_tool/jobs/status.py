"""A top-level job, so the tree is not only groups."""

from __future__ import annotations

from functualize.job import job


@job
def status(environment: str = "dev") -> str:
    """Report what is currently deployed."""
    return f"All services healthy in {environment}"
