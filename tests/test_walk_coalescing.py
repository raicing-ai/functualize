"""The walk writes the scope file once per node, not three times (AC-17).

`FreshStore.batch` existed to hold the lock across many mutations, and the
module docstring told callers to use it. Nothing in `src/` or `plugins/` ever
did, so `record_step`, `set_position` and `set_scope_status` each performed an
independent locked read-modify-write of a file that also held every fingerprint
and a 200-entry history ring — roughly three full rewrites per node.

These tests pin the count. A regression here is silent and only shows up as I/O.
"""

from __future__ import annotations

import pytest

from functualize._engine.frontier import END, FrontierWalk, GraphModel
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate

# approve ──→ END
LINEAR_GRAPH = GraphModel(entry="approve", edges={"approve": [END]})


@pytest.fixture
def counting_saves(monkeypatch):
    """Count physical writes of the scope document.

    **One patch, since `store-substrate`/T2.** This used to patch two names —
    `save_scopes` and `update_scopes` — because a write could go through either,
    and a spy that missed one counted too few. There is now a single `write` on
    the substrate, so miscounting by patching the wrong door is not possible.
    """
    from functualize._primitives.substrate import JsonFileSubstrate

    calls: list[str] = []
    real = JsonFileSubstrate.write

    def _spy(self, key, payload, **kwargs):
        calls.append(key)
        return real(self, key, payload, **kwargs)

    monkeypatch.setattr(JsonFileSubstrate, "write", _spy)
    return calls


class TestFrontierWritesOncePerCall:
    def test_block_writes_once_not_three_times(self, tmp_path, counting_saves):
        walk = FrontierWalk(LINEAR_GRAPH, FreshStore(JsonFileSubstrate(tmp_path)), "s1")
        counting_saves.clear()

        walk.block("approve", "approve_gate", model="", input_schema={})

        assert len(counting_saves) == 1, (
            f"block() sets position, status and the gate — that is one write, "
            f"not {len(counting_saves)}"
        )

    def test_start_writes_once(self, tmp_path, counting_saves):
        walk = FrontierWalk(LINEAR_GRAPH, FreshStore(JsonFileSubstrate(tmp_path)), "s1")
        counting_saves.clear()

        walk.start("release")

        assert len(counting_saves) == 1


class TestOutcomeIsUnchanged:
    """Coalescing must not change what is recorded — only how often it is
    written."""

    def test_block_records_the_same_thing_it_always_did(self, tmp_path):
        store = FreshStore(JsonFileSubstrate(tmp_path))
        walk = FrontierWalk(LINEAR_GRAPH, store, "s1")

        walk.start("release")
        walk.block("approve", "approve_gate", model="gpt", input_schema={"a": 1})

        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["status"] == "blocked"
        assert scope["position"] == "approve"
        assert scope["workflow"] == "release"
        gate = store.get_gate("s1", "approve_gate")
        assert gate is not None
        assert gate["model"] == "gpt"
        assert gate["input_schema"] == {"a": 1}
        assert gate["payload"] is None


class TestAllOrNothingPerNode:
    """A deliberate behaviour change: a batch writes on clean exit only, so an
    exception mid-node discards that node's writes rather than persisting two of
    three. All-or-nothing beats a torn record."""

    def test_an_exception_mid_batch_leaves_no_partial_node(self, tmp_path):
        store = ScopeStore(JsonFileSubstrate(tmp_path))
        store.ensure_scope("s1", "release")

        with pytest.raises(RuntimeError), store.batch():
            store.record_step("s1", "build::", {"status": "success"})
            store.set_position("s1", "deploy")
            raise RuntimeError("node blew up between writes")

        scope = store.get_scope("s1")
        assert scope is not None
        assert scope["steps"] == {}
        assert scope["position"] is None
