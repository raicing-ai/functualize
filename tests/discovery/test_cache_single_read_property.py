"""Property-based test for cache single-read guarantee.

Tests Property 15 from the design document for the layered-architecture-lazy-boot spec.

Property 15: "For any number of in-memory lookups on the cached provider within
the same process lifetime, the cache file on disk SHALL be read and parsed at
most once. Subsequent lookups SHALL return the in-memory cached result."

**Validates: Requirements 15.4**

# Feature: layered-architecture-lazy-boot, Property 15: Cache file read only once per process
"""

from __future__ import annotations

import json
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


@st.composite
def num_calls(draw: st.DrawFn) -> int:
    """Generate a random number of lookups (2 to 50)."""
    return draw(st.integers(min_value=2, max_value=50))


@st.composite
def cache_entries(draw: st.DrawFn) -> list[dict]:
    """Generate a random list of serialized cache entries.

    Each entry is a valid serialized JobDescriptor dict.
    """
    count = draw(st.integers(min_value=0, max_value=10))
    entries = []
    for i in range(count):
        name = f"job_{i}"
        module_path = f"project.jobs.job_{i}"
        entry = {
            "name": name,
            "group": None,
            "module_path": module_path,
            "source_file": f"/tmp/project/jobs/job_{i}.py",
            "source_mtime": 1000.0 + i,
            "content_hash": f"hash_{i:040d}",
            "docstring": f"Job {i} description",
            "config_fields": [],
            "dependencies": {},
        }
        entries.append(entry)
    return entries


def _make_provider(project_root: Path) -> CachedDirectoryScanProvider:
    """Create a cache provider whose store lives in <root>/.functualize/."""
    cache_dir = project_root / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[], locator=locator, project_root=project_root
    )


def _write_valid_cache(project_root: Path, entries: list[dict]) -> Path:
    """Write a valid cache file with the given entries. Returns its path."""
    cache_dir = project_root / ".functualize"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / CACHE_FILENAME
    entries_dict = {f"{e['source_file']}::{e['name']}": e for e in entries}
    data = {
        "version": CACHE_VERSION,
        "functualize_version": get_functualize_version(),
        "python_version": platform.python_version(),
        "deps_hash": "sha256:__UNREADABLE__",
        "generated_at": "2025-01-01T00:00:00+00:00",
        "entries": entries_dict,
        "pre_filter_decisions": {},
    }
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return cache_path


# Feature: layered-architecture-lazy-boot, Property 15: Cache file read only once per process
class TestCacheSingleReadGuarantee:
    """Property 15: Cache file read only once per process.

    For any number of in-memory lookups on the cached provider within the same
    process lifetime, the cache file on disk SHALL be read and parsed at most
    once. Subsequent lookups SHALL return the in-memory cached result.
    """

    @given(call_count=num_calls(), entries=cache_entries())
    def test_cache_file_read_at_most_once_regardless_of_call_count(
        self, call_count: int, entries: list[dict]
    ) -> None:
        """Multiple in-memory lookups never re-read the cache file.

        # Feature: layered-architecture-lazy-boot, Property 15: Cache file read only once per process
        **Validates: Requirements 15.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cache_path = _write_valid_cache(tmp_path, entries)

            # Track how many times the cache file is read from disk
            read_count = 0
            original_read_text = Path.read_text

            def counting_read_text(self_path: Path, *args, **kwargs):
                nonlocal read_count
                if self_path == cache_path:
                    read_count += 1
                return original_read_text(self_path, *args, **kwargs)

            with patch.object(Path, "read_text", counting_read_text):
                provider = _make_provider(tmp_path)

            # The cache file should have been read exactly once during __init__
            assert read_count == 1, (
                f"Expected exactly 1 read during init, got {read_count}"
            )

            # Look up entries `call_count` times — no additional file reads
            results = []
            for _ in range(call_count):
                results.append(sorted(provider._by_name.keys()))

            # read_count should still be 1 (no re-reads from lookups)
            assert read_count == 1, (
                f"Cache file was re-read after init. "
                f"Expected 1 total read, got {read_count} after {call_count} calls"
            )

            # All results should be equal (same in-memory data returned each time)
            for i, result in enumerate(results):
                assert result == results[0], (
                    f"Call {i + 1} returned different result than call 1"
                )

    @given(call_count=num_calls(), entries=cache_entries())
    def test_lookups_return_consistent_results(
        self, call_count: int, entries: list[dict]
    ) -> None:
        """In-memory lookups return the same data on every call within a process.

        # Feature: layered-architecture-lazy-boot, Property 15: Cache file read only once per process
        **Validates: Requirements 15.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            _write_valid_cache(tmp_path, entries)

            provider = _make_provider(tmp_path)

            # Get the first result as baseline
            baseline = list(provider._by_name.values())

            # Modify the cache file on disk to prove subsequent calls don't re-read
            new_entries = entries + [
                {
                    "name": "injected_job",
                    "group": None,
                    "module_path": "project.jobs.injected",
                    "source_file": "/tmp/project/jobs/injected.py",
                    "source_mtime": 9999.0,
                    "content_hash": "injected_hash_0000000000000000000000000000",
                    "docstring": "This should never appear",
                    "config_fields": [],
                    "dependencies": {},
                }
            ]
            _write_valid_cache(tmp_path, new_entries)

            # All subsequent lookups should still return the original in-memory result
            for i in range(call_count):
                result = list(provider._by_name.values())
                assert result == baseline, (
                    f"Call {i + 2} returned different data after disk modification. "
                    f"The cache file must not be re-read."
                )
                # Specifically check the injected entry is NOT present
                names = [d.name for d in result]
                assert "injected_job" not in names, (
                    "Injected entry appeared — cache file was re-read from disk"
                )
