"""Tests for scaffold context detection.

Validates: Requirements 7.1, 7.2, 7.3, 7.4
"""

from pathlib import Path

import pytest

from functualize._cli.scaffold.context import ContextType, detect_context


class TestDetectContextProjectDir:
    """Test Project_Context detection (R7.1)."""

    def test_project_context_with_package(self, tmp_path: Path) -> None:
        """Detect Project_Context when src/<pkg>/__init__.py exists."""
        pkg_dir = tmp_path / "src" / "mypackage"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.PROJECT
        assert ctx.is_project is True
        assert ctx.cwd == tmp_path
        assert ctx.package_dir == pkg_dir
        assert ctx.package_name == "mypackage"

    def test_jobs_dir_returns_package_jobs_path(self, tmp_path: Path) -> None:
        """jobs_dir returns package_dir/jobs when in project context."""
        pkg_dir = tmp_path / "src" / "mypackage"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        ctx = detect_context(tmp_path)

        assert ctx.jobs_dir == pkg_dir / "jobs"


class TestDetectContextBareDir:
    """Test Bare_Context detection (R7.2)."""

    def test_bare_context_no_src(self, tmp_path: Path) -> None:
        """Detect Bare_Context when no src/ directory exists."""
        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.BARE
        assert ctx.is_project is False
        assert ctx.cwd == tmp_path
        assert ctx.package_dir is None
        assert ctx.package_name is None

    def test_bare_context_jobs_dir_is_none(self, tmp_path: Path) -> None:
        """jobs_dir is None when in bare context."""
        ctx = detect_context(tmp_path)

        assert ctx.jobs_dir is None


class TestDetectContextEmptySrc:
    """Test edge case: src/ exists but is empty (R7.2)."""

    def test_empty_src_is_bare(self, tmp_path: Path) -> None:
        """Empty src/ directory results in Bare_Context."""
        (tmp_path / "src").mkdir()

        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.BARE
        assert ctx.package_dir is None
        assert ctx.package_name is None


class TestDetectContextSrcWithoutInit:
    """Test edge case: src/ has child dirs but none with __init__.py (R7.2)."""

    def test_src_child_without_init_is_bare(self, tmp_path: Path) -> None:
        """src/ with child directories lacking __init__.py is Bare_Context."""
        child = tmp_path / "src" / "somedir"
        child.mkdir(parents=True)
        # No __init__.py

        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.BARE
        assert ctx.package_dir is None

    def test_src_with_file_not_dir_is_bare(self, tmp_path: Path) -> None:
        """src/ containing only files (not dirs) is Bare_Context."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "readme.txt").write_text("not a package")

        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.BARE


class TestDetectContextMultiplePackages:
    """Test deterministic resolution with multiple packages (R7.3)."""

    def test_multiple_packages_picks_first_sorted(self, tmp_path: Path) -> None:
        """With multiple valid packages, sorted() picks first alphabetically."""
        src = tmp_path / "src"
        for name in ["zebra", "alpha", "middle"]:
            pkg = src / name
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("")

        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.PROJECT
        assert ctx.package_name == "alpha"
        assert ctx.package_dir == src / "alpha"

    def test_mixed_valid_and_invalid_packages(self, tmp_path: Path) -> None:
        """Only directories with __init__.py are considered packages."""
        src = tmp_path / "src"
        # "aaa" has no __init__.py — should be skipped
        (src / "aaa").mkdir(parents=True)
        # "bbb" has __init__.py — should be selected
        bbb = src / "bbb"
        bbb.mkdir(parents=True)
        (bbb / "__init__.py").write_text("")

        ctx = detect_context(tmp_path)

        assert ctx.context_type == ContextType.PROJECT
        assert ctx.package_name == "bbb"
        assert ctx.package_dir == bbb


class TestDetectContextDefaultCwd:
    """Test that detect_context uses Path.cwd() when no argument given (R7.4)."""

    def test_default_cwd_usage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """detect_context() without args uses the current working directory."""
        pkg_dir = tmp_path / "src" / "mypkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")

        monkeypatch.chdir(tmp_path)
        ctx = detect_context()

        assert ctx.context_type == ContextType.PROJECT
        assert ctx.cwd == tmp_path
        assert ctx.package_name == "mypkg"

    def test_default_cwd_bare(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """detect_context() without args in bare dir returns Bare_Context."""
        monkeypatch.chdir(tmp_path)
        ctx = detect_context()

        assert ctx.context_type == ContextType.BARE
        assert ctx.cwd == tmp_path
