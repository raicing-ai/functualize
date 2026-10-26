"""`root = true` bounds the project-folder lookup and the project identity (G9–G11).

Walk C (the ``.functualize/`` lookup) used to stop only at the filesystem root.
A nested ``root = true`` project with no ``.functualize/`` of its own therefore
adopted its *ancestor's* folder: the ancestor's convention plugins ran, its
state and runs were read and written, and ``builtin data show`` reported
``Mode: project`` at the ancestor.

After the fix such a root is standalone, and its root-marker directory is the
one identity for itself and every subfolder: ``nested`` and ``nested/sub``
resolve the same freshness file under the XDG cache, keyed by ``nested``.

Marked ``real_state_root``: the subject is the state path itself, so the
autouse sandbox (``tests/conftest.py::_isolate_state_root``) must not redirect
it. Every ``func`` runs in a subprocess with ``HOME`` and all ``XDG_*`` roots
under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from functualize._primitives.locator import compute_project_id

pytestmark = pytest.mark.real_state_root

# Use the project root so `uv run` picks up the workspace
PROJECT_ROOT = Path(__file__).parent.parent.parent
_AUDIT_PLUGIN = (
    PROJECT_ROOT
    / "examples"
    / "project"
    / "shared_plugins"
    / ".functualize"
    / "plugins"
    / "audit_log.py"
)


def _env(tmp_path: Path) -> dict[str, str]:
    """A process environment whose home and XDG roots live under ``tmp_path``."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FUNCTUALIZE_", "XDG_"))
    }
    home = tmp_path / "home"
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        COLUMNS="1000",
    )
    return env


def _run_func(
    *args: str, cwd: Path, env: dict[str, str], timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    """Run `uv run func` with the given args in the specified directory."""
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=timeout,
    )


def _data_show(cwd: Path, env: dict[str, str]) -> tuple[str, str]:
    """``(Mode line, Freshness path)`` from `func builtin data show`."""
    result = _run_func("builtin", "data", "show", cwd=cwd, env=env)
    assert result.returncode == 0, result.stderr
    mode = re.search(r"^Mode:\s+(.*)$", result.stdout, re.MULTILINE)
    fresh = re.search(r"^Freshness path:\s+(\S+)", result.stdout, re.MULTILINE)
    assert mode is not None and fresh is not None, result.stdout
    return mode.group(1), fresh.group(1)


def _n4_tree(tmp_path: Path) -> tuple[Path, Path]:
    """N4: a root with no `.functualize/` under an ancestor that has one.

    Returns ``(outer, nested)``. The ancestor's folder carries the example
    convention plugin, which announces every finished job with ``[audit]``.
    """
    outer = tmp_path / "work" / "outer"
    nested = outer / "nested"
    (outer / ".functualize" / "plugins").mkdir(parents=True)
    shutil.copy(_AUDIT_PLUGIN, outer / ".functualize" / "plugins" / "audit_log.py")
    (outer / ".functualize.toml").write_text("")
    (nested / "jobs").mkdir(parents=True)
    (nested / "jobs" / "nested_only.py").write_text(
        "def nested_only() -> None:\n"
        '    """Nested only."""\n'
        '    print("NESTED nested_only() ran")\n'
    )
    (nested / "sub").mkdir()
    (nested / ".functualize.toml").write_text(
        'root = true\njobs_directories = ["jobs"]\n'
    )
    return outer, nested


def _hashes(*roots: Path) -> dict[str, str]:
    """sha256 of every file under ``roots``, keyed by path."""
    digests: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digests[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


class TestARootWithoutItsOwnFolder:
    """G9: the ancestor's `.functualize/` is not the nested root's."""

    def test_g9_ancestor_convention_plugin_does_not_run(self, tmp_path: Path) -> None:
        _outer, nested = _n4_tree(tmp_path)

        run = _run_func("nested-only", cwd=nested, env=_env(tmp_path))

        assert run.returncode == 0, run.stderr
        assert "NESTED nested_only() ran" in run.stdout
        assert "[audit]" not in run.stdout

    def test_g9_root_and_subfolder_share_one_standalone_identity(
        self, tmp_path: Path
    ) -> None:
        _outer, nested = _n4_tree(tmp_path)
        env = _env(tmp_path)
        expected = (
            tmp_path
            / "home"
            / ".cache"
            / "functualize"
            / compute_project_id(nested)
            / "fresh.json"
        )

        from_root = _data_show(nested, env)
        from_sub = _data_show(nested / "sub", env)

        for mode, fresh in (from_root, from_sub):
            assert mode.startswith("standalone"), mode
            assert Path(fresh) == expected
        assert from_root == from_sub


class TestTheAncestorDataIsUntouched:
    """G10: running the nested root reads and writes nothing of the ancestor's."""

    def test_g10_ancestor_folder_and_vault_hashes_are_unchanged(
        self, tmp_path: Path
    ) -> None:
        outer, nested = _n4_tree(tmp_path)
        env = _env(tmp_path)
        vault_dir = (
            tmp_path
            / "home"
            / ".local"
            / "share"
            / "functualize"
            / "vaults"
            / compute_project_id(outer)
        )
        watched = (outer / ".functualize", vault_dir)
        before = _hashes(*watched)

        assert _run_func("nested-only", cwd=nested, env=env).returncode == 0
        _data_show(nested, env)
        _data_show(nested / "sub", env)

        assert _hashes(*watched) == before


class TestStandaloneWithoutARootIsUnchanged:
    """G11: no root and no `.functualize/` — each directory is its own identity."""

    def test_g11_directory_and_subdirectory_keep_distinct_identities(
        self, tmp_path: Path
    ) -> None:
        directory = tmp_path / "work" / "dir"
        (directory / "sub").mkdir(parents=True)
        env = _env(tmp_path)

        mode_dir, fresh_dir = _data_show(directory, env)
        mode_sub, fresh_sub = _data_show(directory / "sub", env)

        assert mode_dir.startswith("standalone")
        assert mode_sub.startswith("standalone")
        assert fresh_dir != fresh_sub
        assert compute_project_id(directory) in fresh_dir
        assert compute_project_id(directory / "sub") in fresh_sub
