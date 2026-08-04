"""E2E test: cold boot → cache → warm boot → grouped jobs accessible.

Validates that the full boot lifecycle works correctly for grouped jobs:
1. Cold boot discovers grouped jobs and writes qualified names to cache
2. Warm boot reads cache and correctly resolves group/job names
3. The job is accessible via both discovery paths (cold and warm)

**Validates: Requirements 7, 15**
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME
from functualize._primitives.locator import ResourceLocator
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.app.utils import read_routing_names_from_cache


def _make_provider(
    project_root: Path, jobs_dirs: list[str]
) -> CachedDirectoryScanProvider:
    """Create a cache provider whose store lives in <root>/.functualize/."""
    cache_dir = project_root / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=jobs_dirs, locator=locator, project_root=project_root
    )


def _create_grouped_job_module(jobs_dir: Path) -> Path:
    """Create a job module with JOB_GROUP = 'infra' and a provision() function."""
    content = '''\
"""Infrastructure provisioning jobs."""

JOB_GROUP = "infra"


def provision():
    """Provision cloud resources."""
    return "provisioned"
'''
    module_path = jobs_dir / "infra_jobs.py"
    module_path.write_text(content, encoding="utf-8")
    return module_path


def _clear_modules(*prefixes: str) -> None:
    """Remove modules from sys.modules that match the given prefixes."""
    to_remove = [
        key
        for key in sys.modules
        if any(key.startswith(p) or key == p for p in prefixes)
    ]
    for key in to_remove:
        del sys.modules[key]


@pytest.mark.slow
class TestGroupedColdWarmBootE2E:
    """E2E: cold boot → cache → warm boot for grouped jobs.

    **Validates: Requirements 7, 15**
    """

    def test_cold_boot_discovers_grouped_job(self, tmp_path: Path) -> None:
        """Cold boot (no cache) discovers 'infra.provision' via full import.

        **Validates: Requirements 7, 15**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_grouped_job_module(jobs_dir)

        cache_path = tmp_path / ".functualize" / CACHE_FILENAME
        assert not cache_path.exists(), "Cache should not exist before cold boot"

        # Cold boot via list_jobs reconciliation
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        descriptors = provider.list_jobs()

        # Verify "infra.provision" was discovered
        descriptor_names = {d.name for d in descriptors}
        assert "infra.provision" in descriptor_names

        # Verify the descriptor has correct group
        infra_desc = next(d for d in descriptors if d.name == "infra.provision")
        assert infra_desc.group == "infra"

    def test_cache_written_with_qualified_names(self, tmp_path: Path) -> None:
        """After cold boot, cache file contains qualified names and group info.

        **Validates: Requirements 15**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_grouped_job_module(jobs_dir)

        cache_path = tmp_path / ".functualize" / CACHE_FILENAME

        # Cold boot populates cache
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        # Verify cache file exists and contains qualified names
        assert cache_path.exists()
        data = json.loads(cache_path.read_text(encoding="utf-8"))

        # Check cache entries have qualified name and group
        entries = data["entries"]
        assert len(entries) >= 1

        # Find the infra.provision entry
        found = False
        for entry_data in entries.values():
            if entry_data["name"] == "infra.provision":
                assert entry_data["group"] == "infra"
                found = True
                break

        assert found, (
            "Cache must contain an entry with name='infra.provision' and group='infra'"
        )

    def test_warm_boot_reads_grouped_names_from_cache(self, tmp_path: Path) -> None:
        """Warm boot reads cache and returns 'infra.provision' in job_names
        and 'infra' in group_names.

        **Validates: Requirements 7**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_grouped_job_module(jobs_dir)

        cache_path = tmp_path / ".functualize" / CACHE_FILENAME

        # Cold boot to populate cache
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()
        assert cache_path.exists()

        # Warm boot: read routing names from cache
        result = read_routing_names_from_cache(cache_path)
        assert result is not None, (
            "read_routing_names_from_cache should succeed on valid cache"
        )

        job_names, group_names = result

        # Verify "infra.provision" is in job_names
        assert "infra.provision" in job_names

        # Verify "infra" is in group_names
        assert "infra" in group_names

    def test_full_cold_warm_cycle_job_accessible_both_paths(
        self, tmp_path: Path
    ) -> None:
        """Full cycle: cold boot discovers job, warm boot cache provides
        routing info, and the job is accessible via both cold and warm paths.

        **Validates: Requirements 7, 15**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_grouped_job_module(jobs_dir)

        cache_path = tmp_path / ".functualize" / CACHE_FILENAME

        # ── Step 1: Cold boot (no cache) ─────────────────────────────────
        assert not cache_path.exists()

        # Cold boot via list_jobs (same as real boot path)
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        cold_descriptors = provider.list_jobs()
        cold_names = {d.name for d in cold_descriptors}

        assert "infra.provision" in cold_names
        assert cache_path.exists(), "Cache must be written after cold boot"

        # ── Step 2: Verify cache content ─────────────────────────────────
        result = read_routing_names_from_cache(cache_path)
        assert result is not None
        job_names, group_names = result
        assert "infra.provision" in job_names
        assert "infra" in group_names

        # ── Step 3: Warm boot (cache exists) ──────────────────────────────
        # Clear module cache to simulate fresh process
        _clear_modules("_functualize_sync_", "infra_jobs")

        # Warm boot: a fresh provider loads from the existing cache and
        # serves entries without re-importing
        provider_warm = _make_provider(tmp_path, [str(jobs_dir)])
        assert len(provider_warm._entries) >= 1, "Warm boot should load cache entries"

        warm_descriptors = provider_warm.list_jobs()
        warm_names = {d.name for d in warm_descriptors}

        assert "infra.provision" in warm_names

        # ── Step 4: Verify job accessible via both paths ─────────────────
        # Cold boot produced the same job names as warm boot
        assert cold_names == warm_names

        # The warm-booted descriptor has the correct group and func_name
        warm_desc = next(d for d in warm_descriptors if d.name == "infra.provision")
        assert warm_desc.group == "infra"
        assert warm_desc.func_name == "provision"

        # ── Step 5: Verify FunctualizeApp also discovers the grouped job ──
        app = FunctualizeApp(
            name="test-grouped",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )
        app_jobs = app.get_jobs()
        app_names = {j.name for j in app_jobs}
        assert "infra.provision" in app_names

        app_desc = next(j for j in app_jobs if j.name == "infra.provision")
        assert app_desc.group == "infra"
        assert app_desc.func_name == "provision"

    def test_warm_boot_with_nested_group(self, tmp_path: Path) -> None:
        """Nested groups (e.g., 'infra.aws') emit ancestor prefixes in cache routing.

        **Validates: Requirements 7**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create a module with nested JOB_GROUP
        content = '''\
"""AWS infrastructure jobs."""

JOB_GROUP = "infra.aws"


def provision():
    """Provision AWS resources."""
    return "aws-provisioned"
'''
        (jobs_dir / "aws_jobs.py").write_text(content, encoding="utf-8")

        cache_path = tmp_path / ".functualize" / CACHE_FILENAME

        # Cold boot
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()
        assert cache_path.exists()

        # Warm boot: read routing names
        result = read_routing_names_from_cache(cache_path)
        assert result is not None
        job_names, group_names = result

        # Verify qualified name
        assert "infra.aws.provision" in job_names

        # Verify ancestor prefixes are emitted
        assert "infra.aws" in group_names
        assert "infra" in group_names  # ancestor prefix
