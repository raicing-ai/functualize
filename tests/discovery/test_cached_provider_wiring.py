"""Unit tests for CachedDirectoryScanProvider wiring into provider selection (Task 11.6).

Tests cover:
- CachedDirectoryScanProvider is the default provider when lazy_boot=True
- func <job_name> execution uses get_job(name) for locate phase
- Cache storage: XDG for standalone, .functualize/ for declared projects
- Silent fallback to fresh discovery on cache miss

Requirements: 15.1, 15.2, 15.4, 15.5
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import compute_project_id
from functualize.app.config import JobSources


@pytest.fixture(autouse=True)
def reset_app_state():
    """Reset AppState before each test."""
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


def _write_job(jobs_dir: Path, name: str, body: str = "pass") -> None:
    """Write a simple job module."""
    (jobs_dir / f"{name}.py").write_text(
        textwrap.dedent(f"""\
        def {name}():
            '''{name} job.'''
            {body}
        """)
    )


class TestCachedProviderWiringInApp:
    """Test that CachedDirectoryScanProvider is wired as default when lazy=True."""

    def test_pipeline_uses_cached_provider_when_lazy(self, tmp_path, monkeypatch):
        """When lazy_boot=True (default), pipeline primary provider is CachedDirectoryScanProvider."""
        from functualize.app.core import FunctualizeApp

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_job(jobs_dir, "deploy")

        # Isolate cache to tmp_path to avoid stale global caches
        xdg_cache = tmp_path / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # The first provider in the pipeline should be CachedDirectoryScanProvider
        pipeline = app._resolution_pipeline
        assert pipeline.provider_count >= 1
        first_provider = pipeline._providers[0].provider
        assert isinstance(first_provider, CachedDirectoryScanProvider)

    def test_cached_provider_get_job_returns_descriptor(self, tmp_path, monkeypatch):
        """CachedDirectoryScanProvider.get_job(name) returns the descriptor for a valid job."""
        from functualize.app.core import FunctualizeApp

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_job(jobs_dir, "deploy")

        # Isolate cache to tmp_path to avoid stale global caches
        xdg_cache = tmp_path / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        pipeline = app._resolution_pipeline
        provider = pipeline._providers[0].provider
        assert isinstance(provider, CachedDirectoryScanProvider)

        # get_job should find the job via O(1) lookup or targeted discovery
        descriptor = provider.get_job("deploy")
        assert descriptor is not None
        assert descriptor.name == "deploy"

    def test_cached_provider_get_job_miss_returns_none(self, tmp_path, monkeypatch):
        """CachedDirectoryScanProvider.get_job(name) returns None for missing jobs."""
        from functualize.app.core import FunctualizeApp

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_job(jobs_dir, "deploy")

        # Isolate cache to tmp_path to avoid stale global caches
        xdg_cache = tmp_path / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        pipeline = app._resolution_pipeline
        provider = pipeline._providers[0].provider

        # Non-existent job should return None (silent fallback)
        assert provider.get_job("nonexistent") is None


class TestCacheStorageLocation:
    """Test cache storage follows ResourceLocator conventions (Requirement 15.5)."""

    def test_declared_project_uses_functualize_dir(self, tmp_path, monkeypatch):
        """When .functualize/ exists, cache writes go there."""
        from functualize.app.core import FunctualizeApp

        # Create .functualize/ directory to simulate declared-project mode
        functualize_dir = tmp_path / ".functualize"
        functualize_dir.mkdir()

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_job(jobs_dir, "deploy")

        # Set CWD to tmp_path so _find_functualize_dir finds it
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Trigger cache write by calling list_jobs via the provider
        pipeline = app._resolution_pipeline
        provider = pipeline._providers[0].provider
        assert isinstance(provider, CachedDirectoryScanProvider)

        provider.list_jobs()  # This triggers cache persistence

        # Cache should be written to .functualize/ directory
        cache_file = functualize_dir / "cache.json"
        assert cache_file.exists()

    def test_standalone_mode_uses_xdg_cache(self, tmp_path, monkeypatch):
        """When no .functualize/ exists, cache writes go to XDG cache."""
        from functualize.app.core import FunctualizeApp

        # No .functualize/ directory — standalone mode
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_job(jobs_dir, "deploy")

        # Set up XDG cache directory
        xdg_cache = tmp_path / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))
        monkeypatch.chdir(tmp_path)

        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        # Trigger cache write
        pipeline = app._resolution_pipeline
        provider = pipeline._providers[0].provider
        assert isinstance(provider, CachedDirectoryScanProvider)

        provider.list_jobs()

        # Cache should be in XDG cache directory
        project_id = compute_project_id(str(tmp_path))
        cache_dir = xdg_cache / "functualize" / project_id
        cache_file = cache_dir / "cache.json"
        assert cache_file.exists()
