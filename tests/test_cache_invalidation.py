"""Unit tests for tiered per-entry cache invalidation.

Tests CachedDirectoryScanProvider._is_entry_valid() (Tier 1 + Tier 2) and
_is_entry_valid_deep() (Tier 1 + Tier 2 + Tier 3) methods.

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor


def _make_descriptor(
    source_file: str,
    content: bytes,
    mtime: float,
    module_path: str = "test_module",
    dependencies: dict[str, str] | None = None,
) -> JobDescriptor:
    """Create a JobDescriptor with correct hash for the given content."""
    content_hash = hashlib.sha256(content).hexdigest()
    return JobDescriptor(
        name="test_job",
        group=None,
        module_path=module_path,
        source_file=source_file,
        source_mtime=mtime,
        content_hash=content_hash,
        docstring=None,
        config_fields=[],
        dependencies=dependencies or {},
    )


def _create_provider(tmp_path: Path) -> CachedDirectoryScanProvider:
    """Create a cache provider rooted at a minimal valid project."""
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["click"]\n')
    cache_dir = tmp_path / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=tmp_path
    )


class TestIsEntryValidTier1:
    """Tier 1: mtime unchanged → VALID."""

    def test_mtime_matches_returns_true(self, tmp_path: Path) -> None:
        """When mtime matches cached value, entry is valid immediately."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid(entry) is True

    def test_mtime_matches_does_not_read_content(self, tmp_path: Path) -> None:
        """Tier 1 pass should not compute sha256 (perf requirement)."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
        )
        cache._add_entry(entry)

        with patch(
            "functualize._discovery.cached_provider.Path.read_bytes"
        ) as mock_read:
            result = cache._is_entry_valid(entry)

        assert result is True
        mock_read.assert_not_called()


class TestIsEntryValidTier2:
    """Tier 2: mtime differs but sha256 matches → update mtime, VALID."""

    def test_content_unchanged_but_mtime_changed(self, tmp_path: Path) -> None:
        """When content is same but mtime differs, entry is valid + mtime updated."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        old_mtime = os.path.getmtime(str(source)) - 100.0  # Fake old mtime

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=old_mtime,
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid(entry) is True

        # Verify mtime was updated in memory
        entry_key = f"{entry.source_file}::{entry.name}"
        updated_entry = cache._entries[entry_key]
        assert updated_entry.source_mtime != old_mtime
        assert updated_entry.source_mtime == os.path.getmtime(str(source))

    def test_tier2_marks_cache_dirty(self, tmp_path: Path) -> None:
        """When Tier 2 passes, cache is marked dirty for persistence."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        old_mtime = os.path.getmtime(str(source)) - 50.0

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=old_mtime,
        )
        cache._add_entry(entry)
        cache._dirty = False  # Reset dirty flag after add

        cache._is_entry_valid(entry)

        assert cache._dirty is True


class TestIsEntryValidBothFail:
    """Both Tier 1 and Tier 2 fail → INVALID."""

    def test_content_changed_returns_false(self, tmp_path: Path) -> None:
        """When both mtime and content hash differ, entry is invalid."""
        source = tmp_path / "job.py"
        source.write_text("x = 2")  # Different content
        old_mtime = os.path.getmtime(str(source)) - 100.0

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",  # Original content (different from file)
            mtime=old_mtime,
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid(entry) is False


class TestIsEntryValidDeletedFile:
    """Source file deleted → INVALID; reconciliation removes the entry."""

    def test_deleted_file_returns_false(self, tmp_path: Path) -> None:
        """When source file doesn't exist, returns False."""
        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(tmp_path / "nonexistent.py"),
            content=b"x = 1",
            mtime=12345.0,
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid(entry) is False

    def test_deleted_file_removed_by_list_jobs(self, tmp_path: Path) -> None:
        """list_jobs() reconciliation removes entries for deleted files."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        cache = _create_provider(tmp_path)
        cache._directories = [str(jobs_dir)]
        entry = _make_descriptor(
            source_file=str(jobs_dir / "nonexistent.py"),
            content=b"x = 1",
            mtime=12345.0,
        )
        cache._add_entry(entry)
        entry_key = f"{entry.source_file}::{entry.name}"
        assert entry_key in cache._entries

        cache.list_jobs()

        assert entry_key not in cache._entries


class TestIsEntryValidDeepTier3:
    """Tier 3: dependency hash verification."""

    def test_no_dependencies_passes_vacuously(self, tmp_path: Path) -> None:
        """When dependencies dict is empty, Tier 3 passes vacuously."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
            dependencies={},
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid_deep(entry) is True

    def test_all_dependencies_valid(self, tmp_path: Path) -> None:
        """When all dependency hashes match, entry is valid."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        dep = tmp_path / "helper.py"
        dep.write_text("y = 2")
        dep_hash = hashlib.sha256(b"y = 2").hexdigest()

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
            dependencies={str(dep): dep_hash},
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid_deep(entry) is True

    def test_dependency_hash_mismatch(self, tmp_path: Path) -> None:
        """When a dependency's content changed, entry is invalid."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        dep = tmp_path / "helper.py"
        dep.write_text("y = CHANGED")
        old_dep_hash = hashlib.sha256(b"y = 2").hexdigest()  # Old hash

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
            dependencies={str(dep): old_dep_hash},
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid_deep(entry) is False

    def test_dependency_file_missing(self, tmp_path: Path) -> None:
        """When a dependency file doesn't exist, entry is invalid."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
            dependencies={str(tmp_path / "missing.py"): "abc123"},
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid_deep(entry) is False

    def test_multiple_dependencies_one_invalid(self, tmp_path: Path) -> None:
        """If any single dependency is invalid, entry is invalid."""
        source = tmp_path / "job.py"
        source.write_text("x = 1")
        mtime = os.path.getmtime(str(source))

        dep_good = tmp_path / "good.py"
        dep_good.write_text("a = 1")
        good_hash = hashlib.sha256(b"a = 1").hexdigest()

        dep_bad = tmp_path / "bad.py"
        dep_bad.write_text("b = CHANGED")
        old_bad_hash = hashlib.sha256(b"b = original").hexdigest()

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",
            mtime=mtime,
            dependencies={
                str(dep_good): good_hash,
                str(dep_bad): old_bad_hash,
            },
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid_deep(entry) is False

    def test_deep_returns_false_when_tier1_tier2_fail(self, tmp_path: Path) -> None:
        """If Tier 1 + Tier 2 fail, Tier 3 is never reached."""
        source = tmp_path / "job.py"
        source.write_text("x = 2")  # Different content
        old_mtime = os.path.getmtime(str(source)) - 100.0

        cache = _create_provider(tmp_path)
        entry = _make_descriptor(
            source_file=str(source),
            content=b"x = 1",  # Original content differs
            mtime=old_mtime,
            dependencies={},
        )
        cache._add_entry(entry)

        assert cache._is_entry_valid_deep(entry) is False
