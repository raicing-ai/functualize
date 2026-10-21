"""A collision is visible wherever its surviving command is presented."""

from __future__ import annotations

import json

import pytest

from tests.conftest import surfaces

JOBS = {
    "tools.py": (
        'JOB_GROUP = "tools"\n\n'
        'def status() -> None:\n    print("STATUS")\n\n'
        'def status_() -> None:\n    print("STATUS-UNDERSCORE")\n'
    ),
}

# The same pair split over two files, plus a clean job in the group and an
# ungrouped pair reached through `func <job>` rather than a group walk.
TWO_FILES = {
    "tools.py": (
        'JOB_GROUP = "tools"\n\n'
        "import sys\n\n"
        'def status() -> None:\n    print("STATUS-A", file=sys.stderr)\n\n'
        'def other() -> None:\n    print("OTHER")\n'
    ),
    "tools_more.py": (
        'JOB_GROUP = "tools"\n\n'
        "import sys\n\n"
        'def status_() -> None:\n    print("STATUS-B", file=sys.stderr)\n'
    ),
    "ops.py": (
        'def check() -> None:\n    print("CHECK")\n\n'
        'def check_() -> None:\n    print("CHECK-UNDERSCORE")\n'
    ),
}


def _notices(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "JobNameCollision" in line]


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


@surfaces("func")
@pytest.mark.parametrize("args", [["tools", "status"], ["check"]])
def test_two_file_finding_is_one_line_before_the_run_cold_and_warm(
    cli_run, project_tree, args
):
    """One physical line per finding, ahead of the job, on both routes."""
    root = project_tree(jobs=TWO_FILES)
    cold = cli_run(args, cwd=root)
    warm = cli_run(args, cwd=root)
    assert cold.exit_code == warm.exit_code == 0
    assert _notices(cold.stderr) == _notices(warm.stderr)
    (line,) = _notices(cold.stderr)
    assert line.startswith(f"JobNameCollision: {' '.join(args)}: ")
    if args[0] == "tools":
        assert "status_ (" in line
        assert "tools_more.py) runs" in line
        assert "status (" in line
        assert "tools.py) was dropped" in line
        assert cold.stderr.index("JobNameCollision") < cold.stderr.index("STATUS-")


@surfaces("func")
def test_every_human_surface_prints_the_same_line(cli_run, project_tree):
    root = project_tree(jobs=TWO_FILES)
    run = cli_run(["tools", "status"], cwd=root)
    listing = cli_run(["tools", "--help"], cwd=root)
    info = cli_run(["builtin", "info", "jobs"], cwd=root)
    assert _notices(run.stderr) == _notices(listing.stdout)
    assert _notices(run.stderr)[0] in _notices(info.stdout)


@surfaces("func")
def test_a_clean_command_has_no_warning(cli_run, project_tree):
    root = project_tree(jobs=TWO_FILES)
    result = cli_run(["tools", "other"], cwd=root)
    assert result.exit_code == 0
    assert "JobNameCollision" not in result.stderr
    listing = cli_run(["tools", "--help"], cwd=root)
    other_row = next(
        index
        for index, line in enumerate(listing.stdout.splitlines())
        if line.strip().startswith("other")
    )
    following = listing.stdout.splitlines()[other_row + 1 : other_row + 2]
    assert not any("JobNameCollision" in line for line in following)
