"""Unit tests for built-in providers: DirectoryScanProvider, EntryPointProvider.

Tests cover construction validation, scanning behavior with temp directories,
caching, and mocked entry point discovery.

**Validates: Requirements 6.1-6.5, 8.1-8.5**
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from functualize._discovery.providers import (
    DirectoryScanProvider,
    EntryPointProvider,
)
from functualize._types.descriptors import JobDescriptor

# --- Helpers ---


def _make_descriptor(name: str, group: str | None = None) -> JobDescriptor:
    """Create a minimal JobDescriptor for testing."""
    return JobDescriptor(
        name=name,
        group=group,
        module_path=f"test.{name}",
        source_file=f"/fake/{name}.py",
        source_mtime=0.0,
        content_hash="a" * 64,
        docstring=None,
        config_fields=[],
        dependencies={},
        metadata=None,
    )


# =============================================================================
# DirectoryScanProvider Tests
# =============================================================================


class TestDirectoryScanProvider:
    """Tests for DirectoryScanProvider.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    """

    def test_empty_directories_raises_value_error(self) -> None:
        """Empty directories list raises ValueError.

        **Validates: Requirements 6.1**
        """
        with pytest.raises(ValueError, match="At least one directory path is required"):
            DirectoryScanProvider(directories=[])

    def test_non_existent_directory_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-existent directory is skipped with a warning log.

        **Validates: Requirements 6.4**
        """
        fake_dir = str(tmp_path / "does_not_exist")
        provider = DirectoryScanProvider(directories=[fake_dir])

        with caplog.at_level(logging.WARNING):
            jobs = provider.list_jobs()

        assert jobs == []
        assert "not found or not readable" in caplog.text

    def test_valid_directory_scans_and_returns_descriptors(
        self, tmp_path: Path
    ) -> None:
        """Valid directory with job modules returns descriptors.

        **Validates: Requirements 6.2, 6.3**
        """
        # Create a simple job module
        job_file = tmp_path / "deploy.py"
        job_file.write_text('def deploy():\n    """Deploy job."""\n    pass\n')

        provider = DirectoryScanProvider(directories=[str(tmp_path)])
        jobs = provider.list_jobs()

        assert len(jobs) == 1
        assert jobs[0].name == "deploy"

    def test_mixed_valid_and_invalid_directories(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Mix of valid and invalid directories: valid ones scanned, invalid skipped.

        **Validates: Requirements 6.2, 6.4**
        """
        # Create a valid directory with a job
        valid_dir = tmp_path / "valid_jobs"
        valid_dir.mkdir()
        job_file = valid_dir / "build.py"
        job_file.write_text('def build():\n    """Build job."""\n    pass\n')

        # Non-existent directory
        fake_dir = str(tmp_path / "nonexistent")

        provider = DirectoryScanProvider(directories=[str(valid_dir), fake_dir])

        with caplog.at_level(logging.WARNING):
            jobs = provider.list_jobs()

        # Valid directory produces descriptors
        assert len(jobs) == 1
        assert jobs[0].name == "build"
        # Warning logged for non-existent directory
        assert "not found or not readable" in caplog.text

    def test_results_are_cached_after_first_scan(self, tmp_path: Path) -> None:
        """Results are cached after the first scan call.

        **Validates: Requirements 6.2**
        """
        job_file = tmp_path / "cached_job.py"
        job_file.write_text('def cached_job():\n    """Cached job."""\n    pass\n')

        provider = DirectoryScanProvider(directories=[str(tmp_path)])

        # First call triggers scan
        jobs1 = provider.list_jobs()
        assert len(jobs1) == 1

        # Modify the directory (add a new file) - should NOT be picked up
        new_file = tmp_path / "new_job.py"
        new_file.write_text('def new_job():\n    """New job."""\n    pass\n')

        # Second call returns cached result
        jobs2 = provider.list_jobs()
        assert len(jobs2) == 1  # Still 1, not 2
        assert jobs1 is jobs2  # Same list object (cached)

    def test_get_job_returns_matching_descriptor(self, tmp_path: Path) -> None:
        """get_job returns the matching descriptor by name.

        **Validates: Requirements 6.3**
        """
        job_file = tmp_path / "test_job.py"
        job_file.write_text('def test_job():\n    """Test job."""\n    pass\n')

        provider = DirectoryScanProvider(directories=[str(tmp_path)])
        result = provider.get_job("test_job")

        assert result is not None
        assert result.name == "test-job"

    def test_get_job_returns_none_for_absent_name(self, tmp_path: Path) -> None:
        """get_job returns None for names not in the provider.

        **Validates: Requirements 6.3**
        """
        job_file = tmp_path / "existing.py"
        job_file.write_text('def existing():\n    """Existing."""\n    pass\n')

        provider = DirectoryScanProvider(directories=[str(tmp_path)])
        result = provider.get_job("nonexistent")

        assert result is None


# =============================================================================
# EntryPointProvider Tests
# =============================================================================


class TestEntryPointProvider:
    """Construction only. The provider's behaviour lives in its own file.

    ``tests/discovery/test_entry_point_jobs.py`` owns it, and owns it because
    the contract changed: this class used to assert that ``list_jobs()`` calls
    ``ep.load()`` and that a broken entry point is *absent* from the listing.
    Both are now deliberately false.

    Enumeration reads ``EntryPoint.name``/``.value`` — metadata — and imports
    nothing, because the eager version would have imported every job-publishing
    distribution on every boot. And a broken entry point stays listed with its
    name visible, failing at materialization instead: hiding it would leave a
    user with a package they installed, a job they cannot see, and no reason
    given.

    Rewritten rather than adapted. Per the constitution, code asserting a
    replaced contract is removed rather than kept alongside — there are no
    users to deprecate toward.

    **Validates: Requirements 8.1**
    """

    def test_default_group_is_functualize_jobs(self) -> None:
        """Default group parameter is 'functualize.jobs'.

        **Validates: Requirements 8.1**
        """
        provider = EntryPointProvider()
        assert provider._group == "functualize.jobs"

    def test_custom_group(self) -> None:
        """Custom group name is accepted.

        **Validates: Requirements 8.1**
        """
        provider = EntryPointProvider(group="my.custom.group")
        assert provider._group == "my.custom.group"

    def test_an_empty_group_yields_no_jobs(self) -> None:
        with patch("functualize._discovery.providers.entry_points", return_value=()):
            assert EntryPointProvider().list_jobs() == []
