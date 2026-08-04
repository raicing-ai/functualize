"""Unit tests for pre-filter decision caching in CachedDirectoryScanProvider.

Tests cover:
- Negative decision persistence (eligible=False only)
- Positive decisions NOT persisted
- Mtime-based invalidation of cached decisions
- Pre-filter decisions stored inside the single discovery cache file
- Pre-filter cache bypassed during get_job(name) calls
- Silent recovery on corrupted cache
- PreFilterDecision dataclass serialization

**Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

import pytest

from functualize._discovery.cached_provider import (
    CachedDirectoryScanProvider,
    PreFilterDecision,
)
from functualize._primitives.cache_format import (
    CACHE_FILENAME,
    CACHE_VERSION,
    compute_deps_hash,
    get_functualize_version,
)
from functualize._primitives.locator import ResourceLocator

# =============================================================================
# Helpers
# =============================================================================


def _make_locator(tmp_path: Path) -> ResourceLocator:
    """Create a ResourceLocator that reads/writes to tmp_path."""
    return (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )


def _cache_file(tmp_path: Path) -> Path:
    """Path of the single discovery cache file for _make_locator providers."""
    return tmp_path / "cache" / CACHE_FILENAME


def _write_cache_with_decisions(
    tmp_path: Path, decisions: dict, project_root: Path | None = None
) -> None:
    """Pre-seed a valid cache file containing the given pre-filter decisions."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CACHE_VERSION,
        "functualize_version": get_functualize_version(),
        "python_version": platform.python_version(),
        "deps_hash": compute_deps_hash(project_root or tmp_path),
        "generated_at": "2025-01-01T00:00:00+00:00",
        "entries": {},
        "pre_filter_decisions": decisions,
    }
    (cache_dir / CACHE_FILENAME).write_text(json.dumps(data), encoding="utf-8")


def _write_module(directory: Path, name: str, content: str | None = None) -> Path:
    """Write a simple job module file."""
    if content is None:
        content = f'def {name}():\n    """{name} job."""\n    pass\n'
    module_file = directory / f"{name}.py"
    module_file.write_text(content)
    return module_file


class RejectAllFilter:
    """Pre-filter that rejects all files."""

    def should_import(self, source_file: Path) -> bool:
        return False


class AcceptAllFilter:
    """Pre-filter that accepts all files."""

    def should_import(self, source_file: Path) -> bool:
        return True


class SelectiveFilter:
    """Pre-filter that only accepts files not containing 'excluded' in name."""

    def should_import(self, source_file: Path) -> bool:
        return "excluded" not in source_file.name


class CountingFilter:
    """Pre-filter that counts how many times should_import is called."""

    def __init__(self, accept: bool = False) -> None:
        self.call_count = 0
        self._accept = accept

    def should_import(self, source_file: Path) -> bool:
        self.call_count += 1
        return self._accept


# =============================================================================
# PreFilterDecision dataclass tests
# =============================================================================


class TestPreFilterDecision:
    """Tests for PreFilterDecision dataclass serialization."""

    def test_to_dict(self) -> None:
        """to_dict serializes all fields correctly."""
        decision = PreFilterDecision(
            source_file="/path/to/file.py",
            eligible=False,
            source_mtime=1234567890.123,
        )
        result = decision.to_dict()
        assert result == {
            "source_file": "/path/to/file.py",
            "eligible": False,
            "source_mtime": 1234567890.123,
        }

    def test_from_dict(self) -> None:
        """from_dict deserializes correctly."""
        data = {
            "source_file": "/path/to/file.py",
            "eligible": False,
            "source_mtime": 1234567890.123,
        }
        decision = PreFilterDecision.from_dict(data)
        assert decision.source_file == "/path/to/file.py"
        assert decision.eligible is False
        assert decision.source_mtime == 1234567890.123

    def test_from_dict_invalid_structure(self) -> None:
        """from_dict raises ValueError on non-dict input."""
        with pytest.raises(ValueError, match="Expected a dict"):
            PreFilterDecision.from_dict("not a dict")  # type: ignore

    def test_from_dict_missing_keys(self) -> None:
        """from_dict raises ValueError on missing keys."""
        with pytest.raises(ValueError, match="Missing required keys"):
            PreFilterDecision.from_dict({"source_file": "/path"})

    def test_from_dict_wrong_type(self) -> None:
        """from_dict raises ValueError on wrong field types."""
        with pytest.raises(ValueError, match="Expected 'eligible' to be bool"):
            PreFilterDecision.from_dict(
                {
                    "source_file": "/path/to/file.py",
                    "eligible": "no",
                    "source_mtime": 123.0,
                }
            )

    def test_roundtrip(self) -> None:
        """to_dict -> from_dict preserves all fields."""
        original = PreFilterDecision(
            source_file="/some/path.py",
            eligible=False,
            source_mtime=9999.9,
        )
        restored = PreFilterDecision.from_dict(original.to_dict())
        assert restored == original


# =============================================================================
# Negative decision persistence tests
# =============================================================================


class TestNegativeDecisionPersistence:
    """Tests for persisting negative pre-filter decisions.

    **Validates: Requirements 19.1, 19.2**
    """

    def test_negative_decision_persisted_to_disk(self, tmp_path: Path) -> None:
        """When pre-filter returns False, a negative decision is persisted.

        **Validates: Requirement 19.1**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "rejected")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=RejectAllFilter(),
        )

        # Trigger list_jobs which processes new files
        provider.list_jobs()

        # Verify the discovery cache file exists
        cache_file = _cache_file(tmp_path)
        assert cache_file.exists()

        # Verify it contains the negative decision
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "pre_filter_decisions" in data
        assert len(data["pre_filter_decisions"]) == 1

        # Check the stored decision
        decision_data = list(data["pre_filter_decisions"].values())[0]
        assert decision_data["eligible"] is False
        assert "rejected" in decision_data["source_file"]

    def test_positive_decision_not_persisted(self, tmp_path: Path) -> None:
        """When pre-filter returns True, no decision is persisted.

        **Validates: Requirement 19.2**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "accepted")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=AcceptAllFilter(),
        )

        provider.list_jobs()

        # No pre-filter decisions should be stored
        cache_file = _cache_file(tmp_path)
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            assert len(data.get("pre_filter_decisions", {})) == 0

    def test_mixed_decisions_only_negative_persisted(self, tmp_path: Path) -> None:
        """Only negative decisions are persisted; positive ones are not.

        **Validates: Requirements 19.1, 19.2**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "allowed")
        _write_module(jobs_dir, "excluded_module")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=SelectiveFilter(),
        )

        provider.list_jobs()

        # Only the excluded file should have a cached decision
        cache_file = _cache_file(tmp_path)
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(data["pre_filter_decisions"]) == 1
        decision_data = list(data["pre_filter_decisions"].values())[0]
        assert "excluded_module" in decision_data["source_file"]


# =============================================================================
# Mtime-based invalidation tests
# =============================================================================


class TestMtimeInvalidation:
    """Tests for mtime-based invalidation of cached decisions.

    **Validates: Requirements 19.3, 19.4**
    """

    def test_cached_decision_used_when_mtime_matches(self, tmp_path: Path) -> None:
        """Cached negative decision is used without re-running pre-filter.

        **Validates: Requirement 19.3**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "excluded_file")
        locator = _make_locator(tmp_path)

        counting_filter = CountingFilter(accept=False)
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=counting_filter,
        )

        # First call: pre-filter runs
        provider.list_jobs()
        first_count = counting_filter.call_count
        assert first_count >= 1

        # Second call: should use cached decision (no additional pre-filter call)
        provider.list_jobs()
        assert counting_filter.call_count == first_count

    def test_cached_decision_invalidated_on_mtime_change(self, tmp_path: Path) -> None:
        """Cached decision is re-evaluated when file mtime changes.

        **Validates: Requirement 19.4**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        module_file = _write_module(jobs_dir, "changeable")
        locator = _make_locator(tmp_path)

        counting_filter = CountingFilter(accept=False)
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=counting_filter,
        )

        # First call: pre-filter runs and caches negative decision
        provider.list_jobs()
        first_count = counting_filter.call_count

        # Modify the file to change mtime
        time.sleep(0.05)
        module_file.write_text('def changeable():\n    """Updated."""\n    return 1\n')

        # Second call: mtime changed, pre-filter should re-run
        provider.list_jobs()
        assert counting_filter.call_count > first_count

    def test_file_becomes_eligible_after_modification(self, tmp_path: Path) -> None:
        """File that was excluded becomes eligible after modification.

        **Validates: Requirement 19.4**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        # Write a file that the filter will reject
        module_file = _write_module(jobs_dir, "excluded_initially")
        locator = _make_locator(tmp_path)

        # Filter that rejects files with "excluded" in name initially,
        # but changes behavior on second call
        call_count = [0]

        class EvolvingFilter:
            def should_import(self, source_file: Path) -> bool:
                call_count[0] += 1
                # First time: reject, after modification: accept
                return not call_count[0] <= 1

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=EvolvingFilter(),
        )

        # First list_jobs: file rejected
        jobs1 = provider.list_jobs()
        assert len(jobs1) == 0

        # Modify the file (change mtime)
        time.sleep(0.05)
        module_file.write_text(
            'def excluded_initially():\n    """Now eligible."""\n    pass\n'
        )

        # Second list_jobs: mtime changed, re-evaluates, now accepted
        jobs2 = provider.list_jobs()
        assert len(jobs2) == 1
        assert jobs2[0].name == "excluded-initially"


# =============================================================================
# Storage location tests
# =============================================================================


class TestStorageLocation:
    """Tests for pre-filter decision storage location.

    **Validates: Requirement 19.6**
    """

    def test_pre_filter_decisions_stored_in_single_cache_file(
        self, tmp_path: Path
    ) -> None:
        """Pre-filter decisions live inside the single discovery cache file.

        **Validates: Requirement 19.6**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "excluded_job")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=RejectAllFilter(),
        )

        provider.list_jobs()

        # One file holds both the entries and the pre-filter decisions
        cache_file = _cache_file(tmp_path)
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "entries" in data
        assert "pre_filter_decisions" in data
        assert len(data["pre_filter_decisions"]) == 1


# =============================================================================
# get_job bypass tests
# =============================================================================


class TestGetJobBypass:
    """Tests for pre-filter cache bypass during get_job(name) calls.

    **Validates: Requirement 19.7**
    """

    def test_get_job_bypasses_pre_filter_cache(self, tmp_path: Path) -> None:
        """get_job(name) does not use cached pre-filter decisions.

        **Validates: Requirement 19.7**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "target_job")
        locator = _make_locator(tmp_path)

        # Use a filter that rejects initially but then accepts
        call_count = [0]

        class ToggleFilter:
            def should_import(self, source_file: Path) -> bool:
                call_count[0] += 1
                # For list_jobs: reject (creates cached negative decision)
                # For get_job: accept (bypasses cache, runs raw filter)
                return call_count[0] > 1

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=ToggleFilter(),
        )

        # list_jobs caches a negative decision
        jobs = provider.list_jobs()
        assert len(jobs) == 0

        # get_job should bypass the cache and run the raw filter
        # (the filter now returns True on subsequent calls)
        result = provider.get_job("target_job")
        assert result is not None
        assert result.name == "target-job"

    def test_get_job_does_not_consult_cached_negative_decision(
        self, tmp_path: Path
    ) -> None:
        """get_job ignores cached negative decisions completely.

        **Validates: Requirement 19.7**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "my_job")
        locator = _make_locator(tmp_path)

        # Pre-seed a negative decision in the cache file
        source_file = str((jobs_dir / "my_job.py").resolve())
        mtime = os.path.getmtime(source_file)

        _write_cache_with_decisions(
            tmp_path,
            {
                source_file: {
                    "source_file": source_file,
                    "eligible": False,
                    "source_mtime": mtime,
                }
            },
        )

        # Use AcceptAllFilter — the raw filter will accept
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=AcceptAllFilter(),
        )

        # get_job should bypass the cached negative decision
        result = provider.get_job("my_job")
        assert result is not None
        assert result.name == "my-job"


# =============================================================================
# Silent recovery tests
# =============================================================================


class TestSilentRecovery:
    """Tests for silent recovery on pre-filter cache corruption.

    **Validates: Requirement 19.5**
    """

    def test_corrupted_pre_filter_cache_starts_empty(self, tmp_path: Path) -> None:
        """Corrupted pre-filter cache is discarded silently.

        **Validates: Requirement 19.5**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "survivor")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        # Write corrupted cache file
        (cache_dir / CACHE_FILENAME).write_text("not valid json{{{", encoding="utf-8")

        locator = _make_locator(tmp_path)

        # Should not raise
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=RejectAllFilter(),
        )

        # Should work normally (re-evaluates all files)
        jobs = provider.list_jobs()
        assert len(jobs) == 0  # RejectAll means no jobs imported

    def test_invalid_structure_pre_filter_cache(self, tmp_path: Path) -> None:
        """Invalid structure in pre-filter cache is handled gracefully.

        **Validates: Requirement 19.5**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "test_job")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        # Write structurally invalid cache (valid JSON but wrong structure)
        (cache_dir / CACHE_FILENAME).write_text(
            json.dumps({"wrong_key": []}), encoding="utf-8"
        )

        locator = _make_locator(tmp_path)

        # Should not raise
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=AcceptAllFilter(),
        )

        # Should work normally
        result = provider.get_job("test_job")
        assert result is not None

    def test_invalid_decision_entry_skipped(self, tmp_path: Path) -> None:
        """Individual invalid entries are skipped without affecting others.

        **Validates: Requirement 19.5**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "good_excluded")

        source_file = str((jobs_dir / "good_excluded.py").resolve())
        mtime = os.path.getmtime(source_file)

        # Write cache with one valid and one invalid decision entry
        _write_cache_with_decisions(
            tmp_path,
            {
                source_file: {
                    "source_file": source_file,
                    "eligible": False,
                    "source_mtime": mtime,
                },
                "/bad/entry": "not a dict",
            },
        )

        locator = _make_locator(tmp_path)

        # Should not raise — invalid entry is skipped
        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=RejectAllFilter(),
        )

        # The valid cached decision should be loaded
        assert source_file in provider._pre_filter_decisions


# =============================================================================
# Cross-restart persistence tests
# =============================================================================


class TestCrossRestartPersistence:
    """Tests for pre-filter decisions persisting across provider restarts.

    **Validates: Requirements 19.1, 19.3**
    """

    def test_decisions_survive_provider_restart(self, tmp_path: Path) -> None:
        """Pre-filter decisions persist and are loaded by new provider instances.

        **Validates: Requirements 19.1, 19.3**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "no_jobs_here")
        locator = _make_locator(tmp_path)

        counting_filter = CountingFilter(accept=False)

        # First provider: caches negative decision
        provider1 = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=counting_filter,
        )
        provider1.list_jobs()
        first_count = counting_filter.call_count
        assert first_count >= 1

        # Second provider: should load cached decision
        counting_filter2 = CountingFilter(accept=False)
        provider2 = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=counting_filter2,
        )

        # list_jobs should NOT re-run the pre-filter (uses cached decision)
        provider2.list_jobs()
        assert counting_filter2.call_count == 0

    def test_no_pre_filter_decisions_when_no_filter_configured(
        self, tmp_path: Path
    ) -> None:
        """No pre-filter decisions are stored when pre_filter is None."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _write_module(jobs_dir, "job1")
        locator = _make_locator(tmp_path)

        provider = CachedDirectoryScanProvider(
            directories=[str(jobs_dir)],
            locator=locator,
            pre_filter=None,
        )

        provider.list_jobs()

        # The cache file exists (job entries) but holds no decisions
        cache_file = _cache_file(tmp_path)
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data.get("pre_filter_decisions", {}) == {}
