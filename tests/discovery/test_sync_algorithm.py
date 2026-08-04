"""Unit tests for the boot-time discovery reconciliation algorithm.

Validates that:
- discover_module_files scans directories using pkgutil paths (no imports)
- New files on disk are imported and added to cache
- Deleted files have their cache entries removed
- Invalid cache entries trigger re-import
- Import failures are logged and skipped
- Cache is written to disk after reconciliation
- Return value is a sequence of all valid JobDescriptors

Requirements validated: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._discovery.sync import (
    discover_module_files,
    full_import_and_extract,
)
from functualize._primitives.cache_format import (
    CACHE_FILENAME,
    CACHE_VERSION,
    compute_deps_hash,
    get_functualize_version,
)
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor


def _make_descriptor(
    name: str = "deploy",
    module_path: str = "deploy",
    source_file: str = "/tmp/project/jobs/deploy.py",
    source_mtime: float = 1000.0,
    content_hash: str = "abc123",
) -> JobDescriptor:
    """Create a simple JobDescriptor for testing."""
    return JobDescriptor(
        name=name,
        group=None,
        module_path=module_path,
        source_file=source_file,
        source_mtime=source_mtime,
        content_hash=content_hash,
        docstring=f"{name} job",
        config_fields=[],
        dependencies={},
    )


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


def _write_valid_cache(project_root: Path, entries: dict | None = None) -> None:
    """Write a valid cache file with optional entries."""
    cache_path = _cache_path(project_root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CACHE_VERSION,
        "functualize_version": get_functualize_version(),
        "python_version": platform.python_version(),
        "deps_hash": compute_deps_hash(project_root),
        "generated_at": "2025-01-01T00:00:00+00:00",
        "entries": entries or {},
        "pre_filter_decisions": {},
    }
    cache_path.write_text(json.dumps(data), encoding="utf-8")


def _create_job_module(jobs_dir: Path, name: str, content: str | None = None) -> Path:
    """Create a Python job module file in a directory.

    Args:
        jobs_dir: The directory to create the module in.
        name: The module name (without .py extension).
        content: Optional custom content. Defaults to a simple job function.

    Returns:
        Path to the created module file.
    """
    if content is None:
        content = f'''"""A {name} job."""

def {name}():
    """{name.title()} job function."""
    pass
'''
    module_path = jobs_dir / f"{name}.py"
    module_path.write_text(content, encoding="utf-8")
    return module_path


class TestDiscoverModuleFiles:
    """Tests for discover_module_files filesystem scanning."""

    def test_discovers_py_files_in_directory(self, tmp_path: Path) -> None:
        """Should find .py files in the given directory."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")
        _create_job_module(jobs_dir, "build")

        result = discover_module_files([str(jobs_dir)])

        assert len(result) == 2
        assert str((jobs_dir / "deploy.py").resolve()) in result
        assert str((jobs_dir / "build.py").resolve()) in result

    def test_skips_packages(self, tmp_path: Path) -> None:
        """Should skip sub-packages (directories with __init__.py)."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")

        sub_pkg = jobs_dir / "sub_pkg"
        sub_pkg.mkdir()
        (sub_pkg / "__init__.py").write_text("")

        result = discover_module_files([str(jobs_dir)])

        assert len(result) == 1
        assert str((jobs_dir / "deploy.py").resolve()) in result

    def test_handles_nonexistent_directory(self, tmp_path: Path) -> None:
        """Should handle non-existent directories gracefully."""
        result = discover_module_files([str(tmp_path / "nonexistent")])
        assert result == set()

    def test_handles_multiple_directories(self, tmp_path: Path) -> None:
        """Should scan multiple directories."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        dir2 = tmp_path / "dir2"
        dir2.mkdir()

        _create_job_module(dir1, "job1")
        _create_job_module(dir2, "job2")

        result = discover_module_files([str(dir1), str(dir2)])

        assert len(result) == 2

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Should return empty set for empty directory."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        result = discover_module_files([str(jobs_dir)])
        assert result == set()


class TestFullImportAndExtract:
    """Tests for full_import_and_extract module import + descriptor extraction."""

    def test_extracts_simple_job(self, tmp_path: Path) -> None:
        """Should extract a JobDescriptor from a simple job module."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        module_file = _create_job_module(jobs_dir, "deploy")

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert len(descriptors) == 1
        assert descriptors[0].name == "deploy"
        assert descriptors[0].source_file == str(module_file.resolve())
        assert descriptors[0].content_hash != ""
        assert descriptors[0].source_mtime > 0

    def test_extracts_job_with_group(self, tmp_path: Path) -> None:
        """Should extract group from JOB_GROUP module attribute."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""A grouped job."""

JOB_GROUP = "infra"

def provision():
    """Provision infrastructure."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "infra_job", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert len(descriptors) == 1
        assert descriptors[0].name == "infra.provision"
        assert descriptors[0].group == "infra"

    def test_extracts_job_with_config(self, tmp_path: Path) -> None:
        """Should extract config fields from a Pydantic BaseModel parameter."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""A job with config."""

from pydantic import BaseModel

class DeployConfig(BaseModel):
    region: str = "us-east-1"
    replicas: int = 3

def deploy(config: DeployConfig):
    """Deploy to cloud."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "deploy_config", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert len(descriptors) == 1
        assert descriptors[0].name == "deploy"
        assert len(descriptors[0].config_fields) == 2
        field_names = {f.name for f in descriptors[0].config_fields}
        assert "region" in field_names
        assert "replicas" in field_names

    def test_raises_on_syntax_error(self, tmp_path: Path) -> None:
        """Should raise SyntaxError for files with syntax errors."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        module_file = jobs_dir / "bad.py"
        module_file.write_text("def broken(:\n    pass\n")

        with pytest.raises(SyntaxError):
            full_import_and_extract(str(module_file.resolve()), tmp_path)

    def test_returns_empty_on_no_job_function(self, tmp_path: Path) -> None:
        """Should return empty list when no registerable function is found."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Empty module with no functions."""

SOME_CONSTANT = 42
'''
        module_file = _create_job_module(jobs_dir, "empty_mod", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)
        assert descriptors == []

    def test_extracts_all_public_functions(self, tmp_path: Path) -> None:
        """Should extract ALL public functions from a multi-function module."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Multi-function module."""

def deploy():
    """Deploy job."""
    pass

def build():
    """Build job."""
    pass

def test_something():
    """Test job."""
    pass

def _private_helper():
    """Should be skipped."""
    pass

MY_CONSTANT = 42
'''
        module_file = _create_job_module(jobs_dir, "multi", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        # Should extract 3 public functions (deploy, build, test_something)
        # _private_helper and MY_CONSTANT should be skipped
        names = {d.name for d in descriptors}
        assert names == {"deploy", "build", "test-something"}
        assert len(descriptors) == 3

    def test_multi_function_with_group(self, tmp_path: Path) -> None:
        """All functions in a module with JOB_GROUP should share the group."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Grouped multi-function module."""

JOB_GROUP = "infra"

def provision():
    """Provision."""
    pass

def teardown():
    """Teardown."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "infra_jobs", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert len(descriptors) == 2
        names = {d.name for d in descriptors}
        assert names == {"infra.provision", "infra.teardown"}
        for d in descriptors:
            assert d.group == "infra"

    def test_skips_imported_functions(self, tmp_path: Path) -> None:
        """Functions imported from other modules should be skipped."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with imports."""

from os.path import join

def my_job():
    """My job."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "with_imports", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        # Only my_job should be extracted, not 'join'
        assert len(descriptors) == 1
        assert descriptors[0].name == "my-job"


class TestListJobsReconciliation:
    """Tests for the list_jobs() cache reconciliation algorithm."""

    def test_new_files_added_to_cache(self, tmp_path: Path) -> None:
        """New files on disk should be imported and added to cache."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")

        provider = _make_provider(tmp_path, [str(jobs_dir)])
        assert len(provider._entries) == 0

        result = provider.list_jobs()

        assert len(result) == 1
        assert result[0].name == "deploy"

    def test_deleted_files_removed_from_cache(self, tmp_path: Path) -> None:
        """Cache entries with no file on disk should be removed."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create a cache with an entry for a file that doesn't exist
        fake_source = str((jobs_dir / "old_job.py").resolve())
        descriptor = _make_descriptor(
            name="old_job",
            module_path="old_job",
            source_file=fake_source,
        )
        _write_valid_cache(
            tmp_path,
            {f"{descriptor.source_file}::{descriptor.name}": descriptor.to_dict()},
        )

        provider = _make_provider(tmp_path, [str(jobs_dir)])
        assert len(provider._entries) == 1

        result = provider.list_jobs()

        assert len(result) == 0

    def test_existing_valid_entries_preserved(self, tmp_path: Path) -> None:
        """Valid cache entries should be preserved without re-import."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")

        # First reconciliation to populate cache
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        result1 = provider.list_jobs()
        assert len(result1) == 1

        # Second reconciliation should preserve the entry (file unchanged)
        provider2 = _make_provider(tmp_path, [str(jobs_dir)])

        with patch("functualize._discovery.sync.extract_module") as mock_import:
            result2 = provider2.list_jobs()

        # extract_module should NOT have been called (entry is valid)
        mock_import.assert_not_called()

        # The entry should still be there
        assert len(result2) == 1
        assert result2[0].name == "deploy"

    def test_invalid_entries_reimported(self, tmp_path: Path) -> None:
        """Invalid cache entries should trigger re-import."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        module_file = _create_job_module(jobs_dir, "deploy")

        # First reconciliation to populate
        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        # Modify the file to invalidate
        new_content = '''"""Updated deploy job."""

def deploy():
    """Updated deploy function."""
    return "v2"
'''
        module_file.write_text(new_content, encoding="utf-8")

        # Second reconciliation should detect the change and re-import
        provider2 = _make_provider(tmp_path, [str(jobs_dir)])
        result = provider2.list_jobs()

        assert len(result) == 1
        assert result[0].name == "deploy"
        assert result[0].docstring == "Updated deploy function."

    def test_import_failures_skipped(self, tmp_path: Path) -> None:
        """Import failures should be logged and skipped."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Create a module with a syntax error
        bad_file = jobs_dir / "bad_job.py"
        bad_file.write_text("def broken(:\n    pass\n")

        # Create a valid module
        _create_job_module(jobs_dir, "good_job")

        provider = _make_provider(tmp_path, [str(jobs_dir)])
        result = provider.list_jobs()

        # Only the good job should be in results
        assert len(result) == 1
        assert result[0].name == "good-job"

    def test_cache_written_after_reconciliation(self, tmp_path: Path) -> None:
        """Cache should be written to disk after reconciliation."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "deploy")

        provider = _make_provider(tmp_path, [str(jobs_dir)])
        provider.list_jobs()

        cache_path = _cache_path(tmp_path)
        assert cache_path.exists()

        # Verify the cache file contains the entry and format header
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["version"] == CACHE_VERSION
        assert "entries" in data
        assert len(data["entries"]) == 1

    def test_returns_all_valid_descriptors(self, tmp_path: Path) -> None:
        """Should return all valid JobDescriptor entries."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_job_module(jobs_dir, "job1")
        _create_job_module(jobs_dir, "job2")
        _create_job_module(jobs_dir, "job3")

        provider = _make_provider(tmp_path, [str(jobs_dir)])
        result = provider.list_jobs()

        assert len(result) == 3
        names = {d.name for d in result}
        assert names == {"job1", "job2", "job3"}

    def test_empty_dirs_returns_empty_list(self, tmp_path: Path) -> None:
        """Should return empty list when no modules are found."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        provider = _make_provider(tmp_path, [str(jobs_dir)])
        result = provider.list_jobs()

        assert list(result) == []

    def test_multiple_dirs(self, tmp_path: Path) -> None:
        """Should handle scanning multiple job directories."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        dir2 = tmp_path / "dir2"
        dir2.mkdir()

        _create_job_module(dir1, "job_a")
        _create_job_module(dir2, "job_b")

        provider = _make_provider(tmp_path, [str(dir1), str(dir2)])
        result = provider.list_jobs()

        assert len(result) == 2
        names = {d.name for d in result}
        assert names == {"job-a", "job-b"}


class TestJobGroupValidation:
    """Tests for JOB_GROUP validation at discovery time (Requirement 2)."""

    def test_invalid_job_group_empty_segment_skips_module(self, tmp_path: Path) -> None:
        """Module with JOB_GROUP containing empty segments is skipped."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with bad group."""

JOB_GROUP = "infra..aws"

def provision():
    """Provision."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "bad_group", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert descriptors == []

    def test_invalid_job_group_leading_dot_skips_module(self, tmp_path: Path) -> None:
        """Module with JOB_GROUP having a leading dot is skipped."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with leading dot group."""

JOB_GROUP = ".infra"

def provision():
    """Provision."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "leading_dot", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert descriptors == []

    def test_invalid_job_group_trailing_dot_skips_module(self, tmp_path: Path) -> None:
        """Module with JOB_GROUP having a trailing dot is skipped."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with trailing dot group."""

JOB_GROUP = "infra."

def provision():
    """Provision."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "trailing_dot", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert descriptors == []

    def test_invalid_job_group_non_identifier_skips_module(
        self, tmp_path: Path
    ) -> None:
        """Module with JOB_GROUP segment that isn't a valid identifier is skipped."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with invalid segment."""

JOB_GROUP = "infra.123bad"

def provision():
    """Provision."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "bad_segment", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert descriptors == []

    def test_invalid_job_group_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid JOB_GROUP produces a warning log message."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with bad group."""

JOB_GROUP = "infra..aws"

def provision():
    """Provision."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "warn_group", content)

        import logging

        with caplog.at_level(logging.WARNING):
            full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert any("invalid JOB_GROUP" in record.message for record in caplog.records)

    def test_valid_job_group_still_works(self, tmp_path: Path) -> None:
        """Valid JOB_GROUP values pass validation and produce descriptors."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        content = '''"""Module with valid nested group."""

JOB_GROUP = "infra.aws"

def provision():
    """Provision."""
    pass
'''
        module_file = _create_job_module(jobs_dir, "valid_group", content)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert len(descriptors) == 1
        assert descriptors[0].name == "infra.aws.provision"
        assert descriptors[0].group == "infra.aws"
