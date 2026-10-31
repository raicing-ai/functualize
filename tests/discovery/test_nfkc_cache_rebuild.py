"""A cache from before NFKC name registration must be rebuilt."""

from __future__ import annotations

import json
from pathlib import Path

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME, CACHE_VERSION
from functualize._primitives.locator import ResourceLocator


def test_old_cache_name_rebuilds_with_new_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "grouped.py").write_text(
        'JOB_GROUP = "ǆ_ops"\n\ndef run_it():\n    return 1\n', encoding="utf-8"
    )
    cache_dir = tmp_path / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )

    def provider() -> CachedDirectoryScanProvider:
        return CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator, project_root=tmp_path
        )

    assert [job.name for job in provider().list_jobs()] == ["dž-ops.run-it"]
    cache_file = cache_dir / CACHE_FILENAME
    old_cache = json.loads(cache_file.read_text(encoding="utf-8"))
    old_cache["version"] = 21
    for entry in old_cache["entries"].values():
        entry["name"] = "ǆ-ops.run-it"
        entry["group"] = "ǆ-ops"
    cache_file.write_text(json.dumps(old_cache), encoding="utf-8")

    assert [job.name for job in provider().list_jobs()] == ["dž-ops.run-it"]
    rebuilt = json.loads(cache_file.read_text(encoding="utf-8"))
    assert rebuilt["version"] == CACHE_VERSION
    assert [entry["name"] for entry in rebuilt["entries"].values()] == ["dž-ops.run-it"]
