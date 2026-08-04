"""E2E test: ungrouped project continues to work unchanged.

Verifies that a project without any JOB_GROUP declarations continues to
function exactly as before — jobs are discoverable by bare name, detect_mode
routes them as Mode.JOB, and they execute successfully via CLI invocation.

Requirements validated: 8
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._cli.dispatch import Mode, detect_mode
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.app.utils import enumerate_group_names, enumerate_job_names

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


def _create_ungrouped_module(jobs_dir: Path, name: str, code: str) -> Path:
    """Write an ungrouped job module (no JOB_GROUP) to jobs_dir."""
    module_file = jobs_dir / f"{name}.py"
    module_file.write_text(textwrap.dedent(code), encoding="utf-8")
    return module_file


# ===========================================================================
# E2E: Ungrouped Project Unchanged (Requirement 8)
# ===========================================================================


class TestUngroupedProjectUnchanged:
    """End-to-end: ungrouped project (no JOB_GROUP) works exactly as before."""

    def test_ungrouped_jobs_discoverable_by_bare_name(self, tmp_path: Path) -> None:
        """Jobs in modules without JOB_GROUP are registered by bare function name."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_ungrouped_module(
            jobs_dir,
            "deploy",
            """\
            def deploy():
                '''Deploy the application.'''
                print("deploying")
            """,
        )
        _create_ungrouped_module(
            jobs_dir,
            "migrate",
            """\
            def migrate():
                '''Run database migrations.'''
                print("migrating")
            """,
        )

        app = FunctualizeApp(
            name="ungrouped-app",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )

        job_names = {j.name for j in app.get_jobs()}
        assert "deploy" in job_names
        assert "migrate" in job_names
        # No dots in names — these are bare names, not qualified
        for name in job_names:
            assert "." not in name

    def test_detect_mode_returns_job_for_ungrouped(self, tmp_path: Path) -> None:
        """detect_mode classifies bare-name jobs as Mode.JOB, not Mode.GROUP."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_ungrouped_module(
            jobs_dir,
            "deploy",
            """\
            def deploy():
                '''Deploy.'''
                pass
            """,
        )
        _create_ungrouped_module(
            jobs_dir,
            "migrate",
            """\
            def migrate():
                '''Migrate.'''
                pass
            """,
        )

        # Enumerate names as the CLI would during pre-boot
        job_names = enumerate_job_names([str(jobs_dir)])
        group_names = enumerate_group_names([str(jobs_dir)])

        # No groups should be found for ungrouped modules
        assert len(group_names) == 0

        # detect_mode should classify "deploy" as JOB
        mode, args = detect_mode(
            ["func", "deploy"], job_names=job_names, group_names=group_names
        )
        assert mode is Mode.JOB
        assert args == ["deploy"]

        # detect_mode should classify "migrate" as JOB
        mode, args = detect_mode(
            ["func", "migrate"], job_names=job_names, group_names=group_names
        )
        assert mode is Mode.JOB
        assert args == ["migrate"]

    def test_ungrouped_jobs_executable_by_bare_name(self, tmp_path: Path) -> None:
        """Ungrouped jobs can be invoked by bare name via CLI and execute correctly."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_ungrouped_module(
            jobs_dir,
            "deploy",
            """\
            def deploy():
                '''Deploy the application.'''
                print("deploy-success")
            """,
        )
        _create_ungrouped_module(
            jobs_dir,
            "migrate",
            """\
            def migrate():
                '''Run migrations.'''
                print("migrate-success")
            """,
        )

        app = FunctualizeApp(
            name="ungrouped-app",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )

        # Execute "deploy" by bare name
        result = runner.invoke(app.cli_command, ["deploy"])
        assert result.exit_code == 0
        assert "deploy-success" in result.output

        # Execute "migrate" by bare name
        result = runner.invoke(app.cli_command, ["migrate"])
        assert result.exit_code == 0
        assert "migrate-success" in result.output

    def test_ungrouped_job_with_arguments(self, tmp_path: Path) -> None:
        """Ungrouped jobs with typed CLI arguments continue to work."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_ungrouped_module(
            jobs_dir,
            "deploy",
            """\
            def deploy(
                env: str = "staging",
                dry_run: bool = False,
            ):
                '''Deploy the application.'''
                print(f"deploying to {env}, dry_run={dry_run}")
            """,
        )

        app = FunctualizeApp(
            name="ungrouped-app",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )

        result = runner.invoke(
            app.cli_command, ["deploy", "--env", "production", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "deploying to production" in result.output
        assert "dry_run=True" in result.output

    def test_ungrouped_multi_function_module(self, tmp_path: Path) -> None:
        """Module with multiple functions and no JOB_GROUP registers all by bare name."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        _create_ungrouped_module(
            jobs_dir,
            "ops",
            """\
            def restart():
                '''Restart services.'''
                print("restarting")

            def status():
                '''Show service status.'''
                print("all-healthy")
            """,
        )

        app = FunctualizeApp(
            name="ungrouped-app",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )

        job_names = {j.name for j in app.get_jobs()}
        assert "restart" in job_names
        assert "status" in job_names

        # Both should execute by bare name
        result = runner.invoke(app.cli_command, ["restart"])
        assert result.exit_code == 0
        assert "restarting" in result.output

        result = runner.invoke(app.cli_command, ["status"])
        assert result.exit_code == 0
        assert "all-healthy" in result.output

    def test_ungrouped_coexists_with_grouped(self, tmp_path: Path) -> None:
        """Ungrouped and grouped jobs can coexist in the same project."""
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        # Ungrouped module
        _create_ungrouped_module(
            jobs_dir,
            "deploy",
            """\
            def deploy():
                '''Deploy (ungrouped).'''
                print("flat-deploy")
            """,
        )

        # Grouped module
        _create_ungrouped_module(
            jobs_dir,
            "infra_jobs",
            """\
            JOB_GROUP = "infra"

            def provision():
                '''Provision infra.'''
                print("infra-provision")
            """,
        )

        app = FunctualizeApp(
            name="mixed-app",
            job_sources=JobSources(directories=[str(jobs_dir)]),
        )

        job_names = {j.name for j in app.get_jobs()}
        # Ungrouped: bare name
        assert "deploy" in job_names
        # Grouped: qualified name
        assert "infra.provision" in job_names

        # Ungrouped job executes by bare name
        result = runner.invoke(app.cli_command, ["deploy"])
        assert result.exit_code == 0
        assert "flat-deploy" in result.output

        # Grouped job executes via group sub-command
        result = runner.invoke(app.cli_command, ["infra", "provision"])
        assert result.exit_code == 0
        assert "infra-provision" in result.output
