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

import pytest
from functualize_substrate_sqlite import SqliteRuntimeStore, SQLiteSubstratePlugin
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.lease import LeaseHeldError, StaleGenerationError
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.plugin import (
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    Conflict,
    IllegalTransition,
    ResumeWorkflow,
    RuntimeStoreConfig,
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


def test_the_holder_may_retake_its_own_lease(store: SqliteRuntimeStore) -> None:
    """Data model §5's rule: ``lease_owner = :runner OR expired``."""
    _held(store, "a")

    again = _claim(store, "a")

    assert isinstance(again, Claimed)
    assert again.generation == 2


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
