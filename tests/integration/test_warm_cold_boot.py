"""Integration tests for warm boot and cold boot paths.

Tests end-to-end flow:
- Cold boot creates the discovery cache file
- Subsequent warm boot uses cache (no module imports)
- `func --help` with real job directories shows all commands
- Performance benchmark: 50 modules warm boot < 10ms

Requirements validated: 15.1, 15.2
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME, CACHE_VERSION
from functualize._primitives.locator import ResourceLocator
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_job_module(jobs_dir: Path, name: str, content: str | None = None) -> Path:
    """Create a Python job module file in a directory."""
    if content is None:
        content = f'''"""A {name} job."""

def {name}():
    """{name.title()} job function."""
    pass
'''
    module_path = jobs_dir / f"{name}.py"
    module_path.write_text(content, encoding="utf-8")
    return module_path


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


def _cache_path(project_root: Path) -> Path:
    return project_root / ".functualize" / CACHE_FILENAME


# ===========================================================================
# 1. Cold Boot → Warm Boot Cycle
# ===========================================================================


class TestColdBootWarmBootCycle:
    """Test that cold boot creates cache and subsequent warm boot uses it."""

    def test_cold_boot_creates_cache_file(self, tmp_path: Path) -> None:
        """Cold boot (no cache file) should create the discovery cache file."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")
        _create_job_module(jobs_dir, "build")

        cache_path = _cache_path(tmp_path)
        assert not cache_path.exists()

        # Cold boot via list_jobs reconciliation
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        descriptors = provider.list_jobs()

        # Cache file should now exist
        assert cache_path.exists()
        assert len(descriptors) == 2

        # Verify cache content
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["version"] == CACHE_VERSION
        assert len(data["entries"]) == 2
        # Cache keys are now composite (source_file::job_name)
        entry_names = {entry_data["name"] for entry_data in data["entries"].values()}
        assert "deploy" in entry_names
        assert "build" in entry_names

    def test_warm_boot_uses_cache_without_reimporting(self, tmp_path: Path) -> None:
        """Warm boot should read from cache without re-importing modules."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")
        _create_job_module(jobs_dir, "build")

        # First pass: cold boot to populate cache
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        assert _cache_path(tmp_path).exists()

        # Second pass: warm boot — should NOT call extract_module
        provider2 = _make_provider(tmp_path, [str(jobs_dir)])
        assert len(provider2._entries) == 2  # entries loaded from cache

        with patch("functualize._discovery.sync.extract_module") as mock_import:
            descriptors = provider2.list_jobs()

        # No modules should have been re-imported (all valid)
        mock_import.assert_not_called()
        assert len(descriptors) == 2

    def test_cold_boot_then_warm_boot_produces_same_descriptors(
        self, tmp_path: Path
    ) -> None:
        """Cold boot and warm boot should produce equivalent descriptor sets."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "alpha")
        _create_job_module(jobs_dir, "beta")
        _create_job_module(jobs_dir, "gamma")

        # Cold boot
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        cold_descriptors = provider.list_jobs()
        cold_names = {d.name for d in cold_descriptors}

        # Warm boot
        provider2 = _make_provider(tmp_path, [str(jobs_dir)])
        warm_descriptors = provider2.list_jobs()
        warm_names = {d.name for d in warm_descriptors}

        assert cold_names == warm_names == {"alpha", "beta", "gamma"}


# ===========================================================================
# 2. Warm Boot No-Import Test
# ===========================================================================


class TestWarmBootNoImport:
    """Verify that warm boot path does not import job modules."""

    def test_warm_boot_does_not_call_importlib_import_module(
        self, tmp_path: Path
    ) -> None:
        """Warm boot with valid cache entries must not call importlib.import_module."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "job_a")
        _create_job_module(jobs_dir, "job_b")
        _create_job_module(jobs_dir, "job_c")

        # Cold boot to populate cache
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        # Warm boot — mock importlib.import_module to verify it's never called
        provider2 = _make_provider(tmp_path, [str(jobs_dir)])

        with (
            patch("importlib.import_module") as mock_import_module,
            patch("functualize._discovery.sync.extract_module") as mock_full_import,
        ):
            descriptors = provider2.list_jobs()

        # Neither import path should have been triggered
        mock_full_import.assert_not_called()
        # importlib.import_module is used by lazy wrappers only at invocation time
        # During sync, it should never be called for warm boot
        for call in mock_import_module.call_args_list:
            # Only allow internal imports (not job modules)
            called_module = call[0][0] if call[0] else ""
            assert not called_module.startswith("job_"), (
                f"importlib.import_module was called for job module: {called_module}"
            )

        assert len(descriptors) == 3


# ===========================================================================
# 3. func --help Shows Commands
# ===========================================================================


class TestFuncHelpShowsCommands:
    """Test that --help with real job directories shows all job commands."""

    def test_help_shows_discovered_jobs_via_cold_boot(self, tmp_path: Path) -> None:
        """func --help should list all job commands after cold boot."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")
        _create_job_module(jobs_dir, "build")
        _create_job_module(jobs_dir, "test_runner")

        app = FunctualizeApp(
            name="test-app", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--help"])

        assert result.exit_code == 0
        assert "deploy" in result.output
        assert "build" in result.output
        assert "test-runner" in result.output or "test_runner" in result.output

    def test_help_shows_grouped_commands(self, tmp_path: Path) -> None:
        """func --help should show grouped job commands."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Infrastructure jobs."""

JOB_GROUP = "infra"

def provision():
    """Provision cloud resources."""
    pass
'''
        _create_job_module(jobs_dir, "infra_job", content)
        _create_job_module(jobs_dir, "standalone_job")

        app = FunctualizeApp(
            name="test-app", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        result = runner.invoke(app.cli_command, ["--help"])

        assert result.exit_code == 0
        assert "infra" in result.output
        assert "standalone-job" in result.output

    def test_help_shows_builtin_commands(self, tmp_path: Path) -> None:
        """func --help should show the builtin subtree alongside job commands.

        Since B2b the adapter mounts the reserved ``builtin`` group itself, so
        no hand registration is needed.
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")

        app = FunctualizeApp(
            name="test-app", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        result = runner.invoke(app.cli_command, ["--help"])

        assert result.exit_code == 0
        assert "builtin" in result.output


# ===========================================================================
# 4. Performance Benchmark
# ===========================================================================


class TestWarmBootPerformance:
    """Benchmark warm boot performance with many modules.

    Soft assertion: 50 modules warm boot < 10ms.
    CI environments may be slower, so this uses a warning rather than failure.
    """

    def test_warm_boot_50_modules_under_10ms(self, tmp_path: Path) -> None:
        """Warm boot with 50 cached modules should complete in under 10ms.

        This is a soft assertion — it warns on CI if exceeded rather than
        failing, since CI environments may have variable performance.
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create 50 job module files
        for i in range(50):
            _create_job_module(jobs_dir, f"job_{i:03d}")

        # Cold boot to populate cache
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        cache_path = _cache_path(tmp_path)
        assert cache_path.exists()

        # Verify all 50 entries are cached
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert len(data["entries"]) == 50

        # Warm boot benchmark
        iterations = 5
        times = []

        for _ in range(iterations):
            provider_instance = _make_provider(tmp_path, [str(jobs_dir)])

            start = time.perf_counter()
            descriptors = provider_instance.list_jobs()
            elapsed = time.perf_counter() - start

            times.append(elapsed)
            assert len(descriptors) == 50

        median_time_ms = sorted(times)[len(times) // 2] * 1000

        # Soft assertion: warn if exceeded, don't fail hard
        # CI environments can be significantly slower
        if median_time_ms > 10.0:
            import warnings

            warnings.warn(
                f"Warm boot median time ({median_time_ms:.2f}ms) exceeded 10ms target. "
                f"Times: {[f'{t * 1000:.2f}ms' for t in times]}. "
                f"This may be expected on slower CI hardware.",
                stacklevel=1,
            )

        # Hard limit: should always be under 100ms even on slow hardware
        assert median_time_ms < 100.0, (
            f"Warm boot took {median_time_ms:.2f}ms — exceeds hard limit of 100ms"
        )

    def test_warm_boot_scales_linearly(self, tmp_path: Path) -> None:
        """Warm boot time should scale roughly linearly with module count."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create 100 modules
        for i in range(100):
            _create_job_module(jobs_dir, f"job_{i:03d}")

        # Cold boot
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        # Benchmark with all 100 modules
        provider2 = _make_provider(tmp_path, [str(jobs_dir)])
        start = time.perf_counter()
        descriptors = provider2.list_jobs()
        elapsed_100 = time.perf_counter() - start

        assert len(descriptors) == 100

        # Per-module cost should be < 0.2ms (as per requirement 15.5)
        per_module_ms = (elapsed_100 * 1000) / 100
        if per_module_ms > 0.2:
            import warnings

            warnings.warn(
                f"Per-module warm boot cost ({per_module_ms:.3f}ms) "
                f"exceeded 0.2ms target. Total: {elapsed_100 * 1000:.2f}ms for 100 modules.",
                stacklevel=1,
            )

        # Hard limit: should not exceed 1ms per module on any reasonable hardware
        assert per_module_ms < 1.0, (
            f"Per-module cost {per_module_ms:.3f}ms exceeds hard limit of 1ms"
        )
