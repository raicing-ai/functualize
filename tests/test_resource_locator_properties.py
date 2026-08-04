"""Property-based tests for ResourceLocator (Properties 3–4).

Tests the ResourceLocator from functualize.primitives.locator:
- Property 3: ResourceLocator resolve semantics (union, dedup, first-wins)
- Property 4: ResourceLocator read/write asymmetry

# Feature: unified-architecture-redesign, Properties 3–4
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._primitives.locator import ResourceLocator, compute_project_id

# =============================================================================
# Strategies
# =============================================================================

# Strategy for generating valid relative filenames (safe for filesystem)
_safe_filenames = st.from_regex(r"[a-z][a-z0-9_]{0,8}\.[a-z]{1,4}", fullmatch=True)

# Strategy for number of read sources (at least 1, reasonably bounded)
_num_sources = st.integers(min_value=1, max_value=5)


# Strategy for generating file content per source directory
# Returns: list of (source_index, list_of_filenames_in_that_source)
@st.composite
def _sources_with_overlapping_files(
    draw: st.DrawFn,
) -> tuple[int, list[list[str]]]:
    """Generate N source directories, each with a set of filenames.

    Some filenames may overlap across sources to test dedup behavior.
    Returns (num_sources, list_of_filename_lists_per_source).
    """
    n_sources = draw(st.integers(min_value=2, max_value=5))

    # Generate a shared pool of filenames that sources can pick from
    pool = draw(
        st.lists(
            _safe_filenames,
            min_size=1,
            max_size=10,
            unique=True,
        )
    )

    sources: list[list[str]] = []
    for _ in range(n_sources):
        # Each source picks a subset of the pool
        source_files = draw(
            st.lists(
                st.sampled_from(pool),
                min_size=0,
                max_size=len(pool),
                unique=True,
            )
        )
        sources.append(source_files)

    return n_sources, sources


@st.composite
def _sources_with_shared_relative_path(
    draw: st.DrawFn,
) -> tuple[str, int, list[bool]]:
    """Generate a relative path and N sources where some contain it.

    Returns (relative_path, num_sources, presence_per_source).
    """
    relative_path = draw(_safe_filenames)
    n_sources = draw(st.integers(min_value=2, max_value=5))
    # At least one source should have it for an interesting test
    presence = draw(
        st.lists(
            st.booleans(),
            min_size=n_sources,
            max_size=n_sources,
        ).filter(lambda ps: any(ps))
    )
    return relative_path, n_sources, presence


# =============================================================================
# Property 3: ResourceLocator resolve semantics (union, dedup, first-wins)
# =============================================================================


class TestResourceLocatorResolveSemantics:
    """Property 3: ResourceLocator resolve semantics (union, dedup, first-wins).

    For any ResourceLocator configured with N read sources containing overlapping
    files, resolve(pattern) SHALL return the union of all matches deduplicated by
    absolute path and ordered by source priority, and resolve_one(relative_path)
    SHALL return the match from the highest-priority source only.

    **Validates: Requirements 1.4, 2.4, 2.5, 2.6**
    """

    @given(data=_sources_with_overlapping_files())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_returns_union_of_all_matches(
        self,
        data: tuple[int, list[list[str]]],
        tmp_path: Path,
    ):
        """resolve(pattern) returns the union of all matching files across sources.

        **Validates: Requirements 1.4, 2.4**
        """
        n_sources, source_files = data
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create source directories and populate them
        source_dirs: list[Path] = []
        for i in range(n_sources):
            d = test_dir / f"source_{i}"
            d.mkdir()
            source_dirs.append(d)
            for filename in source_files[i]:
                (d / filename).write_text(f"from_source_{i}")

        # Build locator with sources in order
        locator = ResourceLocator()
        for d in source_dirs:
            locator.search_explicit(d)

        # resolve("*") should match all files
        results = locator.resolve("*")
        result_paths = set(results)

        # Compute expected union: all unique absolute paths across all sources
        expected_abs_paths: set[str] = set()
        for i, d in enumerate(source_dirs):
            for filename in source_files[i]:
                abs_path = str((d / filename).resolve())
                expected_abs_paths.add(abs_path)

        assert result_paths == expected_abs_paths

    @given(data=_sources_with_overlapping_files())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_deduplicates_by_absolute_path(
        self,
        data: tuple[int, list[list[str]]],
        tmp_path: Path,
    ):
        """resolve(pattern) deduplicates results by absolute path.

        When the same directory is added multiple times, files appear only once.

        **Validates: Requirements 2.4**
        """
        _, source_files = data
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create a single source directory
        single_dir = test_dir / "shared"
        single_dir.mkdir()
        all_files_in_source = set()
        for file_list in source_files:
            for filename in file_list:
                (single_dir / filename).write_text("content")
                all_files_in_source.add(filename)

        # Add the same directory multiple times
        locator = ResourceLocator()
        for _ in range(3):
            locator.search_explicit(single_dir)

        results = locator.resolve("*")

        # Each file should appear exactly once despite duplicate sources
        assert len(results) == len(all_files_in_source)
        # All results should have unique absolute paths
        assert len(set(results)) == len(results)

    @given(data=_sources_with_overlapping_files())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_ordered_by_source_priority(
        self,
        data: tuple[int, list[list[str]]],
        tmp_path: Path,
    ):
        """resolve(pattern) orders results by source priority (first configured first).

        When multiple sources have unique files, files from the higher-priority
        source appear before files from lower-priority sources.

        **Validates: Requirements 2.4**
        """
        n_sources, source_files = data
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create source directories with unique files per source
        source_dirs: list[Path] = []
        for i in range(n_sources):
            d = test_dir / f"source_{i}"
            d.mkdir()
            source_dirs.append(d)
            for filename in source_files[i]:
                (d / filename).write_text(f"from_source_{i}")

        # Build locator with sources in order
        locator = ResourceLocator()
        for d in source_dirs:
            locator.search_explicit(d)

        results = locator.resolve("*")

        # For any two results, if they come from different sources,
        # the one from the higher-priority source should appear first
        result_to_source_priority: dict[str, int] = {}
        for i, d in enumerate(source_dirs):
            for filename in source_files[i]:
                abs_path = str((d / filename).resolve())
                # Only record if not already seen (first-wins for dedup)
                if abs_path not in result_to_source_priority:
                    result_to_source_priority[abs_path] = i

        # Verify ordering: results are ordered by source priority
        priorities_in_order = [
            result_to_source_priority[r]
            for r in results
            if r in result_to_source_priority
        ]
        assert priorities_in_order == sorted(priorities_in_order)

    @given(data=_sources_with_shared_relative_path())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_one_returns_highest_priority_match(
        self,
        data: tuple[str, int, list[bool]],
        tmp_path: Path,
    ):
        """resolve_one(relative_path) returns match from highest-priority source.

        **Validates: Requirements 2.5**
        """
        relative_path, n_sources, presence = data
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create source directories
        source_dirs: list[Path] = []
        for i in range(n_sources):
            d = test_dir / f"source_{i}"
            d.mkdir()
            source_dirs.append(d)
            if presence[i]:
                (d / relative_path).write_text(f"from_source_{i}")

        # Build locator
        locator = ResourceLocator()
        for d in source_dirs:
            locator.search_explicit(d)

        result = locator.resolve_one(relative_path)

        # Find expected: first source (by priority) that has the file
        expected_source_idx = next(i for i, p in enumerate(presence) if p)
        expected = str((source_dirs[expected_source_idx] / relative_path).resolve())

        assert result == expected

    @given(
        relative_path=_safe_filenames,
        n_sources=st.integers(min_value=1, max_value=5),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_one_returns_none_when_not_found(
        self,
        relative_path: str,
        n_sources: int,
        tmp_path: Path,
    ):
        """resolve_one returns None when no source contains the file.

        **Validates: Requirements 2.6**
        """
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create empty source directories
        locator = ResourceLocator()
        for i in range(n_sources):
            d = test_dir / f"source_{i}"
            d.mkdir()
            locator.search_explicit(d)

        result = locator.resolve_one(relative_path)
        assert result is None

    @given(data=_sources_with_shared_relative_path())
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_resolve_one_stops_at_first_match(
        self,
        data: tuple[str, int, list[bool]],
        tmp_path: Path,
    ):
        """resolve_one stops searching after the first match (first source wins).

        The returned path corresponds to the highest-priority source that
        contains the file, regardless of what lower-priority sources contain.

        **Validates: Requirements 2.5**
        """
        relative_path, n_sources, presence = data
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))

        # Create source directories with different content at same relative path
        source_dirs: list[Path] = []
        for i in range(n_sources):
            d = test_dir / f"source_{i}"
            d.mkdir()
            source_dirs.append(d)
            if presence[i]:
                (d / relative_path).write_text(f"unique_content_source_{i}")

        locator = ResourceLocator()
        for d in source_dirs:
            locator.search_explicit(d)

        result = locator.resolve_one(relative_path)
        assert result is not None

        # Verify it's from the first source that has the file
        first_present_idx = next(i for i, p in enumerate(presence) if p)
        expected_dir = source_dirs[first_present_idx]
        assert result == str((expected_dir / relative_path).resolve())


# =============================================================================
# Property 4: ResourceLocator read/write asymmetry
# =============================================================================


class TestResourceLocatorReadWriteAsymmetry:
    """Property 4: ResourceLocator read/write asymmetry.

    For any ResourceLocator configured in standalone mode (no .functualize/
    ancestor), writable(relative_path) SHALL always return a path within the
    XDG platform cache directory and SHALL never return a path within the
    project working directory.

    **Validates: Requirements 2.1, 2.2, 2.7**
    """

    @given(
        relative_path=_safe_filenames,
        project_path_suffix=st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
    )
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_writable_returns_path_within_xdg_cache(
        self,
        relative_path: str,
        project_path_suffix: str,
        tmp_path: Path,
        monkeypatch,
    ):
        """In standalone mode, writable() returns a path within XDG platform cache.

        **Validates: Requirements 2.1, 2.2**
        """
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))
        xdg_cache = test_dir / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

        # Simulate standalone mode: project dir with no .functualize ancestor
        project_dir = test_dir / f"project_{project_path_suffix}"
        project_dir.mkdir()

        project_id = compute_project_id(str(project_dir))

        # Configure locator in standalone mode
        locator = (
            ResourceLocator()
            .search_explicit(project_dir)
            .write_to_platform_cache(project_id)
        )

        result = locator.writable(relative_path)

        # Result MUST be within XDG cache
        assert str(xdg_cache) in str(result)
        # Result MUST contain 'functualize' and project_id in the path
        assert "functualize" in str(result)
        assert project_id in str(result)

    @given(
        relative_path=_safe_filenames,
        project_path_suffix=st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
    )
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_writable_never_returns_path_within_project_directory(
        self,
        relative_path: str,
        project_path_suffix: str,
        tmp_path: Path,
        monkeypatch,
    ):
        """In standalone mode, writable() never returns a path within the project dir.

        **Validates: Requirements 2.2, 2.7**
        """
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))
        xdg_cache = test_dir / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

        # Project directory (standalone mode — no .functualize/)
        project_dir = test_dir / f"project_{project_path_suffix}"
        project_dir.mkdir()

        project_id = compute_project_id(str(project_dir))

        locator = (
            ResourceLocator()
            .search_explicit(project_dir)
            .write_to_platform_cache(project_id)
        )

        result = locator.writable(relative_path)

        # Result MUST NOT be within the project directory
        assert not str(result).startswith(str(project_dir.resolve()))

    @given(
        relative_path=_safe_filenames,
        project_path_suffix=st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True),
    )
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_writable_creates_parent_directories(
        self,
        relative_path: str,
        project_path_suffix: str,
        tmp_path: Path,
        monkeypatch,
    ):
        """writable() creates parent directories so the path is ready for writing.

        **Validates: Requirements 2.7**
        """
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))
        xdg_cache = test_dir / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

        project_dir = test_dir / f"project_{project_path_suffix}"
        project_dir.mkdir()

        project_id = compute_project_id(str(project_dir))

        locator = (
            ResourceLocator()
            .search_explicit(project_dir)
            .write_to_platform_cache(project_id)
        )

        result = locator.writable(relative_path)

        # Parent directory must exist after calling writable()
        assert result.parent.exists()

    @given(
        relative_path=_safe_filenames,
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_project_id_is_deterministic(
        self,
        relative_path: str,
        tmp_path: Path,
        monkeypatch,
    ):
        """compute_project_id produces deterministic output for the same path.

        Two locators configured with the same project path produce the same
        write target location.

        **Validates: Requirements 2.2**
        """
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))
        xdg_cache = test_dir / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

        project_dir = test_dir / "myproject"
        project_dir.mkdir()

        project_id_1 = compute_project_id(str(project_dir))
        project_id_2 = compute_project_id(str(project_dir))
        assert project_id_1 == project_id_2

        locator1 = ResourceLocator().write_to_platform_cache(project_id_1)
        locator2 = ResourceLocator().write_to_platform_cache(project_id_2)

        result1 = locator1.writable(relative_path)
        result2 = locator2.writable(relative_path)

        assert result1 == result2

    @given(
        relative_path=_safe_filenames,
        sub_path=st.from_regex(
            r"[a-z][a-z0-9_]{0,5}/[a-z][a-z0-9_]{0,5}", fullmatch=True
        ),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_writable_with_nested_relative_path(
        self,
        relative_path: str,
        sub_path: str,
        tmp_path: Path,
        monkeypatch,
    ):
        """writable() handles nested relative paths (with subdirectories).

        **Validates: Requirements 2.7**
        """
        test_dir = Path(tempfile.mkdtemp(dir=tmp_path))
        xdg_cache = test_dir / "xdg_cache"
        xdg_cache.mkdir()
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

        project_dir = test_dir / "project"
        project_dir.mkdir()

        project_id = compute_project_id(str(project_dir))
        locator = ResourceLocator().write_to_platform_cache(project_id)

        nested_path = f"{sub_path}/{relative_path}"
        result = locator.writable(nested_path)

        # Parent directory must be created
        assert result.parent.exists()
        # Must be within XDG cache
        assert str(xdg_cache) in str(result)
        # Must NOT be in project directory
        assert not str(result).startswith(str(project_dir.resolve()))
