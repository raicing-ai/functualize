"""`data show`, `run` and `history` read the storage the run wrote to.

`plugin-taxonomy`/T5 fixed five commands that built their stores with
``Store.for_project(Path.cwd())``, which routes through ``substrate_for_project``
and **always** answers `JsonFileSubstrate`. A plugin does not choose storage that
way — it calls ``app.install_substrate`` at ``APP_READY`` — so with a substrate
plugin installed these commands read a different backend from the one the run
wrote to. Measured in one project, immediately after one successful run::

    func builtin why <job>   ->  SKIP (up to date)   # reads the database
    func builtin data show   ->  Fingerprints: 0     # reads the files

The command whose whole job is *tell me where my data is* reported none about a
project that had some.

**This file exists because the fix shipped with nothing defending it.** Reverting
`_project_substrate` to the pre-fix behaviour — ``return None``, which sends every
caller back to the cwd walk — left `tests/cli`, `tests/_cli`, `tests/core` and
`tests/app` at **3,499 passed, 0 failed**. Found by the Verify phase's sabotage
step, not by the suite.

The substrate here is a plain `JsonFileSubstrate` rooted somewhere the cwd walk
cannot reach, rather than a SQLite one: the defect is *which storage is asked*,
not which backend, and using a second backend would let a test pass for the
wrong reason on a machine where the plugin happens to be installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner, Result

from functualize._cli.builtins import register_builtin_commands
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.app.utils import FreshStore, RunStore

_KEY = "jobs.collect:v1"


def _cli() -> click.Group:
    group = click.Group(name="func")
    register_builtin_commands(group)
    return group


def _run(args: list[str], *, app: Any = None) -> Result:
    return CliRunner().invoke(
        _cli(), ["builtin", *args], obj={"app": app} if app else {}
    )


class _App:
    """Only the member these commands reach for.

    A real `FunctualizeApp` would resolve a substrate of its own from the cwd,
    which is the thing under test — so the double hands over exactly the
    storage the test installed and nothing else.
    """

    def __init__(self, substrate: JsonFileSubstrate) -> None:
        self.substrate = substrate


@pytest.fixture
def elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JsonFileSubstrate:
    """A substrate the cwd walk cannot find, holding one of everything."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    store_root = tmp_path / "somewhere-else"
    store_root.mkdir()
    substrate = JsonFileSubstrate(store_root)

    FreshStore(substrate).put_fingerprint(_KEY, {"hash": "abc123"})
    RunStore(substrate).open_run(
        {"run_id": "run-0001", "job": "collect", "surface": "cli"}
    )
    return substrate


def test_data_show_counts_the_installed_substrate(elsewhere: JsonFileSubstrate) -> None:
    """The fix. Without it this reads the empty cwd and prints 0."""
    result = _run(["data", "show"], app=_App(elsewhere))

    assert result.exit_code == 0, result.output
    assert "Fingerprints: 1" in result.output


def test_data_show_without_an_app_still_walks_the_cwd(
    elsewhere: JsonFileSubstrate,
) -> None:
    """The fallback is deliberate, so it is asserted rather than assumed.

    `func` builds a context for the builtins that need one; without it the cwd
    walk is the correct answer, because nothing installed anything.
    """
    result = _run(["data", "show"])

    assert result.exit_code == 0, result.output
    assert "Fingerprints: 0" in result.output


def test_run_list_reads_the_installed_substrate(elsewhere: JsonFileSubstrate) -> None:
    result = _run(["run", "list"], app=_App(elsewhere))

    assert result.exit_code == 0, result.output
    assert "run-0001" in result.output or "collect" in result.output
