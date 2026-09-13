"""A real state store for tests.

A plain module rather than a fixture or a conftest helper, because it is used
from four directories (`tests/`, `tests/context/`, `tests/core/`,
`tests/hooks/`) and `from tests.context.conftest import …` reads like a
mistake from any of the other three.

**The store is real.** There is deliberately no in-memory double: one standing
in for the production collaborator at the seam under test is how `Perf` shipped
unwired for its entire life — every test that called `perf.mark()` called it on
`NoopPerf`, which accepted everything silently, so nothing exercised the real
one (ADR-021).

There is no performance argument for a double either — but the numbers that
show it are **empty-store** numbers, and saying so matters because they were
once used to defend more than they can: 0.557 ms per unbatched ``set``,
0.091 ms per ``get``, 1.1 ms for 100 sets in ``batch()``, 0.012 ms to
construct. That is what a *test* pays, which is the relevant cost here. On a
real project's 1 MB ``scopes.json`` the same ``set`` costs **58 ms**, because
every state operation re-reads the whole file and the file has no cap — see
`.spec/features/scope-record-lifecycle/`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

__all__ = ["new_state_store"]


def new_state_store(scope_id: str = "test-scope") -> Any:
    """A real `ScopeBackedStateStore`, in a directory cleaned up with it."""
    from functualize._engine.capabilities.state import ScopeBackedStateStore
    from functualize._primitives.scope_store import ScopeStore
    from functualize._primitives.substrate import JsonFileSubstrate

    tmp = tempfile.TemporaryDirectory(prefix="functualize-state-")
    store = ScopeBackedStateStore(
        ScopeStore(JsonFileSubstrate(Path(tmp.name))), scope_id
    )
    # Hold the directory for exactly the store's lifetime.
    store._tmp = tmp
    return store
