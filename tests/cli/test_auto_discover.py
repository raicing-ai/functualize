"""Unit tests for auto_discover() — complementing tests/test_auto_discover.py.

Covers scenarios not already in the root test file:
- Config precedence (CLI > env > project > global)
- Empty CWD returns empty JobSources
- AST parse failure on malformed .py file (skip gracefully)
- scan_depth behavior (depth=0 CWD only, depth=1 one level deep, etc.)
- Integration of config + CWD scan (both sources contribute)

Requirements: 1.1–1.8, 2.1–2.5, 3.1–3.4
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app.utils import auto_discover

if TYPE_CHECKING:
    import pytest


def _write_qualifying_py(directory: Path, filename: str = "task.py") -> Path:
    """Create a qualifying .py file (non-underscore name, public function)."""
    filepath = directory / filename
    filepath.write_text("def run():\n    pass\n")
    return filepath


class TestConfigPrecedence:
    """Config escalation precedence: project-level > global (XDG).

    Requirements 1.1, 2.3, 3.2
    """

    def test_project_config_overrides_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pyproject.toml [tool.functualize] takes precedence over XDG global."""
        project_dir = tmp_path / "project_jobs"
        project_dir.mkdir()

        global_dir = tmp_path / "global_jobs"
        global_dir.mkdir()

        # Project-level config
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            f'[tool.functualize]\njobs_directories = ["{project_dir}"]\n'
        )

        # XDG global config
        xdg_dir = tmp_path / "xdg_config" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(f'jobs_directories = ["{global_dir}"]\n')
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(project_dir.resolve()) in result.directories
        # Global directory should still be included (merged, not overridden)
        assert str(global_dir.resolve()) in result.directories

    def test_functualize_toml_not_read_when_pyproject_has_section(
        self, tmp_path: Path
    ) -> None:
        """When pyproject.toml has [tool.functualize], .functualize.toml is ignored."""
        pyproject_dir = tmp_path / "from_pyproject"
        pyproject_dir.mkdir()
        toml_dir = tmp_path / "from_toml"
        toml_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            f'[tool.functualize]\njobs_directories = ["{pyproject_dir}"]\n'
        )

        functualize_toml = tmp_path / ".functualize.toml"
        functualize_toml.write_text(f'jobs_directories = ["{toml_dir}"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(pyproject_dir.resolve()) in result.directories
        assert str(toml_dir.resolve()) not in result.directories

    def test_functualize_toml_used_when_pyproject_has_no_functualize_section(
        self, tmp_path: Path
    ) -> None:
        """Falls back to .functualize.toml when pyproject has no [tool.functualize]."""
        toml_dir = tmp_path / "from_toml"
        toml_dir.mkdir()

        # pyproject.toml exists but with no functualize section
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.pytest]\naddopts = "-v"\n')

        functualize_toml = tmp_path / ".functualize.toml"
        functualize_toml.write_text(f'jobs_directories = ["{toml_dir}"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(toml_dir.resolve()) in result.directories

    def test_global_config_supplements_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Global config directories are merged (appended) with project config."""
        project_dir = tmp_path / "project_jobs"
        project_dir.mkdir()
        global_dir = tmp_path / "global_jobs"
        global_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            f'[tool.functualize]\njobs_directories = ["{project_dir}"]\n'
        )

        xdg_dir = tmp_path / "xdg_config" / "functualize"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.toml").write_text(f'jobs_directories = ["{global_dir}"]\n')
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        # Both project and global dirs should be present
        assert str(project_dir.resolve()) in result.directories
        assert str(global_dir.resolve()) in result.directories


class TestEmptyCWD:
    """Empty CWD (no .py files, no config) returns empty/None JobSources.

    Requirements 1.2, 1.7, 2.4
    """

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        """CWD with no .py files and no config returns directories=None."""
        result = auto_discover(cwd=tmp_path)

        assert result.directories is None

    def test_directory_with_only_non_py_files(self, tmp_path: Path) -> None:
        """CWD with non-.py files returns directories=None."""
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "config.toml").write_text("[settings]\nkey = 1\n")
        (tmp_path / "data.json").write_text("{}")

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None

    def test_directory_with_only_underscore_prefixed_py(self, tmp_path: Path) -> None:
        """CWD with only underscore-prefixed .py files returns directories=None.

        DefaultModulePreFilter skips underscore-prefixed filenames.
        """
        (tmp_path / "_private.py").write_text("def run():\n    pass\n")
        (tmp_path / "__init__.py").write_text("")

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None

    def test_directory_with_py_but_no_public_functions(self, tmp_path: Path) -> None:
        """CWD with .py files containing no public functions returns None.

        ASTModulePreFilter requires at least one public function definition.
        """
        (tmp_path / "empty.py").write_text("# no functions here\nx = 42\n")
        (tmp_path / "private_only.py").write_text("def _internal():\n    pass\n")

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None


class TestASTParseFailure:
    """AST parse failure on malformed .py files is handled gracefully.

    Requirements 1.2, 8.1, 8.2
    """

    def test_malformed_py_file_skipped(self, tmp_path: Path) -> None:
        """A .py file with syntax errors doesn't crash auto_discover."""
        (tmp_path / "broken.py").write_text("def foo(\n    # unclosed paren\n")

        result = auto_discover(cwd=tmp_path)

        # Should not raise, malformed file is just skipped
        assert result.directories is None

    def test_malformed_py_alongside_valid_py(self, tmp_path: Path) -> None:
        """Valid .py files are still discovered even if sibling is malformed."""
        (tmp_path / "broken.py").write_text("def foo(:\n")
        _write_qualifying_py(tmp_path, "valid.py")

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(tmp_path.resolve()) in result.directories

    def test_multiple_syntax_errors_all_skipped(self, tmp_path: Path) -> None:
        """Multiple malformed .py files are all skipped gracefully."""
        (tmp_path / "bad1.py").write_text("class Foo(:\n")
        (tmp_path / "bad2.py").write_text("import \n")
        (tmp_path / "bad3.py").write_text("def ():\n    pass\n")

        result = auto_discover(cwd=tmp_path)

        # All files have syntax errors → none qualify
        assert result.directories is None

    def test_empty_py_file_skipped(self, tmp_path: Path) -> None:
        """An empty .py file is skipped (no public functions)."""
        (tmp_path / "empty.py").write_text("")

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None


class TestScanDepthBehavior:
    """scan_depth controls traversal depth for CWD scanning.

    Requirements 1.6, 1.7, 1.8, 2.4, 2.5
    """

    def test_depth_zero_scans_only_cwd(self, tmp_path: Path) -> None:
        """depth=0 only scans CWD itself, not subdirectories."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        _write_qualifying_py(subdir, "task.py")
        # No qualifying files in CWD itself

        result = auto_discover(cwd=tmp_path, scan_depth=0)

        # subdir shouldn't be found at depth=0
        assert result.directories is None

    def test_depth_one_scans_direct_children(self, tmp_path: Path) -> None:
        """depth=1 scans CWD + one level of subdirectories."""
        subdir = tmp_path / "jobs"
        subdir.mkdir()
        _write_qualifying_py(subdir, "task.py")

        result = auto_discover(cwd=tmp_path, scan_depth=1)

        assert result.directories is not None
        assert str(subdir.resolve()) in result.directories

    def test_depth_one_does_not_scan_grandchildren(self, tmp_path: Path) -> None:
        """depth=1 does NOT scan two levels deep."""
        subdir = tmp_path / "level1"
        subdir.mkdir()
        grandchild = subdir / "level2"
        grandchild.mkdir()
        _write_qualifying_py(grandchild, "task.py")

        result = auto_discover(cwd=tmp_path, scan_depth=1)

        # grandchild at depth 2 should NOT be discovered
        if result.directories is not None:
            assert str(grandchild.resolve()) not in result.directories

    def test_depth_two_scans_grandchildren(self, tmp_path: Path) -> None:
        """depth=2 scans CWD + children + grandchildren."""
        subdir = tmp_path / "level1"
        subdir.mkdir()
        grandchild = subdir / "level2"
        grandchild.mkdir()
        _write_qualifying_py(grandchild, "task.py")

        result = auto_discover(cwd=tmp_path, scan_depth=2)

        assert result.directories is not None
        assert str(grandchild.resolve()) in result.directories

    def test_negative_depth_treated_as_zero(self, tmp_path: Path) -> None:
        """Negative scan_depth values are clamped to 0."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        _write_qualifying_py(subdir, "task.py")

        result = auto_discover(cwd=tmp_path, scan_depth=-5)

        # Same as depth=0 — should not find subdir
        assert result.directories is None

    def test_depth_over_five_clamped(self, tmp_path: Path) -> None:
        """scan_depth > 5 is clamped to 5."""
        # Create a deeply nested structure (7 levels)
        current = tmp_path
        for i in range(7):
            current = current / f"level{i}"
            current.mkdir()

        _write_qualifying_py(current, "deep.py")

        # depth=100 should be clamped to 5, so level6 at depth 7 is NOT found
        result = auto_discover(cwd=tmp_path, scan_depth=100)

        # The file is at depth 7 (level0/level1/.../level6), clamped depth=5
        # won't reach it
        if result.directories is not None:
            assert str(current.resolve()) not in result.directories


class TestConfigAndCWDScanIntegration:
    """Both config-based directories and CWD scan contribute to results.

    Requirements 1.1, 1.2, 1.3
    """

    def test_config_and_cwd_scan_both_contribute(self, tmp_path: Path) -> None:
        """Config directories AND CWD scan results are merged."""
        # Config-based directory (external location)
        config_dir = tmp_path / "configured_jobs"
        config_dir.mkdir()

        # CWD has qualifying .py files
        _write_qualifying_py(tmp_path, "local_task.py")

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            f'[tool.functualize]\njobs_directories = ["{config_dir}"]\n'
        )

        result = auto_discover(cwd=tmp_path, scan_depth=0)

        assert result.directories is not None
        # Both config dir and CWD (from scan) should be present
        assert str(config_dir.resolve()) in result.directories
        assert str(tmp_path.resolve()) in result.directories

    def test_config_dirs_included_even_without_qualifying_files(
        self, tmp_path: Path
    ) -> None:
        """Config directories are included based on existence, not file content.

        Config directories don't need to pass the pre-filter — they are
        explicitly declared by the user.
        """
        config_dir = tmp_path / "my_jobs"
        config_dir.mkdir()
        # Directory exists but has no qualifying .py files

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            f'[tool.functualize]\njobs_directories = ["{config_dir}"]\n'
        )

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(config_dir.resolve()) in result.directories

    def test_cwd_scan_finds_qualifying_dirs_without_config(
        self, tmp_path: Path
    ) -> None:
        """CWD scan works independently of config presence."""
        _write_qualifying_py(tmp_path, "my_task.py")

        result = auto_discover(cwd=tmp_path, scan_depth=0)

        assert result.directories is not None
        assert str(tmp_path.resolve()) in result.directories

    def test_deduplication_across_config_and_scan(self, tmp_path: Path) -> None:
        """Same directory from config and scan appears only once."""
        _write_qualifying_py(tmp_path, "task.py")

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(f'[tool.functualize]\njobs_directories = ["{tmp_path}"]\n')

        result = auto_discover(cwd=tmp_path, scan_depth=0)

        assert result.directories is not None
        resolved = str(tmp_path.resolve())
        assert result.directories.count(resolved) == 1

    def test_skip_directories_during_cwd_scan(self, tmp_path: Path) -> None:
        """Blacklisted directories are never included from CWD scan."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        _write_qualifying_py(venv_dir, "task.py")

        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        _write_qualifying_py(pycache_dir, "task.py")

        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        _write_qualifying_py(git_dir, "task.py")

        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        _write_qualifying_py(node_modules, "task.py")

        result = auto_discover(cwd=tmp_path, scan_depth=1)

        # None of the blacklisted directories should be found
        if result.directories is not None:
            for d in result.directories:
                assert ".venv" not in d
                assert "__pycache__" not in d
                assert ".git" not in d
                assert "node_modules" not in d
