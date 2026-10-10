"""The legacy import (task 16): seven steps, one authority at every instant.

Gates: a legal fixture imports and verifies (AC-3); a ``completed`` scope still
holding a live lease is refused and listed, with the source file byte-for-byte
unchanged (AC-4, E-4); a process killed at each of the seven steps leaves
exactly one of {the documents authoritative, the cutover marker present}, and
the next run finishes the job (E-5); a second run is a no-op.

The fixture is written the way legacy data was: the document store over a
`SQLiteSubstrate`, plus a bare-payload deposit through the legacy helper.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from functualize_substrate_sqlite import SQLiteSubstrate
from functualize_substrate_sqlite._legacy_import import (
    STEPS,
    Mode,
    Outcome,
    import_legacy,
)

from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.scope_store import ScopeStore
from functualize._types.gate_resolution import (
    CandidateEvaluation,
    EvaluationOutcome,
    GateCandidate,
)
from functualize.plugin import (
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    FinishAttempt,
    RunQuery,
    StartAttempt,
    StateBatch,
    SuspendAtGate,
)

T0 = datetime.now(UTC).replace(microsecond=0)


def _legacy(db: Path) -> None:
    """A project that ran on the plugin before selection was configuration."""
    store = DocumentRuntimeStore(SQLiteSubstrate(db))
    with store.transaction() as tx:
        claimed = tx.workflows.claim(ClaimWorkflow("walk-1", "runner", T0, 60.0))
    assert isinstance(claimed, Claimed)
    gen = claimed.generation
    with store.transaction() as tx:
        tx.workflows.complete_step(
            CompleteStep(
                "walk-1",
                gen,
                "first",
                T0,
                result={"rows": 3},
                decision_key="pick",
                chosen_target="gate",
                position="gate",
            )
        )
        tx.workflows.write_state(
            StateBatch("walk-1", gen, T0, {"rows": 3, "name": "x"})
        )
        tx.events.append("walk.note", {"n": 1})
    with store.transaction() as tx:
        tx.workflows.suspend(
            SuspendAtGate(
                "walk-1",
                gen,
                "approve",
                "req-1",
                "approve",
                T0,
                schema={"type": "object"},
            )
        )
    with store.transaction() as tx:
        tx.inputs.append(
            GateCandidate(
                "cand-1",
                "req-1",
                0,
                "human",
                T0,
                CandidateEvaluation(EvaluationOutcome.ACCEPTED),
                {"ok": True},
            )
        )
    with store.transaction() as tx:
        tx.runs.start_attempt(StartAttempt("build", "cli", T0, scope_id="walk-1"))
    [run] = store.runs.recent(RunQuery(job="build"))
    with store.transaction() as tx:
        tx.events.append("run.note", {"m": 2}, run_id=run.run_id)
        tx.runs.finish_attempt(
            FinishAttempt(run.run_id, 1, "success", T0 + timedelta(seconds=1))
        )
    # A gate answered through the legacy deposit helper: a bare payload, no candidate.
    scopes = ScopeStore(SQLiteSubstrate(db))
    scopes.ensure_scope("walk-2", "other")
    scopes.put_gate("walk-2", "ok", {"status": "open", "candidates": []})
    scopes.deposit_gate_payload("walk-2", "ok", {"answer": 42})
    SQLiteSubstrate(db).write("fresh", {"entries": {}})


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(db: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "workflow_scopes" not in tables:
            return []
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _authority(db: Path) -> str:
    """Which side is authoritative — and that it is exactly one."""
    marker = _rows(db, "SELECT count(*) FROM runtime_cutover")
    imported = _rows(db, "SELECT count(*) FROM workflow_scopes") + _rows(
        db, "SELECT count(*) FROM runs"
    )
    has_marker = bool(marker) and marker[0][0] == 1
    has_rows = any(n for (n,) in imported)
    assert has_marker == has_rows, (
        f"marker {marker} but imported rows {imported}: two authorities"
    )
    return "relational" if has_marker else "documents"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / ".functualize" / "state.db"
    path.parent.mkdir()
    _legacy(path)
    return path


def test_a_legal_fixture_imports_and_verifies(db: Path) -> None:
    report = import_legacy(db)

    assert report.outcome is Outcome.IMPORTED, report.text()
    assert _authority(db) == "relational"
    assert _rows(
        db,
        "SELECT id, status, position, lease_generation FROM workflow_scopes ORDER BY id",
    ) == [
        ("walk-1", "blocked", "approve", 1),
        ("walk-2", "running", None, 0),
    ]
    assert _rows(db, "SELECT status FROM runs") == [("success",)]
    assert _rows(db, "SELECT attempt_no, status FROM run_attempts") == [
        (1, "succeeded")
    ]
    assert _rows(db, "SELECT key FROM scope_state ORDER BY key") == [
        ("name",),
        ("rows",),
    ]
    assert _rows(db, "SELECT decision_key, chosen_target FROM workflow_branches") == [
        ("pick", "gate")
    ]
    assert _rows(db, "SELECT id, status FROM input_requests ORDER BY id") == [
        ("req-1", "accepted"),
        ("walk-2::ok", "accepted"),
    ]
    assert _rows(db, "SELECT source, outcome FROM input_candidates ORDER BY id") == [
        ("human", "accepted"),
        ("legacy-import", "accepted"),
    ]
    assert report.backup is not None and report.backup.is_file()
    assert "bounded history" in report.text()
    assert _rows(db, "SELECT count(*) FROM run_events") == [(1,)]
    # Derived documents stay where they were.
    assert SQLiteSubstrate(db).read("fresh") is not None


def test_a_second_run_is_a_no_op(db: Path) -> None:
    first = import_legacy(db)
    tables = (
        "workflow_scopes",
        "runs",
        "input_requests",
        "input_candidates",
        "scope_state",
        "scope_events",
    )
    before = {t: _rows(db, f"SELECT count(*) FROM {t}") for t in tables}
    backups = sorted(db.parent.glob("*.bak"))

    again = import_legacy(db)

    assert (first.outcome, again.outcome) == (Outcome.IMPORTED, Outcome.IMPORTED)
    assert "already recorded" in again.text()
    assert {t: _rows(db, f"SELECT count(*) FROM {t}") for t in tables} == before
    assert sorted(db.parent.glob("*.bak")) == backups


def test_a_terminal_scope_holding_a_live_lease_is_refused_and_the_source_untouched(
    db: Path,
) -> None:
    scopes = ScopeStore(SQLiteSubstrate(db))
    scopes.ensure_scope("b4", "wf")
    scopes.claim_scope("b4", owner="ghost", seconds=3600, now=T0)
    scopes.set_scope_status("b4", "completed")
    digest = _digest(db)

    report = import_legacy(db)

    assert report.outcome is Outcome.REFUSED
    assert "scope b4: 'completed' yet holding a live lease" in report.text()
    assert _digest(db) == digest
    assert _authority(db) == "documents"
    assert list(db.parent.glob("*.bak")) == []


def test_dry_run_writes_nothing(db: Path) -> None:
    digest = _digest(db)

    report = import_legacy(db, dry_run=True)

    assert report.outcome is Outcome.IMPORTED and "dry run" in report.text()
    assert _digest(db) == digest
    assert list(db.parent.glob("*.bak")) == []


def test_a_failed_verification_rolls_back(db: Path) -> None:
    def tamper(step: int) -> None:
        if step == 3:
            conn = sqlite3.connect(db)
            conn.execute(
                "UPDATE workflow_scopes SET position = 'tampered' WHERE id = 'walk-1'"
            )
            conn.commit()
            conn.close()

    report = import_legacy(db, on_step=tamper)

    assert report.outcome is Outcome.VERIFY_FAILED, report.text()
    assert _authority(db) == "documents"


def test_a_held_lock_is_exit_5(db: Path) -> None:
    import fcntl

    with (db.parent / f"{db.name}.import.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert import_legacy(db).outcome is Outcome.LOCKED


def test_rollback_restores_the_documents_as_authority(db: Path) -> None:
    import_legacy(db)

    report = import_legacy(db, mode=Mode.ROLLBACK)

    assert report.outcome is Outcome.IMPORTED, report.text()
    assert _authority(db) == "documents"


def _die_at(db: str, step: int) -> None:
    def kill(n: int) -> None:
        if n == step:
            os._exit(9)

    import_legacy(Path(db), on_step=kill)
    os._exit(0)


@pytest.mark.parametrize("step", range(1, len(STEPS) + 1), ids=list(STEPS))
def test_killed_at_any_step_one_authority_holds_and_the_next_run_finishes(
    db: Path, step: int
) -> None:
    child = multiprocessing.get_context("fork").Process(
        target=_die_at, args=(str(db), step)
    )
    child.start()
    child.join(timeout=120)
    assert child.exitcode == 9, f"the import did not reach step {step}"

    authority = _authority(db)
    assert authority == ("documents" if step < 3 else "relational")

    report = import_legacy(db)
    assert report.outcome is Outcome.IMPORTED, report.text()
    assert _authority(db) == "relational"
    assert _rows(db, "SELECT count(*) FROM workflow_scopes") == [(2,)]
