"""Unit tests for enumerate_job_names() in app/utils.py."""

from __future__ import annotations

from pathlib import Path

from functualize.app.utils import enumerate_job_names


class TestEnumerateJobNames:
    """Example-based tests for enumerate_job_names."""

    def test_empty_directory_returns_empty_set(self, tmp_path: Path) -> None:
        """An empty directory yields no job names."""
        result = enumerate_job_names([str(tmp_path)])
        assert result == set()

    def test_mixed_files_only_non_underscore_py_stems(self, tmp_path: Path) -> None:
        """Only .py files not starting with _ are included."""
        (tmp_path / "deploy.py").write_text("def run(): pass")
        (tmp_path / "migrate.py").write_text("def run(): pass")
        (tmp_path / "_helper.py").write_text("# private")
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "README.md").write_text("# docs")
        (tmp_path / "config.toml").write_text("[x]")
        (tmp_path / "data.json").write_text("{}")

        result = enumerate_job_names([str(tmp_path)])
        assert result == {"deploy", "migrate"}

    def test_nonexistent_directory_returns_empty_set(self) -> None:
        """A non-existent directory path is silently skipped."""
        result = enumerate_job_names(["/nonexistent/path/that/does/not/exist"])
        assert result == set()

    def test_multiple_directories_union_of_stems(self, tmp_path: Path) -> None:
        """Multiple directories produce the union of all valid stems."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "deploy.py").write_text("def run(): pass")
        (dir_a / "migrate.py").write_text("def run(): pass")
        (dir_b / "test.py").write_text("def run(): pass")
        (dir_b / "deploy.py").write_text("def run(): pass")  # duplicate stem

        result = enumerate_job_names([str(dir_a), str(dir_b)])
        assert result == {"deploy", "migrate", "test"}

    def test_empty_list_returns_empty_set(self) -> None:
        """An empty jobs_directories list yields no names."""
        result = enumerate_job_names([])
        assert result == set()

    def test_mix_of_existing_and_nonexistent_directories(self, tmp_path: Path) -> None:
        """Non-existent directories are skipped; valid ones contribute names."""
        valid_dir = tmp_path / "jobs"
        valid_dir.mkdir()
        (valid_dir / "build.py").write_text("def run(): pass")

        result = enumerate_job_names(
            ["/nonexistent/dir", str(valid_dir), "/another/missing"]
        )
        assert result == {"build"}

    def test_subdirectories_are_not_traversed(self, tmp_path: Path) -> None:
        """Only top-level .py files are considered (non-recursive)."""
        (tmp_path / "top.py").write_text("def run(): pass")
        sub = tmp_path / "nested"
        sub.mkdir()
        (sub / "deep.py").write_text("def run(): pass")

        result = enumerate_job_names([str(tmp_path)])
        assert result == {"top"}

    def test_directories_named_with_py_suffix_excluded(self, tmp_path: Path) -> None:
        """A directory ending in .py is not treated as a job file."""
        (tmp_path / "fakejob.py").mkdir()
        (tmp_path / "real.py").write_text("def run(): pass")

        result = enumerate_job_names([str(tmp_path)])
        assert result == {"real"}
