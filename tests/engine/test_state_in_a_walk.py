"""`State` inside a walk: `StateBatch` through the port, reads through `state()`.

workflow-persistence-atomic W11, the unit level. The end-to-end legs (a walk
step's `state.set` landing in `scope_state`, resumed in another process) are
gate B-4 in `test_the_walk_on_both_stores.py`; this module pins the capability's
own contract:

- a mutation outside `batch()` lands on its own (per-call durability, W-AC-4);
- `batch()` buffers and lands one write at the outermost clean exit, and a
  raising block discards its writes;
- reads see the buffer over `WorkflowReader.state`, never a stale copy;
- a `State` built for a scope with no walk generation keeps
  `ScopeBackedStateStore` — spec §3 leaves non-walk state alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from functualize._engine.capabilities.state import (
    PortBackedState,
    ScopeBackedStateStore,
    State,
    state_for_scope,
)
from functualize._engine.capabilities.workflow_scope import WorkflowScope
from functualize._types.persistence import StateBatch


def _ports(state: State) -> tuple[Any, str]:
    """The store and scope a walk-scoped `State` writes through.

    The reader below is `WorkflowReader.state`, exactly as a resume reads it —
    the point is that the *port* answers, not the capability's own memory.
    """
    backend = state._bound()  # noqa: SLF001 - the seam under test is the backend
    return backend._store, backend._scope_id  # noqa: SLF001


def _landed(state: State) -> dict[str, object]:
    store, scope_id = _ports(state)
    return dict(store.workflows.state(scope_id))


class TestAMutationLandsOnItsOwn:
    def test_set_is_readable_through_the_reader_immediately(self) -> None:
        state = _walk()
        state.set("rows", 500)
        assert _landed(state) == {"rows": 500}

    def test_delete_is_readable_through_the_reader_immediately(self) -> None:
        state = _walk()
        state.set("rows", 500)
        state.delete("rows")
        assert _landed(state) == {}

    def test_clear_lands_every_current_key_as_a_delete(self) -> None:
        state = _walk()
        state.set("a", 1)
        state.set("b", 2)
        state.clear()
        assert _landed(state) == {}


class TestABatchLandsAtTheOutermostCleanExit:
    def test_nothing_is_durable_until_the_block_exits(self) -> None:
        state = _walk()
        with state.batch():
            state.set("a", 1)
            assert _landed(state) == {}
        assert _landed(state) == {"a": 1}

    def test_a_nested_batch_joins_the_outer_one(self) -> None:
        state = _walk()
        with state.batch():
            state.set("a", 1)
            with state.batch():
                state.set("b", 2)
                assert _landed(state) == {}
            assert _landed(state) == {}
        assert _landed(state) == {"a": 1, "b": 2}

    def test_a_raising_block_discards_its_writes(self) -> None:
        state = _walk()
        with pytest.raises(RuntimeError, match="boom"), state.batch():
            state.set("a", 1)
            raise RuntimeError("boom")
        assert _landed(state) == {}
        assert state.to_dict() == {}

    def test_last_operation_wins_per_key_inside_a_batch(self) -> None:
        state = _walk()
        with state.batch():
            state.set("a", 1)
            state.set("a", 2)
            state.delete("a")
            state.set("a", 3)
        assert _landed(state) == {"a": 3}


class TestReadsSeeTheBufferOverTheReader:
    def test_a_write_from_another_writer_is_visible(self) -> None:
        state = _walk()
        store, scope_id = _ports(state)
        with store.transaction() as tx:
            tx.workflows.write_state(
                StateBatch(scope_id, 0, datetime.now(UTC), {"rows": 500}, ())
            )
        assert state.get("rows") == 500

    def test_the_buffer_reads_over_what_the_reader_has(self) -> None:
        state = _walk()
        state.set("rows", 500)
        with state.batch():
            state.set("rows", 600)
            assert state.get("rows") == 600
        assert state.get("rows") == 600


class TestAStateWithNoWalkGenerationKeepsTheLegacyStore:
    def test_it_is_a_scope_backed_state_store(self) -> None:
        scope, _ = _scope()
        state = state_for_scope(scope)
        assert isinstance(state._bound(), ScopeBackedStateStore)  # noqa: SLF001

    def test_it_writes_the_scope_state_store_not_the_port(self) -> None:
        scope, scope_store = _scope()
        state = state_for_scope(scope)
        state.set("rows", 500)
        assert scope_store.state_snapshot("test-scope") == {"rows": 500}


class TestTheWalkScopedBackendIsThePortOne:
    def test_a_walk_generation_routes_to_the_port(self) -> None:
        state = _walk()
        assert isinstance(state._bound(), PortBackedState)  # noqa: SLF001


# ------------------------------------------------------------------
# Fixtures and helpers
# ------------------------------------------------------------------


def _walk() -> State:
    from functualize.testing.builder import _walk_state

    return _walk_state()


def _scope() -> tuple[WorkflowScope, object]:
    import tempfile
    from pathlib import Path

    from functualize._engine.capabilities.state import ScopeBackedStateStore
    from functualize._primitives.scope_store import ScopeStore
    from functualize._primitives.substrate import JsonFileSubstrate

    tmp = tempfile.TemporaryDirectory(prefix="functualize-test-state-scope-")
    scope_store = ScopeStore(JsonFileSubstrate(Path(tmp.name)))
    backend = ScopeBackedStateStore(scope_store, "test-scope")
    # Keep the directory alive exactly as long as the store that needs it.
    backend._tmp = tmp  # type: ignore[attr-defined]  # noqa: SLF001
    scope = WorkflowScope("test-scope", state_store=backend)
    return scope, scope_store
