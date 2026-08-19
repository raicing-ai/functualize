"""Property-based tests for tiered cache validation.

Tests Properties 4 and 5 from the design document for the
layered-architecture-lazy-boot spec, now implemented by
CachedDirectoryScanProvider.

Property 4 — Validates: Requirements 7.1, 7.2, 7.3
Property 5 — Validates: Requirements 7.4
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor

# --- Helpers ---


def _create_provider(project_root: Path) -> CachedDirectoryScanProvider:
    """Create a cache provider rooted at a minimal valid project."""
    (project_root / "pyproject.toml").write_text(
        '[project]\ndependencies = ["click"]\n'
    )
    cache_dir = project_root / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=project_root
    )


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


# --- Strategies ---


@st.composite
def file_contents(draw: st.DrawFn) -> bytes:
    """Generate non-empty file content as bytes."""
    text = draw(
        st.text(
            min_size=1,
            max_size=200,
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
            ),
        )
    )
    return text.encode("utf-8")


# --- Property 4: Tiered cache validation correctness ---


# Feature: layered-architecture-lazy-boot, Property 4: Tiered cache validation correctness
class TestTieredCacheValidationCorrectness:
    """Property 4: Tiered cache validation correctness.

    For any cache entry and corresponding source file on disk: if the file's
    mtime matches source_mtime, the entry is VALID (Tier 1 pass); if mtime
    differs but sha256 of file content matches content_hash, the entry is VALID
    and source_mtime is updated in memory (Tier 2 pass); if both mtime and
    content hash differ, the entry is INVALID (Tier 2 fail).

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(content=file_contents())
    def test_tier1_mtime_match_is_valid(self, content: bytes):
        """When file mtime matches cached source_mtime, entry is VALID (Tier 1 pass).

        # Feature: layered-architecture-lazy-boot, Property 4: Tiered cache validation correctness
        **Validates: Requirements 7.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "job.py"
            source_file.write_bytes(content)
            mtime = os.path.getmtime(str(source_file))

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=content,
                mtime=mtime,
            )
            cache._add_entry(entry)

            # Tier 1 pass: mtime matches → VALID
            assert cache._is_entry_valid(entry) is True

    @given(
        content=file_contents(), mtime_offset=st.floats(min_value=1.0, max_value=1000.0)
    )
    def test_tier2_hash_match_is_valid_and_mtime_updated(
        self, content: bytes, mtime_offset: float
    ):
        """When mtime differs but content hash matches, entry is VALID and mtime updated in memory (Tier 2 pass).

        # Feature: layered-architecture-lazy-boot, Property 4: Tiered cache validation correctness
        **Validates: Requirements 7.2**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "job.py"
            source_file.write_bytes(content)

            actual_mtime = os.path.getmtime(str(source_file))
            # Use a different mtime so Tier 1 fails
            fake_old_mtime = actual_mtime - mtime_offset

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=content,  # Same content → hash matches
                mtime=fake_old_mtime,  # Different mtime → Tier 1 fails
            )
            cache._add_entry(entry)

            # Tier 2 pass: hash matches → VALID
            assert cache._is_entry_valid(entry) is True

            # source_mtime should be updated in memory to the current file mtime
            entry_key = f"{entry.source_file}::{entry.name}"
            updated_entry = cache._entries[entry_key]
            assert updated_entry.source_mtime == actual_mtime

    @given(
        original_content=file_contents(),
        new_content=file_contents(),
        mtime_offset=st.floats(min_value=1.0, max_value=1000.0),
    )
    def test_both_mtime_and_hash_differ_is_invalid(
        self, original_content: bytes, new_content: bytes, mtime_offset: float
    ):
        """When both mtime and content hash differ, entry is INVALID (Tier 2 fail).

        # Feature: layered-architecture-lazy-boot, Property 4: Tiered cache validation correctness
        **Validates: Requirements 7.3**
        """
        assume(original_content != new_content)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "job.py"
            source_file.write_bytes(new_content)

            actual_mtime = os.path.getmtime(str(source_file))
            fake_old_mtime = actual_mtime - mtime_offset

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=original_content,  # Different from file → hash mismatch
                mtime=fake_old_mtime,  # Different mtime → Tier 1 fails
            )
            cache._add_entry(entry)

            # Both tiers fail → INVALID
            assert cache._is_entry_valid(entry) is False


# --- Property 5: Dependency-level cache invalidation ---


# Feature: layered-architecture-lazy-boot, Property 5: Dependency-level cache invalidation
class TestDependencyLevelCacheInvalidation:
    """Property 5: Dependency-level cache invalidation.

    For any cache entry that passes Tier 1 or Tier 2 validation, if any file
    path in its dependencies dict has a current sha256 that differs from the
    cached hash value, the entry SHALL be considered INVALID.

    **Validates: Requirements 7.4**
    """

    @given(
        source_content=file_contents(),
        dep_new_content=file_contents(),
        dep_old_content=file_contents(),
    )
    def test_tier1_pass_with_changed_dependency_is_invalid(
        self,
        source_content: bytes,
        dep_new_content: bytes,
        dep_old_content: bytes,
    ):
        """Entry passes Tier 1 (mtime match) but a dependency hash differs → INVALID.

        # Feature: layered-architecture-lazy-boot, Property 5: Dependency-level cache invalidation
        **Validates: Requirements 7.4**
        """
        assume(dep_new_content != dep_old_content)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Source file (Tier 1 will pass)
            source_file = tmp_path / "main_job.py"
            source_file.write_bytes(source_content)
            source_mtime = os.path.getmtime(str(source_file))

            # Dependency file: current content on disk differs from cached hash
            dep_file = tmp_path / "dependency.py"
            dep_file.write_bytes(dep_new_content)

            # Cached hash is from old content
            old_dep_hash = hashlib.sha256(dep_old_content).hexdigest()

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=source_content,
                mtime=source_mtime,  # Matches → Tier 1 passes
                module_path="main_module",
                dependencies={str(dep_file): old_dep_hash},
            )
            cache._add_entry(entry)

            # Source passes Tier 1, but dependency hash differs → INVALID
            assert cache._is_entry_valid_deep(entry) is False

    @given(
        source_content=file_contents(),
        dep_new_content=file_contents(),
        dep_old_content=file_contents(),
        mtime_offset=st.floats(min_value=1.0, max_value=1000.0),
    )
    def test_tier2_pass_with_changed_dependency_is_invalid(
        self,
        source_content: bytes,
        dep_new_content: bytes,
        dep_old_content: bytes,
        mtime_offset: float,
    ):
        """Entry passes Tier 2 (hash match, mtime differs) but a dependency hash differs → INVALID.

        # Feature: layered-architecture-lazy-boot, Property 5: Dependency-level cache invalidation
        **Validates: Requirements 7.4**
        """
        assume(dep_new_content != dep_old_content)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Source file (Tier 2 will pass: mtime differs but content hash matches)
            source_file = tmp_path / "main_job.py"
            source_file.write_bytes(source_content)
            actual_mtime = os.path.getmtime(str(source_file))
            fake_old_mtime = actual_mtime - mtime_offset

            # Dependency file: has changed since last cache
            dep_file = tmp_path / "dependency.py"
            dep_file.write_bytes(dep_new_content)
            old_dep_hash = hashlib.sha256(dep_old_content).hexdigest()

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=source_content,  # Same content → Tier 2 passes
                mtime=fake_old_mtime,  # Different mtime → Tier 1 fails
                module_path="main_module",
                dependencies={str(dep_file): old_dep_hash},
            )
            cache._add_entry(entry)

            # Source passes Tier 2, but dependency hash differs → INVALID
            assert cache._is_entry_valid_deep(entry) is False

    @given(
        source_content=file_contents(),
        dep_contents=st.lists(file_contents(), min_size=1, max_size=3),
    )
    def test_tier1_pass_with_valid_dependencies_is_valid(
        self,
        source_content: bytes,
        dep_contents: list[bytes],
    ):
        """Entry passes Tier 1 and all dependency hashes match → VALID.

        # Feature: layered-architecture-lazy-boot, Property 5: Dependency-level cache invalidation
        **Validates: Requirements 7.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Source file (Tier 1 passes)
            source_file = tmp_path / "main_job.py"
            source_file.write_bytes(source_content)
            source_mtime = os.path.getmtime(str(source_file))

            # Create dependency files with matching cached hashes
            dependencies: dict[str, str] = {}
            for i, dep_content in enumerate(dep_contents):
                dep_file = tmp_path / f"dep_{i}.py"
                dep_file.write_bytes(dep_content)
                dep_hash = hashlib.sha256(dep_content).hexdigest()
                dependencies[str(dep_file)] = dep_hash

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=source_content,
                mtime=source_mtime,
                module_path="main_module",
                dependencies=dependencies,
            )
            cache._add_entry(entry)

            # All tiers pass → VALID
            assert cache._is_entry_valid_deep(entry) is True

    @given(
        source_content=file_contents(),
        valid_dep_contents=st.lists(file_contents(), min_size=1, max_size=3),
        bad_dep_new_content=file_contents(),
        bad_dep_old_content=file_contents(),
    )
    def test_any_single_dependency_mismatch_invalidates(
        self,
        source_content: bytes,
        valid_dep_contents: list[bytes],
        bad_dep_new_content: bytes,
        bad_dep_old_content: bytes,
    ):
        """If even one dependency out of many has a mismatched hash, entry is INVALID.

        # Feature: layered-architecture-lazy-boot, Property 5: Dependency-level cache invalidation
        **Validates: Requirements 7.4**
        """
        assume(bad_dep_new_content != bad_dep_old_content)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Source file (Tier 1 passes)
            source_file = tmp_path / "main_job.py"
            source_file.write_bytes(source_content)
            source_mtime = os.path.getmtime(str(source_file))

            # Create valid dependencies
            dependencies: dict[str, str] = {}
            for i, dep_content in enumerate(valid_dep_contents):
                dep_file = tmp_path / f"valid_dep_{i}.py"
                dep_file.write_bytes(dep_content)
                dep_hash = hashlib.sha256(dep_content).hexdigest()
                dependencies[str(dep_file)] = dep_hash

            # Add one invalid dependency (current content differs from cached hash)
            bad_dep_file = tmp_path / "bad_dep.py"
            bad_dep_file.write_bytes(bad_dep_new_content)
            bad_dep_old_hash = hashlib.sha256(bad_dep_old_content).hexdigest()
            dependencies[str(bad_dep_file)] = bad_dep_old_hash

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=source_content,
                mtime=source_mtime,
                module_path="main_module",
                dependencies=dependencies,
            )
            cache._add_entry(entry)

            # One bad dependency → INVALID
            assert cache._is_entry_valid_deep(entry) is False

    @given(
        source_content=file_contents(),
        fake_hash=st.from_regex(r"[0-9a-f]{64}", fullmatch=True),
    )
    def test_missing_dependency_file_invalidates(
        self,
        source_content: bytes,
        fake_hash: str,
    ):
        """If a dependency file no longer exists on disk, entry is INVALID.

        # Feature: layered-architecture-lazy-boot, Property 5: Dependency-level cache invalidation
        **Validates: Requirements 7.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Source file (Tier 1 passes)
            source_file = tmp_path / "main_job.py"
            source_file.write_bytes(source_content)
            source_mtime = os.path.getmtime(str(source_file))

            # Non-existent dependency path
            missing_dep = tmp_path / "deleted_dep.py"

            cache = _create_provider(tmp_path)
            entry = _make_descriptor(
                source_file=str(source_file),
                content=source_content,
                mtime=source_mtime,
                module_path="main_module",
                dependencies={str(missing_dep): fake_hash},
            )
            cache._add_entry(entry)

            # Missing dependency → INVALID
            assert cache._is_entry_valid_deep(entry) is False
