"""A trivial job to watch the file-based plugin react to."""

from functualize.job import RunContext


def greet(rc: RunContext) -> str:
    """Say hello — on success the run-notifier plugin announces it."""
    rc.log("Hello from a job with a file-based plugin watching!")
    return "greeted"
