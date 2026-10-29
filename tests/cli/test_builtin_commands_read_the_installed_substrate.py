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

import json
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


def test_run_list_tags_are_exact_and_limit_after_filters(
    elsewhere: JsonFileSubstrate,
) -> None:
    store = RunStore(elsewhere)
    for number, tags in (
        (2, {"host": "laptop", "attempt": "2"}),
        (3, {"host": "laptop", "attempt": "3"}),
        (4, {"host": "Laptop", "attempt": "3"}),
        (5, {"host": "laptop", "attempt": "3"}),
    ):
        store.open_run(
            {
                "run_id": f"run-000{number}",
                "job": "collect",
                "surface": "cli",
                "run_tags": tags,
            }
        )

    result = _run(
        [
            "run",
            "list",
            "--tag",
            "host:laptop",
            "--tag",
            "attempt:3",
            "--limit",
            "2",
            "--format",
            "json",
        ],
        app=_App(elsewhere),
    )
    assert result.exit_code == 0, result.output
    assert [row["run_id"] for row in json.loads(result.output)["runs"]] == [
        "run-0005",
        "run-0003",
    ]
    mismatch = _run(
        ["run", "list", "--tag", "host:Laptop", "--tag", "attempt:2"],
        app=_App(elsewhere),
    )
    assert mismatch.exit_code == 0
    assert mismatch.output == "No matching runs.\n"


def test_run_list_preserves_untagged_table_and_projects_all_json_rows(
    elsewhere: JsonFileSubstrate,
) -> None:
    app = _App(elsewhere)
    before = _run(["run", "list"], app=app)
    assert before.exit_code == 0
    assert before.output == "run-0001  collect  running  cli  -\n"

    RunStore(elsewhere).open_run(
        {
            "run_id": "run-0002",
            "job": "collect",
            "surface": "cli",
            "run_tags": {"repro": "bug-412", "attempt": "3"},
        }
    )
    table = _run(["run", "list"], app=app)
    assert table.exit_code == 0
    assert table.output == (
        "run-0002  collect  running  cli  -  attempt:3 repro:bug-412\n" + before.output
    )
    rows = json.loads(_run(["run", "list", "--format", "json"], app=app).output)["runs"]
    assert [row["run_tags"] for row in rows] == [
        {"repro": "bug-412", "attempt": "3"},
        {},
    ]


def test_run_show_reports_tags_in_text_and_json(
    elsewhere: JsonFileSubstrate,
) -> None:
    app = _App(elsewhere)
    RunStore(elsewhere).open_run(
        {
            "run_id": "run-0002",
            "job": "collect",
            "parent_run_id": "root",
            "run_tags": {"repro": "bug-412"},
        }
    )
    text = _run(["run", "show", "run-0002"], app=app)
    assert text.exit_code == 0, text.output
    assert "run_tags: repro:bug-412\n" in text.output
    assert text.output.index("parent_run_id: root") < text.output.index("run_tags:")
    assert "run_tags:" not in _run(["run", "show", "run-0001"], app=app).output
    payload = json.loads(
        _run(["run", "show", "run-0002", "--format", "json"], app=app).output
    )
    assert payload["run_tags"] == {"repro": "bug-412"}


def test_run_list_refuses_malformed_tag(elsewhere: JsonFileSubstrate) -> None:
    result = _run(["run", "list", "--tag", "missing-colon"], app=_App(elsewhere))
    assert result.exit_code == 2
    assert "Error: --tag 'missing-colon':" in result.output


def test_run_list_refuses_comma_in_tag_value(elsewhere: JsonFileSubstrate) -> None:
    result = _run(["run", "list", "--tag", "k:a,b"], app=_App(elsewhere))
    assert result.exit_code == 2
    assert "a run tag value cannot contain ','" in result.output


def test_job_tags_do_not_become_run_tags(cli_run, project_tree) -> None:
    project = project_tree(
        jobs={
            "release.py": (
                "from functualize.job import job\n"
                "@job(tags=['infra', 'release'])\n"
                "def release():\n    pass\n"
            )
        }
    )
    detail = cli_run(["builtin", "info", "jobs", "release", "--json"], cwd=project)
    assert detail.exit_code == 0, detail.stderr
    assert json.loads(detail.stdout)["tags"] == ["infra", "release"]
    assert cli_run(["release"], cwd=project).exit_code == 0
    no_match = cli_run(["builtin", "run", "list", "--tag", "infra:yes"], cwd=project)
    assert no_match.exit_code == 0, no_match.stderr
    assert no_match.stdout == "No matching runs.\n"
