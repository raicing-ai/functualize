"""Tests for import_libs sys.path insertion and precedence."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._cli.config import resolve_cli_config

if TYPE_CHECKING:
    import pytest


def _write_toml(path: Path, content: str) -> None:
    """Helper to write TOML content to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestImportLibsResolution:
    """Tests for import_libs field resolution in CliConfig."""

    def test_import_libs_empty_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty by default when not configured."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        monkeypatch.delenv("FUNCTUALIZE_IMPORT_LIBS", raising=False)

        config = resolve_cli_config(cwd=tmp_path)

        assert config.import_libs == ()

    def test_import_libs_from_functualize_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """import_libs populated from .functualize.toml."""
        _write_toml(
            tmp_path / ".functualize.toml",
            'import_libs = ["scripts", "lib"]\n',
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        monkeypatch.delenv("FUNCTUALIZE_IMPORT_LIBS", raising=False)

        config = resolve_cli_config(cwd=tmp_path)

        # Paths should be resolved against anchor (which is tmp_path)
        assert str((tmp_path / "scripts").resolve()) in config.import_libs
        assert str((tmp_path / "lib").resolve()) in config.import_libs

    def test_import_libs_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ENV override FUNCTUALIZE_IMPORT_LIBS works (comma-separated)."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        monkeypatch.setenv("FUNCTUALIZE_IMPORT_LIBS", "/tmp/a,/tmp/b")

        config = resolve_cli_config(cwd=tmp_path)

        assert "/tmp/a" in config.import_libs
        assert "/tmp/b" in config.import_libs

    def test_import_libs_cli_flag_highest_priority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI --import-libs flag takes highest priority."""
        _write_toml(
            tmp_path / ".functualize.toml",
            'import_libs = ["from_file"]\n',
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        monkeypatch.delenv("FUNCTUALIZE_IMPORT_LIBS", raising=False)

        config = resolve_cli_config(
            cli_flags={"import_libs": ["/tmp/cli_lib"]},
            cwd=tmp_path,
        )

        # CLI flag should appear first
        assert config.import_libs[0] == "/tmp/cli_lib"

    def test_import_libs_relative_resolved_against_anchor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative paths resolve against anchor (config file's directory)."""
        # Config at project root
        _write_toml(
            tmp_path / ".functualize.toml",
            'import_libs = ["scripts"]\n',
        )
        # Working from subdirectory
        subdir = tmp_path / "sub" / "deep"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        monkeypatch.delenv("FUNCTUALIZE_IMPORT_LIBS", raising=False)

        config = resolve_cli_config(cwd=subdir)

        # "scripts" should resolve against the anchor (tmp_path), not CWD
        expected = str((tmp_path / "scripts").resolve())
        assert expected in config.import_libs

    def test_import_libs_no_duplicates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No duplicate entries in import_libs."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        _write_toml(
            tmp_path / ".functualize.toml",
            'import_libs = ["scripts"]\n',
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        # Same path via env
        monkeypatch.setenv("FUNCTUALIZE_IMPORT_LIBS", str(scripts))

        config = resolve_cli_config(cwd=tmp_path)

        # Should only appear once despite being in both sources
        assert config.import_libs.count(str(scripts.resolve())) == 1


class TestApplyImportLibs:
    """Tests for _apply_import_libs sys.path insertion."""

    def test_inserts_paths_into_sys_path(self, tmp_path: Path) -> None:
        """Paths are inserted at the front of sys.path."""
        from functualize._cli.main import _apply_import_libs

        lib_dir = str(tmp_path / "mylib")
        original_path = sys.path.copy()

        try:
            _apply_import_libs((lib_dir,))
            assert lib_dir in sys.path
            assert sys.path.index(lib_dir) == 0
        finally:
            sys.path[:] = original_path

    def test_preserves_order(self, tmp_path: Path) -> None:
        """Multiple paths are inserted in the specified order."""
        from functualize._cli.main import _apply_import_libs

        lib_a = str(tmp_path / "a")
        lib_b = str(tmp_path / "b")
        original_path = sys.path.copy()

        try:
            _apply_import_libs((lib_a, lib_b))
            assert sys.path.index(lib_a) < sys.path.index(lib_b)
        finally:
            sys.path[:] = original_path

    def test_skips_if_already_present(self, tmp_path: Path) -> None:
        """Does not add duplicate entries to sys.path."""
        from functualize._cli.main import _apply_import_libs

        lib_dir = str(tmp_path / "mylib")
        original_path = sys.path.copy()

        try:
            sys.path.insert(0, lib_dir)
            count_before = sys.path.count(lib_dir)
            _apply_import_libs((lib_dir,))
            assert sys.path.count(lib_dir) == count_before
        finally:
            sys.path[:] = original_path

    def test_empty_import_libs_noop(self) -> None:
        """Empty tuple is a no-op."""
        from functualize._cli.main import _apply_import_libs

        original_path = sys.path.copy()
        _apply_import_libs(())
        assert sys.path == original_path
