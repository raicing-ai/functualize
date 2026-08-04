"""Unit tests for the auto_discover utility function.

Tests cover:
- Discovery via config escalation (pyproject.toml, .functualize.toml, XDG global)
- Silently skip non-existent configured directories
- Warn on unreadable/malformed config files, continue with empty config
- Edge cases (empty directory, no config found)
- JobSources() with no arguments means "no jobs" (not auto-discover)
"""

from __future__ import annotations

from pathlib import Path

from functualize.app.config import JobSources
from functualize.app.utils import DiscoveryResult, auto_discover


class TestAutoDiscoverConfigEscalation:
    """Tests for config escalation: pyproject.toml → .functualize.toml → XDG global."""

    def test_discovers_from_pyproject_toml(self, tmp_path: Path) -> None:
        """Reads jobs_directories from pyproject.toml [tool.functualize]."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "deploy.py").write_text('JOB_NAME = "deploy"\n')

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.functualize]\njobs_directories = ["jobs"]\n')

        result = auto_discover(cwd=tmp_path)

        assert isinstance(result, DiscoveryResult)
        assert result.directories is not None
        assert str(jobs_dir.resolve()) in result.directories

    def test_discovers_from_functualize_toml(self, tmp_path: Path) -> None:
        """Reads jobs_directories from .functualize.toml when no pyproject section."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        functualize_toml = tmp_path / ".functualize.toml"
        functualize_toml.write_text('jobs_directories = ["jobs"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(jobs_dir.resolve()) in result.directories

    def test_pyproject_takes_precedence_over_functualize_toml(
        self, tmp_path: Path
    ) -> None:
        """pyproject.toml [tool.functualize] wins over .functualize.toml."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.functualize]\njobs_directories = ["jobs"]\n')

        functualize_toml = tmp_path / ".functualize.toml"
        functualize_toml.write_text('jobs_directories = ["other"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(jobs_dir.resolve()) in result.directories
        # .functualize.toml should NOT be read if pyproject has the section
        assert str(other_dir.resolve()) not in result.directories

    def test_discovers_from_xdg_global(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """Reads from XDG global config when no project-level config exists."""
        import pytest

        monkeypatch = pytest.MonkeyPatch()  # noqa: F811
        jobs_dir = tmp_path / "global_jobs"
        jobs_dir.mkdir()

        xdg_dir = tmp_path / "xdg_config" / "functualize"
        xdg_dir.mkdir(parents=True)
        config_toml = xdg_dir / "config.toml"
        config_toml.write_text(f'jobs_directories = ["{jobs_dir}"]\n')

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(jobs_dir.resolve()) in result.directories
        monkeypatch.undo()

    def test_extra_directories_from_config(self, tmp_path: Path) -> None:
        """Reads extra_directories from project config."""
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.functualize]\nextra_directories = ["extra"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert str(extra_dir.resolve()) in result.directories

    def test_no_config_returns_none_directories(self, tmp_path: Path) -> None:
        """When no config files are found, directories is None."""
        result = auto_discover(cwd=tmp_path)

        assert isinstance(result, DiscoveryResult)
        assert result.directories is None


class TestAutoDiscoverNonExistentDirectories:
    """Tests for silently skipping non-existent configured directories."""

    def test_skips_nonexistent_directory(self, tmp_path: Path) -> None:
        """Non-existent directories in config are silently skipped."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.functualize]\njobs_directories = ["nonexistent"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None

    def test_skips_file_not_directory(self, tmp_path: Path) -> None:
        """A file named in jobs_directories is skipped (not a directory)."""
        (tmp_path / "jobs").write_text("not a directory")

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.functualize]\njobs_directories = ["jobs"]\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None

    def test_mixes_existing_and_nonexistent(self, tmp_path: Path) -> None:
        """Only existing directories are returned."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.functualize]\n"
            'jobs_directories = ["jobs", "nonexistent", "also_missing"]\n'
        )

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        assert len(result.directories) == 1
        assert str(jobs_dir.resolve()) in result.directories


class TestAutoDiscoverMalformedConfig:
    """Tests for warning on unreadable/malformed config, continuing with empty."""

    def test_pyproject_without_functualize_section(self, tmp_path: Path) -> None:
        """pyproject.toml without [tool.functualize] is handled gracefully."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.pytest]\naddopts = "-v"\n')

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None

    def test_invalid_pyproject_toml_handled_gracefully(self, tmp_path: Path) -> None:
        """Malformed pyproject.toml warns to stderr and returns empty."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("this is not valid toml {{{{")

        result = auto_discover(cwd=tmp_path)

        # Should not raise, just skip
        assert result.directories is None

    def test_invalid_functualize_toml_handled_gracefully(self, tmp_path: Path) -> None:
        """Malformed .functualize.toml warns to stderr and returns empty."""
        functualize_toml = tmp_path / ".functualize.toml"
        functualize_toml.write_text("this is [[[not valid")

        result = auto_discover(cwd=tmp_path)

        assert result.directories is None


class TestAutoDiscoverDeduplication:
    """Tests for deduplication of results."""

    def test_no_duplicates_in_results(self, tmp_path: Path) -> None:
        """Same directory declared in both jobs_directories and extra_directories."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.functualize]\n"
            'jobs_directories = ["jobs"]\n'
            'extra_directories = ["jobs"]\n'
        )

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        # No duplicates
        assert len(result.directories) == len(set(result.directories))
        assert len(result.directories) == 1

    def test_dedup_across_config_and_cwd_scan(self, tmp_path: Path) -> None:
        """Same directory from config and CWD scan appears only once."""
        # Create a qualifying .py file in tmp_path itself so CWD scan finds it
        qualifying_py = tmp_path / "deploy.py"
        qualifying_py.write_text("def deploy():\n    pass\n")

        # Also declare the same directory (CWD) in config
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(f'[tool.functualize]\njobs_directories = ["{tmp_path}"]\n')

        result = auto_discover(cwd=tmp_path, scan_depth=0)

        assert result.directories is not None
        resolved_cwd = str(tmp_path.resolve())
        # The directory should appear exactly once despite being in both sources
        assert result.directories.count(resolved_cwd) == 1

    def test_dedup_uses_resolved_paths(self, tmp_path: Path) -> None:
        """Deduplication resolves paths so relative and absolute match."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Declare with relative path in config
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.functualize]\n"
            'jobs_directories = ["jobs"]\n'
            f'extra_directories = ["{jobs_dir.resolve()}"]\n'
        )

        result = auto_discover(cwd=tmp_path)

        assert result.directories is not None
        # Only one entry even though declared as both relative and absolute
        assert len(result.directories) == 1


class TestAutoDiscoverDefaults:
    """Tests for default behavior and JobSources() semantics."""

    def test_job_sources_no_args_means_no_jobs(self) -> None:
        """JobSources() with no arguments means 'no jobs' (requirement 8.9)."""
        sources = JobSources()

        assert sources.directories is None
        assert sources.functions is None
        assert sources.job_providers is None

    def test_defaults_to_cwd_when_none(self, tmp_path: Path, monkeypatch) -> None:
        """When cwd is None, uses Path.cwd()."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.functualize]\njobs_directories = ["jobs"]\n')

        monkeypatch.chdir(tmp_path)
        result = auto_discover(cwd=None)

        assert result.directories is not None
        assert str(jobs_dir.resolve()) in result.directories

    def test_returns_job_sources_instance(self, tmp_path: Path) -> None:
        """Always returns a DiscoveryResult instance."""
        result = auto_discover(cwd=tmp_path)

        assert isinstance(result, DiscoveryResult)

    def test_scan_depth_parameter_accepted(self, tmp_path: Path) -> None:
        """scan_depth parameter is accepted (used by task 3.2)."""
        result = auto_discover(cwd=tmp_path, scan_depth=2)

        assert isinstance(result, DiscoveryResult)
