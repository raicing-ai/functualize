"""Namespace-scoped state: count how many times a job has run.

Uses the InMemoryState testing double directly so the example is
self-contained; in a real app the framework injects a `State` capability
backed by whichever state provider is installed (e.g. SQLite).
"""

from functualize_state import StateNamespace
from functualize_state.testing import InMemoryState

from functualize.job import RunContext

# Shared backend for the module (a real app injects this per-scope)
_backend = InMemoryState()


def bump(rc: RunContext) -> int:
    """Increment and report this job's run counter."""
    state = StateNamespace(_backend, prefix="counter:")
    count = state.get("runs", 0) + 1
    state.set("runs", count)
    rc.log(f"This job has now run {count} time(s)")
    return count
