"""Discovery wiring for the @job declaration (S1/T4).

Verifies the JobDeclaration flows through the real scan path into the cache and
survives the warm-cache read (scan + warm-cache parity), and that @job(group=)
overrides convention identity.

`@job(name=)` and `@job(aliases=)` were removed: each gave one job a second
spelling, which is the divergence class this codebase keeps paying for. The
addressable name now derives from `__name__` alone, so the cold path and the
warm path cannot disagree about it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME, CACHE_VERSION
from functualize._primitives.locator import ResourceLocator
from functualize._types.job_declaration import JobDeclaration

# A job module using @job(...) with identity override + operational contract.
_DECLARED_JOB = '''
from functualize.job import job, Deps, Fingerprint, Exec, Retry

@job(
    group="infra",
    extra_description="Ship the app",
    category="deployment",
    tags=["deploy"],
    deps=Deps("lint", "test", policy="keep-going"),
    cache=Fingerprint(sources=["src/**/*.py"], generates=["dist/app.whl"]),
    exec=Exec(retry=Retry(attempts=2)),
)
def deploy():
    """Deploy job."""
    pass
'''

# A plain convention job (no @job) — declaration should be None.
_CONVENTION_JOB = '''
def build():
    """Build job."""
    pass
'''


def _make_provider(tmp_path: Path, jobs_dir: Path) -> CachedDirectoryScanProvider:
    locator = (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs_dir)], locator=locator, project_root=tmp_path
    )


def _cache_file(tmp_path: Path) -> Path:
    return tmp_path / "cache" / CACHE_FILENAME


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs"
    d.mkdir()
    return d


class TestDeclarationInScan:
    def test_declared_job_carries_declaration_on_cold_scan(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "deploy.py").write_text(_DECLARED_JOB)

        provider = _make_provider(tmp_path, jobs_dir)
        jobs = provider.list_jobs()

        (job_desc,) = jobs
        assert isinstance(job_desc.declaration, JobDeclaration)
        decl = job_desc.declaration
        assert decl.deps is not None and decl.deps.refs == ("lint", "test")
        assert decl.deps.policy == "keep-going"
        assert decl.cache is not None and decl.cache.generates == ("dist/app.whl",)
        assert decl.exec is not None

    def test_group_overrides_convention(self, tmp_path: Path, jobs_dir: Path) -> None:
        (jobs_dir / "deploy.py").write_text(_DECLARED_JOB)

        provider = _make_provider(tmp_path, jobs_dir)
        (job_desc,) = provider.list_jobs()

        # @job(group="infra") overrides the absent JOB_GROUP; the leaf name is
        # always the function's own, so there is one spelling of this job.
        assert job_desc.group == "infra"
        assert job_desc.name == "infra.deploy"

    def test_convention_job_has_no_declaration(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "build.py").write_text(_CONVENTION_JOB)

        provider = _make_provider(tmp_path, jobs_dir)
        (job_desc,) = provider.list_jobs()

        assert job_desc.declaration is None
        assert job_desc.name == "build"


class TestScanWarmCacheParity:
    def test_declaration_survives_warm_cache_read(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        (jobs_dir / "deploy.py").write_text(_DECLARED_JOB)

        # Cold scan populates the cache.
        cold = _make_provider(tmp_path, jobs_dir)
        (cold_desc,) = cold.list_jobs()
        assert _cache_file(tmp_path).exists()

        # A fresh provider over the same cache reads warm (no re-scan).
        warm = _make_provider(tmp_path, jobs_dir)
        (warm_desc,) = warm.list_jobs()

        # Parity: the declaration is identical across scan and warm-cache read.
        assert warm_desc.declaration is not None
        assert warm_desc.declaration.to_dict() == cold_desc.declaration.to_dict()
        assert warm_desc.name == cold_desc.name == "infra.deploy"

    def test_cache_version_is_current(self, tmp_path: Path, jobs_dir: Path) -> None:
        (jobs_dir / "deploy.py").write_text(_DECLARED_JOB)
        _make_provider(tmp_path, jobs_dir).list_jobs()

        data = json.loads(_cache_file(tmp_path).read_text(encoding="utf-8"))
        assert data["version"] == CACHE_VERSION == 18
        # The declaration sub-dict is present in the cached entry.
        entry = next(iter(data["entries"].values()))
        assert entry["declaration"]["deps"]["policy"] == "keep-going"
        # Removed fields, each of which `from_dict` reads by name — so a cache
        # still carrying one would raise KeyError rather than degrade, which is
        # what the version pin above protects.
        assert "name" not in entry["declaration"]
        assert "aliases" not in entry["declaration"]
        assert "matrix" not in entry["declaration"]
