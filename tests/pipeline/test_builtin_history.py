"""`func builtin history` — one command over the whole run ring (T42).

The engine and the shell surface write to the same history ring, so this
command renders **both** namespaces from one place. It reads the store directly
(inspecting history is far more common than adding to it, and must not create a
state file in a project that has never run anything), narrows with
`--namespace`, and writes to stdout so the listing composes.
"""

from __future__ import annotations

import textwrap

import pytest

_JOBS = {
    "alpha.py": textwrap.dedent("""
        def alpha() -> None:
            print("ran alpha")
    """),
    "bad.py": textwrap.dedent("""
        def bad() -> None:
            raise RuntimeError("kaboom")
    """),
}


@pytest.fixture
def project(project_tree):
    return project_tree(jobs=_JOBS, convention_dirs=True)


class TestRendering:
    def test_a_run_then_history_shows_it(self, cli_run, project) -> None:
        cli_run(["alpha"], cwd=project)

        result = cli_run(["builtin", "history"], cwd=project)

        assert result.exit_code == 0
        assert "alpha" in result.stdout
        assert "success" in result.stdout

    def test_a_failed_run_shows_its_status(self, cli_run, project) -> None:
        cli_run(["bad"], cwd=project)

        result = cli_run(["builtin", "history"], cwd=project)

        assert "bad" in result.stdout
        assert "failure" in result.stdout

    def test_newest_first(self, cli_run, project) -> None:
        cli_run(["alpha"], cwd=project)
        cli_run(["bad"], cwd=project)

        out = cli_run(["builtin", "history"], cwd=project).stdout

        assert out.index("bad") < out.index("alpha")

    def test_limit_caps_the_output(self, cli_run, project) -> None:
        for _ in range(4):
            cli_run(["alpha"], cwd=project)

        out = cli_run(["builtin", "history", "--limit", "2"], cwd=project).stdout

        assert out.count("alpha") == 2


class TestBothNamespaces:
    def test_job_and_shell_runs_appear_together(self, cli_run, project) -> None:
        """The whole point of one ring: a command that shows what ran, whether
        it was a job or a shell command."""
        from functualize.app.utils import StateStore

        cli_run(["alpha"], cwd=project)
        # A shell record, written the way the shell surface writes it.
        StateStore.for_project(project).append_history(
            {"namespace": "shell", "command": "ls -la", "exit_code": 0}
        )

        out = cli_run(["builtin", "history"], cwd=project).stdout

        assert "alpha" in out
        assert "ls -la" in out

    def test_namespace_filter_narrows_to_one_kind(self, cli_run, project) -> None:
        from functualize.app.utils import StateStore

        cli_run(["alpha"], cwd=project)
        StateStore.for_project(project).append_history(
            {"namespace": "shell", "command": "ls -la", "exit_code": 0}
        )

        out = cli_run(
            ["builtin", "history", "--namespace", "shell"], cwd=project
        ).stdout

        assert "ls -la" in out
        assert "alpha" not in out

    def test_a_nonzero_shell_exit_is_shown(self, cli_run, project) -> None:
        from functualize.app.utils import StateStore

        StateStore.for_project(project).append_history(
            {"namespace": "shell", "command": "false", "exit_code": 1}
        )

        out = cli_run(["builtin", "history"], cwd=project).stdout

        assert "false" in out
        assert "exit 1" in out


class TestEmpty:
    def test_a_project_with_no_history_says_so(self, cli_run, project) -> None:
        """And does not create a state file just by being asked."""
        from pathlib import Path

        from functualize.app.utils import resolve_state_path

        result = cli_run(["builtin", "history"], cwd=project)

        assert "No history" in result.stderr
        assert not resolve_state_path(Path(project)).exists()

    def test_an_empty_namespace_says_so(self, cli_run, project) -> None:
        cli_run(["alpha"], cwd=project)

        result = cli_run(["builtin", "history", "--namespace", "nope"], cwd=project)

        assert "No history" in result.stderr
        assert "nope" in result.stderr
