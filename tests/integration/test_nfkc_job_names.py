"""Written Unicode job names reach their registered NFKC identities."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.discovery_report import JOB_NAME_COLLISION
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_app_state() -> None:
    AppState.reset()


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeApp:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "ungrouped.py").write_text(
        "from pathlib import Path\n"
        "from functualize.job import Deps, RunContext, RunStatus, job\n"
        "def job_aaǆ():\n"
        "    Path(__file__).with_name('child-ran').write_text('yes')\n"
        "def invoke_parent(rc: RunContext):\n"
        "    result = rc.invoke('job_aaǆ')\n"
        "    assert result.status is RunStatus.SUCCESS\n"
        "def parallel_parent(rc: RunContext):\n"
        "    results = rc.invoke_parallel([('job_aaǆ', {})])\n"
        "    assert [r.status for r in results] == [RunStatus.SUCCESS]\n"
        "@job(deps=Deps('job_aaǆ'))\n"
        "def dependent():\n"
        "    assert Path(__file__).with_name('child-ran').read_text() == 'yes'\n",
        encoding="utf-8",
    )
    (jobs / "grouped.py").write_text(
        "JOB_GROUP = \"ǆ_ops\"\ndef run_it():\n    return 'ran'\n",
        encoding="utf-8",
    )
    return FunctualizeApp(
        name="nfkc-names", job_sources=JobSources(directories=[str(jobs)], lazy=False)
    )


@pytest.mark.parametrize("parent", ["invoke-parent", "parallel-parent"])
def test_invoke_surfaces_run_written_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent: str
) -> None:
    app = _app(tmp_path, monkeypatch)
    result = CliRunner().invoke(app.cli_command, [parent])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "jobs" / "child-ran").read_text() == "yes"


@pytest.mark.parametrize("spelling", ["job_aaǆ", "job-aadž"])
def test_cli_accepts_written_and_registered_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    app = _app(tmp_path, monkeypatch)
    result = CliRunner().invoke(app.cli_command, [spelling])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "jobs" / "child-ran").read_text() == "yes"


def test_declared_dependency_resolves_written_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    result = CliRunner().invoke(app.cli_command, ["dependent"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "jobs" / "child-ran").read_text() == "yes"


@pytest.mark.parametrize("spelling", ["ǆ_ops", "dž-ops"])
def test_grouped_cli_accepts_both_spellings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    app = _app(tmp_path, monkeypatch)
    result = CliRunner().invoke(app.cli_command, [spelling, "run-it"])
    assert result.exit_code == 0, result.output


def test_nfkc_equivalent_groups_report_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for filename, group in (("written.py", "ǆ_ops"), ("canonical.py", "dž_ops")):
        (jobs / filename).write_text(
            f'JOB_GROUP = "{group}"\n\ndef run_it():\n    return 1\n',
            encoding="utf-8",
        )
    cache = tmp_path / ".functualize"
    locator = (
        ResourceLocator().search_explicit(str(cache)).write_to_explicit(str(cache))
    )
    provider = CachedDirectoryScanProvider(
        directories=[str(jobs)], locator=locator, project_root=tmp_path
    )
    provider.list_jobs()
    assert any(
        failure.error_type == JOB_NAME_COLLISION
        for failure in provider.discovery_failures
    )
