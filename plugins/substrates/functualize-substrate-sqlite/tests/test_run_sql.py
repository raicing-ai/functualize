"""Run, input, event and effect writers over SQLite (task 9).

Gates: an attempt is unique per ``(run_id, attempt_no)``; event ``seq`` is
strictly increasing per run and per scope; one OPEN input request per gate
per generation; an outbox row commits only with its transition.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from functualize_substrate_sqlite import SqliteRuntimeStore, SQLiteSubstratePlugin
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.lease import StaleGenerationError
from functualize._types.errors import InputRequestNotOpenError
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    ConsumeInput,
    FinishAttempt,
    IllegalTransition,
    RuntimeStoreConfig,
    StartAttempt,
    StateBatch,
    SuspendAtGate,
)

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> SqliteRuntimeStore:
    config = RuntimeStoreConfig(
        url=f"sqlite://{tmp_path / 'state.db'}", scheme="sqlite", project_root=tmp_path
    )
    return cast("SqliteRuntimeStore", SqliteRuntimeStoreFactory().prepare(config).store)


def _rows(store: SqliteRuntimeStore, sql: str, *args: object) -> list[tuple[Any, ...]]:
    return store.driver.query(sql, args)


def _start(store: SqliteRuntimeStore, job: str = "build") -> str:
    with store.transaction() as tx:
        tx.runs.start_attempt(StartAttempt(job, "cli", T0, args_hash="h"))
    [(run_id,)] = _rows(store, "SELECT id FROM runs WHERE job = ?", job)
    return str(run_id)


def _claimed(store: SqliteRuntimeStore) -> int:
    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow("s1", "a", T0, 60.0))
    assert isinstance(claimed, Claimed)
    return claimed.generation


def _gate(store: SqliteRuntimeStore, request_id: str = "req-1") -> int:
    gen = _claimed(store)
    with store.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate("s1", gen, "approve", request_id, "approve", T0)
        )
    return gen


def _candidate(
    n: int, outcome: EvaluationOutcome, request_id: str = "req-1"
) -> GateCandidate:
    return GateCandidate(
        candidate_id=f"c{n}",
        request_id=request_id,
        ordinal=n,
        source="human",
        submitted_at=T0,
        evaluation=CandidateEvaluation(
            outcome=outcome, detail="d", errors=(("f", "bad"),)
        ),
        payload={"answer": n},
    )


# -- runs and attempts -----------------------------------------------------------


def test_start_opens_the_run_and_attempt_1(store: SqliteRuntimeStore) -> None:
    run_id = _start(store)

    assert _rows(store, "SELECT job, surface, status, args_hash FROM runs") == [
        ("build", "cli", "running", "h")
    ]
    assert _rows(store, "SELECT run_id, attempt_no, status FROM run_attempts") == [
        (run_id, 1, "running")
    ]


@pytest.mark.parametrize(
    ("sent", "run", "attempt"),
    [
        ("success", "success", "succeeded"),
        ("Failure", "failure", "failed"),
        ("succeeded", "success", "succeeded"),
    ],
)
def test_finish_settles_attempt_and_run_in_both_vocabularies(
    store: SqliteRuntimeStore, sent: str, run: str, attempt: str
) -> None:
    run_id = _start(store)
    with store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt(run_id, 1, sent, T0, failure_code="E1"))

    assert _rows(store, "SELECT status FROM runs") == [(run,)]
    assert _rows(store, "SELECT status, failure_code FROM run_attempts") == [
        (attempt, "E1")
    ]


def test_a_retry_inserts_the_next_attempt_beside_the_first(
    store: SqliteRuntimeStore,
) -> None:
    run_id = _start(store)
    with store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt(run_id, 1, "blocked", T0))
    with store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt(run_id, 2, "success", T0))

    assert _rows(
        store, "SELECT attempt_no, status FROM run_attempts ORDER BY attempt_no"
    ) == [
        (1, "running"),
        (2, "succeeded"),
    ]


def test_an_attempt_is_unique_per_run_and_number(store: SqliteRuntimeStore) -> None:
    run_id = _start(store)

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        store.driver.batch(
            [
                (
                    "INSERT INTO run_attempts (id, namespace_id, run_id, attempt_no, status, "
                    "started_at) VALUES ('dup', 'default', ?, 1, 'running', 'now')",
                    (run_id,),
                )
            ]
        )


def test_a_terminal_run_is_never_moved_again(store: SqliteRuntimeStore) -> None:
    run_id = _start(store)
    with store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt(run_id, 1, "success", T0))

    with pytest.raises(IllegalTransition), store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt(run_id, 1, "failure", T0))


def test_finishing_a_run_never_opened_is_ignored(store: SqliteRuntimeStore) -> None:
    with store.transaction() as tx:
        tx.runs.finish_attempt(FinishAttempt("run-missing", 1, "success", T0))

    assert _rows(store, "SELECT count(*) FROM runs") == [(0,)]


# -- events ----------------------------------------------------------------


def test_run_and_scope_event_seq_is_strictly_increasing_per_owner(
    store: SqliteRuntimeStore,
) -> None:
    one, two = _start(store, "one"), _start(store, "two")
    gen = _claimed(store)
    with store.transaction() as tx:
        for n in range(3):
            tx.events.append("tick", {"n": n}, run_id=one)
        tx.events.append("tick", None, run_id=two)
    with store.transaction() as tx:
        tx.events.append("tick", None, run_id=one)
    for n in range(2):
        with store.transaction() as tx:
            tx.workflows.write_state(_noop_state(gen))
            tx.events.append("walked", {"n": n})

    assert _rows(
        store, "SELECT seq FROM run_events WHERE run_id = ? ORDER BY rowid", one
    ) == [(1,), (2,), (3,), (4,)]
    assert _rows(store, "SELECT seq FROM run_events WHERE run_id = ?", two) == [(1,)]
    assert _rows(store, "SELECT seq, type FROM scope_events ORDER BY seq") == [
        (1, "walked"),
        (2, "walked"),
    ]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.driver.batch([("UPDATE scope_events SET type = 'rewritten'", ())])


def _noop_state(gen: int) -> StateBatch:
    """A fenced write that marks ``s1`` as this unit's scope and changes nothing."""
    return StateBatch("s1", gen, T0, {})


def test_an_event_naming_no_run_needs_exactly_one_scope(
    store: SqliteRuntimeStore,
) -> None:
    with pytest.raises(ValueError, match="no single log"), store.transaction() as tx:
        tx.events.append("orphan")


# -- inputs ----------------------------------------------------------------


def test_one_open_request_per_gate_and_generation(store: SqliteRuntimeStore) -> None:
    gen = _gate(store, "req-1")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        store.driver.batch(
            [
                (
                    "INSERT INTO input_requests (id, namespace_id, scope_id, gate_key, "
                    "generation, status, created_at) VALUES ('req-2', 'default', 's1', "
                    "'approve', ?, 'open', 'now')",
                    (gen,),
                )
            ]
        )


def test_an_accepted_candidate_answers_the_request_once(
    store: SqliteRuntimeStore,
) -> None:
    _gate(store)
    with store.transaction() as tx:
        tx.inputs.append(_candidate(1, EvaluationOutcome.INVALID))
        tx.inputs.append(_candidate(2, EvaluationOutcome.ACCEPTED))
        tx.inputs.append(_candidate(3, EvaluationOutcome.NOT_REACHED))

    assert _rows(store, "SELECT status FROM input_requests") == [("accepted",)]
    assert _rows(
        store,
        "SELECT ordinal, outcome, errors, payload FROM input_candidates ORDER BY ordinal",
    ) == [
        (1, "invalid", '[["f", "bad"]]', '{"answer": 1}'),
        (2, "accepted", '[["f", "bad"]]', '{"answer": 2}'),
        (3, "not_reached", '[["f", "bad"]]', '{"answer": 3}'),
    ]
    with pytest.raises(InputRequestNotOpenError), store.transaction() as tx:
        tx.inputs.append(_candidate(4, EvaluationOutcome.ACCEPTED))


def test_a_refused_candidate_applies_nothing_from_its_unit(
    store: SqliteRuntimeStore,
) -> None:
    gen = _gate(store)
    with store.transaction() as tx:
        tx.inputs.append(_candidate(1, EvaluationOutcome.ACCEPTED))

    with pytest.raises(InputRequestNotOpenError), store.transaction() as tx:
        tx.workflows.write_state(StateBatch("s1", gen, T0, {"k": 1}))
        tx.inputs.append(_candidate(2, EvaluationOutcome.INVALID))

    assert _rows(store, "SELECT count(*) FROM scope_state") == [(0,)]
    assert _rows(store, "SELECT count(*) FROM input_candidates") == [(1,)]


def test_a_candidate_for_a_missing_request_is_refused(
    store: SqliteRuntimeStore,
) -> None:
    with (
        pytest.raises(InputRequestNotOpenError, match="missing"),
        store.transaction() as tx,
    ):
        tx.inputs.append(_candidate(1, EvaluationOutcome.ACCEPTED, request_id="nope"))


def test_consume_is_fenced_and_idempotent(store: SqliteRuntimeStore) -> None:
    gen = _gate(store)
    with store.transaction() as tx:
        tx.inputs.append(_candidate(1, EvaluationOutcome.ACCEPTED))

    with pytest.raises(StaleGenerationError), store.transaction() as tx:
        tx.inputs.consume(ConsumeInput("s1", gen + 7, "req-1", T0))
    for _ in range(2):
        with store.transaction() as tx:
            tx.inputs.consume(ConsumeInput("s1", gen, "req-1", T0))

    assert _rows(store, "SELECT status FROM input_requests") == [("consumed",)]


def test_consuming_an_unanswered_request_is_refused(store: SqliteRuntimeStore) -> None:
    gen = _gate(store)

    with pytest.raises(ValueError, match="not accepted"), store.transaction() as tx:
        tx.inputs.consume(ConsumeInput("s1", gen, "req-1", T0))


# -- effects ----------------------------------------------------------------


def test_an_outbox_row_commits_only_with_its_transition(
    store: SqliteRuntimeStore,
) -> None:
    gen = _claimed(store)
    with pytest.raises(RuntimeError), store.transaction() as tx:
        tx.workflows.write_state(_noop_state(gen))
        tx.effects.append("workflow", "notify", {"to": "x"}, idempotency_key="k1")
        raise RuntimeError("the transition failed")
    assert _rows(store, "SELECT count(*) FROM outbox") == [(0,)]

    with store.transaction() as tx:
        tx.workflows.write_state(_noop_state(gen))
        tx.effects.append("workflow", "notify", {"to": "x"}, idempotency_key="k1")
    with store.transaction() as tx:
        tx.effects.append("workflow", "notify", {"to": "x"}, idempotency_key="k1")

    assert _rows(
        store, "SELECT aggregate_type, aggregate_id, topic, status FROM outbox"
    ) == [("workflow", "s1", "notify", "pending")]


def test_a_takeover_drops_the_fenced_transition_and_its_outbox_intent(
    store: SqliteRuntimeStore,
) -> None:
    gen = _claimed(store)
    with store.transaction() as stale:
        stale.workflows.write_state(StateBatch("s1", gen, T0, {"late": 1}))
        stale.effects.append("workflow", "notify", idempotency_key="stale")
        with store.transaction() as fresh:
            claimed = fresh.workflows.claim(
                ClaimWorkflow("s1", "new-owner", T0, 60.0, force=True)
            )
            assert isinstance(claimed, Claimed)

    assert _rows(store, "SELECT count(*) FROM scope_state") == [(0,)]
    assert _rows(store, "SELECT count(*) FROM outbox") == [(0,)]


# -- reachability: the boot-selected store ----------------------------------------


def test_a_boot_selected_store_writes_runs_inputs_events_and_effects(
    tmp_path: Path,
) -> None:
    """Task 9's call path: boot selects ``sqlite:``; the engine's store's
    ``transaction().runs`` / ``.inputs`` / ``.events`` / ``.effects`` are these writers."""

    def alpha() -> None:
        """A job."""

    app = FunctualizeApp(
        "run-sql",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [
                    DefaultSource(
                        {"runtime_store": {"url": f"sqlite://{tmp_path / 'state.db'}"}}
                    )
                ]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    store = cast("SqliteRuntimeStore", app.execution_engine._runtime_store)

    run_id = _start(store)
    _gate(store)
    with store.transaction() as tx:
        tx.events.append("started", run_id=run_id)
        tx.inputs.append(_candidate(1, EvaluationOutcome.ACCEPTED))
        tx.effects.append("workflow", "notify")

    assert _rows(store, "SELECT count(*) FROM run_events") == [(1,)]
    assert _rows(store, "SELECT count(*) FROM input_candidates") == [(1,)]
    assert _rows(store, "SELECT count(*) FROM outbox") == [(1,)]
