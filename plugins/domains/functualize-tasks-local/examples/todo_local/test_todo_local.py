"""The todo_local example, run the way the plugin README runs it.

One process per command, in a project directory with a `.functualize/`, so the
list can only survive between commands by being in the app's substrate. The
example it replaces imported the state package ADR-022 retired, and failed at
collection.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from functualize.app import FunctualizeApp

HERE = Path(__file__).parent
SCRIPT = HERE / "todo_local.py"
README = HERE.parent.parent / "README.md"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project directory: `.functualize/` puts the substrate inside it."""
    root = tmp_path / "todo-demo"
    (root / ".functualize").mkdir(parents=True)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return root


def _run(project: Path, *args: str) -> list[str]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_the_list_survives_between_processes(project: Path) -> None:
    _run(project, "add", "Write the report")
    _run(project, "add", "Review the report")
    _run(project, "done", "Write")

    assert _run(project, "list") == [
        "[done] Write the report",
        "[pending] Review the report",
    ]


def test_the_tasks_are_in_the_apps_substrate(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read back through a fresh app, not through the example's provider."""
    _run(project, "add", "Write the report")
    monkeypatch.chdir(project)

    stored = FunctualizeApp("reader").substrate.read("tasks")

    assert stored is not None
    assert [t["title"] for t in stored.data["tasks"].values()] == ["Write the report"]
    assert (project / ".functualize" / "tasks.json").is_file()


def test_the_readme_quick_start_is_this_example() -> None:
    """The README prints this file; a copy that drifts is a Quick Start that lies."""
    blocks = re.findall(r"```python\n(.*?)```", README.read_text(), re.DOTALL)

    assert SCRIPT.read_text() in blocks
