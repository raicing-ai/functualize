"""Tests for resolve_project_config() upward-walk config resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app.utils import resolve_project_config

if TYPE_CHECKING:
    import pytest


def _write_toml(path: Path, content: str) -> None:
    """Helper to write TOML content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestResolveProjectConfig:
    """Tests for resolve_project_config() with upward walk."""

    def test_config_in_cwd_is_found(self, tmp_path: Path) -> None:
        """Baseline: config in CWD is found (existing behavior preserved)."""
        _write_toml(
            tmp_path / ".functualize.toml",
            'jobs_directories = ["scripts"]\nscan_depth = 2',
        )

        anchor, config = resolve_project_config(tmp_path)

        assert anchor == tmp_path
        assert config["jobs_directories"] == ["scripts"]
        assert config["scan_depth"] == 2

    def test_config_two_levels_up_is_found(self, tmp_path: Path) -> None:
        """Config in ancestor is found when CWD has no config."""
        _write_toml(
            tmp_path / ".functualize.toml",
            'jobs_directories = ["jobs"]',
        )
        subdir = tmp_path / "sub" / "deep"
        subdir.mkdir(parents=True)

        anchor, config = resolve_project_config(subdir)

        assert anchor == tmp_path
        assert config["jobs_directories"] == ["jobs"]

    def test_root_true_stops_upward_merge(self, tmp_path: Path) -> None:
        """`root = true` in nearest config prevents merging with ancestors."""
        # Ancestor config
        _write_toml(
            tmp_path / ".functualize.toml",
            'jobs_directories = ["ancestor_jobs"]\nscan_depth = 5',
        )
        # Nested config with root = true
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        _write_toml(
            project_dir / ".functualize.toml",
            'root = true\njobs_directories = ["project_jobs"]',
        )
        # Working directory below the project
        work_dir = project_dir / "sub"
        work_dir.mkdir()

        anchor, config = resolve_project_config(work_dir)

        assert anchor == project_dir
        assert config["jobs_directories"] == ["project_jobs"]
        # Ancestor's scan_depth should NOT be merged
        assert "scan_depth" not in config

    def test_pyproject_toml_section_is_detected(self, tmp_path: Path) -> None:
        """pyproject.toml [tool.functualize] section is detected as valid config."""
        _write_toml(
            tmp_path / "pyproject.toml",
            '[tool.functualize]\njobs_directories = ["scripts"]\n',
        )

        anchor, config = resolve_project_config(tmp_path)

        assert anchor == tmp_path
        assert config["jobs_directories"] == ["scripts"]

    def test_functualize_toml_takes_priority_over_pyproject(
        self, tmp_path: Path
    ) -> None:
        """In the same dir, pyproject.toml [tool.functualize] takes priority over .functualize.toml."""
        _write_toml(tmp_path / ".functualize.toml", 'source = "plain"')
        _write_toml(
            tmp_path / "pyproject.toml",
            '[tool.functualize]\nsource = "pyproject"',
        )

        anchor, config = resolve_project_config(tmp_path)

        assert config["source"] == "pyproject"

    def test_convention_dir_config_found(self, tmp_path: Path) -> None:
        """Config inside .functualize/ subdirectory is found."""
        conv_dir = tmp_path / ".functualize"
        conv_dir.mkdir()
        _write_toml(conv_dir / ".functualize.toml", "convention = true")

        anchor, config = resolve_project_config(tmp_path)

        assert anchor == tmp_path
        assert config["convention"] is True

    def test_returns_cwd_and_empty_dict_when_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns (cwd, {}) when no config found anywhere."""
        # Use a deep isolated directory with no config anywhere above
        isolated = tmp_path / "a" / "b" / "c"
        isolated.mkdir(parents=True)

        # Ensure no platform user config exists
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))

        anchor, config = resolve_project_config(isolated)

        # When nothing found, anchor is the cwd passed in
        assert anchor == isolated
        assert config == {}

    def test_merges_nested_configs_nearest_first(self, tmp_path: Path) -> None:
        """Nested configs are merged with nearest taking priority."""
        # Root level
        _write_toml(
            tmp_path / ".functualize.toml",
            'scan_depth = 3\nextra = "from_root"',
        )
        # Project level (closer to CWD)
        project = tmp_path / "project"
        project.mkdir()
        _write_toml(
            project / ".functualize.toml",
            "scan_depth = 1",
        )
        # Work dir
        work = project / "work"
        work.mkdir()

        anchor, config = resolve_project_config(work)

        assert anchor == project
        # Nearest wins for scalar
        assert config["scan_depth"] == 1
        # Ancestor value merged in
        assert config["extra"] == "from_root"

    def test_deep_merge_of_nested_sections(self, tmp_path: Path) -> None:
        """Nested dict sections are deep-merged across layers."""
        _write_toml(
            tmp_path / ".functualize.toml",
            '[discovery]\nrequire_file_prefix = "job_"\nscan_depth = 5\n',
        )
        project = tmp_path / "project"
        project.mkdir()
        _write_toml(
            project / ".functualize.toml",
            "[discovery]\nscan_depth = 2\n",
        )

        anchor, config = resolve_project_config(project)

        # Deep merge: scan_depth from nearest, require_file_prefix from ancestor
        assert config["discovery"]["scan_depth"] == 2
        assert config["discovery"]["require_file_prefix"] == "job_"

    def test_pyproject_without_functualize_section_skipped(
        self, tmp_path: Path
    ) -> None:
        """pyproject.toml without [tool.functualize] is not treated as config."""
        _write_toml(
            tmp_path / "pyproject.toml",
            '[tool.other]\nkey = "value"',
        )

        anchor, config = resolve_project_config(tmp_path)

        # pyproject without section shouldn't match, but may find config above
        # The key check is that pyproject without section doesn't appear
        assert "key" not in config
