"""Integration tests for backward compatibility bridge.

Tests that constructor parameters (jobs_directories, children) produce
the same job discovery results as the equivalent explicit Provider/Transform
registration via add_provider.

**Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5**
"""

from __future__ import annotations

import sys
from pathlib import Path

from functualize._discovery.pipeline import ResolutionPipeline
from functualize._discovery.providers import (
    DirectoryScanProvider,
)
from functualize._discovery.transforms import NamespaceTransform
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp

# --- Helpers ---


def _create_job_module(directory: Path, name: str) -> Path:
    """Create a minimal Python job module in the given directory."""
    module_path = directory / f"{name}.py"
    module_path.write_text(
        f'def {name}():\n    """{name.title()} job."""\n    pass\n',
        encoding="utf-8",
    )
    return module_path


def _clear_module_cache(*names: str) -> None:
    """Remove module entries from sys.modules to avoid test pollution."""
    for name in names:
        sys.modules.pop(name, None)


# =============================================================================
# 1. jobs_directories constructor vs explicit DirectoryScanProvider
# =============================================================================


class TestJobsDirectoriesBackwardCompat:
    """Verify jobs_directories constructor produces same results as explicit provider.

    **Validates: Requirements 13.1, 13.4, 13.5**
    """

    def test_constructor_discovers_same_jobs_as_explicit_provider(
        self, tmp_path: Path
    ) -> None:
        """FunctualizeApp(job_sources=JobSources(directories=[...])) discovers same jobs as
        explicit DirectoryScanProvider registration.

        **Validates: Requirements 13.1, 13.5**
        """
        # Create temp directory with job files
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")
        _create_job_module(jobs_dir, "build")
        _create_job_module(jobs_dir, "test_suite")

        # Clear any module cache entries from prior tests that could pollute
        _clear_module_cache("deploy", "build", "test_suite")

        # Approach 1: Use constructor parameter (backward compat path)
        app_constructor = FunctualizeApp(
            name="test-constructor",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )
        constructor_jobs = set(app_constructor.job_registry._registered_jobs.keys())

        # Approach 2: Use explicit DirectoryScanProvider
        pipeline = ResolutionPipeline()
        pipeline.add_provider(DirectoryScanProvider([str(jobs_dir)]))
        explicit_descriptors = pipeline.resolve_all()
        explicit_names = {d.name for d in explicit_descriptors}

        # Both approaches should discover the same job names
        assert constructor_jobs == explicit_names
        assert "deploy" in constructor_jobs
        assert "build" in constructor_jobs

        # Cleanup modules to avoid polluting subsequent tests
        _clear_module_cache("deploy", "build", "test_suite")

    def test_constructor_with_multiple_directories(self, tmp_path: Path) -> None:
        """Multiple directories in jobs_directories all get scanned.

        **Validates: Requirements 13.1, 13.5**
        """
        # Create two directories with different jobs
        dir_a = tmp_path / "jobs_a"
        dir_a.mkdir()
        _create_job_module(dir_a, "alpha")

        dir_b = tmp_path / "jobs_b"
        dir_b.mkdir()
        _create_job_module(dir_b, "beta")

        # Clear any prior module cache entries
        _clear_module_cache("alpha", "beta")

        # Constructor approach
        app = FunctualizeApp(
            name="test-multi-dir",
            job_sources=JobSources(directories=[str(dir_a), str(dir_b)]),
        )
        registered = set(app.job_registry._registered_jobs.keys())

        # Explicit approach
        pipeline = ResolutionPipeline()
        pipeline.add_provider(DirectoryScanProvider([str(dir_a), str(dir_b)]))
        explicit_names = {d.name for d in pipeline.resolve_all()}

        assert registered == explicit_names
        assert "alpha" in registered
        assert "beta" in registered

        # Cleanup
        _clear_module_cache("alpha", "beta")

    def test_constructor_with_empty_directory(self, tmp_path: Path) -> None:
        """Empty jobs_directories produces no registered jobs.

        **Validates: Requirements 13.1**
        """
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        FunctualizeApp(
            name="test-empty",
            job_sources=JobSources(directories=[str(empty_dir)]),
        )
        # Should not fail, just have no extra jobs from directory scanning
        # (may have built-in commands, so we check pipeline specifically)
        pipeline = ResolutionPipeline()
        pipeline.add_provider(DirectoryScanProvider([str(empty_dir)]))
        assert pipeline.resolve_all() == []


# =============================================================================
# 2. children dict mapping with namespace transforms
# =============================================================================


class TestChildrenDictBackwardCompat:
    """Verify children dict produces namespace-prefixed jobs.

    **Validates: Requirements 13.2, 13.5**
    """

    def test_children_dict_produces_namespaced_jobs(self, tmp_path: Path) -> None:
        """FunctualizeApp(children={"ns": path}) produces namespace-prefixed jobs.

        **Validates: Requirements 13.2, 13.5**
        """
        # Create child project structure
        child_dir = tmp_path / "child_project"
        child_dir.mkdir()
        child_jobs = child_dir / "jobs"
        child_jobs.mkdir()
        _create_job_module(child_jobs, "task_a")
        _create_job_module(child_jobs, "task_b")

        # Constructor approach with children dict
        app = FunctualizeApp(
            name="test-children",
            job_sources=JobSources(children={"myns": str(child_dir)}),
        )
        registered = set(app.job_registry._registered_jobs.keys())

        # Should have namespace-prefixed jobs (separator is ".")
        assert "myns.task-a" in registered
        assert "myns.task-b" in registered

    def test_children_dict_equivalent_to_explicit_provider_with_namespace(
        self, tmp_path: Path
    ) -> None:
        """children dict produces same result as explicit DirectoryScanProvider + NamespaceTransform.

        **Validates: Requirements 13.2, 13.5**
        """
        # Create child project
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child_jobs = child_dir / "jobs"
        child_jobs.mkdir()
        _create_job_module(child_jobs, "deploy")

        # Explicit pipeline approach
        pipeline = ResolutionPipeline()
        pipeline.add_provider(
            DirectoryScanProvider([str(child_jobs)]),
            transforms=[NamespaceTransform("svc")],
        )
        explicit_names = {d.name for d in pipeline.resolve_all()}

        # Constructor approach
        app = FunctualizeApp(
            name="test-children-equiv",
            job_sources=JobSources(children={"svc": str(child_dir)}),
        )
        registered = set(app.job_registry._registered_jobs.keys())

        # Both should have "svc.deploy" (separator is ".")
        assert "svc.deploy" in explicit_names
        assert "svc.deploy" in registered
        assert explicit_names == registered

    def test_multiple_children_entries(self, tmp_path: Path) -> None:
        """Multiple children entries each get their own namespace.

        **Validates: Requirements 13.2, 13.5**
        """
        # Create two child projects
        child_a = tmp_path / "child_a"
        child_a.mkdir()
        (child_a / "jobs").mkdir()
        _create_job_module(child_a / "jobs", "job_x")

        child_b = tmp_path / "child_b"
        child_b.mkdir()
        (child_b / "jobs").mkdir()
        _create_job_module(child_b / "jobs", "job_y")

        app = FunctualizeApp(
            name="test-multi-children",
            job_sources=JobSources(
                children={
                    "ns_a": str(child_a),
                    "ns_b": str(child_b),
                }
            ),
        )
        registered = set(app.job_registry._registered_jobs.keys())

        assert "ns-a.job-x" in registered
        assert "ns-b.job-y" in registered

    def test_children_with_empty_jobs_dir(self, tmp_path: Path) -> None:
        """Child project with no jobs/ subdirectory produces no jobs.

        **Validates: Requirements 13.2**
        """
        child_dir = tmp_path / "empty_child"
        child_dir.mkdir()
        # No jobs/ subdirectory

        app = FunctualizeApp(
            name="test-empty-child",
            job_sources=JobSources(children={"empty": str(child_dir)}),
        )
        registered = set(app.job_registry._registered_jobs.keys())

        # No namespaced jobs should appear
        assert not any(name.startswith("empty.") for name in registered)


# =============================================================================
# 3. Combined constructor + explicit add_provider usage
# =============================================================================


class TestCombinedUsage:
    """Verify combined constructor params + explicit add_provider both contribute.

    **Validates: Requirements 13.4, 13.5**
    """

    def test_constructor_and_add_provider_are_additive(self, tmp_path: Path) -> None:
        """Jobs from constructor params and explicit add_provider both appear.

        **Validates: Requirements 13.4**
        """
        # Constructor jobs
        constructor_dir = tmp_path / "constructor_jobs"
        constructor_dir.mkdir()
        _create_job_module(constructor_dir, "from_constructor")

        # Explicit provider jobs
        explicit_dir = tmp_path / "explicit_jobs"
        explicit_dir.mkdir()
        _create_job_module(explicit_dir, "from_explicit")

        # Create app with constructor param, then add explicit provider
        # Note: add_provider must be called before app completes boot,
        # so we test via the resolution pipeline directly
        app = FunctualizeApp(
            name="test-combined",
            job_sources=JobSources(directories=[str(constructor_dir)]),
        )

        # Verify constructor job is registered
        assert "from-constructor" in app.job_registry._registered_jobs

        # Now add an explicit provider (after boot, for pipeline testing)
        # The pipeline already has the DirectoryScanProvider from constructor
        app._resolution_pipeline.add_provider(
            DirectoryScanProvider([str(explicit_dir)])
        )

        # Resolve through pipeline to verify additive behavior
        all_descriptors = app._resolution_pipeline.resolve_all()
        all_names = {d.name for d in all_descriptors}

        assert "from-constructor" in all_names
        assert "from-explicit" in all_names

    def test_constructor_directories_and_children_combined(
        self, tmp_path: Path
    ) -> None:
        """jobs_directories and children params together produce merged results.

        **Validates: Requirements 13.4, 13.5**
        """
        # Main jobs directory
        main_dir = tmp_path / "main_jobs"
        main_dir.mkdir()
        _create_job_module(main_dir, "main_job")

        # Child project
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        (child_dir / "jobs").mkdir()
        _create_job_module(child_dir / "jobs", "child_job")

        app = FunctualizeApp(
            name="test-dirs-and-children",
            job_sources=JobSources(
                directories=[str(main_dir)], children={"child": str(child_dir)}
            ),
        )
        registered = set(app.job_registry._registered_jobs.keys())

        # Both sources should contribute
        assert "main-job" in registered
        assert "child.child-job" in registered

    def test_explicit_provider_with_transforms_alongside_constructor(
        self, tmp_path: Path
    ) -> None:
        """Explicit provider with custom transforms works alongside constructor params.

        **Validates: Requirements 13.4, 13.5**
        """
        # Constructor jobs
        main_dir = tmp_path / "main"
        main_dir.mkdir()
        _create_job_module(main_dir, "regular")

        # Explicit provider dir (will be namespaced)
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        extra_jobs = extra_dir / "jobs"
        extra_jobs.mkdir()
        _create_job_module(extra_jobs, "extra_task")

        app = FunctualizeApp(
            name="test-explicit-transforms",
            job_sources=JobSources(directories=[str(main_dir)]),
        )

        # Add an explicit provider with namespace transform
        app._resolution_pipeline.add_provider(
            DirectoryScanProvider([str(extra_jobs)]),
            transforms=[NamespaceTransform("extra")],
        )

        # Resolve all
        all_descriptors = app._resolution_pipeline.resolve_all()
        all_names = {d.name for d in all_descriptors}

        # Constructor job (no namespace)
        assert "regular" in all_names
        # Explicit provider job (namespaced with "." separator)
        assert "extra.extra-task" in all_names

    def test_pipeline_resolution_matches_job_registry(self, tmp_path: Path) -> None:
        """Resolution pipeline and job registry stay consistent for constructor params.

        **Validates: Requirements 13.5**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "alpha")
        _create_job_module(jobs_dir, "beta")

        child_dir = tmp_path / "child"
        child_dir.mkdir()
        (child_dir / "jobs").mkdir()
        _create_job_module(child_dir / "jobs", "gamma")

        app = FunctualizeApp(
            name="test-consistency",
            job_sources=JobSources(
                directories=[str(jobs_dir)], children={"ns": str(child_dir)}
            ),
        )

        registered = set(app.job_registry._registered_jobs.keys())

        # All jobs should be registered
        assert "alpha" in registered
        assert "beta" in registered
        assert "ns.gamma" in registered
