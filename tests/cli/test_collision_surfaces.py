"""A collision is visible wherever its surviving command is presented."""

from __future__ import annotations

import json

from tests.conftest import surfaces

JOBS = {
    "tools.py": (
        'JOB_GROUP = "tools"\n\n'
        'def status() -> None:\n    print("STATUS")\n\n'
        'def status_() -> None:\n    print("STATUS-UNDERSCORE")\n'
    ),
}


@surfaces("func")
def test_collision_warns_on_invocation_and_group_help(cli_run, project_tree):
    root = project_tree(jobs=JOBS)
    run = cli_run(["tools", "status"], cwd=root)
    help_result = cli_run(["tools", "--help"], cwd=root)
    assert run.exit_code == help_result.exit_code == 0
    assert "JobNameCollision" in run.stderr
    assert run.stderr.count("JobNameCollision") == 1
    assert "tools status" in run.stderr
    assert "JobNameCollision" in help_result.stdout


@surfaces("func")
def test_collision_is_attached_to_info_jobs_without_changing_identity(
    cli_run, project_tree
):
    root = project_tree(jobs=JOBS)
    result = cli_run(["builtin", "info", "jobs", "--json"], cwd=root)
    assert result.exit_code == 0
    row = next(
        row for row in json.loads(result.stdout) if row["name"] == "tools.status"
    )
    assert row["collisions"]
    assert row["name"] == "tools.status"
