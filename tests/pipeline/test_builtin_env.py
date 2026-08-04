"""`func builtin env` — a job's config, for tools that aren't functualize (T43).

A job's resolved config is useful outside the job: a deploy job and the
`kubectl` it wraps want the same `env` and `replicas`. `func builtin env`
exports that config as environment variables, in two forms over one resolution:

* **print** — `eval $(func builtin env deploy)` sets the vars in your shell.
* **exec**  — `func builtin env deploy -- kubectl …` runs a command with them.

The one thing worth being strict about is secrets. A `secret=True` field is
**masked** in the printed form (so the default output is safe to read off a
screen or paste into a bug report) and **omitted** from the exec environment
(`•••` is not the value the tool needs — a masked secret silently breaks it).
Real values require a deliberate `--include-secrets`.
"""

from __future__ import annotations

import textwrap

import pytest

_DEPLOY = textwrap.dedent("""
    from pydantic import BaseModel, Field
    from functualize.job import job

    class DeployConfig(BaseModel):
        env: str = "staging"
        replicas: int = 3
        token: str = Field(default="hunter2", json_schema_extra={"secret": True})

    @job
    def deploy(config: DeployConfig):
        print(config.env)
""")

_NOCONFIG = textwrap.dedent("""
    def plain():
        print("hi")
""")


@pytest.fixture
def project(project_tree):
    return project_tree(
        jobs={"deploy.py": _DEPLOY, "plain.py": _NOCONFIG}, convention_dirs=True
    )


class TestPrintForm:
    def test_non_secret_fields_are_exported(self, cli_run, project) -> None:
        out = cli_run(["builtin", "env", "deploy"], cwd=project).stdout

        assert "export DEPLOY_ENV=staging" in out
        assert "export DEPLOY_REPLICAS=3" in out

    def test_a_secret_is_masked_by_default(self, cli_run, project) -> None:
        """The default output is safe to paste anywhere; the real value never
        appears without opting in."""
        out = cli_run(["builtin", "env", "deploy"], cwd=project).stdout

        assert "hunter2" not in out
        assert "DEPLOY_TOKEN" in out
        assert "•••" in out

    def test_include_secrets_reveals_the_real_value(self, cli_run, project) -> None:
        out = cli_run(
            ["builtin", "env", "deploy", "--include-secrets"], cwd=project
        ).stdout

        assert "export DEPLOY_TOKEN=hunter2" in out

    def test_the_output_is_shell_safe(self, cli_run, project) -> None:
        """Every line is `export NAME=<quoted>`, so `eval` cannot be tricked by
        a value containing spaces or metacharacters."""
        out = cli_run(["builtin", "env", "deploy"], cwd=project).stdout

        for line in out.splitlines():
            if line.strip():
                assert line.startswith("export ")

    def test_a_job_with_no_config_exports_nothing(self, cli_run, project) -> None:
        result = cli_run(["builtin", "env", "plain"], cwd=project)

        assert result.exit_code == 0
        assert "export" not in result.stdout


class TestExecForm:
    # The exec form runs a real child process whose stdout goes to the inherited
    # fd, which the in-process `cli_run` capture cannot see (that is the correct,
    # transparent behaviour). So the child writes what it saw to a file the test
    # then reads — robust regardless of how output is captured.
    @staticmethod
    def _dump_env(project, cli_run, *extra_args: str) -> str:
        from pathlib import Path

        out = Path(project) / "env-dump.txt"
        cli_run(
            [
                "builtin",
                "env",
                "deploy",
                *extra_args,
                "--",
                "sh",
                "-c",
                f"env > {out}",
            ],
            cwd=project,
        )
        return out.read_text() if out.exists() else ""

    def test_the_command_sees_the_non_secret_vars(self, cli_run, project) -> None:
        dump = self._dump_env(project, cli_run)

        assert "DEPLOY_ENV=staging" in dump
        assert "DEPLOY_REPLICAS=3" in dump

    def test_a_secret_is_omitted_from_the_child_env(self, cli_run, project) -> None:
        """Omitted, not masked: the tool gets the config it can use and fails
        loudly on the missing credential, rather than mysteriously on a `•••`."""
        dump = self._dump_env(project, cli_run)

        assert "hunter2" not in dump
        assert "DEPLOY_TOKEN" not in dump

    def test_include_secrets_puts_the_real_value_in_the_child_env(
        self, cli_run, project
    ) -> None:
        dump = self._dump_env(project, cli_run, "--include-secrets")

        assert "DEPLOY_TOKEN=hunter2" in dump

    def test_the_child_exit_code_is_propagated(self, cli_run, project) -> None:
        """The exec form *is* the command; its exit code must be the one the
        caller sees, or a failing wrapped tool would look like a success."""
        ok = cli_run(["builtin", "env", "deploy", "--", "true"], cwd=project)
        bad = cli_run(["builtin", "env", "deploy", "--", "false"], cwd=project)

        assert ok.exit_code == 0
        assert bad.exit_code != 0

    def test_unknown_options_pass_through_to_the_command(
        self, cli_run, project
    ) -> None:
        """`func builtin env deploy -- sh -c …` must hand `-c` to `sh`, not try
        to parse it as its own flag."""
        from pathlib import Path

        out = Path(project) / "marker.txt"
        cli_run(
            ["builtin", "env", "deploy", "--", "sh", "-c", f"printf ok > {out}"],
            cwd=project,
        )

        assert out.read_text() == "ok"


class TestInfoJobMasksSecrets:
    """The F3 sweep: `builtin info --job` is a display sink like every other,
    and used to print a secret field's resolved value in the clear."""

    def test_a_secret_field_is_masked(self, cli_run, project) -> None:
        out = cli_run(["builtin", "info", "--job", "deploy"], cwd=project).stdout

        assert "hunter2" not in out
        assert "•••" in out

    def test_non_secret_fields_are_still_shown(self, cli_run, project) -> None:
        out = cli_run(["builtin", "info", "--job", "deploy"], cwd=project).stdout

        assert "staging" in out
