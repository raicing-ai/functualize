"""Property-based test for sync reconciliation algorithm.

Tests Property 6 from the design document for the layered-architecture-lazy-boot spec.

Property 6: "For any set of on-disk module files and cached entries: (a) every file
on disk with no cache entry SHALL be added to the cache after sync, and (b) every
cache entry whose source file no longer exists on disk SHALL be removed from the
cache after sync."

**Validates: Requirements 8.2, 8.3**

# Feature: layered-architecture-lazy-boot, Property 6: Sync reconciliation — new files added, deleted files removed
"""

from __future__ import annotations

import hashlib
import json
import keyword
import os
import platform
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import (
    CACHE_FILENAME,
    CACHE_VERSION,
    get_functualize_version,
)
from functualize._primitives.locator import ResourceLocator

# --- Strategies ---

# Python keywords and builtins that cannot be used as function/module names safely
_PYTHON_KEYWORDS = set(keyword.kwlist) | {"True", "False", "None"}

# Valid Python identifiers for module/function names (simple lowercase with underscores)
# Filtered to exclude Python keywords which would cause syntax errors when used
# as function names in generated job modules.
_module_names = st.from_regex(r"[a-z][a-z0-9_]{2,12}", fullmatch=True).filter(
    lambda n: n.isidentifier() and not n.startswith("__") and n not in _PYTHON_KEYWORDS
)


@st.composite
def on_disk_module_names(draw: st.DrawFn) -> list[str]:
    """Generate a unique set of module names that will exist on disk."""
    return draw(st.lists(_module_names, min_size=0, max_size=8, unique=True))


@st.composite
def cached_module_names(draw: st.DrawFn) -> list[str]:
    """Generate a unique set of module names that will have cache entries."""
    return draw(st.lists(_module_names, min_size=0, max_size=8, unique=True))


def _create_simple_job_file(jobs_dir: Path, name: str) -> Path:
    """Create a minimal valid Python job module file.

    The file contains a simple public function that can be imported and
    extracted by full_import_and_extract.
    """
    content = f'''"""Job module: {name}."""

def {name}():
    """{name} job function."""
    pass
'''
    module_path = jobs_dir / f"{name}.py"
    module_path.write_text(content, encoding="utf-8")
    return module_path


def _make_cache_entry_dict(name: str, source_file: str) -> dict:
    """Create a serialized cache entry dict for a module that may not exist on disk."""
    return {
        "name": name,
        "group": None,
        "module_path": name,
        "source_file": source_file,
        "source_mtime": 1000.0,
        "content_hash": hashlib.sha256(b"fake content").hexdigest(),
        "docstring": f"{name} job function.",
        "config_fields": [],
        "dependencies": {},
    }


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


def _write_valid_cache(project_root: Path, entries: dict) -> None:
    """Write a valid cache file with the given entries dict."""
    cache_dir = project_root / ".functualize"
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CACHE_VERSION,
        "functualize_version": get_functualize_version(),
        "python_version": platform.python_version(),
        "deps_hash": "sha256:__UNREADABLE__",
        "generated_at": "2025-01-01T00:00:00+00:00",
        "entries": entries,
        "pre_filter_decisions": {},
    }
    (cache_dir / CACHE_FILENAME).write_text(json.dumps(data), encoding="utf-8")


# Feature: layered-architecture-lazy-boot, Property 6: Sync reconciliation — new files added, deleted files removed
class TestSyncReconciliation:
    """Property 6: Sync reconciliation — new files added, deleted files removed.

    For any set of on-disk module files and cached entries: (a) every file on
    disk with no cache entry SHALL be added to the cache after sync, and (b)
    every cache entry whose source file no longer exists on disk SHALL be
    removed from the cache after sync.
    """

    @given(
        disk_names=on_disk_module_names(),
        cache_only_names=cached_module_names(),
    )
    @settings(max_examples=100)
    def test_new_files_added_and_deleted_files_removed(
        self, disk_names: list[str], cache_only_names: list[str]
    ) -> None:
        """For any combination of on-disk files and cached entries, sync
        reconciliation adds new files and removes deleted files.

        # Feature: layered-architecture-lazy-boot, Property 6: Sync reconciliation — new files added, deleted files removed
        **Validates: Requirements 8.2, 8.3**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            # Ensure cache_only_names don't overlap with disk_names
            # (cache_only entries represent files that were deleted from disk)
            cache_only_names_filtered = [
                n for n in cache_only_names if n not in disk_names
            ]

            # --- Set up on-disk files ---
            on_disk_files: set[str] = set()
            for name in disk_names:
                module_file = _create_simple_job_file(jobs_dir, name)
                on_disk_files.add(str(module_file.resolve()))

            # --- Set up cached entries for "deleted" files (not on disk) ---
            cache_entries: dict[str, dict] = {}
            cached_deleted_files: set[str] = set()
            for name in cache_only_names_filtered:
                # Point to a file path in the jobs_dir that does NOT exist
                fake_source = str((jobs_dir / f"{name}.py").resolve())
                cache_entries[name] = _make_cache_entry_dict(name, fake_source)
                cached_deleted_files.add(fake_source)

            # Write the cache with only the "deleted" entries
            _write_valid_cache(tmp_path, cache_entries)

            # --- Run reconciliation ---
            provider = _make_provider(tmp_path, [str(jobs_dir)])
            result = provider.list_jobs()

            # --- Assertions ---
            result_source_files = {d.source_file for d in result}
            result_names = {d.name for d in result}

            # (a) Every file on disk with no prior cache entry SHALL be added
            for name in disk_names:
                expected_path = str((jobs_dir / f"{name}.py").resolve())
                assert expected_path in result_source_files, (
                    f"New on-disk file '{name}' was not added to cache after sync. "
                    f"Expected source_file={expected_path} in results."
                )

            # (b) Every cached entry whose source file no longer exists on disk
            #     SHALL be removed (not appear in results)
            for name in cache_only_names_filtered:
                deleted_path = str((jobs_dir / f"{name}.py").resolve())
                assert deleted_path not in result_source_files, (
                    f"Deleted file '{name}' was not removed from cache after sync. "
                    f"source_file={deleted_path} should not be in results."
                )
                assert name not in result_names, (
                    f"Deleted job '{name}' still appears in sync results by name."
                )

    @given(
        disk_names=on_disk_module_names(),
        shared_names=st.lists(_module_names, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_new_files_added_alongside_existing_valid_entries(
        self, disk_names: list[str], shared_names: list[str]
    ) -> None:
        """When some files already have valid cache entries, new files are
        still added without disturbing existing entries.

        # Feature: layered-architecture-lazy-boot, Property 6: Sync reconciliation — new files added, deleted files removed
        **Validates: Requirements 8.2, 8.3**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            # Ensure disk_names don't overlap with shared_names
            new_only_names = [n for n in disk_names if n not in shared_names]

            # Create files for both shared (pre-cached) and new modules
            all_on_disk_names = list(set(shared_names + new_only_names))
            for name in all_on_disk_names:
                _create_simple_job_file(jobs_dir, name)

            # Build cache entries for shared files (valid entries already in cache)
            cache_entries: dict[str, dict] = {}
            for name in shared_names:
                source_file = str((jobs_dir / f"{name}.py").resolve())
                content = Path(source_file).read_bytes()
                content_hash = hashlib.sha256(content).hexdigest()
                mtime = os.path.getmtime(source_file)
                cache_entries[name] = {
                    "name": name,
                    "group": None,
                    "module_path": name,
                    "source_file": source_file,
                    "source_mtime": mtime,
                    "content_hash": content_hash,
                    "docstring": f"{name} job function.",
                    "config_fields": [],
                    "dependencies": {},
                }

            # Write cache with shared entries only
            _write_valid_cache(tmp_path, cache_entries)

            # --- Run reconciliation ---
            provider = _make_provider(tmp_path, [str(jobs_dir)])
            result = provider.list_jobs()

            result_source_files = {d.source_file for d in result}

            # All on-disk files (both shared and new) should appear in results
            for name in all_on_disk_names:
                expected_path = str((jobs_dir / f"{name}.py").resolve())
                assert expected_path in result_source_files, (
                    f"On-disk file '{name}' not in sync results. "
                    f"Expected source_file={expected_path} in results."
                )

            # No extra entries beyond what's on disk
            assert len(result) == len(all_on_disk_names), (
                f"Expected {len(all_on_disk_names)} results, got {len(result)}. "
                f"Sync should only contain descriptors for on-disk files."
            )
