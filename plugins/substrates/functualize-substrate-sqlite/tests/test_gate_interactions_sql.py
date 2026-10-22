"""Gate interactions on the relational schema (revision 0003).

Gates: evidence is an ``artifact_refs`` row — a reference and a digest, never
bytes; a decision lives in ``input_decisions`` with its observations in
order; an accepted candidate, its decision and its outbox intent are one batch
— all three or none (AC-1); a revision-2 file migrates with every row intact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory
from functualize_substrate_sqlite._migrations import SHIPPED_MIGRATIONS, migrate

from functualize._engine.recording import InputRecorder
from functualize._engine.recording.input_recorder import content_digest
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    EvidenceRef,
)
from functualize.plugin import Claimed, ClaimWorkflow, RuntimeStoreConfig

if TYPE_CHECKING:
    from functualize_substrate_sqlite import SqliteRuntimeStore

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
EVIDENCE = EvidenceRef("artifact://ev_5", content_digest(b"png bytes"), "image/png", 9)


@pytest.fixture
def store(tmp_path: Path) -> SqliteRuntimeStore:
    config = RuntimeStoreConfig(
        url=f"sqlite://{tmp_path / 'state.db'}", scheme="sqlite", project_root=tmp_path
    )
    return cast("SqliteRuntimeStore", SqliteRuntimeStoreFactory().prepare(config).store)


def _rows(store: SqliteRuntimeStore, sql: str, *args: object) -> list[tuple[Any, ...]]:
    return store.driver.query(sql, args)


def _open(store: SqliteRuntimeStore) -> str:
    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow("wf_42", "walker", T0, 60.0))
    assert isinstance(claimed, Claimed)
    command = InputRecorder().opened(
        scope_id="wf_42",
        generation=claimed.generation,
        gate_name="approval",
        position="approval",
        now=T0,
        run_id="run_4",
    )
    with store.transaction() as tx:
        tx.workflows.suspend(command)
    return command.request_id


def _accept_unit(store: SqliteRuntimeStore, request_id: str, *, fail: bool) -> str:
    recorder = InputRecorder()
    accepted = recorder.submitted(
        request_id,
        "cli",
        CandidateEvaluation(EvaluationOutcome.ACCEPTED),
        {"approved": True},
        ordinal=0,
        now=T0,
        evidence=[EVIDENCE],
    )
    decision = recorder.decided(
        request_id,
        [accepted],
        accepted.candidate_id,
        policy_id="gate.validate",
        policy_version="v",
        now=T0,
    )
    intent = recorder.accepted_effect(decision, scope_id="wf_42", gate_name="approval")
    with store.transaction() as tx:
        tx.inputs.append(accepted)
        tx.inputs.decide(decision)
        tx.effects.append(
            intent.namespace, intent.topic, intent.payload, intent.idempotency_key
        )
        if fail:
            raise RuntimeError("the unit dies before commit")
    return accepted.candidate_id


def test_evidence_is_a_reference_row_never_bytes(store: SqliteRuntimeStore) -> None:
    candidate_id = _accept_unit(store, _open(store), fail=False)

    assert _rows(
        store,
        "SELECT kind, uri, digest, media_type, size, candidate_id, scope_id, step_key "
        "FROM artifact_refs",
    ) == [
        (
            "gate-evidence",
            "artifact://ev_5",
            EVIDENCE.digest,
            "image/png",
            9,
            candidate_id,
            "wf_42",
            "approval",
        )
    ]
    # Nothing in the candidate row carries the evidence: no column holds it.
    [(evidence,)] = _rows(store, "SELECT evidence FROM input_candidates")
    assert evidence is None


def test_the_candidate_its_decision_and_its_intent_commit_together(
    store: SqliteRuntimeStore,
) -> None:
    request_id = _open(store)

    candidate_id = _accept_unit(store, request_id, fail=False)

    assert _rows(store, "SELECT status FROM input_requests") == [("accepted",)]
    assert _rows(store, "SELECT accepted_id FROM input_decisions") == [(candidate_id,)]
    assert _rows(
        store, "SELECT candidate_id FROM input_decision_observations ORDER BY position"
    ) == [(candidate_id,)]
    assert _rows(
        store, "SELECT topic, idempotency_key, status, aggregate_id FROM outbox"
    ) == [("gate.accepted", f"gate.accepted:{request_id}", "pending", "wf_42")]


def test_a_unit_that_dies_before_commit_leaves_none_of_the_three(
    store: SqliteRuntimeStore,
) -> None:
    request_id = _open(store)

    with pytest.raises(RuntimeError, match="dies before commit"):
        _accept_unit(store, request_id, fail=True)

    assert _rows(store, "SELECT status FROM input_requests") == [("open",)]
    assert _rows(store, "SELECT count(*) FROM input_candidates") == [(0,)]
    assert _rows(store, "SELECT count(*) FROM input_decisions") == [(0,)]
    assert _rows(store, "SELECT count(*) FROM outbox") == [(0,)]
    assert _rows(store, "SELECT count(*) FROM artifact_refs") == [(0,)]


def test_decisions_are_append_only(store: SqliteRuntimeStore) -> None:
    _accept_unit(store, _open(store), fail=False)

    with pytest.raises(Exception, match="append-only"):
        store.driver.batch([("UPDATE input_decisions SET policy_id = 'forged'", ())])


def test_a_revision_2_file_migrates_with_its_rows_intact(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    driver = LocalSqliteDriver(path)
    try:
        assert migrate(driver, SHIPPED_MIGRATIONS[:2]) == 2
        driver.batch(
            [
                ("INSERT INTO namespaces VALUES ('default', 'default', 'now')", ()),
                (
                    "INSERT INTO workflow_scopes (namespace_id, id, workflow, status, "
                    "lease_generation, created_at, updated_at) VALUES "
                    "('default', 'wf', 'w', 'blocked', 1, 'now', 'now')",
                    (),
                ),
                (
                    "INSERT INTO input_requests (id, namespace_id, scope_id, gate_key, "
                    "generation, status, created_at) VALUES "
                    "('req_old', 'default', 'wf', 'g', 1, 'open', 'now')",
                    (),
                ),
            ]
        )
        assert migrate(driver) == 4
        assert driver.query(
            "SELECT id, status, run_id, position FROM input_requests"
        ) == [("req_old", "open", None, None)]
    finally:
        driver.close()


def test_revision_4_is_shipped_verbatim() -> None:
    sql = (
        resources.files("functualize_substrate_sqlite")
        .joinpath("_schema", "0004_gate_interactions.sql")
        .read_text(encoding="utf-8")
    )
    assert SHIPPED_MIGRATIONS[3].sql == sql
    # Additive only: every statement creates or alters, nothing drops.
    assert "DROP " not in sql.upper()
