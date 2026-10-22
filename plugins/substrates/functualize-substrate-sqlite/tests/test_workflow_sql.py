"""`WorkflowWriter` over SQLite (task 8): the fence, the lifecycle, the claim.

The headline gate is data model §5: a writer whose generation was taken over
matches **zero rows**, and the live value survives — both when the writer is
refused up front (``StaleGenerationError``, as on the document store) and when
the takeover lands between its check and its commit, where only the predicate
can stop it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from functualize_substrate_sqlite import SqliteRuntimeStore, SQLiteSubstratePlugin
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory
from functualize_substrate_sqlite._transaction import iso

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.lease import LeaseHeldError, StaleGenerationError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.plugin import (
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    Conflict,
    ConsumeInput,
    IllegalTransition,
    MoveScope,
    RecordBranch,
    RecordStep,
    ReleaseLease,
    RenewLease,
    ResumeWorkflow,
    RuntimeStoreConfig,
    StartWalk,
    StateBatch,
    SuspendAtGate,
)

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
LEASE = 60.0


@pytest.fixture
def store(tmp_path: Path) -> SqliteRuntimeStore:
    config = RuntimeStoreConfig(
        url=f"sqlite://{tmp_path / 'state.db'}", scheme="sqlite", project_root=tmp_path
    )
    return cast("SqliteRuntimeStore", SqliteRuntimeStoreFactory().prepare(config).store)


def _claim(
    store: SqliteRuntimeStore,
    owner: str = "a",
    *,
    at: datetime = T0,
    force: bool = False,
) -> Claimed | Conflict:
    with store.transaction() as tx:
        return tx.workflows.claim(ClaimWorkflow("s1", owner, at, LEASE, force=force))


def _held(store: SqliteRuntimeStore, owner: str = "a") -> int:
    claimed = _claim(store, owner)
    assert isinstance(claimed, Claimed)
    return claimed.generation


def _row(store: SqliteRuntimeStore, sql: str, *args: object) -> list[tuple[Any, ...]]:
    return store.driver.query(sql, args)


def _state(store: SqliteRuntimeStore) -> dict[str, Any]:
    return {
        k: v
        for k, v in _row(
            store, "SELECT key, value FROM scope_state WHERE scope_id = 's1'"
        )
    }


# -- claim ----------------------------------------------------------------


def test_a_first_claim_creates_the_scope_at_generation_1(
    store: SqliteRuntimeStore,
) -> None:
    claimed = _claim(store)

    assert claimed == Claimed("s1", 1, T0 + timedelta(seconds=LEASE))
    assert _row(store, "SELECT status, lease_owner FROM workflow_scopes") == [
        ("running", "a")
    ]


def test_claim_commits_one_batch_of_one_statement(store: SqliteRuntimeStore) -> None:
    with patch.object(store.driver, "batch", wraps=store.driver.batch) as batch:
        assert isinstance(_claim(store), Claimed)
        assert isinstance(_claim(store, "b"), Conflict)

    assert batch.call_count == 2
    assert all(len(call.args[0]) == 1 for call in batch.call_args_list)


def test_a_live_lease_is_a_conflict_value_not_an_exception(
    store: SqliteRuntimeStore,
) -> None:
    _held(store, "a")

    assert _claim(store, "b") == Conflict("s1", held_by="a", held_generation=1)


def test_an_expired_lease_is_reclaimed_at_the_next_generation(
    store: SqliteRuntimeStore,
) -> None:
    _held(store, "a")

    later = _claim(store, "b", at=T0 + timedelta(seconds=LEASE + 1))

    assert isinstance(later, Claimed)
    assert later.generation == 2


def test_force_takes_a_live_lease(store: SqliteRuntimeStore) -> None:
    _held(store, "a")

    assert isinstance(_claim(store, "b", force=True), Claimed)


def test_a_live_same_owner_claim_is_conflict(store: SqliteRuntimeStore) -> None:
    """A second walk in this process must renew, not claim over the first."""
    _held(store, "a")

    assert _claim(store, "a", at=T0 + timedelta(seconds=1)) == Conflict(
        "s1", held_by="a", held_generation=1
    )
    assert _row(store, "SELECT lease_owner, lease_generation FROM workflow_scopes") == [
        ("a", 1)
    ]


def test_the_same_owner_may_reclaim_after_expiry(store: SqliteRuntimeStore) -> None:
    _held(store, "a")

    again = _claim(store, "a", at=T0 + timedelta(seconds=LEASE))

    assert isinstance(again, Claimed)
    assert again.generation == 2


def test_renew_and_release_are_fenced_single_updates(
    store: SqliteRuntimeStore,
) -> None:
    generation = _held(store)
    later = T0 + timedelta(seconds=5)
    with store.transaction() as tx:
        tx.workflows.renew(RenewLease("s1", generation, "a", later, LEASE))
    assert _row(
        store,
        "SELECT lease_owner, lease_generation, lease_expires_at FROM workflow_scopes",
    ) == [("a", generation, iso(later + timedelta(seconds=LEASE)))]

    with store.transaction() as tx:
        tx.workflows.release(ReleaseLease("s1", generation, later))
    assert _row(
        store,
        "SELECT lease_owner, lease_generation, lease_expires_at FROM workflow_scopes",
    ) == [(None, generation, iso(later))]
    assert _claim(store, "b", at=later) == Claimed(
        "s1", generation + 1, later + timedelta(seconds=LEASE)
    )


# -- the fence --------------------------------------------------------------


def test_a_stale_generation_is_refused_up_front_and_the_live_value_survives(
    store: SqliteRuntimeStore,
) -> None:
    first = _held(store, "a")
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", first, T0, {"rows": 1}))
    _claim(store, "b", force=True)

    with pytest.raises(StaleGenerationError), store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", first, T0, {"rows": 999}))

    assert _state(store) == {"rows": "1"}


def test_a_takeover_between_check_and_commit_matches_zero_rows(
    store: SqliteRuntimeStore,
) -> None:
    """The race only the predicate can stop: the stale write is staged under a
    generation that was current, and the takeover commits before it does."""
    first = _held(store, "a")
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", first, T0, {"rows": 1}))

    with store.transaction() as stale:
        stale.workflows.write_state(
            StateBatch("s1", first, T0, {"rows": 999, "new": 1}, deletes=("rows",))
        )
        stale.workflows.complete_step(
            CompleteStep("s1", first, "step", T0, scope_status="completed")
        )
        _claim(store, "b", force=True)  # commits on the spot, mid-unit

    assert _state(store) == {"rows": "1"}
    assert _row(store, "SELECT count(*) FROM workflow_steps") == [(0,)]
    assert _row(store, "SELECT status, lease_generation FROM workflow_scopes") == [
        ("running", 2)
    ]


def test_a_renewal_overtaken_between_check_and_commit_is_refused(
    store: SqliteRuntimeStore,
) -> None:
    """A renewal is the one write whose *caller* reads the outcome.

    The heartbeat decides from it whether the walk still owns the scope, so a
    renewal the predicate stopped must say so, as the up-front check would
    have — not return as if it had extended the lease.
    """
    first = _held(store, "a")

    with pytest.raises(StaleGenerationError), store.transaction() as tx:
        tx.workflows.renew(RenewLease("s1", first, "a", T0, LEASE))
        _claim(store, "b", force=True)  # commits on the spot, mid-unit

    assert _row(store, "SELECT lease_owner, lease_generation FROM workflow_scopes") == [
        ("b", first + 1)
    ]


def test_generation_0_fences_nothing(store: SqliteRuntimeStore) -> None:
    """As on the document store: an unclaimed walk writes with no generation."""
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", 0, T0, {"k": "v"}))

    assert _state(store) == {"k": '"v"'}


# -- state ------------------------------------------------------------------


def test_state_upserts_version_and_deletes(store: SqliteRuntimeStore) -> None:
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", gen, T0, {"a": 1, "b": 2}))
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", gen, T0, {"a": 3}, deletes=("b",)))

    assert _row(store, "SELECT key, value, version FROM scope_state") == [("a", "3", 2)]


# -- lifecycle ----------------------------------------------------------------


def test_an_edge_outside_the_scope_machine_is_refused(
    store: SqliteRuntimeStore,
) -> None:
    """``completed -> blocked`` is not in `_types/lifecycle.SCOPE`.

    (``completed -> running`` *is* — it is the retry edge — so the store
    allows it; the machine, not this module, decides which moves exist.)
    """
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "last", T0, scope_status="completed")
        )

    with pytest.raises(IllegalTransition), store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "again", T0, scope_status="blocked")
        )

    assert _row(store, "SELECT status FROM workflow_scopes") == [("completed",)]


def test_cancelled_is_absorbing_nothing_moves_it_back_to_running(
    store: SqliteRuntimeStore,
) -> None:
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.cancel(CancelWorkflow("s1", gen, T0))

    with pytest.raises(IllegalTransition), store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "x", T0, scope_status="running")
        )
    with pytest.raises(IllegalTransition), store.transaction() as tx:
        tx.workflows.resume(ResumeWorkflow("s1", "a", "approve", T0, LEASE))

    assert _row(store, "SELECT status FROM workflow_scopes") == [("cancelled",)]


def test_completed_to_running_is_the_retry_edge_and_is_allowed(
    store: SqliteRuntimeStore,
) -> None:
    """`_types/lifecycle.SCOPE` lists ``(completed, running)``; the store follows it."""
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "x", T0, scope_status="completed")
        )
    with store.transaction() as tx:
        tx.workflows.resume(ResumeWorkflow("s1", "a", "retry", T0, LEASE))

    assert _row(store, "SELECT status, lease_generation FROM workflow_scopes") == [
        ("running", gen + 1)
    ]


def test_a_cancelled_scope_cannot_be_cancelled_again(store: SqliteRuntimeStore) -> None:
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.cancel(CancelWorkflow("s1", gen, T0, reason="stop"))

    with pytest.raises(IllegalTransition), store.transaction() as tx:
        tx.workflows.cancel(CancelWorkflow("s1", gen, T0, force=True))


def test_a_step_records_result_branch_position_and_terminal_at(
    store: SqliteRuntimeStore,
) -> None:
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep(
                "s1",
                gen,
                "pick",
                T0,
                result={"n": 1},
                decision_key="pick",
                chosen_target="left",
                position="left",
            )
        )
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "left", T0, position=None, scope_status="completed")
        )

    assert _row(
        store, "SELECT step_key, status, result FROM workflow_steps ORDER BY step_key"
    ) == [
        ("left", "success", None),
        ("pick", "success", '{"n": 1}'),
    ]
    assert _row(store, "SELECT decision_key, chosen_target FROM workflow_branches") == [
        ("pick", "left")
    ]
    [(status, position, terminal_at)] = _row(
        store, "SELECT status, position, terminal_at FROM workflow_scopes"
    )
    assert (status, position) == ("completed", None)
    assert terminal_at is not None


def test_a_branch_is_immutable_once_written(store: SqliteRuntimeStore) -> None:
    gen = _held(store)
    for target in ("left", "right"):
        with store.transaction() as tx:
            tx.workflows.complete_step(
                CompleteStep(
                    "s1",
                    gen,
                    "pick",
                    T0,
                    decision_key="pick",
                    chosen_target=target,
                    position=target,
                )
            )

    assert _row(store, "SELECT chosen_target FROM workflow_branches") == [("left",)]


def test_a_retry_re_entering_running_clears_terminal_at(
    store: SqliteRuntimeStore,
) -> None:
    gen = _held(store)
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "x", T0, status="failed", scope_status="failed")
        )
    with store.transaction() as tx:
        tx.workflows.complete_step(CompleteStep("s1", gen, "x", T0, iteration=1))

    assert _row(store, "SELECT status, terminal_at FROM workflow_scopes") == [
        ("running", None)
    ]


# -- gates -----------------------------------------------------------------


def _suspend(store: SqliteRuntimeStore, gen: int, request_id: str) -> None:
    with store.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate(
                "s1",
                gen,
                "approve",
                request_id,
                "approve",
                T0,
                schema={"type": "object"},
            )
        )


def test_suspend_opens_one_request_and_blocks_the_scope(
    store: SqliteRuntimeStore,
) -> None:
    gen = _held(store)
    _suspend(store, gen, "req-1")

    assert _row(
        store, "SELECT id, gate_key, generation, status, schema FROM input_requests"
    ) == [("req-1", "approve", gen, "open", '{"type": "object"}')]
    assert _row(store, "SELECT status, position FROM workflow_scopes") == [
        ("blocked", "approve")
    ]


def test_a_re_entering_walk_keeps_the_live_request(store: SqliteRuntimeStore) -> None:
    gen = _held(store)
    _suspend(store, gen, "req-1")
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "noop", T0, position="approve")
        )
    _suspend(store, gen, "req-2")

    assert _row(store, "SELECT id FROM input_requests") == [("req-1",)]


def test_resume_takes_a_new_generation_and_fences_the_suspended_walk(
    store: SqliteRuntimeStore,
) -> None:
    old = _held(store, "a")
    _suspend(store, old, "req-1")

    with store.transaction() as tx:
        tx.workflows.resume(ResumeWorkflow("s1", "a", "approve", T0, LEASE))

    assert _row(store, "SELECT status, lease_generation FROM workflow_scopes") == [
        ("running", old + 1)
    ]
    with pytest.raises(StaleGenerationError), store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", old, T0, {"late": 1}))


def test_resume_over_someone_elses_live_lease_raises(store: SqliteRuntimeStore) -> None:
    gen = _held(store, "a")
    _suspend(store, gen, "req-1")

    with pytest.raises(LeaseHeldError), store.transaction() as tx:
        tx.workflows.resume(ResumeWorkflow("s1", "b", "approve", T0, LEASE))


def test_cancel_records_its_event_and_force_needs_no_generation(
    store: SqliteRuntimeStore,
) -> None:
    _held(store, "a")
    with store.transaction() as tx:
        tx.workflows.cancel(CancelWorkflow("s1", 0, T0, force=True, reason="operator"))

    assert _row(store, "SELECT status FROM workflow_scopes") == [("cancelled",)]
    assert _row(store, "SELECT seq, type, payload FROM scope_events") == [
        (1, "workflow.cancelled", '{"reason": "operator"}')
    ]


def test_a_raising_unit_applies_nothing(store: SqliteRuntimeStore) -> None:
    gen = _held(store)
    with pytest.raises(RuntimeError), store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", gen, T0, {"a": 1}))
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "x", T0, scope_status="completed")
        )
        raise RuntimeError("mid-transition")

    assert _state(store) == {}
    assert _row(store, "SELECT status FROM workflow_scopes") == [("running",)]


# -- reachability: the boot-selected store ----------------------------------------


def _boot_sqlite(project: Path) -> FunctualizeApp:
    def alpha() -> None:
        """A job."""

    return FunctualizeApp(
        "workflow-sql",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [
                    DefaultSource(
                        {"runtime_store": {"url": f"sqlite://{project / 'state.db'}"}}
                    )
                ]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )


def test_a_boot_selected_store_claims_and_writes(tmp_path: Path) -> None:
    """Task 8's call path: boot selects ``sqlite:``, and the engine's store's
    ``transaction().workflows`` is this writer."""
    store = _boot_sqlite(tmp_path).execution_engine._runtime_store

    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow("s1", "runner", T0, LEASE))
    assert isinstance(claimed, Claimed)
    with store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", claimed.generation, T0, {"k": 1}))

    assert cast("SqliteRuntimeStore", store).driver.query(
        "SELECT key FROM scope_state"
    ) == [("k",)]


# -- the records slice: start / record_step / record_branch / move ---------


def test_start_creates_the_scope_running_with_entry_and_digest(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.start(StartWalk("s1", held, "my-flow", "first", "digest-1", T0))

    assert _row(
        store, "SELECT workflow, status, position, graph_digest FROM workflow_scopes"
    ) == [("my-flow", "running", "first", "digest-1")]


def test_start_keeps_a_held_position_and_the_first_digest(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.start(StartWalk("s1", held, "f", "first", "digest-1", T0))
    with store.transaction() as tx:
        tx.workflows.move(MoveScope("s1", held, "blocked", "gate-1", T0))
    with store.transaction() as tx:
        tx.workflows.start(StartWalk("s1", held, "f", "first", "digest-2", T0))

    assert _row(
        store, "SELECT position, graph_digest, status FROM workflow_scopes"
    ) == [("gate-1", "digest-1", "running")]


def test_record_step_persists_the_step_metadata_columns(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.record_step(
            RecordStep(
                "s1",
                held,
                "__epilogue__",
                T0,
                T0,
                result="done",
                reusable=True,
                result_kind="json",
                result_type="str",
                inputs={"n": 1},
                effecting=True,
            )
        )

    assert _row(
        store,
        "SELECT step_key, status, result, reusable, result_kind, result_type, "
        "inputs, effecting FROM workflow_steps",
    ) == [("__epilogue__", "success", '"done"', 1, "json", "str", '{"n": 1}', 1)]
    assert store.workflows.step("s1", "__epilogue__").result == "done"  # type: ignore[union-attr]
    [view] = store.workflows.steps("s1")
    assert view.reusable and view.effecting and view.result_kind == "json"


def test_an_attempt_round_trips_through_record_and_complete(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    started = T0 - timedelta(seconds=30)
    with store.transaction() as tx:
        tx.workflows.record_step(
            RecordStep(
                "s1",
                held,
                "charge::",
                T0,
                None,
                status="attempting",
                effecting=True,
                attempt=2,
                started_at=started,
            )
        )
    attempting = store.workflows.step("s1", "charge::")
    assert attempting is not None and attempting.status == "attempting"
    assert (attempting.attempt, attempting.started_at) == (2, started)
    assert attempting.completed_at is None

    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep(
                "s1",
                held,
                "charge::",
                T0,
                effecting=True,
                attempt=2,
                started_at=started,
            )
        )
    assert _row(
        store, "SELECT status, attempt, started_at, completed_at FROM workflow_steps"
    ) == [("success", 2, iso(started), iso(T0))]
    [done] = store.workflows.steps("s1")
    assert (done.attempt, done.started_at) == (2, started)


def test_a_pure_step_stores_attempt_0_and_no_start(store: SqliteRuntimeStore) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.complete_step(CompleteStep("s1", held, "pure::", T0, result="v"))

    assert _row(store, "SELECT attempt, started_at FROM workflow_steps") == [(0, None)]
    view = store.workflows.step("s1", "pure::")
    assert view is not None and (view.attempt, view.started_at) == (0, None)


def _consumed(store: SqliteRuntimeStore, gen: int, request_id: str) -> None:
    """A request answered and used, with the scope moved back to running."""
    _suspend(store, gen, request_id)
    with store.transaction() as tx:
        tx.inputs.append(
            GateCandidate(
                candidate_id=f"cand-{request_id}",
                request_id=request_id,
                ordinal=0,
                source="cli",
                submitted_at=T0,
                evaluation=CandidateEvaluation(outcome=EvaluationOutcome.ACCEPTED),
                payload={"approved": True},
            )
        )
    with store.transaction() as tx:
        tx.inputs.consume(ConsumeInput("s1", gen, request_id, T0))
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "noop", T0, position="approve")
        )


def _ask_again(
    store: SqliteRuntimeStore, gen: int, request_id: str, supersedes: str
) -> None:
    with store.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate(
                "s1",
                gen,
                "approve",
                request_id,
                "approve",
                T0 + timedelta(seconds=1),
                supersedes=supersedes,
            )
        )


def test_supersedes_opens_a_fresh_request_after_a_consumed_one(
    store: SqliteRuntimeStore,
) -> None:
    gen = _held(store)
    _consumed(store, gen, "req-1")
    _ask_again(store, gen, "req-2", supersedes="req-1")

    assert _row(store, "SELECT id, status FROM input_requests ORDER BY id") == [
        ("req-1", "consumed"),
        ("req-2", "open"),
    ]
    current = store.inputs.for_gate("s1", "approve")
    assert current is not None
    assert (current.request_id, current.status) == ("req-2", "open")

    with store.transaction() as tx:  # the replay reuses the fresh request
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "noop", T0, position="approve")
        )
    _ask_again(store, gen, "req-3", supersedes="req-1")
    assert _row(store, "SELECT id FROM input_requests ORDER BY id") == [
        ("req-1",),
        ("req-2",),
    ]


def test_supersedes_refuses_an_unconsumed_or_unknown_request(
    store: SqliteRuntimeStore,
) -> None:
    gen = _held(store)
    _consumed(store, gen, "req-1")
    with pytest.raises(ValueError, match="req-nonesuch"):
        _ask_again(store, gen, "req-2", supersedes="req-nonesuch")
    _ask_again(store, gen, "req-2", supersedes="req-1")
    with store.transaction() as tx:
        tx.inputs.append(
            GateCandidate(
                candidate_id="cand-2",
                request_id="req-2",
                ordinal=0,
                source="cli",
                submitted_at=T0,
                evaluation=CandidateEvaluation(outcome=EvaluationOutcome.ACCEPTED),
                payload={"approved": False},
            )
        )
        tx.workflows.complete_step(
            CompleteStep("s1", gen, "noop", T0, position="approve")
        )
    with pytest.raises(ValueError, match="not consumed"):
        _ask_again(store, gen, "req-3", supersedes="req-2")
    assert _row(store, "SELECT id, status FROM input_requests ORDER BY id") == [
        ("req-1", "consumed"),
        ("req-2", "accepted"),
    ]


def test_record_branch_replays_the_same_target_and_refuses_a_different_one(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.record_branch(RecordBranch("s1", held, "route", "b", T0))
    with store.transaction() as tx:  # the replay is a no-op
        tx.workflows.record_branch(RecordBranch("s1", held, "route", "b", T0))
    with pytest.raises(ValueError, match="route"), store.transaction() as tx:
        tx.workflows.record_branch(RecordBranch("s1", held, "route", "c", T0))

    assert store.workflows.branch("s1", "route") == "b"
    assert _row(store, "SELECT COUNT(*) FROM workflow_branches") == [(1,)]


def test_move_writes_status_position_and_terminal_at(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.start(StartWalk("s1", held, "f", "first", "d", T0))
    with store.transaction() as tx:
        tx.workflows.move(MoveScope("s1", held, "blocked", "gate-1", T0))

    assert _row(store, "SELECT status, position FROM workflow_scopes") == [
        ("blocked", "gate-1")
    ]


def test_a_stale_generation_lands_nothing_for_the_new_writers(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    _claim(store, "b", force=True)  # generation 2; the first holder is stale

    with pytest.raises(StaleGenerationError), store.transaction() as tx:
        tx.workflows.record_step(RecordStep("s1", held, "late", T0, T0))
    with pytest.raises(StaleGenerationError), store.transaction() as tx:
        tx.workflows.move(MoveScope("s1", held, "blocked", "gate-9", T0))

    assert _row(store, "SELECT COUNT(*) FROM workflow_steps") == [(0,)]
    assert _row(store, "SELECT position FROM workflow_scopes") == [(None,)]


def test_for_gate_tracks_the_gate_request_across_statuses(
    store: SqliteRuntimeStore,
) -> None:
    """One gate keeps one request id (the reuse rule), and `for_gate` finds
    it whatever its status; newest-wins is pinned against a second row."""
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.suspend(SuspendAtGate("s1", held, "ask", "req-1", "gate-1", T0))

    found = store.inputs.for_gate("s1", "ask")
    assert found is not None and found.request_id == "req-1"  # open

    with store.transaction() as tx:
        tx.inputs.append(
            GateCandidate(
                candidate_id="cand-1",
                request_id="req-1",
                ordinal=0,
                source="cli",
                submitted_at=T0,
                evaluation=CandidateEvaluation(outcome=EvaluationOutcome.ACCEPTED),
                payload={"answer": "one"},
            )
        )
    assert store.inputs.for_gate("s1", "ask").request_id == "req-1"  # accepted
    with store.transaction() as tx:
        tx.inputs.consume(ConsumeInput("s1", held, "req-1", T0))
    assert store.inputs.for_gate("s1", "ask").request_id == "req-1"  # consumed
    assert store.inputs.for_gate("s1", "nonesuch") is None

    # A second, later row for the same gate answers as the newest — pinned
    # directly because the writer's reuse rule would keep the first id.
    store.driver.batch(
        [
            (
                "INSERT INTO input_requests (id, namespace_id, scope_id, gate_key, "
                "generation, status, created_at) VALUES "
                "('req-9', 'default', 's1', 'ask', 7, 'open', ?)",
                # Written as the store writes timestamps (`iso`), and later:
                # text order is time order only in that one fixed-width form.
                (iso(T0 + timedelta(seconds=1)),),
            )
        ]
    )
    assert store.inputs.for_gate("s1", "ask").request_id == "req-9"


def test_deposited_answer_is_none_a_fact_about_this_store(
    store: SqliteRuntimeStore,
) -> None:
    held = _held(store)
    with store.transaction() as tx:
        tx.workflows.suspend(SuspendAtGate("s1", held, "ask", "req-1", "gate-1", T0))
    with store.transaction() as tx:
        tx.inputs.append(
            GateCandidate(
                candidate_id="cand-1",
                request_id="req-1",
                ordinal=0,
                source="cli",
                submitted_at=T0,
                evaluation=CandidateEvaluation(outcome=EvaluationOutcome.ACCEPTED),
                payload={"answer": "yes"},
            )
        )

    assert store.inputs.deposited_answer("s1", "ask") is None


def test_an_imported_legacy_deposit_resumes_from_its_legacy_candidate(
    tmp_path: Path,
) -> None:
    """R-1's SQLite gate: a bare legacy payload becomes the accepted
    `#legacy` candidate, and `deposited_answer` is None there."""
    from functualize_substrate_sqlite._legacy_import import Outcome, import_legacy
    from functualize_substrate_sqlite.substrate import SQLiteSubstrate

    from functualize._primitives.document_store import DocumentRuntimeStore

    db = tmp_path / "state.db"
    legacy = DocumentRuntimeStore(SQLiteSubstrate(db))
    claimed = _claim(cast("SqliteRuntimeStore", legacy))  # type: ignore[arg-type]
    assert isinstance(claimed, Claimed)
    with legacy.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate("s1", claimed.generation, "ask", "req-1", "gate-1", T0)
        )
    from functualize._primitives.scope_store import ScopeStore

    ScopeStore(SQLiteSubstrate(db)).deposit_gate_payload(
        "s1", "ask", {"answer": "legacy"}
    )
    legacy.close()

    report = import_legacy(db)
    assert report.outcome is Outcome.IMPORTED, report.text()

    config = RuntimeStoreConfig(
        url=f"sqlite://{db}", scheme="sqlite", project_root=tmp_path
    )
    store = cast(
        "SqliteRuntimeStore", SqliteRuntimeStoreFactory().prepare(config).store
    )
    assert store.inputs.deposited_answer("s1", "ask") is None
    found = store.inputs.for_gate("s1", "ask")
    assert found is not None
    candidates = store.inputs.candidates_for(found.request_id)
    assert [c.candidate_id for c in candidates] == [f"{found.request_id}#legacy"]
    assert candidates[0].payload == {"answer": "legacy"}
