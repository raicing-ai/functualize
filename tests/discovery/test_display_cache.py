"""Display-provider records in the discovery cache (v7 `displays` section).

Tests cover:
- Display detection piggybacking on the job scan (co-located and display-only
  modules)
- Persistence into the cache file's top-level `displays` section
- Warm-boot validation: an unchanged display module is not re-imported
- Invalidation: an edited module is re-imported and its entry refreshed or
  dropped when the display class disappears
- DisplayCacheEntry dataclass serialization
- The public `read_display_modules_from_cache` reader (TUI fast path)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import (
    CACHE_FILENAME,
    DisplayCacheEntry,
)
from functualize._primitives.locator import ResourceLocator
from functualize.app.utils import read_display_modules_from_cache

# =============================================================================
# Helpers
# =============================================================================

_DISPLAY_CLASS = """
class GitStatusDisplay:
    display_id = "git-status"
    display_title = "Git"
    display_priority = 10

    def should_show(self, cwd, app):
        return True

    def compose_display(self):
        return iter(())
"""

_JOB_FUNCTION = '''
def deploy():
    """Deploy job."""
    pass
'''


def _make_provider(tmp_path: Path, jobs_dir: Path) -> CachedDirectoryScanProvider:
    locator = (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs_dir)], locator=locator, project_root=tmp_path
    )


def _cache_file(tmp_path: Path) -> Path:
    return tmp_path / "cache" / CACHE_FILENAME


def _read_displays_section(tmp_path: Path) -> dict:
    data = json.loads(_cache_file(tmp_path).read_text(encoding="utf-8"))
    return data.get("displays", {})


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs"
    d.mkdir()
    return d


# =============================================================================
# Detection + persistence
# =============================================================================


class TestDisplayDetectionInScan:
    def test_colocated_display_is_cached_with_jobs(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """A module with a job AND a display yields both cache records."""
        module = jobs_dir / "deploy.py"
        module.write_text(_JOB_FUNCTION + _DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        jobs = provider.list_jobs()

        assert {j.name for j in jobs} == {"deploy"}
        displays = _read_displays_section(tmp_path)
        assert str(module.resolve()) in displays
        entry = displays[str(module.resolve())]
        assert entry["class_names"] == ["GitStatusDisplay"]
        assert entry["content_hash"]

    def test_display_only_module_is_cached(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """A module with displays but no jobs still leaves a cache trace."""
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        jobs = provider.list_jobs()

        assert jobs == []
        displays = _read_displays_section(tmp_path)
        assert str(module.resolve()) in displays

    def test_module_without_displays_leaves_no_display_entry(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "deploy.py"
        module.write_text(_JOB_FUNCTION)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        assert _read_displays_section(tmp_path) == {}

    def test_display_base_class_import_is_not_a_phantom_display(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """`from functualize.ui import Display` must not register the base."""
        module = jobs_dir / "deploy.py"
        module.write_text("from functualize.ui import Display\n" + _JOB_FUNCTION)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        assert _read_displays_section(tmp_path) == {}


# =============================================================================
# Warm boot + invalidation
# =============================================================================


class TestDisplayEntryValidation:
    def test_unchanged_display_only_module_not_reimported(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        """Second reconciliation over an unchanged display-only module is a
        pure cache hit — no import."""
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        warm = _make_provider(tmp_path, jobs_dir)
        with patch("functualize._discovery.sync.extract_module") as mock_extract:
            warm.list_jobs()
        mock_extract.assert_not_called()

    def test_edited_module_refreshes_display_entry(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()
        first_hash = _read_displays_section(tmp_path)[str(module.resolve())][
            "content_hash"
        ]

        module.write_text(_DISPLAY_CLASS.replace("Git", "Mercurial"))
        warm = _make_provider(tmp_path, jobs_dir)
        warm.list_jobs()

        entry = _read_displays_section(tmp_path)[str(module.resolve())]
        assert entry["content_hash"] != first_hash

    def test_removing_display_class_drops_entry(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "deploy.py"
        module.write_text(_JOB_FUNCTION + _DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()
        assert _read_displays_section(tmp_path) != {}

        module.write_text(_JOB_FUNCTION)
        warm = _make_provider(tmp_path, jobs_dir)
        warm.list_jobs()

        assert _read_displays_section(tmp_path) == {}

    def test_deleted_module_drops_display_entry(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()
        assert _read_displays_section(tmp_path) != {}

        module.unlink()
        warm = _make_provider(tmp_path, jobs_dir)
        warm.list_jobs()

        assert _read_displays_section(tmp_path) == {}

    def test_malformed_displays_section_recovers_silently(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        cache_path = _cache_file(tmp_path)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["displays"] = {"bogus": {"not": "an entry"}, 1: []}
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        warm = _make_provider(tmp_path, jobs_dir)
        warm.list_jobs()
        # Rebuilt from the re-import triggered by the discarded entry
        assert str(module.resolve()) in _read_displays_section(tmp_path)


# =============================================================================
# DisplayCacheEntry serialization
# =============================================================================


class TestDisplayCacheEntrySerialization:
    def test_round_trip(self) -> None:
        entry = DisplayCacheEntry(
            source_file="/x/displays.py",
            class_names=("A", "B"),
            source_mtime=123.5,
            content_hash="abc",
        )
        assert DisplayCacheEntry.from_dict(entry.to_dict()) == entry

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {
                "source_file": 1,
                "class_names": [],
                "source_mtime": 0,
                "content_hash": "",
            },
            {
                "source_file": "x",
                "class_names": "A",
                "source_mtime": 0,
                "content_hash": "",
            },
            {
                "source_file": "x",
                "class_names": [1],
                "source_mtime": 0,
                "content_hash": "",
            },
            {
                "source_file": "x",
                "class_names": [],
                "source_mtime": "0",
                "content_hash": "",
            },
            {
                "source_file": "x",
                "class_names": [],
                "source_mtime": 0,
                "content_hash": 3,
            },
        ],
    )
    def test_from_dict_rejects_malformed(self, data: dict) -> None:
        with pytest.raises(ValueError):
            DisplayCacheEntry.from_dict(data)


# =============================================================================
# Public reader (TUI fast path)
# =============================================================================


class TestReadDisplayModulesFromCache:
    def test_reads_flagged_modules(self, tmp_path: Path, jobs_dir: Path) -> None:
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)

        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        result = read_display_modules_from_cache(_cache_file(tmp_path))
        assert result == [(str(module.resolve()), ["GitStatusDisplay"])]

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_display_modules_from_cache(tmp_path / "nope.json") is None

    def test_version_mismatch_returns_none(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)
        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        cache_path = _cache_file(tmp_path)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["version"] = -1
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        assert read_display_modules_from_cache(cache_path) is None

    def test_malformed_entries_are_skipped(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "my_displays.py"
        module.write_text(_DISPLAY_CLASS)
        provider = _make_provider(tmp_path, jobs_dir)
        provider.list_jobs()

        cache_path = _cache_file(tmp_path)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["displays"]["junk"] = {"source_file": "", "class_names": []}
        data["displays"]["junk2"] = "not-a-dict"
        cache_path.write_text(json.dumps(data), encoding="utf-8")

        result = read_display_modules_from_cache(cache_path)
        assert result == [(str(module.resolve()), ["GitStatusDisplay"])]


# =============================================================================
# surface_hint (v7 descriptor field, same bump)
# =============================================================================


class TestSurfaceHintRoundTrip:
    def test_surface_hint_survives_cache_round_trip(
        self, tmp_path: Path, jobs_dir: Path
    ) -> None:
        module = jobs_dir / "report.py"
        module.write_text(
            "from functualize.job import surface_hint\n"
            "\n"
            '@surface_hint("stdout")\n'
            "def report():\n"
            '    """Report job."""\n'
            "    pass\n"
        )

        provider = _make_provider(tmp_path, jobs_dir)
        jobs = provider.list_jobs()
        assert [j.surface_hint for j in jobs] == ["stdout"]

        # Warm reconstruction from the persisted JSON alone
        warm = _make_provider(tmp_path, jobs_dir)
        with patch("functualize._discovery.sync.extract_module") as mock_extract:
            warm_jobs = warm.list_jobs()
        mock_extract.assert_not_called()
        assert [j.surface_hint for j in warm_jobs] == ["stdout"]
