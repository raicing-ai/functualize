"""Property-based test for warm boot zero imports guarantee.

Tests Property 14 from the design document for the layered-architecture-lazy-boot spec.

Property 14: "For any project state where all cached entries pass Tier 1 mtime
validation and no files have been added or removed from disk, the boot-time sync
algorithm SHALL complete without calling importlib.import_module() on any job module."

**Validates: Requirements 15.1**

# Feature: layered-architecture-lazy-boot, Property 14: Warm boot with fully valid cache performs zero module imports
"""

from __future__ import annotations

import hashlib
import json
import keyword
import os
import platform
import tempfile
from pathlib import Path
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import (
    CACHE_FILENAME,
    CACHE_VERSION,
    get_functualize_version,
)
from functualize._primitives.locator import ResourceLocator

# --- Strategies ---

_PYTHON_KEYWORDS = set(keyword.kwlist) | {"True", "False", "None"}

_module_names = st.from_regex(r"[a-z][a-z0-9_]{2,12}", fullmatch=True).filter(
    lambda n: n.isidentifier() and not n.startswith("__") and n not in _PYTHON_KEYWORDS
)


@st.composite
def module_name_lists(draw: st.DrawFn) -> list[str]:
    """Generate a unique list of valid module names (1 to 10 modules)."""
    return draw(st.lists(_module_names, min_size=1, max_size=10, unique=True))


def _create_job_file(jobs_dir: Path, name: str) -> Path:
    """Create a minimal valid Python job module file."""
    content = f'''"""Job module: {name}."""

def {name}():
    """{name} job function."""
    pass
'''
    module_path = jobs_dir / f"{name}.py"
    module_path.write_text(content, encoding="utf-8")
    return module_path


def _build_valid_cache_entry(name: str, source_file: str) -> dict:
    """Build a cache entry dict that exactly matches the on-disk file.

    Reads the actual file to compute correct mtime and content hash,
    ensuring the entry passes Tier 1 mtime validation.
    """
    content = Path(source_file).read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    mtime = os.path.getmtime(source_file)

    return {
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
        "displays": {},
    }
    (cache_dir / CACHE_FILENAME).write_text(json.dumps(data), encoding="utf-8")


# Feature: layered-architecture-lazy-boot, Property 14: Warm boot with fully valid cache performs zero module imports
class TestWarmBootZeroImports:
    """Property 14: Warm boot with fully valid cache performs zero module imports.

    For any project state where all cached entries pass Tier 1 mtime validation
    and no files have been added or removed from disk, the boot-time sync
    algorithm SHALL complete without calling importlib.import_module() on any
    job module.
    """

    @given(names=module_name_lists())
    def test_warm_boot_performs_zero_imports_when_cache_fully_valid(
        self, names: list[str]
    ) -> None:
        """When all cached entries pass Tier 1 mtime validation and no files
        have been added or removed, list_jobs() completes without any module imports.

        # Feature: layered-architecture-lazy-boot, Property 14: Warm boot with fully valid cache performs zero module imports
        **Validates: Requirements 15.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            # Step 1: Create N job module files on disk
            for name in names:
                _create_job_file(jobs_dir, name)

            # Step 2: Build cache entries that exactly match the on-disk files
            # (correct mtime and content hash → passes Tier 1 validation)
            cache_entries: dict[str, dict] = {}
            for name in names:
                source_file = str((jobs_dir / f"{name}.py").resolve())
                cache_entries[name] = _build_valid_cache_entry(name, source_file)

            # Step 3: Write the cache file
            _write_valid_cache(tmp_path, cache_entries)

            # Step 4: Run reconciliation while tracking import calls
            provider = _make_provider(tmp_path, [str(jobs_dir)])

            with (
                patch("functualize._discovery.sync.extract_module") as mock_extract,
                patch(
                    "functualize._discovery.sync.importlib.import_module"
                ) as mock_import,
            ):
                result = provider.list_jobs()

                # Step 5: Assert zero module imports occurred
                (
                    mock_import.assert_not_called(),
                    (
                        f"importlib.import_module was called during warm boot "
                        f"with {len(names)} fully valid cached entries. "
                        f"Calls: {mock_import.call_args_list}"
                    ),
                )

                (
                    mock_extract.assert_not_called(),
                    (
                        f"extract_module was called during warm boot "
                        f"with {len(names)} fully valid cached entries. "
                        f"Calls: {mock_extract.call_args_list}"
                    ),
                )

            # Also verify that all descriptors are returned from cache
            assert len(result) == len(names), (
                f"Expected {len(names)} descriptors from warm boot, got {len(result)}"
            )

    @given(names=module_name_lists())
    def test_warm_boot_returns_all_cached_descriptors_without_imports(
        self, names: list[str]
    ) -> None:
        """Warm boot with valid cache returns all descriptors and each
        descriptor matches the cached data without performing any imports.

        # Feature: layered-architecture-lazy-boot, Property 14: Warm boot with fully valid cache performs zero module imports
        **Validates: Requirements 15.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            jobs_dir = tmp_path / "jobs"
            jobs_dir.mkdir()

            # Create files and build matching cache entries
            for name in names:
                _create_job_file(jobs_dir, name)

            cache_entries: dict[str, dict] = {}
            for name in names:
                source_file = str((jobs_dir / f"{name}.py").resolve())
                cache_entries[name] = _build_valid_cache_entry(name, source_file)

            _write_valid_cache(tmp_path, cache_entries)

            # Run reconciliation with extract_module patched to track calls
            with patch(
                "functualize._discovery.sync.extract_module",
                side_effect=AssertionError(
                    "extract_module should never be called during warm boot"
                ),
            ):
                provider = _make_provider(tmp_path, [str(jobs_dir)])
                result = provider.list_jobs()

            # All cached entries should be present in results
            result_names = {d.name for d in result}
            for name in names:
                assert name in result_names, (
                    f"Cached job '{name}' not returned from warm boot sync. "
                    f"Got names: {result_names}"
                )

            # No extra entries beyond what was cached
            assert len(result) == len(names), (
                f"Expected exactly {len(names)} descriptors, got {len(result)}. "
                f"Extra entries may indicate unexpected imports."
            )
