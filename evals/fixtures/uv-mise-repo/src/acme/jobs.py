"""Existing jobs for the acme CLI."""

from functualize.job import job


@job
def ping() -> str:
    """Return a fixed greeting."""
    return "pong"
