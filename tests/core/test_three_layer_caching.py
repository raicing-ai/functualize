"""Tests for the three-layer caching architecture (Task 15.5).

Validates:
- Layer 2 memoization: get_jobs() returns same list object until invalidated
- Layer 2 invalidation: add_job_provider() and add_job_transform() clear the memo
- Layer 3 is always active: ResolutionPlan cache works regardless of wiring mode
- Static wiring bypasses Layers 1 and 2, Layer 3 still active

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from typing import TYPE_CHECKING

import pytest

from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._discovery.providers import StaticProvider
from functualize.app.config import (
    ConfigSources,
    ExecutionConfig,
    JobSources,
    PluginSources,
)
from functualize.app.core import FunctualizeApp

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor


@pytest.fixture(autouse=True)
def reset_app_state():
    """Reset AppState before each test."""
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


def _make_resolution_chain() -> ResolutionChain:
    """Create a minimal resolution chain for static wiring tests."""
    return ResolutionChain([DefaultSource({})])


def _make_static_app(*functions) -> FunctualizeApp:
    """Create a FunctualizeApp using static wiring (fast path).

    Bypasses all filesystem I/O — pure in-memory construction.
    """
    return FunctualizeApp(
        "test",
        job_sources=JobSources(functions=list(functions)),
        config_sources=ConfigSources(config_resolution_chain=_make_resolution_chain()),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        execution=ExecutionConfig(),
    )


class TestLayer2Memoization:
    """Layer 2: app.get_jobs() is memoized, returning the same list object."""

    def test_get_jobs_returns_same_object_on_repeated_calls(self):
        """get_jobs() should return the same list object on subsequent calls."""

        def deploy():
            """Deploy job."""
            pass

        app = _make_static_app(deploy)

        first = app.get_jobs()
        second = app.get_jobs()
        third = app.get_jobs()

        # Must be the SAME object (identity), not just equal
        assert first is second
        assert second is third

    def test_get_jobs_memo_contains_correct_jobs(self):
        """Memoized result should contain the expected job descriptors."""

        def deploy():
            """Deploy job."""
            pass

        def build():
            """Build job."""
            pass

        app = _make_static_app(deploy, build)

        jobs = app.get_jobs()
        names = {j.name for j in jobs}
        assert "deploy" in names
        assert "build" in names


class TestLayer2Invalidation:
    """Layer 2: add_job_provider() and add_job_transform() invalidate the memo."""

    def test_add_job_provider_invalidates_memo(self):
        """After add_job_provider(), get_jobs() should return a new list object."""

        def deploy():
            """Deploy job."""
            pass

        def extra():
            """Extra job."""
            pass

        app = _make_static_app(deploy)

        first = app.get_jobs()
        assert first is app.get_jobs()  # Still memoized

        # Add a new provider — this should invalidate the memo
        # We need to unfreeze the DI registry first for the pipeline addition
        # Actually, add_job_provider works on the pipeline (not DI registry)
        # But we need to ensure the app isn't frozen for pipeline mutations
        # The resolution pipeline doesn't enforce freeze — only the DI registry does.
        # However, after boot the DI registry is frozen, but that doesn't affect
        # the resolution pipeline. Let's just call add_job_provider.

        # Create a simple provider
        new_provider = StaticProvider([extra])
        app.add_job_provider(new_provider)

        second = app.get_jobs()

        # The memo was invalidated, so this should be a NEW object
        assert first is not second

    def test_add_job_transform_invalidates_memo(self):
        """After add_job_transform(), get_jobs() should return a new list object."""

        def deploy():
            """Deploy job."""
            pass

        app = _make_static_app(deploy)

        first = app.get_jobs()
        assert first is app.get_jobs()  # Still memoized

        # Add a transform — this should invalidate the memo
        class NoopTransform:
            """A transform that does nothing (satisfies JobTransform protocol)."""

            def transform_list(
                self, jobs: Sequence[JobDescriptor]
            ) -> Sequence[JobDescriptor]:
                return jobs

            def transform_get(
                self, name: str, descriptor: JobDescriptor | None
            ) -> JobDescriptor | None:
                return descriptor

        app.add_job_transform(NoopTransform())

        second = app.get_jobs()

        # The memo was invalidated, so this should be a NEW object
        assert first is not second

    def test_memo_reestablished_after_invalidation(self):
        """After invalidation, subsequent get_jobs() calls should re-memoize."""

        def deploy():
            """Deploy job."""
            pass

        def extra():
            """Extra job."""
            pass

        app = _make_static_app(deploy)

        first = app.get_jobs()

        # Invalidate
        app.add_job_provider(StaticProvider([extra]))

        # New memo should be established
        second = app.get_jobs()
        third = app.get_jobs()
        assert second is third
        assert first is not second


class TestLayer3AlwaysActive:
    """Layer 3: ResolutionPlan cache by id(function) is always active."""

    def test_resolution_plan_cached_in_static_wiring(self):
        """In static wiring mode, the engine's resolution plan cache is still active."""

        def deploy():
            """Deploy job."""
            pass

        app = _make_static_app(deploy)

        engine = app.execution_engine

        # Get the resolution plan — should compute and cache
        plan1 = engine._get_resolution_plan(deploy)
        plan2 = engine._get_resolution_plan(deploy)

        # Same object (identity) — cached by id(function)
        assert plan1 is plan2
        assert id(deploy) in engine._resolution_plan_cache

    def test_resolution_plan_cached_in_standard_wiring(self, tmp_path, monkeypatch):
        """In standard wiring mode, the engine's resolution plan cache is active."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "deploy.py").write_text(
            textwrap.dedent("""\
            def deploy():
                '''Deploy job.'''
                pass
            """)
        )

        monkeypatch.chdir(tmp_path)
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        engine = app.execution_engine

        # Use a fresh function to test caching
        def my_func():
            pass

        plan1 = engine._get_resolution_plan(my_func)
        plan2 = engine._get_resolution_plan(my_func)

        # Same object — cached
        assert plan1 is plan2

    def test_resolution_plan_never_invalidated(self):
        """ResolutionPlan cache persists even after add_job_provider mutations."""

        def deploy():
            """Deploy job."""
            pass

        def extra():
            """Extra job."""
            pass

        app = _make_static_app(deploy)
        engine = app.execution_engine

        # Cache a plan
        plan_before = engine._get_resolution_plan(deploy)

        # Mutate the job list (which invalidates Layer 2 but NOT Layer 3)
        app.add_job_provider(StaticProvider([extra]))

        # Layer 3 cache is NOT invalidated
        plan_after = engine._get_resolution_plan(deploy)
        assert plan_before is plan_after

    def test_resolution_plan_keyed_by_function_identity(self):
        """Different functions get different cached plans."""

        def deploy():
            """Deploy job."""
            pass

        def build():
            """Build job."""
            pass

        app = _make_static_app(deploy, build)
        engine = app.execution_engine

        plan_deploy = engine._get_resolution_plan(deploy)
        plan_build = engine._get_resolution_plan(build)

        # Different functions → different plans
        assert plan_deploy is not plan_build

        # But same function → same plan
        assert engine._get_resolution_plan(deploy) is plan_deploy
        assert engine._get_resolution_plan(build) is plan_build


class TestStaticWiringBypass:
    """Static wiring bypasses Layers 1 and 2 by design."""

    def test_static_wiring_uses_static_provider_not_cached_provider(self):
        """Static wiring uses StaticProvider (no disk I/O, no CachedDirectoryScanProvider)."""
        from functualize._discovery.cached_provider import CachedDirectoryScanProvider

        def deploy():
            """Deploy job."""
            pass

        app = _make_static_app(deploy)

        # The pipeline should have a StaticProvider, not CachedDirectoryScanProvider
        pipeline = app._resolution_pipeline
        assert pipeline.provider_count >= 1
        provider = pipeline._providers[0].provider
        assert isinstance(provider, StaticProvider)
        assert not isinstance(provider, CachedDirectoryScanProvider)

    def test_static_wiring_layer3_still_active(self):
        """Even in static wiring, Layer 3 (ResolutionPlan cache) is active."""

        def deploy():
            """Deploy job."""
            pass

        app = _make_static_app(deploy)
        engine = app.execution_engine

        # Verify the cache dict exists and is populated on use
        assert isinstance(engine._resolution_plan_cache, dict)

        plan = engine._get_resolution_plan(deploy)
        assert id(deploy) in engine._resolution_plan_cache
        assert engine._resolution_plan_cache[id(deploy)] is plan

    def test_static_wiring_get_jobs_returns_correct_list(self):
        """Static wiring app.get_jobs() returns the correct job list."""

        def deploy():
            """Deploy job."""
            pass

        def build():
            """Build job."""
            pass

        app = _make_static_app(deploy, build)

        jobs = app.get_jobs()
        names = {j.name for j in jobs}
        assert names == {"deploy", "build"}
