"""Marker provenance guards a selected relational store across boot boundaries."""

from __future__ import annotations

import hashlib
import multiprocessing
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from functualize_substrate_sqlite import (
    CutoverMarkerInvalid,
    LegacyImportRequired,
    SqliteRuntimeStoreFactory,
    SQLiteSubstrate,
    SQLiteSubstratePlugin,
)
from functualize_substrate_sqlite._factory import (
    BORN_RELATIONAL_DIGEST,
    default_database_path,
)
from functualize_substrate_sqlite._import_cli import main as import_main
from functualize_substrate_sqlite._legacy_import import (
    Outcome,
    _source_digest,
    import_legacy,
)

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.plugin import RuntimeStoreConfig
from functualize.types import RunRequest


def alpha() -> None:
    """One job that makes the framework write its run log."""


def _config(root: Path, db: Path) -> RuntimeStoreConfig:
    return RuntimeStoreConfig(url=f"sqlite://{db}", scheme="sqlite", project_root=root)


def _prepare(root: Path, db: Path) -> None:
    prepared = SqliteRuntimeStoreFactory().prepare(_config(root, db))
    prepared.store.close()


def _rows(db: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def _boot(project: Path, db: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeApp:
    monkeypatch.chdir(project)
    return FunctualizeApp(
        "marker-test",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [DefaultSource({"runtime_store": {"url": f"sqlite://{db}"}})]
            )
        ),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )


def _run_once(app: FunctualizeApp, db: Path) -> None:
    app.execute(RunRequest(job_name="alpha", surface="app.execute"))
    assert _rows(db, "SELECT key FROM documents WHERE key = 'runs'") == [("runs",)]


def test_fresh_file_boots_again_after_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "state.db"
    first = _boot(tmp_path, db, monkeypatch)
    assert _rows(
        db, "SELECT source, source_digest, backup_path FROM runtime_cutover"
    ) == [("born-relational", BORN_RELATIONAL_DIGEST, None)]
    _run_once(first, db)
    second = _boot(tmp_path, db, monkeypatch)
    assert second.execution_engine._runtime_store.profile.offline_capable
    assert _rows(db, "SELECT count(*) FROM runtime_cutover") == [(1,)]


def test_legacy_without_marker_is_still_refused(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    SQLiteSubstrate(db).write("runs", {"runs": []})
    digest = _source_digest(db)
    with pytest.raises(LegacyImportRequired, match="functualize-sqlite-import --db"):
        _prepare(tmp_path, db)
    assert _rows(db, "SELECT count(*) FROM runtime_cutover") == [(0,)]
    assert _source_digest(db) == digest


def test_imported_marker_boots(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    SQLiteSubstrate(db).write("runs", {"runs": []})
    report = import_legacy(db)
    assert report.outcome is Outcome.IMPORTED, report.text()
    assert _rows(db, "SELECT source FROM runtime_cutover") == [("documents",)]
    assert _rows(db, "SELECT key FROM documents WHERE key = 'runs'") == [("runs",)]
    _prepare(tmp_path, db)


def test_born_relational_marker_with_legacy_rows_boots(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    _prepare(tmp_path, db)
    SQLiteSubstrate(db).write("runs", {"runs": []})
    _prepare(tmp_path, db)
    assert _rows(db, "SELECT source FROM runtime_cutover") == [("born-relational",)]


@pytest.mark.parametrize(
    "mutation",
    [
        "INSERT INTO runtime_cutover VALUES ('documents', '2026-01-01T00:00:00+00:00', '"
        + "a" * 64
        + "', '/backup')",
        "UPDATE runtime_cutover SET source = 'unknown'",
        "UPDATE runtime_cutover SET source = 'documents', source_digest = '"
        + "a" * 64
        + "'",
        "UPDATE runtime_cutover SET source = 'documents', source_digest = 'wrong', backup_path = '/backup'",
        "UPDATE runtime_cutover SET backup_path = '/backup'",
        "UPDATE runtime_cutover SET source_digest = 'wrong'",
        "UPDATE runtime_cutover SET imported_at = 'not-a-date'",
    ],
    ids=[
        "two-rows",
        "unknown-source",
        "documents-no-backup",
        "documents-bad-digest",
        "born-with-backup",
        "born-bad-digest",
        "bad-time",
    ],
)
def test_degenerate_markers_are_refused(tmp_path: Path, mutation: str) -> None:
    db = tmp_path / "state.db"
    _prepare(tmp_path, db)
    with sqlite3.connect(db) as conn:
        conn.execute(mutation)
    with pytest.raises(CutoverMarkerInvalid) as failure:
        _prepare(tmp_path, db)
    message = str(failure.value)
    assert str(db) in message and "runtime_cutover marker" in message
    assert "Restore the database backup" in message
    assert f"functualize-sqlite-import --db {db}" in message


def _concurrent_prepare(root: str, db: str, barrier: Any, results: Any) -> None:
    barrier.wait()
    try:
        _prepare(Path(root), Path(db))
    except Exception as error:
        results.put(repr(error))
    else:
        results.put("ok")


def test_concurrent_first_prepare_writes_one_marker(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(
            target=_concurrent_prepare, args=(str(tmp_path), str(db), barrier, results)
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
    assert [worker.exitcode for worker in workers] == [0, 0]
    assert [results.get(timeout=2) for _ in workers] == ["ok", "ok"]
    assert _rows(db, "SELECT count(*) FROM runtime_cutover") == [(1,)]


def test_import_on_a_born_relational_file_is_a_no_op(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "state.db"
    _prepare(tmp_path, db)
    SQLiteSubstrate(db).write("runs", {"runs": []})
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    assert import_main(["--db", str(db)]) == 0
    assert "born relational; nothing to import" in capsys.readouterr().out
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert _rows(db, "SELECT source FROM runtime_cutover") == [("born-relational",)]


def test_unselected_data_on_a_born_relational_file_names_no_import(
    tmp_path: Path,
) -> None:
    factory = SqliteRuntimeStoreFactory()
    db = default_database_path(tmp_path)
    _prepare(tmp_path, db)
    detail = factory.unselected_data(tmp_path)
    assert detail is not None and str(db) in detail
    assert "functualize-sqlite-import" not in detail


def test_second_project_boots_after_first_project_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "shared.db"
    first_project = tmp_path / "project-a"
    second_project = tmp_path / "project-b"
    first_project.mkdir()
    second_project.mkdir()
    first = _boot(first_project, db, monkeypatch)
    _run_once(first, db)
    second = _boot(second_project, db, monkeypatch)
    assert second.execution_engine._runtime_store.profile.offline_capable
