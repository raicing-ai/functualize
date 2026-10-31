"""`root = true` bounds every source a nested project resolves (G1–G8).

A nested project that declares ``root = true`` used to stop the walk for its
*config layers* only. Every other walk-A consumer — the job directories, the
convention ``.functualize/jobs/`` and ``lib/`` directories, ``extra_directories``
and the TUI settings list — kept walking past it, so an ancestor's mere marker
file (empty is enough) pulled the ancestor's jobs into the nested project while
``builtin config path`` showed the ancestor as no part of it.

Every gate runs the public ``func`` entry point in a subprocess, with ``HOME``
and all three ``XDG_*`` roots under ``tmp_path`` (the autouse fake home is a
fixed path shared by every checkout). G8 is the one in-process gate: the
settings store is what the TUI reads, and it has no CLI of its own.

Tree, built by :func:`_tree`::

    outer/.functualize.toml                  (empty unless a gate says otherwise)
    outer/.functualize/jobs/outer_only.py
    outer/nested/.functualize.toml           root = true
    outer/nested/.functualize/jobs/nested_only.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# Use the project root so `uv run` picks up the workspace
PROJECT_ROOT = Path(__file__).parent.parent.parent

_OUTER_JOB = (
    "def outer_only() -> None:\n"
    '    """Outer only."""\n'
    '    print("OUTER outer_only() ran")\n'
)
_NESTED_JOB = (
    "def nested_only() -> None:\n"
    '    """Nested only."""\n'
    '    print("NESTED nested_only() ran")\n'
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


def _job_names(cwd: Path, env: dict[str, str]) -> list[str]:
    """The job names `func builtin info jobs --json` reports from ``cwd``."""
    result = _run_func("builtin", "info", "jobs", "--json", cwd=cwd, env=env)
    assert result.returncode == 0, result.stderr
    return sorted(entry["name"] for entry in json.loads(result.stdout))


def _write_job(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.py").write_text(body)


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    """Build the report's tree; return ``(outer, nested)``."""
    outer = tmp_path / "work" / "outer"
    nested = outer / "nested"
    _write_job(outer / ".functualize" / "jobs", "outer_only", _OUTER_JOB)
    _write_job(nested / ".functualize" / "jobs", "nested_only", _NESTED_JOB)
    (outer / ".functualize.toml").write_text("")
    (nested / ".functualize.toml").write_text("root = true\n")
    return outer, nested


class TestAncestorJobsStopAtTheRoot:
    """G1–G4: nothing an ancestor declares or holds is a job source of the root."""

    def test_g1_ancestor_convention_jobs_are_not_listed_or_runnable(
        self, tmp_path: Path
    ) -> None:
        """G1 — the reported tree: the ancestor's job is neither listed nor run."""
        _outer, nested = _tree(tmp_path)
        env = _env(tmp_path)

        assert _job_names(nested, env) == ["nested-only"]

        run = _run_func("outer-only", cwd=nested, env=env)
        assert run.returncode == 1, run.stdout
        assert "Unknown command 'outer-only'" in run.stderr
        assert "OUTER" not in run.stdout

    def test_g2_ancestor_jobs_directories_are_not_sources(self, tmp_path: Path) -> None:
        """G2 — an ancestor's declared ``jobs_directories`` stays the ancestor's."""
        outer, nested = _tree(tmp_path)
        (outer / ".functualize.toml").write_text('jobs_directories = ["shared"]\n')
        _write_job(
            outer / "shared",
            "shared_job",
            'def shared_job() -> None:\n    """Shared."""\n',
        )

        assert "shared-job" not in _job_names(nested, _env(tmp_path))

    def test_g3_ancestor_extra_directories_are_not_sources(
        self, tmp_path: Path
    ) -> None:
        """G3 — the same rule for ``extra_directories``."""
        outer, nested = _tree(tmp_path)
        (outer / ".functualize.toml").write_text('extra_directories = ["extra"]\n')
        _write_job(
            outer / "extra",
            "extra_job",
            'def extra_job() -> None:\n    """Extra."""\n',
        )

        assert "extra-job" not in _job_names(nested, _env(tmp_path))

    def test_g4_ancestor_convention_lib_is_not_importable(self, tmp_path: Path) -> None:
        """G4 — the ancestor's ``.functualize/lib/`` is not on the nested path."""
        outer, nested = _tree(tmp_path)
        lib = outer / ".functualize" / "lib"
        lib.mkdir(parents=True)
        (lib / "outerlib.py").write_text("VALUE = 1\n")
        _write_job(
            nested / ".functualize" / "jobs",
            "uses_lib",
            "def uses_lib() -> None:\n"
            '    """Import the ancestor library."""\n'
            "    import outerlib\n"
            '    print(f"LIB {outerlib.VALUE}")\n',
        )

        run = _run_func("uses-lib", cwd=nested, env=_env(tmp_path))

        assert "LIB 1" not in run.stdout
        assert "ModuleNotFoundError" in run.stdout + run.stderr


class TestWithoutARootNothingChanges:
    """G5–G6: inheritance without a root, and declared paths under one."""

    def test_g5_no_root_inherits_the_ancestor(self, tmp_path: Path) -> None:
        """G5 — an empty nested file declares no root, so the union stays."""
        _outer, nested = _tree(tmp_path)
        (nested / ".functualize.toml").write_text("")

        assert _job_names(nested, _env(tmp_path)) == ["nested-only", "outer-only"]

    def test_g6_a_root_may_declare_a_directory_outside_itself(
        self, tmp_path: Path
    ) -> None:
        """G6 — a path the root *declares* is the root's choice, not a leak."""
        outer, nested = _tree(tmp_path)
        (outer / ".functualize.toml").unlink()
        _write_job(
            outer / "shared",
            "shared_job",
            'def shared_job() -> None:\n    """Shared."""\n',
        )
        (nested / ".functualize.toml").write_text(
            'root = true\njobs_directories = ["../shared"]\n'
        )

        assert _job_names(nested, _env(tmp_path)) == ["nested-only", "shared-job"]


class TestTheWarmCacheAgrees:
    """G7: the discovery cache answers what a cold boot answers."""

    def test_g7_cold_and_warm_boots_list_the_same_jobs(self, tmp_path: Path) -> None:
        """Cold, then warm: both bounded by the root."""
        _outer, nested = _tree(tmp_path)
        env = _env(tmp_path)

        cold = _job_names(nested, env)
        warm = _job_names(nested, env)

        assert cold == warm == ["nested-only"]

    def test_g7_a_warm_cache_shrinks_when_the_root_appears(
        self, tmp_path: Path
    ) -> None:
        """Warm a union cache, then declare the root: the set shrinks."""
        _outer, nested = _tree(tmp_path)
        env = _env(tmp_path)
        (nested / ".functualize.toml").write_text("")
        assert _job_names(nested, env) == ["nested-only", "outer-only"]
        assert _job_names(nested, env) == ["nested-only", "outer-only"]

        (nested / ".functualize.toml").write_text("root = true\n")
        # A distinct mtime even on a coarse-grained filesystem clock.
        stamp = (nested / ".functualize.toml").stat().st_mtime + 2
        os.utime(nested / ".functualize.toml", (stamp, stamp))

        assert _job_names(nested, env) == ["nested-only"]
        assert _job_names(nested, env) == ["nested-only"]


class TestTheSettingsStoreStopsAtTheRoot:
    """G8: the TUI settings chain lists no file above the root."""

    def test_g8_ancestor_settings_file_is_not_a_layer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._cli.data.func_settings import FuncSettingsStore

        outer, nested = _tree(tmp_path)
        (outer / ".functualize.toml").write_text("[cli]\nshow_timing = true\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.chdir(nested)

        store = FuncSettingsStore.discover()
        layer_paths = [info.path for info in store.layers]
        show_timing = next(k for k in store.resolve() if k.name == "cli.show_timing")
        sources = [entry.source_id for entry in show_timing.chain]
        winner = show_timing.winning

        assert outer / ".functualize.toml" not in layer_paths
        assert f"file:{outer / '.functualize.toml'}" not in sources
        assert winner is not None
        assert winner.source_id == "default"
