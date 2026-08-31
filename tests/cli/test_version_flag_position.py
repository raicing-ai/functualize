"""The `--version` flag is position-aware: only recognized before the command name.

`func --version` → prints functualize version (pre-boot, no discovery).
`func deploy --version v1` → passes `--version v1` to the deploy job.

This is the same convention as other global flags (`--log-level`, `--output`):
they must come before the first positional. Only `--help` / `-h` is special
(Click handles it per-command for job/group help pages).
"""

from __future__ import annotations

from tests.conftest import surfaces

# `func`-only: this exercises the **pre-boot dispatch layer**
# (`_cli/dispatch.py` + `_cli/main.py`), which resolves the command, renders
# listings and errors, and handles pre-command global flags before an app is
# ever built. An app entry point has no such layer — click owns its tree — so
# there is no second surface for these to run on.
#
# The underlying divergence is real and recorded in `.spec/STATE.md`: the two
# surfaces disagree about listings, unknown commands and their exit codes.
# Nothing in this cycle decided to close it.
pytestmark = surfaces("func")


class TestVersionFlagPositionAware:
    """The --version flag fires only when it precedes the command name."""

    def test_bare_version_prints_version(self, cli_run) -> None:
        """func --version → version string, exit 0."""
        result = cli_run(["--version"])
        assert result.exit_code == 0
        assert "functualize" in result.stdout.lower()

    def test_version_before_any_command_prints_version(self, cli_run) -> None:
        """func --log-level DEBUG --version → version string (all pre-positional)."""
        result = cli_run(["--log-level", "DEBUG", "--version"])
        assert result.exit_code == 0
        assert "functualize" in result.stdout.lower()

    def test_version_after_command_is_job_flag(self, cli_run, project_tree) -> None:
        """func deploy --version v1 → runs the job, does NOT print functualize version.

        The deploy job has a `version` field, so `--version v1` is its flag.
        """
        root = project_tree(
            jobs={
                "deploy.py": (
                    "from pydantic import BaseModel, Field\n"
                    "\n"
                    "class DeployConfig(BaseModel):\n"
                    "    service: str = Field(default='web')\n"
                    "    version: str = Field(description='deploy version')\n"
                    "\n"
                    "def deploy(config: DeployConfig):\n"
                    "    print(f'deploying {config.version}')\n"
                ),
            }
        )
        result = cli_run(["deploy", "--version", "v1"], cwd=root)
        # Must NOT contain the functualize version string
        assert "functualize" not in result.stdout.lower()
        # Must have run the job
        assert "deploying v1" in result.stdout
        assert result.exit_code == 0

    def test_version_after_group_is_not_global(self, cli_run, project_tree) -> None:
        """func infra --version → NOT the global version flag.

        Even for a group, --version after the group name is not global.
        It should error (unknown mid-path flag) rather than print the version.
        """
        root = project_tree(
            jobs={
                "infra.py": (
                    "JOB_GROUP = 'infra'\n"
                    "\n"
                    "def provision():\n"
                    "    print('provisioned')\n"
                ),
            }
        )
        result = cli_run(["infra", "--version"], cwd=root)
        # Must NOT print the functualize version
        assert "functualize" not in result.stdout.lower()
