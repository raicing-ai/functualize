"""Which project a vault belongs to, and what may be imported to answer it.

Two kinds of test here, and the structural ones are not decoration. The whole
reason this module exists separately from ``vault.py`` is that boot must decide
whether a vault exists *before* importing ``cryptography``; a future import that
quietly reintroduced that dependency would put the cost back on every cold boot
without failing anything else.
"""

from __future__ import annotations

import ast
from pathlib import Path

from functualize._config.vault_paths import (
    VAULT_MODES,
    project_root_for,
    vault_path_for_project,
)

_MODULE = Path(__file__).resolve().parents[2] / (
    "src/functualize/_config/vault_paths.py"
)


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, from its AST."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class TestTheColdBootGate:
    """`vault_paths` is the module boot may import before deciding anything."""

    def test_it_does_not_import_cryptography(self) -> None:
        assert not any(m.startswith("cryptography") for m in _imported_modules(_MODULE))

    def test_it_reaches_only_into_primitives(self) -> None:
        """Not a style rule: anything else risks pulling the cipher back in.

        `_config.vault` imports AESGCM at module level. If this module ever
        imports it — directly or through a sibling that does — the `stat` that
        boot performs stops being cheap and the split has silently failed.
        """
        internal = {
            m for m in _imported_modules(_MODULE) if m.startswith("functualize")
        }
        assert internal, "expected at least one internal import"
        assert all(m.startswith("functualize._primitives") for m in internal), internal


class TestProjectIdentity:
    def test_a_subdirectory_reaches_the_same_vault_as_the_root(
        self, tmp_path: Path
    ) -> None:
        """The defect this task exists to fix.

        `vault put` from `src/` then the job from the root used to resolve two
        different vaults, so the stored secret was simply not found.
        """
        (tmp_path / ".functualize").mkdir()
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)

        assert vault_path_for_project(nested) == vault_path_for_project(tmp_path)

    def test_the_root_is_the_parent_of_the_functualize_dir(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".functualize").mkdir()
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)

        root, mode = project_root_for(nested)

        assert root == tmp_path.resolve()
        assert mode == "project"

    def test_without_a_marker_the_starting_directory_is_the_root(
        self, tmp_path: Path
    ) -> None:
        """Standalone mode is the fallback, not a failure — `func` runs over
        loose scripts anywhere, and littering a `.functualize/` beside each one
        would be worse than a keyed directory."""
        root, mode = project_root_for(tmp_path)

        assert root == tmp_path.resolve()
        assert mode == "standalone"

    def test_two_projects_do_not_share_a_vault(self, tmp_path: Path) -> None:
        one = tmp_path / "one"
        two = tmp_path / "two"
        for project in (one, two):
            (project / ".functualize").mkdir(parents=True)

        assert vault_path_for_project(one) != vault_path_for_project(two)

    def test_running_from_the_project_root_is_unchanged(self, tmp_path: Path) -> None:
        """Why this needs no data migration for the common case.

        The id is now hashed over the project root instead of the working
        directory. When you run from the root those are the same string, so a
        vault created before this change is still found. Only the invocations
        that were finding the *wrong* vault move.
        """
        from functualize._primitives.locator import compute_project_id

        (tmp_path / ".functualize").mkdir()
        resolved = tmp_path.resolve()

        assert compute_project_id(str(resolved)) in str(
            vault_path_for_project(resolved)
        )

    def test_modes_are_exactly_two(self) -> None:
        assert VAULT_MODES == ("project", "standalone")
