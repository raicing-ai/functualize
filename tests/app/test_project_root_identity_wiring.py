"""A declared root gives app boot one standalone identity in every subfolder."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize import FunctualizeApp
from functualize._primitives.locator import compute_project_id
from functualize.app.config import JobSources

pytestmark = pytest.mark.real_state_root


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name, folder in (
        ("XDG_CACHE_HOME", ".cache"),
        ("XDG_CONFIG_HOME", ".config"),
        ("XDG_DATA_HOME", ".local/share"),
        ("XDG_STATE_HOME", ".local/state"),
    ):
        monkeypatch.setenv(name, str(home / folder))
    return home


def test_root_and_subfolder_boot_share_state_and_warm_discovery_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolate_home(tmp_path, monkeypatch)
    root = tmp_path / "project"
    sub = root / "sub"
    jobs = root / "jobs"
    jobs.mkdir(parents=True)
    sub.mkdir()
    (root / ".functualize.toml").write_text(
        'root = true\njobs_directories = ["jobs"]\n'
    )
    (jobs / "hello.py").write_text(
        "from pathlib import Path\n"
        'Path(__file__).with_name("imports.log").open("a").write("imported\\n")\n'
        "def hello() -> None:\n    pass\n"
    )

    expected_dir = home / ".cache" / "functualize" / compute_project_id(root)
    sub_dir = home / ".cache" / "functualize" / compute_project_id(sub)

    monkeypatch.chdir(root)
    root_app = FunctualizeApp(
        "root-identity", job_sources=JobSources(directories=[str(jobs)])
    )
    state_path = root_app._resource_locator.writable("state-probe.txt")
    assert state_path == expected_dir / "state-probe.txt"
    state_path.write_text("from-root")
    assert "hello" in {job.name for job in root_app.get_jobs()}
    cache_path = expected_dir / "cache.json"
    assert cache_path.is_file()
    assert (jobs / "imports.log").read_text().splitlines() == ["imported"]

    monkeypatch.chdir(sub)
    sub_app = FunctualizeApp(
        "root-identity", job_sources=JobSources(directories=[str(jobs)])
    )
    assert sub_app._resource_locator.writable("state-probe.txt") == state_path
    assert sub_app._resource_locator.resolve_one("state-probe.txt") == str(state_path)
    assert "hello" in {job.name for job in sub_app.get_jobs()}
    assert cache_path.is_file()
    assert (jobs / "imports.log").read_text().splitlines() == ["imported"]
    assert not sub_dir.exists()


def test_without_root_subfolders_keep_separate_standalone_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _isolate_home(tmp_path, monkeypatch)
    plain = tmp_path / "plain"
    sub = plain / "sub"
    sub.mkdir(parents=True)

    monkeypatch.chdir(plain)
    plain_app = FunctualizeApp("plain-identity")
    monkeypatch.chdir(sub)
    sub_app = FunctualizeApp("plain-identity")

    assert plain_app._resource_locator.writable("state-probe.txt") == (
        home / ".cache" / "functualize" / compute_project_id(plain) / "state-probe.txt"
    )
    assert sub_app._resource_locator.writable("state-probe.txt") == (
        home / ".cache" / "functualize" / compute_project_id(sub) / "state-probe.txt"
    )
