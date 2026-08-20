"""Property-based tests for auto_discover preservation behavior (Property 2).

Tests that CWD scanning, scan_depth clamping, skip-list application, and
deduplication logic remain unchanged. These tests MUST PASS on the unfixed
code — they capture the baseline behavior to preserve after the fix.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7**
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.app.utils import (
    _SKIP_DIRECTORIES,
    _should_skip_directory,
    auto_discover,
)

# =============================================================================
# Strategies
# =============================================================================

# Strategy: generate arbitrary integer scan_depth values
_scan_depth_strategy = st.integers(min_value=-100, max_value=100)

# Strategy: generate valid directory names that should NOT be skipped
_valid_dir_names = st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True).filter(
    lambda n: n not in _SKIP_DIRECTORIES and not n.startswith(".")
)

# Strategy: generate directory names that SHOULD be skipped (dot-prefixed)
_dot_prefixed_names = st.from_regex(r"\.[a-z][a-z0-9_]{0,8}", fullmatch=True)

# Strategy: generate directory names from _SKIP_DIRECTORIES
_skip_dir_names = st.sampled_from(sorted(_SKIP_DIRECTORIES))

# Strategy: generate skippable names (either dot-prefixed or in skip set)
_skippable_names = st.one_of(_dot_prefixed_names, _skip_dir_names)


# =============================================================================
# Helpers
# =============================================================================


def _create_qualifying_py_file(directory: Path) -> None:
    """Create a qualifying .py file that passes DefaultModulePreFilter + ASTModulePreFilter.

    A qualifying file must:
    - Have a .py extension
    - Not start with underscore
    - Pass DefaultModulePreFilter (no test/conftest patterns)
    - Pass ASTModulePreFilter (contains function defs)
    """
    (directory / "deploy.py").write_text(
        "def deploy():\n    '''A job function.'''\n    pass\n"
    )


# =============================================================================
# Property 2: Preservation - CWD Scan and Depth Clamping Unchanged
# =============================================================================


class TestScanDepthClamping:
    """Property: For all scan_depth integers, effective depth equals max(0, min(scan_depth, 5)).

    **Validates: Requirements 3.2**
    """

    @given(scan_depth=_scan_depth_strategy)
    def test_scan_depth_clamped_to_0_5_range(self, scan_depth: int) -> None:
        """For all scan_depth integers, effective depth equals max(0, min(scan_depth, 5)).

        We verify this by creating a directory tree deeper than 5 levels,
        placing qualifying files at each level, and checking that auto_discover
        never returns directories deeper than min(5, max(0, scan_depth)).

        **Validates: Requirements 3.2**
        """
        expected_depth = max(0, min(scan_depth, 5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a linear directory tree 7 levels deep with qualifying files
            current = tmp_path
            for i in range(7):
                child = current / f"level{i}"
                child.mkdir()
                _create_qualifying_py_file(child)
                current = child

            # Also add a qualifying file at root
            _create_qualifying_py_file(tmp_path)

            result = auto_discover(cwd=tmp_path, scan_depth=scan_depth)

            if result.directories is None:
                return

            # All returned directories should be at depth <= expected_depth from cwd
            cwd_resolved = tmp_path.resolve()
            for dir_str in result.directories:
                dir_path = Path(dir_str)
                try:
                    rel = dir_path.relative_to(cwd_resolved)
                    depth = len(rel.parts)
                except ValueError:
                    # Not relative to CWD - could be from config (skip)
                    continue
                assert depth <= expected_depth, (
                    f"Directory {dir_path} is at depth {depth} "
                    f"but expected_depth is {expected_depth} "
                    f"(scan_depth={scan_depth})"
                )

    @given(scan_depth=st.integers(min_value=-100, max_value=-1))
    def test_negative_scan_depth_clamps_to_zero(self, scan_depth: int) -> None:
        """Negative scan_depth values clamp to 0 (no subdirectory scanning).

        **Validates: Requirements 3.2**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a subdirectory with qualifying files
            sub = tmp_path / "sub"
            sub.mkdir()
            _create_qualifying_py_file(sub)

            # Root also gets a qualifying file
            _create_qualifying_py_file(tmp_path)

            result = auto_discover(cwd=tmp_path, scan_depth=scan_depth)

            # With effective depth 0, only CWD itself should appear (no subdirs)
            if result.directories is not None:
                cwd_resolved = str(tmp_path.resolve())
                for dir_str in result.directories:
                    assert dir_str == cwd_resolved, (
                        f"With negative scan_depth={scan_depth}, "
                        f"only CWD should be found but got {dir_str}"
                    )

    @given(scan_depth=st.integers(min_value=6, max_value=100))
    def test_large_scan_depth_clamps_to_five(self, scan_depth: int) -> None:
        """scan_depth values > 5 clamp to 5.

        **Validates: Requirements 3.2**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a directory tree 7 levels deep
            current = tmp_path
            for i in range(7):
                child = current / f"level{i}"
                child.mkdir()
                _create_qualifying_py_file(child)
                current = child

            _create_qualifying_py_file(tmp_path)

            result = auto_discover(cwd=tmp_path, scan_depth=scan_depth)

            if result.directories is None:
                return

            # Directories at depth > 5 should NOT be included
            cwd_resolved = tmp_path.resolve()
            for dir_str in result.directories:
                dir_path = Path(dir_str)
                try:
                    rel = dir_path.relative_to(cwd_resolved)
                    depth = len(rel.parts)
                except ValueError:
                    continue
                assert depth <= 5, (
                    f"Directory {dir_path} at depth {depth} exceeds max 5 "
                    f"even though scan_depth={scan_depth}"
                )


class TestSkipDirectories:
    """Property: For all directory names in _SKIP_DIRECTORIES or dot-prefixed, those
    directories are never included in scan results.

    **Validates: Requirements 3.4**
    """

    @given(skip_name=_skippable_names)
    def test_skippable_directories_never_in_scan_results(self, skip_name: str) -> None:
        """For all directory names in _SKIP_DIRECTORIES or dot-prefixed,
        those directories are never included in scan results.

        **Validates: Requirements 3.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a skippable directory with qualifying files
            skip_dir = tmp_path / skip_name
            skip_dir.mkdir()
            _create_qualifying_py_file(skip_dir)

            # Also create a qualifying file in root so we get results
            _create_qualifying_py_file(tmp_path)

            result = auto_discover(cwd=tmp_path, scan_depth=1)

            if result.directories is None:
                return

            # The skipped directory should never appear
            skip_resolved = str(skip_dir.resolve())
            assert skip_resolved not in result.directories, (
                f"Directory '{skip_name}' should be skipped but was found in results"
            )

    @given(skip_name=_skip_dir_names)
    def test_explicit_skip_list_directories_excluded(self, skip_name: str) -> None:
        """Each directory in _SKIP_DIRECTORIES is properly excluded by _should_skip_directory.

        **Validates: Requirements 3.4**
        """
        assert _should_skip_directory(skip_name) is True

    @given(dot_name=_dot_prefixed_names)
    def test_dot_prefixed_directories_excluded(self, dot_name: str) -> None:
        """All dot-prefixed directories are excluded from scanning.

        **Validates: Requirements 3.4**
        """
        assert _should_skip_directory(dot_name) is True

    @given(valid_name=_valid_dir_names)
    def test_non_skippable_directories_not_excluded(self, valid_name: str) -> None:
        """Valid directory names that are not in skip list and not dot-prefixed
        are NOT excluded by the skip logic.

        **Validates: Requirements 3.4**
        """
        assert _should_skip_directory(valid_name) is False


class TestCwdScanPreservation:
    """Property: For all CWD-only directory trees (no ancestor configs),
    auto_discover produces the same set of scanned directories as the original
    implementation — skip-list applied, pre-filters applied, dedup by resolved path.

    **Validates: Requirements 3.1, 3.3, 3.4**
    """

    @given(
        num_valid=st.integers(min_value=0, max_value=3),
        num_skip=st.integers(min_value=0, max_value=2),
    )
    def test_cwd_scan_includes_valid_excludes_skipped(
        self, num_valid: int, num_skip: int
    ) -> None:
        """CWD scan includes directories with qualifying .py files and
        excludes skippable directories, preserving the existing logic.

        **Validates: Requirements 3.1, 3.3, 3.4**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            valid_dirs: list[Path] = []
            skip_dirs: list[Path] = []

            # Create valid subdirectories with qualifying files
            for i in range(num_valid):
                d = tmp_path / f"valid_{i}"
                d.mkdir()
                _create_qualifying_py_file(d)
                valid_dirs.append(d)

            # Create skippable subdirectories with qualifying files
            skip_names = sorted(_SKIP_DIRECTORIES)[:num_skip]
            for name in skip_names:
                d = tmp_path / name
                d.mkdir()
                _create_qualifying_py_file(d)
                skip_dirs.append(d)

            # Root has qualifying file so it's found at depth 0
            _create_qualifying_py_file(tmp_path)

            result = auto_discover(cwd=tmp_path, scan_depth=1)

            if result.directories is None:
                # Should at least find CWD itself (has qualifying .py file)
                pytest.fail("Expected at least CWD in results")

            result_set = set(result.directories)
            cwd_resolved = str(tmp_path.resolve())

            # CWD should always be in results (it has qualifying .py)
            assert cwd_resolved in result_set

            # Valid directories should be in results
            for d in valid_dirs:
                assert str(d.resolve()) in result_set, (
                    f"Valid directory {d.name} should be in results"
                )

            # Skipped directories should NOT be in results
            for d in skip_dirs:
                assert str(d.resolve()) not in result_set, (
                    f"Skipped directory {d.name} should NOT be in results"
                )

    @given(scan_depth=st.integers(min_value=0, max_value=5))
    def test_non_existent_directories_silently_skipped(self, scan_depth: int) -> None:
        """Non-existent directories referenced in config are silently skipped
        without errors.

        **Validates: Requirements 3.7**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a config pointing to non-existent directories
            pyproject = tmp_path / "pyproject.toml"
            pyproject.write_text(
                "[tool.functualize]\n"
                'jobs_directories = ["does_not_exist", "also_missing", "nope"]\n'
            )

            # Should not raise any exception
            result = auto_discover(cwd=tmp_path, scan_depth=scan_depth)

            # Non-existent dirs are skipped - either None or only CWD scan results
            if result.directories is not None:
                for d in result.directories:
                    assert Path(d).is_dir(), (
                        f"Result should only contain existing directories, got {d}"
                    )

    def test_deduplication_by_resolved_path(self, tmp_path: Path) -> None:
        """Deduplication by resolved absolute path works — same directory
        referenced multiple ways appears only once.

        **Validates: Requirements 3.3**
        """
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Reference same directory in multiple ways
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.functualize]\n"
            'jobs_directories = ["jobs"]\n'
            f'extra_directories = ["{jobs_dir.resolve()}"]\n'
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)

        if result.directories is not None:
            # Check no duplicates exist
            assert len(result.directories) == len(set(result.directories))
            # Specifically, jobs_dir should appear only once
            jobs_resolved = str(jobs_dir.resolve())
            assert result.directories.count(jobs_resolved) <= 1


class TestDefaultCwdBehavior:
    """Property: auto_discover defaults to CWD when no argument provided.

    **Validates: Requirements 3.1**
    """

    def test_defaults_to_cwd_when_none(self, tmp_path: Path, monkeypatch) -> None:
        """When cwd is None, auto_discover uses Path.cwd() as default.

        **Validates: Requirements 3.1**
        """
        _create_qualifying_py_file(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = auto_discover(cwd=None, scan_depth=0)

        assert result.directories is not None
        assert str(tmp_path.resolve()) in result.directories
