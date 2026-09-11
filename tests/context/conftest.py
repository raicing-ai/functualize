"""Shared fixtures for the context tests.

The store these build is the **real** one, over a real ``scopes.json`` in a
throwaway directory. There is deliberately no in-memory double: a double
standing in for the production collaborator at the seam under test is how
`Perf` shipped unwired for its entire life — every test that called
``perf.mark()`` called it on ``NoopPerf``, which accepted everything silently,
so nothing ever exercised the real one (ADR-021).

There is no performance argument for a double either. Measured on this store:
**0.557 ms** per unbatched ``set``, **0.091 ms** per ``get``, 1.1 ms for 100
sets inside ``batch()``, and 0.012 ms to construct one.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


def new_state_store(scope_id: str = "test-scope") -> Any:
    """A real `ScopeBackedStateStore`, in a directory cleaned with it."""
    from functualize._engine.capabilities.state import ScopeBackedStateStore
    from functualize._primitives.scope_store import ScopeStore

    tmp = tempfile.TemporaryDirectory(prefix="functualize-state-")
    store = ScopeBackedStateStore(ScopeStore(Path(tmp.name) / "scopes.json"), scope_id)
    # Hold the directory for exactly the store's lifetime.
    store._tmp = tmp
    return store
