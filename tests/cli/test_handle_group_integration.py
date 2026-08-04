"""Integration tests for _handle_group CLI handler.

Tests the full flow: boot app, discover grouped jobs, and handle
group listing, sub-command execution, nested groups, and unknown sub-command errors.

Validates Requirements: 4, 5, 6
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize._cli.main import _handle_group

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def infra_project(tmp_path: Path) -> Path:
    """Create a temporary project with grouped job modules.

    Layout:
      jobs/
        infra_jobs.py    → JOB_GROUP = "infra", functions: provision, teardown
        infra_aws_jobs.py → JOB_GROUP = "infra.aws", functions: provision, teardown
    """
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    # infra group module
    (jobs_dir / "infra_jobs.py").write_text(
        '''\
"""Infrastructure management jobs."""

JOB_GROUP = "infra"


def provision(env: str = "dev"):
    """Provision infrastructure resources."""
    print(f"provisioning:{env}")


def teardown():
    """Tear down infrastructure."""
    print("teardown:done")
''',
        encoding="utf-8",
    )

    # infra.aws nested group module
    (jobs_dir / "infra_aws_jobs.py").write_text(
        '''\
"""AWS infrastructure jobs."""

JOB_GROUP = "infra.aws"


def provision(region: str = "us-east-1"):
    """Provision AWS resources."""
    print(f"aws-provision:{region}")


def teardown():
    """Tear down AWS resources."""
    print("aws-teardown:done")
''',
        encoding="utf-8",
    )

    return tmp_path


def _make_effective(jobs_dir: str) -> dict[str, list[str]]:
    """Build the effective directories dict for _handle_group."""
    return {"jobs_directories": [jobs_dir], "import_libs": []}


def _make_cli_flags() -> dict[str, Any]:
    """Return minimal cli_flags dict."""
    return {}


# ---------------------------------------------------------------------------
# Test: Group Listing (Requirement 5)
# ---------------------------------------------------------------------------


class TestGroupListing:
    """Test that `func infra` (no sub-command) lists sub-commands and sub-groups."""

    def test_infra_lists_commands_and_subgroups(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra` with no sub-command, THEN lists commands and sub-groups, exit 0.

        Validates: Requirement 5.1, 5.4
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        # Should list sub-groups
        assert "aws" in captured.out
        # Should list commands from the infra group
        assert "provision" in captured.out
        assert "teardown" in captured.out

    def test_nested_group_listing(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra aws` with no sub-command, THEN lists nested group commands.

        Validates: Requirement 5.2
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "aws"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        # Should list commands in infra.aws
        assert "provision" in captured.out
        assert "teardown" in captured.out

    def test_listing_shows_usage_line(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Group listing shows a usage line with the group path.

        Validates: Requirement 5.1
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        _handle_group(
            args=["infra"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        captured = capsys.readouterr()
        assert "Usage: func infra" in captured.out


# ---------------------------------------------------------------------------
# Test: Sub-command Execution (Requirement 4)
# ---------------------------------------------------------------------------


class TestSubCommandExecution:
    """Test that `func infra provision` executes the correct job."""

    def test_infra_provision_executes(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra provision`, THEN executes infra.provision job.

        Validates: Requirement 4.1
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "provision"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "provisioning:dev" in captured.out

    def test_infra_provision_with_args(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra provision --env prod`, THEN passes args to job.

        Validates: Requirement 4.1
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "provision", "--env", "prod"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "provisioning:prod" in captured.out


# ---------------------------------------------------------------------------
# Test: Nested Group Execution (Requirement 4)
# ---------------------------------------------------------------------------


class TestNestedGroupExecution:
    """Test that `func infra aws provision` executes the nested job."""

    def test_infra_aws_provision_executes(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra aws provision`, THEN executes infra.aws.provision.

        Validates: Requirement 4.2
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "aws", "provision"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "aws-provision:us-east-1" in captured.out

    def test_infra_aws_provision_with_args(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra aws provision --region eu-west-1`, THEN passes args.

        Validates: Requirement 4.2
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "aws", "provision", "--region", "eu-west-1"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "aws-provision:eu-west-1" in captured.out


# ---------------------------------------------------------------------------
# Test: Unknown Sub-command Error (Requirement 6)
# ---------------------------------------------------------------------------


class TestUnknownSubCommand:
    """Test that `func infra unknown` produces clear error + exit 1."""

    def test_unknown_subcommand_errors(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra unknown`, THEN prints error and exits 1.

        Validates: Requirement 6.1, 6.2
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "unknown"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "unknown" in captured.err.lower() or "unknown" in captured.out.lower()

    def test_unknown_subcommand_suggests_available(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN unknown sub-command, THEN available commands are listed.

        Validates: Requirement 6.3
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        _handle_group(
            args=["infra", "unknown"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        captured = capsys.readouterr()
        stderr = captured.err
        # Should suggest available sub-commands
        assert "provision" in stderr or "teardown" in stderr or "aws" in stderr

    def test_nested_group_unknown_subcommand(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra aws nonexistent`, THEN error with exit 1.

        Validates: Requirement 6.1, 6.2
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "aws", "nonexistent"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert (
            "nonexistent" in captured.err.lower()
            or "nonexistent" in captured.out.lower()
        )


# ---------------------------------------------------------------------------
# Test: Global flag placement (D1, model A — globals go before the group)
# ---------------------------------------------------------------------------


class TestGlobalFlagPlacement:
    """Global flags belong *before* the group name (the git/click idiom).

    `func --log-level DEBUG infra provision` is the supported form: the global
    is consumed by `_extract_global_options` before dispatch, so `_handle_group`
    only ever sees the path (`[infra, provision]`) — that case is
    `TestSubCommandExecution`. What this class pins is the *rejection* side: a
    flag that reaches the group walk is in the wrong place, and must error (exit
    2) rather than stop the walk and silently list children with exit 0. A known
    global gets a "put it before the group" hint; an unknown flag gets a generic
    one. The earlier "reaches the job mid-path" behavior was dropped: it served
    an unidiomatic placement nothing (not even the inline TUI) needed, and the
    mid-path flag space is left to the future GroupOptions design.
    """

    def test_misplaced_global_after_group_errors_with_hint(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN `func infra --log-level DEBUG provision`, THEN exit 2 + hint.

        The global is after the group name — wrong place. The error names the
        flag and the group and points at the correct spelling; the job must not
        run.
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "--log-level", "DEBUG", "provision"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "--log-level" in captured.err
        assert "must come before the group name" in captured.err
        assert "infra" in captured.err
        assert "provisioning" not in captured.out, "the job must not have run"

    def test_misplaced_global_in_nested_group_errors(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The rule holds at depth: `func infra aws --log-level DEBUG provision`."""
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "aws", "--log-level", "DEBUG", "provision"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "--log-level" in captured.err
        assert "must come before the group name" in captured.err
        assert "aws-provision" not in captured.out

    def test_unknown_flag_after_group_errors(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """WHEN an unknown flag reaches the group walk, THEN error (exit 2).

        This is the silent-listing-exit-0 D1 exists to kill: the walk stops at
        the flag, the group branch lists children, and the run reports success
        while doing nothing the user asked for. Unknown (not a global) → generic
        message, no "before the group name" hint.
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "--bogus-flag", "provision"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 2, "an unknown flag before a command must not exit 0"
        captured = capsys.readouterr()
        assert "--bogus-flag" in captured.err
        assert "unknown option" in captured.err.lower()
        assert "must come before the group name" not in captured.err, (
            "unknown flag is not a known global — no targeted hint"
        )
        assert "provisioning" not in captured.out, "the job must not have run"

    def test_job_option_after_the_leaf_still_reaches_the_job(
        self, infra_project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Model A only restricts *globals*: a job's own option after the leaf
        still reaches it. `func infra provision --env prod` runs env=prod.

        This is the boundary that keeps the rejection rule from over-reaching —
        the error only fires on a non-leaf node, so once the path is fully
        consumed everything belongs to the job.
        """
        jobs_dir = str(infra_project / "jobs")
        group_names = {"infra", "infra.aws"}

        exit_code = _handle_group(
            args=["infra", "provision", "--env", "prod"],
            anchor=infra_project,
            merged_config={},
            effective=_make_effective(jobs_dir),
            cli_flags=_make_cli_flags(),
            group_names=group_names,
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "provisioning:prod" in captured.out
