"""Tests for convention directory detection and auto-wiring."""

from __future__ import annotations

from pathlib import Path

from functualize.app.utils import resolve_effective_directories


class TestConventionDirectories:
    """Tests for .functualize/ convention directory auto-wiring."""

    def test_jobs_convention_dir_auto_added(self, tmp_path: Path) -> None:
        """Project with .functualize/jobs/ gets it auto-added to jobs_directories."""
        jobs_dir = tmp_path / ".functualize" / "jobs"
        jobs_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert str(jobs_dir.resolve()) in result["jobs_directories"]

    def test_lib_convention_dir_auto_added(self, tmp_path: Path) -> None:
        """.functualize/lib/ auto-added to import_libs."""
        lib_dir = tmp_path / ".functualize" / "lib"
        lib_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert str(lib_dir.resolve()) in result["import_libs"]

    def test_plugins_convention_dir_auto_added(self, tmp_path: Path) -> None:
        """.functualize/plugins/ auto-added to plugins_directories."""
        plugins_dir = tmp_path / ".functualize" / "plugins"
        plugins_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert str(plugins_dir.resolve()) in result["plugins_directories"]

    def test_missing_convention_dirs_silently_skipped(self, tmp_path: Path) -> None:
        """Missing convention directories are silently skipped."""
        # No .functualize/ directory at all
        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert result["jobs_directories"] == []
        assert result["import_libs"] == []
        assert result["plugins_directories"] == []

    def test_explicit_config_appears_before_convention(self, tmp_path: Path) -> None:
        """Explicit config entries appear earlier in the list than convention dirs."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        jobs_dir = tmp_path / ".functualize" / "jobs"
        jobs_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"jobs_directories": ["scripts"]},
        )

        dirs = result["jobs_directories"]
        scripts_idx = dirs.index(str(scripts.resolve()))
        convention_idx = dirs.index(str(jobs_dir.resolve()))
        assert scripts_idx < convention_idx

    def test_explicit_import_libs_before_convention_lib(self, tmp_path: Path) -> None:
        """Explicit import_libs config appears before .functualize/lib/."""
        custom_lib = tmp_path / "custom_lib"
        custom_lib.mkdir()
        lib_dir = tmp_path / ".functualize" / "lib"
        lib_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"import_libs": ["custom_lib"]},
        )

        libs = result["import_libs"]
        custom_idx = libs.index(str(custom_lib.resolve()))
        convention_idx = libs.index(str(lib_dir.resolve()))
        assert custom_idx < convention_idx

    def test_convention_not_duplicate_if_in_config(self, tmp_path: Path) -> None:
        """If convention dir is already in explicit config, it's not duplicated."""
        lib_dir = tmp_path / ".functualize" / "lib"
        lib_dir.mkdir(parents=True)

        # Explicit config also points to the same dir
        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"import_libs": [str(lib_dir)]},
        )

        # Should only appear once
        libs = result["import_libs"]
        assert libs.count(str(lib_dir.resolve())) == 1

    def test_all_three_convention_dirs_together(self, tmp_path: Path) -> None:
        """All three convention dirs work simultaneously."""
        (tmp_path / ".functualize" / "jobs").mkdir(parents=True)
        (tmp_path / ".functualize" / "lib").mkdir(parents=True)
        (tmp_path / ".functualize" / "plugins").mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert len(result["jobs_directories"]) == 1
        assert len(result["import_libs"]) == 1
        assert len(result["plugins_directories"]) == 1
        assert "jobs" in result["jobs_directories"][0]
        assert "lib" in result["import_libs"][0]
        assert "plugins" in result["plugins_directories"][0]

    def test_functualize_dir_exists_but_subdirs_missing(self, tmp_path: Path) -> None:
        """.functualize/ dir exists but convention subdirs don't → nothing added."""
        (tmp_path / ".functualize").mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert result["jobs_directories"] == []
        assert result["import_libs"] == []
        assert result["plugins_directories"] == []
