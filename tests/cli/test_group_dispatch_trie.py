"""End-to-end group dispatch, now that `_dispatch_group` walks the group trie.

Convergence A4.1 replaced a greedy dotted-prefix loop over a merged name set
with a single trie descent. The corpus in `test_dispatch_characterization.py`
covers `detect_mode`'s *classification*; nothing covered what the group handler
does after it, which is where the walk actually lived. These are the behaviors
the walk is responsible for, pinned end-to-end through the real `main()`.

A4.1 is a zero-behavioral-diff task, so every expectation here was captured
from the pre-trie implementation before the rewrite, not written to describe
the new one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

JOBS = {
    # A top-level job whose name is also a group -> the duality case.
    "top.py": "def deploy():\n    '''Top-level deploy.'''\n    print('TOP-DEPLOY')\n",
    "dual.py": (
        'JOB_GROUP = "deploy"\n\n'
        "def web():\n    '''Deploy web.'''\n    print('DEPLOY-WEB')\n"
    ),
    "infra_root.py": (
        'JOB_GROUP = "infra"\n\n'
        "def provision():\n    '''Provision.'''\n    print('PROVISION')\n"
    ),
    "infra_aws.py": (
        'JOB_GROUP = "infra.aws"\n\n'
        "def launch(region: str = 'eu'):\n"
        "    '''Launch a box.'''\n"
        "    print(f'LAUNCH {region}')\n\n"
        "def terminate():\n    '''Terminate a box.'''\n    print('TERMINATE')\n"
    ),
}


@pytest.fixture()
def grouped(project_tree) -> Path:
    return project_tree(jobs=JOBS)


class TestNavigation:
    def test_nested_group_runs_its_job(self, cli_run, grouped: Path) -> None:
        result = cli_run(["infra", "aws", "launch"], cwd=grouped)
        assert result.exit_code == 0
        assert "LAUNCH eu" in result.stdout

    def test_job_options_survive_the_walk(self, cli_run, grouped: Path) -> None:
        """Tokens after the command are the job's, not the walk's."""
        result = cli_run(["infra", "aws", "launch", "--region", "us"], cwd=grouped)
        assert result.exit_code == 0
        assert "LAUNCH us" in result.stdout

    def test_dotted_token_addresses_the_same_path(self, cli_run, grouped: Path) -> None:
        """`func infra.aws launch` worked before the trie and still does.

        `resolve_name` rejects a dot inside one segment, so the walk has to
        split a dotted token itself.
        """
        result = cli_run(["infra.aws", "launch"], cwd=grouped)
        assert result.exit_code == 0
        assert "LAUNCH eu" in result.stdout

    def test_shallow_group_runs_its_own_job(self, cli_run, grouped: Path) -> None:
        result = cli_run(["infra", "provision"], cwd=grouped)
        assert result.exit_code == 0
        assert "PROVISION" in result.stdout


class TestListing:
    def test_group_lists_sub_groups_and_commands(self, cli_run, grouped: Path) -> None:
        result = cli_run(["infra"], cwd=grouped)
        assert result.exit_code == 0
        assert "Sub-groups:" in result.stdout
        assert "aws" in result.stdout
        assert "provision" in result.stdout

    def test_leaf_group_lists_only_commands(self, cli_run, grouped: Path) -> None:
        result = cli_run(["infra", "aws"], cwd=grouped)
        assert result.exit_code == 0
        assert "Sub-groups:" not in result.stdout
        assert "launch" in result.stdout
        assert "terminate" in result.stdout

    def test_usage_line_echoes_the_tokens_as_typed(
        self, cli_run, grouped: Path
    ) -> None:
        """A user who typed the dotted form reads their own spelling back."""
        result = cli_run(["infra.aws"], cwd=grouped)
        assert result.exit_code == 0
        assert "Usage: func infra.aws <command>" in result.stdout

    def test_a_duality_node_lists_rather_than_runs(
        self, cli_run, grouped: Path
    ) -> None:
        """`deploy` is both a job and a group; A4.1 keeps the group reading.

        Letting the payload win over its own subtree is what
        `TrieResolution.is_group_listing` encodes, and it is a deliberate
        behavior change that A4.1 — a zero-diff refactor — does not make.
        """
        result = cli_run(["deploy"], cwd=grouped)
        assert result.exit_code == 0
        assert "Usage: func deploy <command>" in result.stdout
        assert "TOP-DEPLOY" not in result.stdout

    def test_a_duality_node_still_routes_to_its_children(
        self, cli_run, grouped: Path
    ) -> None:
        result = cli_run(["deploy", "web"], cwd=grouped)
        assert result.exit_code == 0
        assert "DEPLOY-WEB" in result.stdout


class TestErrors:
    def test_unknown_sub_command_names_the_group(self, cli_run, grouped: Path) -> None:
        result = cli_run(["infra", "nope"], cwd=grouped)
        assert result.exit_code == 1
        assert "Unknown command 'nope' in group 'infra'" in result.stderr
        assert "Available:" in result.stderr

    def test_unknown_sub_command_in_a_nested_group(
        self, cli_run, grouped: Path
    ) -> None:
        result = cli_run(["infra", "aws", "nope"], cwd=grouped)
        assert result.exit_code == 1
        assert "in group 'infra aws'" in result.stderr


class TestGroupWithNoJobs:
    """A group the cold-boot sweep knows about but no job registers under.

    `enumerate_group_names` AST-scans for `JOB_GROUP` independently of what
    discovery registers, so on a cold boot `func ghost` classifies as GROUP
    while the booted app has nothing under `ghost`. It listed an empty group
    before the trie; without seeding the trie from the caller's group names it
    would resolve nothing and report `ghost` as an unknown command *inside
    itself*. The warm path cannot reach this — cached group names are derived
    from cached job entries — so it needs its own fixture.
    """

    def test_declared_but_empty_group_lists_rather_than_errors(
        self, cli_run, project_tree
    ) -> None:
        root = project_tree(
            jobs={
                "empty_group.py": 'JOB_GROUP = "ghost"\n\n\ndef _helper():\n    return 1\n'
            }
        )
        result = cli_run(["ghost"], cwd=root)
        assert result.exit_code == 0
        assert "Usage: func ghost <command>" in result.stdout
        assert "No commands available." in result.stdout
