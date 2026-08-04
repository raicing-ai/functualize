"""Tests for resolve_effective_directories() — full precedence chain."""

from __future__ import annotations

from pathlib import Path

from functualize.app.utils import resolve_effective_directories


class TestResolveEffectiveDirectories:
    """Tests for resolve_effective_directories() precedence and deduplication."""

    def test_cli_override_appears_first(self, tmp_path: Path) -> None:
        """CLI overrides take highest precedence (appear first in list)."""
        cli_path = tmp_path / "cli_libs"
        cli_path.mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
            cli_overrides={"import_libs": [str(cli_path)]},
        )

        assert result["import_libs"][0] == str(cli_path.resolve())

    def test_env_prepends_after_cli(self, tmp_path: Path) -> None:
        """ENV values appear after CLI but before file layer."""
        cli_path = tmp_path / "cli"
        cli_path.mkdir()
        env_path = tmp_path / "env"
        env_path.mkdir()
        file_path = tmp_path / "file"
        file_path.mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"import_libs": ["file"]},
            cli_overrides={"import_libs": [str(cli_path)]},
            env_overrides={"import_libs": [str(env_path)]},
        )

        libs = result["import_libs"]
        assert libs[0] == str(cli_path.resolve())
        assert libs[1] == str(env_path.resolve())
        assert str(file_path.resolve()) in libs

    def test_file_layer_paths_resolve_relative_to_anchor(self, tmp_path: Path) -> None:
        """Relative paths in file layer resolve against anchor."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"import_libs": ["scripts"]},
        )

        assert str(scripts_dir.resolve()) in result["import_libs"]

    def test_convention_dirs_only_included_when_exist(self, tmp_path: Path) -> None:
        """Convention directories are only included when they exist on disk."""
        # No .functualize/lib exists
        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )
        assert result["import_libs"] == []

        # Create convention dir
        (tmp_path / ".functualize" / "lib").mkdir(parents=True)
        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )
        assert len(result["import_libs"]) == 1
        assert ".functualize/lib" in result["import_libs"][0]

    def test_convention_dirs_after_file_layer(self, tmp_path: Path) -> None:
        """Convention dirs come after explicit file config."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (tmp_path / ".functualize" / "lib").mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"import_libs": ["scripts"]},
        )

        libs = result["import_libs"]
        # scripts comes first (file layer), then convention dir
        assert libs[0] == str(scripts.resolve())
        assert ".functualize/lib" in libs[1]

    def test_deduplication_preserves_first_occurrence(self, tmp_path: Path) -> None:
        """Deduplication preserves first occurrence."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"import_libs": ["scripts"]},
            cli_overrides={"import_libs": [str(scripts)]},
        )

        # Should only appear once
        assert result["import_libs"].count(str(scripts.resolve())) == 1

    def test_jobs_directories_with_convention(self, tmp_path: Path) -> None:
        """jobs_directories convention: .functualize/jobs/ auto-added."""
        jobs_dir = tmp_path / ".functualize" / "jobs"
        jobs_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert len(result["jobs_directories"]) == 1
        assert "jobs" in result["jobs_directories"][0]

    def test_plugins_directories_with_convention(self, tmp_path: Path) -> None:
        """plugins_directories convention: .functualize/plugins/ auto-added."""
        plugins_dir = tmp_path / ".functualize" / "plugins"
        plugins_dir.mkdir(parents=True)

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
        )

        assert len(result["plugins_directories"]) == 1
        assert "plugins" in result["plugins_directories"][0]

    def test_exclude_patterns_are_not_resolved_as_paths(self, tmp_path: Path) -> None:
        """exclude_patterns are glob patterns, not paths — no resolution."""
        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"exclude_patterns": ["**/test_*.py", "build/*"]},
        )

        patterns = result["exclude_patterns"]
        assert "**/test_*.py" in patterns
        assert "build/*" in patterns

    def test_global_config_provides_baseline(self, tmp_path: Path) -> None:
        """Global config values appear in the result."""
        global_lib = tmp_path / "global_lib"
        global_lib.mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={},
            global_config={"import_libs": [str(global_lib)]},
        )

        assert str(global_lib.resolve()) in result["import_libs"]

    def test_discovery_subsection_fallback(self, tmp_path: Path) -> None:
        """Keys under [discovery] subsection are also checked."""
        extra = tmp_path / "extra"
        extra.mkdir()

        result = resolve_effective_directories(
            anchor=tmp_path,
            merged_config={"discovery": {"extra_directories": ["extra"]}},
        )

        assert str(extra.resolve()) in result["extra_directories"]
