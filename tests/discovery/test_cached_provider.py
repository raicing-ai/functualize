"""Unit tests for CachedDirectoryScanProvider.

Tests cover:
- JobProvider Protocol satisfaction (structural typing)
- O(1) name-based lookup via _by_name dict
- mtime validation and re-import on stale cache
- Incremental list_jobs() validation (new/modified/deleted)
- Pre-filter application
- ResourceLocator integration for cache storage
- Silent recovery on corrupted/missing cache

**Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10**
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.protocols import JobProvider

# =============================================================================
# Helpers
# =============================================================================


def _make_locator(tmp_path: Path) -> ResourceLocator:
    """Create a ResourceLocator that reads/writes to tmp_path."""
    return (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )


def _write_module(directory: Path, name: str, content: str | None = None) -> Path:
    """Write a simple job module file."""
    if content is None:
        content = f'def {name}():\n    """{name} job."""\n    pass\n'
    module_file = directory / f"{name}.py"
    module_file.write_text(content)
    return module_file


# =============================================================================
# Tests
# =============================================================================


class TestProtocolSatisfaction:
    """Tests for JobProvider Protocol structural typing.

    **Validates: Requirements 13.1**
    """

    def test_satisfies_job_provider_protocol(self, tmp_path: Path) -> None:
        """CachedDirectoryScanProvider satisfies JobProvider via structural typing."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        assert isinstance(provider, JobProvider)

    def test_has_list_jobs_method(self, tmp_path: Path) -> None:
        """Provider has list_jobs() method."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        assert hasattr(provider, "list_jobs")
        assert callable(provider.list_jobs)

    def test_has_get_job_method(self, tmp_path: Path) -> None:
        """Provider has get_job(name) method."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        assert hasattr(provider, "get_job")
        assert callable(provider.get_job)


class TestGetJob:
    """Tests for get_job(name) behavior.

    **Validates: Requirements 13.2, 13.3, 13.4, 13.5**
    """

    def test_get_job_returns_descriptor_for_existing_job(self, tmp_path: Path) -> None:
        """get_job returns a descriptor for a job that exists.

        **Validates: Requirements 13.2**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "deploy")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        result = provider.get_job("deploy")
        assert result is not None
        assert result.name == "deploy"

    def test_get_job_returns_none_for_nonexistent_job(self, tmp_path: Path) -> None:
        """get_job returns None for a job that doesn't exist.

        **Validates: Requirements 13.5**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "deploy")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        result = provider.get_job("nonexistent")
        assert result is None

    def test_get_job_uses_cached_descriptor_when_valid(self, tmp_path: Path) -> None:
        """get_job returns cached descriptor without re-import when mtime unchanged.

        **Validates: Requirements 13.2**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "build")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # First call triggers import
        result1 = provider.get_job("build")
        assert result1 is not None

        # Second call should return same cached descriptor
        result2 = provider.get_job("build")
        assert result2 is not None
        assert result2.name == "build"

    def test_get_job_reimports_on_mtime_change(self, tmp_path: Path) -> None:
        """get_job re-imports module when source file mtime changes.

        **Validates: Requirements 13.3**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        module_file = _write_module(jobs_dir, "evolve")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # First access populates cache
        result1 = provider.get_job("evolve")
        assert result1 is not None
        original_hash = result1.content_hash

        # Modify the file (change content and touch mtime)
        time.sleep(0.05)  # Ensure mtime differs
        module_file.write_text(
            'def evolve():\n    """Updated evolve job."""\n    return 42\n'
        )

        # get_job should detect stale entry and re-import
        result2 = provider.get_job("evolve")
        assert result2 is not None
        assert result2.name == "evolve"
        assert result2.content_hash != original_hash

    def test_get_job_targeted_discovery_on_cache_miss(self, tmp_path: Path) -> None:
        """get_job does targeted discovery when name not in cache.

        **Validates: Requirements 13.4**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        locator = _make_locator(tmp_path)

        # Create provider with empty cache
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Now add a module file after provider creation
        _write_module(jobs_dir, "late_arrival")

        # get_job should discover it via targeted scan
        result = provider.get_job("late_arrival")
        assert result is not None
        assert result.name == "late-arrival"

    def test_get_job_returns_none_on_import_failure(self, tmp_path: Path) -> None:
        """get_job returns None without raising when import fails.

        **Validates: Requirements 13.5**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        # Write a module with syntax error
        module_file = jobs_dir / "broken.py"
        module_file.write_text("def broken(\n    pass  # syntax error\n")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Should not raise
        result = provider.get_job("broken")
        assert result is None


class TestListJobs:
    """Tests for list_jobs() behavior.

    **Validates: Requirements 13.9**
    """

    def test_list_jobs_returns_all_descriptors(self, tmp_path: Path) -> None:
        """list_jobs returns descriptors for all valid modules.

        **Validates: Requirements 13.9**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "deploy")
        _write_module(jobs_dir, "build")
        _write_module(jobs_dir, "test_suite")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        jobs = provider.list_jobs()
        names = {j.name for j in jobs}

        assert "deploy" in names
        assert "build" in names
        assert "test-suite" in names

    def test_list_jobs_detects_new_files(self, tmp_path: Path) -> None:
        """list_jobs imports new files added after initial scan.

        **Validates: Requirements 13.9**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "original")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Initial scan
        jobs1 = provider.list_jobs()
        assert len(jobs1) == 1

        # Add a new module
        _write_module(jobs_dir, "newcomer")

        # list_jobs should pick up the new file
        jobs2 = provider.list_jobs()
        names = {j.name for j in jobs2}
        assert "newcomer" in names

    def test_list_jobs_removes_deleted_files(self, tmp_path: Path) -> None:
        """list_jobs removes entries for deleted files.

        **Validates: Requirements 13.9**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        deploy_file = _write_module(jobs_dir, "deploy")
        _write_module(jobs_dir, "build")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Initial scan
        jobs1 = provider.list_jobs()
        assert len(jobs1) == 2

        # Delete a module
        deploy_file.unlink()

        # list_jobs should detect deletion
        jobs2 = provider.list_jobs()
        names = {j.name for j in jobs2}
        assert "deploy" not in names
        assert "build" in names

    def test_list_jobs_reimports_modified_files(self, tmp_path: Path) -> None:
        """list_jobs re-imports modules whose mtime has changed.

        **Validates: Requirements 13.9**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        module_file = _write_module(jobs_dir, "mutable")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Initial scan
        jobs1 = provider.list_jobs()
        original_hash = jobs1[0].content_hash

        # Modify the file
        time.sleep(0.05)
        module_file.write_text('def mutable():\n    """Modified."""\n    return 1\n')

        # list_jobs should detect change and re-import
        jobs2 = provider.list_jobs()
        assert len(jobs2) == 1
        assert jobs2[0].content_hash != original_hash


class TestPreFilter:
    """Tests for pre-filter application.

    **Validates: Requirements 13.6**
    """

    def test_pre_filter_applied_before_import(self, tmp_path: Path) -> None:
        """Pre-filter prevents import of excluded modules.

        **Validates: Requirements 13.6**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "allowed")
        _write_module(jobs_dir, "excluded")
        locator = _make_locator(tmp_path)

        class SelectiveFilter:
            def should_import(self, source_file: Path) -> bool:
                return "excluded" not in source_file.name

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=SelectiveFilter(),
        )

        jobs = provider.list_jobs()
        names = {j.name for j in jobs}

        assert "allowed" in names
        assert "excluded" not in names

    def test_none_pre_filter_imports_everything(self, tmp_path: Path) -> None:
        """No pre-filter (None) imports all modules.

        **Validates: Requirements 13.6**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "alpha")
        _write_module(jobs_dir, "beta")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator, pre_filter=None
        )

        jobs = provider.list_jobs()
        names = {j.name for j in jobs}

        assert "alpha" in names
        assert "beta" in names


class TestCachePersistence:
    """Tests for cache persistence via ResourceLocator.

    **Validates: Requirements 13.7, 13.8, 13.10**
    """

    def test_cache_persisted_to_disk_via_locator(self, tmp_path: Path) -> None:
        """Cache is written to disk at the location specified by ResourceLocator.

        **Validates: Requirements 13.7**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "persist_test")
        cache_dir = tmp_path / "cache"
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Trigger scan (which persists cache)
        provider.list_jobs()

        # Verify cache file exists
        cache_file = cache_dir / "cache.json"
        assert cache_file.exists()

        # Verify contents are valid JSON
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "entries" in data

    def test_cache_loaded_from_disk_on_init(self, tmp_path: Path) -> None:
        """A new provider instance loads existing cache from disk.

        **Validates: Requirements 13.7**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "cached_job")
        locator = _make_locator(tmp_path)

        # First provider: scans and persists
        provider1 = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )
        provider1.list_jobs()

        # Second provider: should load from cache
        provider2 = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Should find the job without needing to scan
        result = provider2.get_job("cached_job")
        assert result is not None
        assert result.name == "cached-job"

    def test_corrupted_cache_starts_empty(self, tmp_path: Path) -> None:
        """Corrupted cache file causes provider to start empty without error.

        **Validates: Requirements 13.10**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "survivor")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        # Write corrupted cache
        (cache_dir / "cache.json").write_text("not valid json{{{")

        locator = _make_locator(tmp_path)

        # Should not raise
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Should be able to discover jobs (rebuilds on demand)
        result = provider.get_job("survivor")
        assert result is not None
        assert result.name == "survivor"

    def test_missing_cache_starts_empty(self, tmp_path: Path) -> None:
        """Missing cache file causes provider to start empty without error.

        **Validates: Requirements 13.10**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "fresh")
        locator = _make_locator(tmp_path)

        # No cache file exists - should not raise
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Should discover jobs via targeted scan
        result = provider.get_job("fresh")
        assert result is not None
        assert result.name == "fresh"


class TestMultiFunctionModules:
    """Tests for multi-function module support.

    **Validates: Requirements 13.8**
    """

    def test_multi_function_module_creates_separate_entries(
        self, tmp_path: Path
    ) -> None:
        """A module with multiple public functions creates one entry per job.

        **Validates: Requirements 13.8**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(
            jobs_dir,
            "multi",
            content=(
                'def deploy():\n    """Deploy."""\n    pass\n\n'
                'def build():\n    """Build."""\n    pass\n\n'
                'def test_run():\n    """Test."""\n    pass\n'
            ),
        )
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        jobs = provider.list_jobs()
        names = {j.name for j in jobs}

        assert "deploy" in names
        assert "build" in names
        assert "test-run" in names

    def test_get_job_finds_function_from_multi_function_module(
        self, tmp_path: Path
    ) -> None:
        """get_job can find any function from a multi-function module.

        **Validates: Requirements 13.8**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(
            jobs_dir,
            "services",
            content=(
                'def start():\n    """Start."""\n    pass\n\n'
                'def stop():\n    """Stop."""\n    pass\n'
            ),
        )
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)], locator=locator
        )

        # Both should be accessible
        assert provider.get_job("start") is not None
        assert provider.get_job("stop") is not None
