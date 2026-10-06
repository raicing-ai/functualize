"""``functualize-sqlite-import`` (task 17): the console script, end to end.

Run as the installed console script in a subprocess — the entry point is the
call path, so removing ``[project.scripts]`` turns these red (the sabotage
proof that ticks tasks 16 and 17). Exit codes are `contracts.md` §6's. The
command runs while boot refuses with ``LegacyImportRequired``, and afterwards
boot with ``sqlite:`` succeeds.
"""

from __future__ import annotations

import fcntl
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from functualize_substrate_sqlite import (
    LegacyImportRequired,
    SqliteRuntimeStore,
    SQLiteSubstrate,
    SQLiteSubstratePlugin,
    _import_cli,
    _legacy_import,
)
from functualize_substrate_sqlite._legacy_verify import VerifyError

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.scope_store import ScopeStore
from functualize.app.config import ConfigSources, JobSources, PluginSources
from tests.test_legacy_import import T0, _legacy

SCRIPT = Path(sys.executable).parent / "functualize-sqlite-import"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args], capture_output=True, text=True, timeout=120
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _boot(db: Path) -> FunctualizeApp:
    def alpha() -> None:
        """A job."""

    return FunctualizeApp(
        "import-cli",
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


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "state.db"
    _legacy(path)
    return path


def test_the_console_script_is_installed() -> None:
    assert SCRIPT.is_file(), f"{SCRIPT} is not installed; [project.scripts] is missing"


def test_it_runs_while_boot_refuses_and_after_it_boot_succeeds(db: Path) -> None:
    with pytest.raises(LegacyImportRequired, match="functualize-sqlite-import"):
        _boot(db)

    done = _run("--db", str(db))

    assert done.returncode == 0, done.stderr
    assert "imported and verified" in done.stdout and "backup kept at" in done.stdout
    store = _boot(db).execution_engine._runtime_store
    assert isinstance(store, SqliteRuntimeStore)
    view = store.workflows.workflow("walk-1")
    assert view is not None and view.status == "blocked"


def test_dry_run_changes_nothing(db: Path) -> None:
    digest = _digest(db)

    done = _run("--db", str(db), "--dry-run")

    assert done.returncode == 0, done.stderr
    assert "dry run" in done.stdout
    assert _digest(db) == digest
    assert list(db.parent.glob("*.bak")) == []


def test_refused_records_are_exit_3_and_listed(db: Path) -> None:
    scopes = ScopeStore(SQLiteSubstrate(db))
    scopes.ensure_scope("b4", "wf")
    scopes.claim_scope("b4", owner="ghost", seconds=3600, now=T0)
    scopes.set_scope_status("b4", "completed")
    digest = _digest(db)

    done = _run("--db", str(db))

    assert done.returncode == 3
    assert "scope b4" in done.stderr
    assert _digest(db) == digest


def test_a_held_lock_is_exit_5(db: Path) -> None:
    with (db.parent / f"{db.name}.import.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert _run("--db", str(db)).returncode == 5


def test_project_resolves_the_default_database(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / ".functualize").mkdir(parents=True)
    _legacy(project / ".functualize" / "state.db")

    done = _run("--project", str(project), "--dry-run")

    assert done.returncode == 0, done.stderr
    assert "found 2 scope(s)" in done.stdout


def test_resume_without_an_import_is_a_usage_error(db: Path) -> None:
    assert _run("--db", str(db), "--resume").returncode == 2


def test_a_failed_verification_is_exit_4(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disagree(*_: object) -> None:
        raise VerifyError("injected")

    monkeypatch.setattr(_legacy_import, "verify_rows", disagree)

    assert _import_cli.main(["--db", str(db)]) == 4
    assert SQLiteSubstrate(db).read("scopes") is not None
