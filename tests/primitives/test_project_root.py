"""`_primitives/project_root.py` — the one owner of "where a project stops".

Pins the boundary for every marker form, the bounded ``.functualize/`` lookup,
the identity rule, and — for the derived candidate list — that walk A reads
exactly what it read when the list was written out by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from functualize._primitives.locator import ResourceLocator
from functualize._primitives.project_root import (
    PROJECT_CONFIG_CANDIDATES,
    find_functualize_dir,
    find_project_boundary,
    is_root_config,
    project_config_at,
    project_config_file_table,
    project_identity_dir,
)

if TYPE_CHECKING:
    from pathlib import Path


def _literal_extract(path: Path) -> dict[str, Any] | None:
    """The hand-written extractor the derived list replaced, verbatim."""
    import tomllib

    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    tool = data.get("tool", {})
    if isinstance(tool, dict):
        section = tool.get("functualize")
        if isinstance(section, dict):
            return section
    return None


_LITERAL_CANDIDATES: list[Any] = [
    ("pyproject.toml", _literal_extract),
    ".functualize.toml",
    ".functualize/.functualize.toml",
]


def _resolve(candidates: list[Any], start: Path) -> list[tuple[Path, dict[str, Any]]]:
    return (
        ResourceLocator().search_upward(start=start).resolve_all_candidates(candidates)
    )


class TestTheDerivedCandidatesMatchTheOldList:
    """Smell 2: derived from `_types/settings.py`, read exactly as before."""

    def test_names_and_order(self) -> None:
        names = [c if isinstance(c, str) else c[0] for c in PROJECT_CONFIG_CANDIDATES]
        assert names == [
            "pyproject.toml",
            ".functualize.toml",
            ".functualize/.functualize.toml",
        ]

    def test_all_three_files_present(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\n[tool.functualize]\nlevel = "pyproject"\n'
        )
        (tmp_path / ".functualize.toml").write_text('level = "plain"\n')
        (tmp_path / ".functualize").mkdir()
        (tmp_path / ".functualize" / ".functualize.toml").write_text(
            'level = "convention"\n'
        )
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".functualize.toml").write_text('level = "sub"\n')

        assert _resolve(PROJECT_CONFIG_CANDIDATES, sub) == _resolve(
            _LITERAL_CANDIDATES, sub
        )
        assert project_config_at(tmp_path) == {"level": "pyproject"}

    def test_pyproject_without_the_table_falls_through(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        (tmp_path / ".functualize.toml").write_text('level = "plain"\n')

        assert _resolve(PROJECT_CONFIG_CANDIDATES, tmp_path) == _resolve(
            _LITERAL_CANDIDATES, tmp_path
        )
        assert project_config_at(tmp_path) == {"level": "plain"}

    def test_settings_table_of_each_file_kind(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.functualize.cli]\nshow_timing = true\n")
        plain = tmp_path / ".functualize.toml"
        plain.write_text("[cli]\nshow_timing = false\n")

        assert project_config_file_table(pyproject) == (
            {"cli": {"show_timing": True}},
            "tool.functualize",
        )
        assert project_config_file_table(plain) == (
            {"cli": {"show_timing": False}},
            "",
        )
        assert project_config_file_table(tmp_path / "missing.toml") == ({}, "")


class TestTheRootPredicate:
    def test_only_boolean_true_is_a_root(self) -> None:
        assert is_root_config({"root": True})
        assert not is_root_config({"root": "true"})
        assert not is_root_config({"root": False})
        assert not is_root_config({})


class TestTheBoundary:
    """N7: every marker form ends the walk; nothing else does."""

    @pytest.mark.parametrize(
        ("relative", "content"),
        [
            ("pyproject.toml", "[tool.functualize]\nroot = true\n"),
            (".functualize.toml", "root = true\n"),
            (".functualize/.functualize.toml", "root = true\n"),
        ],
        ids=["pyproject", "dotfile", "convention"],
    )
    def test_each_marker_form(
        self, tmp_path: Path, relative: str, content: str
    ) -> None:
        root = tmp_path / "outer" / "nested"
        marker = root / relative
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(content)
        (tmp_path / "outer" / ".functualize.toml").write_text("root = true\n")
        deep = root / "a" / "b"
        deep.mkdir(parents=True)

        assert find_project_boundary(deep) == root.resolve()
        assert find_project_boundary(root) == root.resolve()

    def test_pyproject_without_the_table_is_not_a_marker(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("root = true\n")

        assert find_project_boundary(tmp_path) is None

    def test_root_non_bool_does_not_stop(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize.toml").write_text('root = "true"\n')

        assert find_project_boundary(tmp_path) is None

    def test_no_marker_anywhere(self, tmp_path: Path) -> None:
        assert find_project_boundary(tmp_path) is None


class TestTheBoundedFolderLookup:
    def test_folder_at_the_boundary_is_found(self, tmp_path: Path) -> None:
        root = tmp_path / "nested"
        (root / ".functualize").mkdir(parents=True)
        (root / ".functualize.toml").write_text("root = true\n")
        sub = root / "sub"
        sub.mkdir()

        assert find_functualize_dir(sub) == (root / ".functualize").resolve()

    def test_folder_above_the_boundary_is_not_found(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize").mkdir()
        root = tmp_path / "nested"
        root.mkdir()
        (root / ".functualize.toml").write_text("root = true\n")

        assert find_functualize_dir(root / ".") is None

    def test_without_a_boundary_the_walk_is_unbounded(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)

        assert find_functualize_dir(sub) == (tmp_path / ".functualize").resolve()


class TestTheIdentity:
    def test_n4_root_without_its_own_folder(self, tmp_path: Path) -> None:
        """The root-marker directory, from the root and from a subfolder."""
        (tmp_path / ".functualize").mkdir()
        root = tmp_path / "nested"
        (root / "sub").mkdir(parents=True)
        (root / ".functualize.toml").write_text("root = true\n")

        assert project_identity_dir(root) == root.resolve()
        assert project_identity_dir(root / "sub") == root.resolve()

    def test_n6_root_with_its_own_folder(self, tmp_path: Path) -> None:
        root = tmp_path / "nested"
        (root / ".functualize").mkdir(parents=True)
        (root / ".functualize.toml").write_text("root = true\n")
        (root / "sub").mkdir()

        assert project_identity_dir(root / "sub") == root.resolve()

    def test_inheriting_project_keys_by_its_folder(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize").mkdir()
        sub = tmp_path / "sub"
        sub.mkdir()

        assert project_identity_dir(sub) == tmp_path.resolve()

    def test_standalone_is_its_own_identity(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()

        assert project_identity_dir(sub) == sub.resolve()
        assert project_identity_dir(tmp_path) == tmp_path.resolve()
