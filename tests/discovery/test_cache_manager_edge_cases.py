"""Unit tests for cached provider store edge cases.

Validates Requirements 5.1–5.6, 6.1–6.6:
- Missing cache file → cold boot (empty state, no error)
- Invalid JSON content → empty cache + warning logged
- Unrecognized version number → cache discarded + file deleted
- functualize version mismatch → entries discarded, file deleted
- Python version mismatch → entries discarded, file deleted
- deps_hash mismatch → entries discarded, file deleted
- persist with permission error → warning logged, no exception raised
- Non-existent cache directory → empty cache, no error
"""

from __future__ import annotations

import json
import logging
import platform
from pathlib import Path
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    import pytest


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


def _cache_path(project_root: Path) -> Path:
    cache_dir = project_root / ".functualize"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / CACHE_FILENAME


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


def _write_cache(cache_path: Path, data: dict) -> None:
    """Write arbitrary JSON data to cache file."""
    cache_path.write_text(json.dumps(data), encoding="utf-8")


def _make_valid_cache_data(
    project_root: Path,
    entries: dict | None = None,
    functualize_version: str | None = None,
    python_version: str | None = None,
    deps_hash: str | None = None,
) -> dict:
    """Build valid cache data dict with optional overrides."""
    return {
        "version": CACHE_VERSION,
        "functualize_version": functualize_version or get_functualize_version(),
        "python_version": python_version or platform.python_version(),
        "deps_hash": deps_hash or compute_deps_hash(project_root),
        "generated_at": "2025-01-01T00:00:00+00:00",
        "entries": entries or {},
        "pre_filter_decisions": {},
    }


class TestMissingCacheFile:
    """Test: Missing cache file → cold boot (Requirement 5.4)."""

    def test_missing_cache_starts_empty(self, tmp_path: Path) -> None:
        """When cache file doesn't exist, the provider starts empty."""
        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []

    def test_missing_cache_no_error_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When cache file doesn't exist, no error or warning is logged."""
        with caplog.at_level(logging.DEBUG):
            _make_provider(tmp_path)

        # No warnings about missing cache file (cold boot is normal)
        warning_messages = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any(
            "cache" in r.message.lower() and "missing" in r.message.lower()
            for r in warning_messages
        ), f"Unexpected warning logged: {[r.message for r in warning_messages]}"


class TestInvalidJSON:
    """Test: Invalid JSON content → empty cache + warning (Requirement 5.5)."""

    def test_invalid_json_starts_empty(self, tmp_path: Path) -> None:
        """When cache file contains invalid JSON, the provider starts empty."""
        _cache_path(tmp_path).write_text(
            "this is { not valid json !!!}", encoding="utf-8"
        )

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []

    def test_invalid_json_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When cache file has invalid JSON, a warning is logged."""
        _cache_path(tmp_path).write_text("{broken json content", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            _make_provider(tmp_path)

        assert any(
            "failed to load discovery cache" in r.message.lower()
            for r in caplog.records
        ), (
            f"Expected warning about unreadable cache, got: {[r.message for r in caplog.records]}"
        )

    def test_empty_file_starts_empty(self, tmp_path: Path) -> None:
        """Empty cache file treated as invalid JSON → empty cache."""
        _cache_path(tmp_path).write_text("", encoding="utf-8")

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []


class TestUnrecognizedVersion:
    """Test: Unrecognized version number → cache discarded (Requirement 5.5)."""

    def test_wrong_version_starts_empty(self, tmp_path: Path) -> None:
        """Cache with wrong version number yields an empty provider."""
        data = _make_valid_cache_data(tmp_path)
        data["version"] = 999  # Unrecognized version
        _write_cache(_cache_path(tmp_path), data)

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []

    def test_wrong_version_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cache with wrong version logs a warning about the version mismatch."""
        data = _make_valid_cache_data(tmp_path)
        data["version"] = 1  # Old/unrecognized version
        _write_cache(_cache_path(tmp_path), data)

        with caplog.at_level(logging.WARNING):
            _make_provider(tmp_path)

        assert any("version mismatch" in r.message.lower() for r in caplog.records), (
            f"Expected version warning, got: {[r.message for r in caplog.records]}"
        )

    def test_wrong_version_deletes_cache_file(self, tmp_path: Path) -> None:
        """Cache with wrong version is deleted from disk."""
        cache_path = _cache_path(tmp_path)
        data = _make_valid_cache_data(tmp_path)
        data["version"] = 999
        _write_cache(cache_path, data)

        _make_provider(tmp_path)
        assert not cache_path.exists()

    def test_missing_version_field_starts_empty(self, tmp_path: Path) -> None:
        """Cache without version field yields an empty provider."""
        data = _make_valid_cache_data(tmp_path)
        del data["version"]
        _write_cache(_cache_path(tmp_path), data)

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []


class TestGlobalInvalidationFunctualizeVersion:
    """Test: functualize version mismatch → entries discarded, file deleted (Req 6.1)."""

    def test_version_mismatch_discards_entries(self, tmp_path: Path) -> None:
        """When functualize version differs, all entries are discarded."""
        descriptor = _make_descriptor(source_file=str(tmp_path / "deploy.py"))
        data = _make_valid_cache_data(
            tmp_path,
            entries={
                f"{descriptor.source_file}::{descriptor.name}": descriptor.to_dict()
            },
            functualize_version="0.0.0-old",
        )
        _write_cache(_cache_path(tmp_path), data)

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []

    def test_version_mismatch_deletes_cache_file(self, tmp_path: Path) -> None:
        """When functualize version differs, cache file is deleted from disk."""
        cache_path = _cache_path(tmp_path)
        data = _make_valid_cache_data(tmp_path, functualize_version="0.0.0-old")
        _write_cache(cache_path, data)

        _make_provider(tmp_path)
        assert not cache_path.exists()

    def test_version_mismatch_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When functualize version differs, a warning is logged."""
        data = _make_valid_cache_data(tmp_path, functualize_version="99.99.99")
        _write_cache(_cache_path(tmp_path), data)

        with caplog.at_level(logging.WARNING):
            _make_provider(tmp_path)

        assert any(
            "functualize version" in r.message.lower() for r in caplog.records
        ), (
            f"Expected version mismatch warning, got: {[r.message for r in caplog.records]}"
        )


class TestGlobalInvalidationPythonVersion:
    """Test: Python version mismatch → entries discarded, file deleted (Req 6.2)."""

    def test_python_version_mismatch_discards_entries(self, tmp_path: Path) -> None:
        """When Python version differs, all entries are discarded."""
        descriptor = _make_descriptor(source_file=str(tmp_path / "deploy.py"))
        data = _make_valid_cache_data(
            tmp_path,
            entries={
                f"{descriptor.source_file}::{descriptor.name}": descriptor.to_dict()
            },
            python_version="2.7.0",
        )
        _write_cache(_cache_path(tmp_path), data)

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []

    def test_python_version_mismatch_deletes_cache_file(self, tmp_path: Path) -> None:
        """When Python version differs, cache file is deleted from disk."""
        cache_path = _cache_path(tmp_path)
        data = _make_valid_cache_data(tmp_path, python_version="2.7.0")
        _write_cache(cache_path, data)

        _make_provider(tmp_path)
        assert not cache_path.exists()

    def test_python_version_mismatch_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When Python version differs, a warning is logged."""
        data = _make_valid_cache_data(tmp_path, python_version="2.7.0")
        _write_cache(_cache_path(tmp_path), data)

        with caplog.at_level(logging.WARNING):
            _make_provider(tmp_path)

        assert any("python version" in r.message.lower() for r in caplog.records), (
            f"Expected Python version warning, got: {[r.message for r in caplog.records]}"
        )


class TestGlobalInvalidationDepsHash:
    """Test: deps_hash mismatch → entries discarded, file deleted (Req 6.3)."""

    def test_deps_hash_mismatch_discards_entries(self, tmp_path: Path) -> None:
        """When deps_hash differs, all entries are discarded."""
        descriptor = _make_descriptor(source_file=str(tmp_path / "deploy.py"))
        data = _make_valid_cache_data(
            tmp_path,
            entries={
                f"{descriptor.source_file}::{descriptor.name}": descriptor.to_dict()
            },
            deps_hash="sha256:totally_different_hash",
        )
        _write_cache(_cache_path(tmp_path), data)

        provider = _make_provider(tmp_path)
        assert list(provider._by_name.values()) == []

    def test_deps_hash_mismatch_deletes_cache_file(self, tmp_path: Path) -> None:
        """When deps_hash differs, cache file is deleted from disk."""
        cache_path = _cache_path(tmp_path)
        data = _make_valid_cache_data(tmp_path, deps_hash="sha256:old_hash_value")
        _write_cache(cache_path, data)

        _make_provider(tmp_path)
        assert not cache_path.exists()

    def test_deps_hash_mismatch_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When deps_hash differs, a warning is logged."""
        data = _make_valid_cache_data(tmp_path, deps_hash="sha256:mismatched")
        _write_cache(_cache_path(tmp_path), data)

        with caplog.at_level(logging.WARNING):
            _make_provider(tmp_path)

        assert any("dependencies hash" in r.message.lower() for r in caplog.records), (
            f"Expected deps hash warning, got: {[r.message for r in caplog.records]}"
        )


class TestPersistFailure:
    """Test: persist with permission error → warning logged, no exception (Req 5.6)."""

    def test_persist_permission_error_no_exception(self, tmp_path: Path) -> None:
        """_persist_cache() with permission error does not raise an exception."""
        provider = _make_provider(tmp_path)
        provider._add_entry(_make_descriptor(source_file=str(tmp_path / "job.py")))

        with patch.object(
            Path, "write_text", side_effect=PermissionError("Permission denied")
        ):
            # Should not raise
            provider._persist_cache()

    def test_persist_permission_error_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_persist_cache() with permission error logs a warning."""
        provider = _make_provider(tmp_path)
        provider._add_entry(_make_descriptor(source_file=str(tmp_path / "job.py")))

        with (
            patch.object(
                Path, "write_text", side_effect=PermissionError("Permission denied")
            ),
            caplog.at_level(logging.WARNING),
        ):
            provider._persist_cache()

        assert any("failed to persist" in r.message.lower() for r in caplog.records), (
            f"Expected persist failure warning, got: {[r.message for r in caplog.records]}"
        )

    def test_persist_oserror_no_exception(self, tmp_path: Path) -> None:
        """_persist_cache() with OSError (disk full) does not raise."""
        provider = _make_provider(tmp_path)
        provider._add_entry(_make_descriptor(source_file=str(tmp_path / "job.py")))

        with patch.object(
            Path, "write_text", side_effect=OSError("No space left on device")
        ):
            # Should not raise
            provider._persist_cache()


class TestNonExistentCacheDirectory:
    """Test: Non-existent cache directory → empty cache, no error (Req 5.1)."""

    def test_nonexistent_cache_dir_starts_empty(self, tmp_path: Path) -> None:
        """When the cache directory doesn't exist, the provider starts empty."""
        nonexistent = tmp_path / "does_not_exist"
        locator = (
            ResourceLocator()
            .search_explicit(str(nonexistent / ".functualize"))
            .write_to_explicit(str(nonexistent / ".functualize"))
        )
        provider = CachedDirectoryScanProvider(
            directories=[], locator=locator, project_root=nonexistent
        )
        assert list(provider._by_name.values()) == []
