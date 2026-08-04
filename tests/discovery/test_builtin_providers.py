"""Unit tests for built-in providers: DirectoryScanProvider, EntryPointProvider.

Tests cover construction validation, scanning behavior with temp directories,
caching, and mocked entry point discovery.

**Validates: Requirements 6.1-6.5, 8.1-8.5**
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """Tests for EntryPointProvider.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
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

    @patch("importlib.metadata.entry_points")
    def test_successful_entry_point_load(self, mock_entry_points: MagicMock) -> None:
        """Successful entry point load builds a JobDescriptor.

        **Validates: Requirements 8.2, 8.3**
        """
        # Create a mock entry point
        mock_ep = MagicMock()
        mock_ep.name = "my_plugin_job"
        mock_loaded = MagicMock()
        mock_loaded.__module__ = "my_plugin.jobs"
        mock_loaded.__doc__ = "A plugin job."
        mock_loaded.__annotations__ = {}
        mock_ep.load.return_value = mock_loaded

        mock_entry_points.return_value = [mock_ep]

        provider = EntryPointProvider(group="functualize.jobs")
        jobs = provider.list_jobs()

        assert len(jobs) == 1
        assert jobs[0].name == "my-plugin-job"
        assert jobs[0].module_path == ""
        assert jobs[0].docstring == "A plugin job."

    @patch("importlib.metadata.entry_points")
    def test_broken_entry_point_skipped_with_warning(
        self,
        mock_entry_points: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Broken entry point is skipped with a warning log.

        **Validates: Requirements 8.4**
        """
        # Create a mock entry point that fails to load
        mock_ep = MagicMock()
        mock_ep.name = "broken_plugin"
        mock_ep.load.side_effect = ImportError("Module not found")

        mock_entry_points.return_value = [mock_ep]

        provider = EntryPointProvider(group="functualize.jobs")

        with caplog.at_level(logging.WARNING):
            jobs = provider.list_jobs()

        assert jobs == []
        assert "Failed to load entry point 'broken_plugin'" in caplog.text

    @patch("importlib.metadata.entry_points")
    def test_mixed_successful_and_broken_entry_points(
        self,
        mock_entry_points: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Mix of successful and broken entry points: successful ones returned, broken skipped.

        **Validates: Requirements 8.2, 8.4**
        """
        # Good entry point
        good_ep = MagicMock()
        good_ep.name = "good_job"
        good_loaded = MagicMock()
        good_loaded.__module__ = "good_plugin.jobs"
        good_loaded.__doc__ = "Good job."
        good_loaded.__annotations__ = {}
        good_ep.load.return_value = good_loaded

        # Bad entry point
        bad_ep = MagicMock()
        bad_ep.name = "bad_job"
        bad_ep.load.side_effect = RuntimeError("Broken import")

        mock_entry_points.return_value = [good_ep, bad_ep]

        provider = EntryPointProvider(group="functualize.jobs")

        with caplog.at_level(logging.WARNING):
            jobs = provider.list_jobs()

        assert len(jobs) == 1
        assert jobs[0].name == "good-job"
        assert "Failed to load entry point 'bad_job'" in caplog.text

    @patch("importlib.metadata.entry_points")
    def test_get_job_returns_matching_descriptor(
        self, mock_entry_points: MagicMock
    ) -> None:
        """get_job returns the correct descriptor for a known name.

        **Validates: Requirements 8.3**
        """
        mock_ep = MagicMock()
        mock_ep.name = "lookup_job"
        mock_loaded = MagicMock()
        mock_loaded.__module__ = "plugin.module"
        mock_loaded.__doc__ = None
        mock_loaded.__annotations__ = {}
        mock_ep.load.return_value = mock_loaded

        mock_entry_points.return_value = [mock_ep]

        provider = EntryPointProvider()
        result = provider.get_job("lookup_job")

        assert result is not None
        assert result.name == "lookup-job"

    @patch("importlib.metadata.entry_points")
    def test_get_job_returns_none_for_absent_name(
        self, mock_entry_points: MagicMock
    ) -> None:
        """get_job returns None for names not found.

        **Validates: Requirements 8.3**
        """
        mock_ep = MagicMock()
        mock_ep.name = "existing_job"
        mock_loaded = MagicMock()
        mock_loaded.__module__ = "plugin.module"
        mock_loaded.__doc__ = None
        mock_loaded.__annotations__ = {}
        mock_ep.load.return_value = mock_loaded

        mock_entry_points.return_value = [mock_ep]

        provider = EntryPointProvider()
        result = provider.get_job("nonexistent")

        assert result is None

    @patch("importlib.metadata.entry_points")
    def test_results_are_cached(self, mock_entry_points: MagicMock) -> None:
        """Results are cached after the first call to list_jobs.

        **Validates: Requirements 8.2**
        """
        mock_ep = MagicMock()
        mock_ep.name = "cached_ep"
        mock_loaded = MagicMock()
        mock_loaded.__module__ = "cached.module"
        mock_loaded.__doc__ = None
        mock_loaded.__annotations__ = {}
        mock_ep.load.return_value = mock_loaded

        mock_entry_points.return_value = [mock_ep]

        provider = EntryPointProvider()

        jobs1 = provider.list_jobs()
        jobs2 = provider.list_jobs()

        # Only called entry_points once (cached)
        mock_entry_points.assert_called_once()
        assert jobs1 is jobs2
