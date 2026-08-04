"""§D.7 HARD-GATE probes (S3/T20).

The S4 workflow walker is not built yet, but §D.7 requires the graph model to
honor four constraints **when S3 ships** — retrofitting them later would mean
engine rework. These probes are walker-shaped: they exercise the engine the
walker will sit on, without the walker.

(a) Runtime frontier expansion — two modes over one graph model.
(b) A BLOCKED node state joining the guard states.
(c) Position and gate payloads persist in the state store.
(d) Per-scope step records; branch choices recorded once and read on replay.
"""

from __future__ import annotations

import pytest

from functualize._engine.frontier import (
    END,
    FrontierWalk,
    GraphModel,
    WalkState,
    step_key,
)
from functualize._engine.guards import GuardState, GuardVerdict
from functualize._engine.scheduler import DepScheduler
from functualize._primitives.state_store import StateStore

# check ─┬─(ok)──→ deploy ──→ END
#        └─(fail)→ rollback ─→ END
CONDITIONAL_GRAPH = GraphModel(
    entry="check",
    edges={"deploy": ["notify"], "rollback": [END], "notify": [END]},
    conditional={"check": {"ok": "deploy", "fail": "rollback"}},
)


@pytest.fixture
def store(tmp_path) -> StateStore:
    return StateStore(tmp_path / "state.json")


def _walk(store: StateStore, scope: str = "s1") -> FrontierWalk:
    return FrontierWalk(CONDITIONAL_GRAPH, store, scope)


class TestD7aFrontierExpansion:
    """(a) A ConditionalEdge target is unknowable until its source returns."""

    def test_walk_starts_at_entry(self, store) -> None:
        assert _walk(store).start() == ["check"]

    def test_conditional_target_is_unknown_before_the_source_returns(self) -> None:
        # The whole justification for push mode: no upfront schedule exists.
        assert CONDITIONAL_GRAPH.successors("check") == []

    def test_frontier_expands_on_the_chosen_branch(self, store) -> None:
        walk = _walk(store)
        walk.start()
        assert walk.complete("check", choice="ok") == ["deploy"]

    def test_other_branch_is_not_scheduled(self, store) -> None:
        walk = _walk(store)
        walk.start()
        assert "rollback" not in walk.complete("check", choice="ok")

    def test_expansion_continues_past_the_branch(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.complete("check", choice="ok")
        assert walk.complete("deploy") == ["notify"]

    def test_end_terminates_the_walk(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.complete("check", choice="fail")
        assert walk.complete("rollback") == []
        assert store.get_scope("s1")["status"] == WalkState.COMPLETED

    def test_pull_mode_still_works_on_one_graph_model(self) -> None:
        # (a) requires TWO modes over ONE model: the DAG scheduler is unchanged
        # and still schedules a whole graph up front.
        order = DepScheduler({"lint": [], "test": ["lint"]}).plan().order
        assert order == ("lint", "test")


class TestD7bBlockedState:
    """(b) BLOCKED joins the guard states, carrying the awaited model."""

    def test_blocked_is_a_guard_state(self) -> None:
        verdict = GuardVerdict(
            GuardState.BLOCKED, "awaiting approval", awaiting="Approval"
        )
        assert verdict.state is GuardState.BLOCKED
        assert not verdict.will_run
        assert verdict.awaiting == "Approval"

    def test_blocked_is_distinct_from_the_skip_states(self) -> None:
        # A blocked node is not "skipped" — it is waiting, and will resume.
        assert not GuardState.BLOCKED.is_skip

    def test_walk_reports_blocked(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.block("check", "approve", model="Approval")
        assert walk.is_blocked()


class TestD7cBlockedPersistence:
    """(c) Position and gate payloads survive to be observed and resumed."""

    def test_position_persists_across_a_reload(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.block("check", "approve", model="Approval")

        # A different process reads the same file.
        reloaded = StateStore(store.path)
        assert reloaded.get_position("s1") == "check"
        assert reloaded.get_scope("s1")["status"] == WalkState.BLOCKED

    def test_gate_schema_persists_for_an_agent_to_read(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.block(
            "check",
            "approve",
            model="Approval",
            input_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        gate = StateStore(store.path).get_gate("s1", "approve")
        assert gate["model"] == "Approval"
        assert gate["input_schema"]["properties"]["ok"]["type"] == "boolean"
        assert gate["payload"] is None  # nothing deposited yet

    def test_deposited_payload_is_visible_to_the_resuming_walk(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.block("check", "approve", model="Approval")

        # An MCP agent (another process) deposits the input.
        StateStore(store.path).deposit_gate_payload("s1", "approve", {"ok": True})

        resumed = FrontierWalk(CONDITIONAL_GRAPH, StateStore(store.path), "s1")
        assert resumed.gate_payload("approve") == {"ok": True}

    def test_resume_continues_at_the_blocked_position(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.complete("check", choice="ok")
        walk.block("deploy", "approve")

        resumed = FrontierWalk(CONDITIONAL_GRAPH, StateStore(store.path), "s1")
        assert resumed.start() == ["deploy"]  # not back at the entry


class TestD7dPerScopeRecords:
    """(d) One record type, four consumers — including replay determinism."""

    def test_step_record_round_trips(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.complete("check", choice="ok", args_hash="h1", return_value={"n": 1})
        record = store.get_step("s1", step_key("check", "h1"))
        assert record["status"] == "success"
        assert record["return_value"] == {"n": 1}

    def test_records_are_scoped(self, store) -> None:
        FrontierWalk(CONDITIONAL_GRAPH, store, "s1").complete("check", choice="ok")
        other = FrontierWalk(CONDITIONAL_GRAPH, store, "s2")
        assert not other.should_replay_skip("check")

    def test_replay_skips_a_completed_step(self, store) -> None:
        walk = _walk(store)
        walk.start()
        walk.complete("check", choice="ok", args_hash="h1")
        resumed = FrontierWalk(CONDITIONAL_GRAPH, StateStore(store.path), "s1")
        assert resumed.should_replay_skip("check", "h1")

    def test_replay_does_not_skip_a_different_args_hash(self, store) -> None:
        walk = _walk(store)
        walk.complete("check", choice="ok", args_hash="h1")
        assert not walk.should_replay_skip("check", "h2")

    def test_failed_step_is_not_replay_skipped(self, store) -> None:
        walk = _walk(store)
        walk.complete("check", choice="ok", args_hash="h1", status="failed")
        assert not walk.should_replay_skip("check", "h1")

    def test_branch_choice_is_recorded_on_first_evaluation(self, store) -> None:
        # Records the choice KEY (schema §1 "<chosen_target_key>"), not the
        # resolved node: replay re-resolves through the current graph instead
        # of pinning a target name that the graph may since have renamed.
        walk = _walk(store)
        walk.start()
        walk.complete("check", choice="ok")
        assert store.get_branch("s1", "check") == "ok"

    def test_recorded_branch_wins_on_replay(self, store) -> None:
        """The determinism guarantee: a flaky condition cannot switch branches."""
        walk = _walk(store)
        walk.start()
        assert walk.complete("check", choice="ok") == ["deploy"]

        # Replay: the condition now evaluates the OTHER way (clock, random,
        # changed file). The walk must still follow the branch it took.
        resumed = FrontierWalk(CONDITIONAL_GRAPH, StateStore(store.path), "s1")
        assert resumed.complete("check", choice="fail") == ["deploy"]

    def test_epilogue_record_is_once_per_scope(self, store) -> None:
        store.record_epilogue("s1", {"status": "success", "return_value": 1})
        assert store.get_epilogue("s1")["return_value"] == 1
        assert StateStore(store.path).get_epilogue("s1") is not None
