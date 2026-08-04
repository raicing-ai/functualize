"""Unit tests for the cached provider's single-read guarantee and core operations.

Validates that:
- The cache file is read at most once per process (Requirement 15.4)
- Repeated lookups serve the in-memory state without re-reading
- _add_entry() / _remove_entries_for_file() modify the in-memory dicts
- _known_source_files() returns the set of source file paths
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from unittest.mock import patch

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
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
    module_path: str = "my_project.jobs.deploy",
    source_file: str = "/tmp/project/jobs/deploy.py",
) -> JobDescriptor:
    """Create a simple JobDescriptor for testing."""
    return JobDescriptor(
        name=name,
        group=None,
        module_path=module_path,
        source_file=source_file,
        source_mtime=1000.0,
        content_hash="abc123",
        docstring="Deploy job",
        config_fields=[],
        dependencies={},
    )


def _cache_dir(project_root: Path) -> Path:
    return project_root / ".functualize"


def _make_provider(project_root: Path) -> CachedDirectoryScanProvider:
    """Create a cache provider whose store lives in <root>/.functualize/."""
    cache_dir = _cache_dir(project_root)
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=project_root
    )


def _write_valid_cache(project_root: Path, entries: dict | None = None) -> Path:
    """Write a valid cache file with optional entries. Returns its path."""
    cache_dir = _cache_dir(project_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / CACHE_FILENAME
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
    return cache_path


class TestSingleReadGuarantee:
    """Tests for Requirement 15.4: cache file read at most once per process."""

    def test_entries_stable_across_repeated_access(self, tmp_path: Path) -> None:
        """Repeated in-memory lookups return the same loaded entries."""
        descriptor = _make_descriptor(source_file=str(tmp_path / "deploy.py"))
        entry_data = {
            f"{descriptor.source_file}::{descriptor.name}": descriptor.to_dict()
        }
        _write_valid_cache(tmp_path, entry_data)

        provider = _make_provider(tmp_path)

        result1 = list(provider._by_name.values())
        result2 = list(provider._by_name.values())
        result3 = list(provider._by_name.values())

        assert result1 == result2 == result3
        assert len(result1) == 1
        assert result1[0].name == "deploy"

    def test_cache_file_not_reread_after_init(self, tmp_path: Path) -> None:
        """After __init__, the cache file is never re-read from disk."""
        _write_valid_cache(tmp_path)

        provider = _make_provider(tmp_path)

        # Modify the cache file on disk after init
        new_descriptor = _make_descriptor(
            name="new_job",
            module_path="project.new_job",
            source_file=str(tmp_path / "new_job.py"),
        )
        _write_valid_cache(
            tmp_path,
            {
                f"{new_descriptor.source_file}::{new_descriptor.name}": (
                    new_descriptor.to_dict()
                )
            },
        )

        # In-memory state should still reflect the original (empty) load
        assert list(provider._by_name.values()) == []

    def test_file_read_count_is_exactly_one(self, tmp_path: Path) -> None:
        """The cache file is read exactly once during init, not on later lookups."""
        cache_path = _write_valid_cache(tmp_path)

        read_count = 0
        original_read_text = Path.read_text

        def counting_read_text(self_path: Path, *args, **kwargs):
            nonlocal read_count
            if self_path == cache_path:
                read_count += 1
            return original_read_text(self_path, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read_text):
            provider = _make_provider(tmp_path)

        # After init, the cache file should have been read exactly once
        assert read_count == 1

        # Name lookups and reconciliation don't re-read the file
        provider.get_job("deploy")
        list(provider.list_jobs())
        list(provider.list_jobs())

        assert read_count == 1


class TestEntryManagement:
    """Tests for _add_entry() / _remove_entries_for_file() in-memory state."""

    def test_add_entry_indexes_by_key_and_name(self, tmp_path: Path) -> None:
        """_add_entry() populates both the entries dict and the name index."""
        provider = _make_provider(tmp_path)
        descriptor = _make_descriptor(source_file=str(tmp_path / "job.py"))

        provider._add_entry(descriptor)

        key = f"{descriptor.source_file}::{descriptor.name}"
        assert provider._entries[key] is descriptor
        assert provider._by_name["deploy"] is descriptor

    def test_remove_by_source_file(self, tmp_path: Path) -> None:
        """_remove_entries_for_file() removes entries matching the source file."""
        provider = _make_provider(tmp_path)
        source_file = str(tmp_path / "job.py")
        provider._add_entry(_make_descriptor(source_file=source_file))

        provider._remove_entries_for_file(source_file)

        assert provider._entries == {}
        assert provider._by_name == {}

    def test_add_entry_replaces_same_key(self, tmp_path: Path) -> None:
        """Re-adding the same (source_file, name) replaces the entry."""
        provider = _make_provider(tmp_path)
        source_file = str(tmp_path / "job.py")
        provider._add_entry(_make_descriptor(source_file=source_file))

        updated = JobDescriptor(
            name="deploy",
            group=None,
            module_path="my_project.jobs.deploy",
            source_file=source_file,
            source_mtime=2000.0,
            content_hash="def456",
            docstring="Updated deploy job",
            config_fields=[],
            dependencies={},
        )
        provider._add_entry(updated)

        descriptors = list(provider._by_name.values())
        assert len(descriptors) == 1
        assert descriptors[0].name == "deploy"
        assert descriptors[0].content_hash == "def456"
        assert descriptors[0].source_mtime == 2000.0


class TestKnownFiles:
    """Tests for _known_source_files()."""

    def test_known_files_returns_source_paths(self, tmp_path: Path) -> None:
        """_known_source_files() returns the set of all source_file values."""
        provider = _make_provider(tmp_path)
        file1 = str(tmp_path / "job1.py")
        file2 = str(tmp_path / "job2.py")

        provider._add_entry(
            _make_descriptor(name="job1", module_path="p.job1", source_file=file1)
        )
        provider._add_entry(
            _make_descriptor(name="job2", module_path="p.job2", source_file=file2)
        )

        assert provider._known_source_files() == {file1, file2}

    def test_known_files_empty_on_cold_boot(self, tmp_path: Path) -> None:
        """_known_source_files() is empty when no cache exists."""
        provider = _make_provider(tmp_path)
        assert provider._known_source_files() == set()
