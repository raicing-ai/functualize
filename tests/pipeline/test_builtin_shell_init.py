"""`func builtin shell-init` end to end — print, install, and the path (T44b).

The extraction (T44a) and emission (T44b) are unit-tested elsewhere; this drives
the actual command, because two things only the command decides need pinning:
where `--install` writes (it must be the same directory the rest of the tool
resolves, via `resolve_cache_path`, with no second rule to drift), and that the
emitted script really is callback-free when produced through the booted app —
the greppable rule, verified on the real output rather than a fixture.
"""

from __future__ import annotations

import textwrap

import pytest

_JOBS = {
    "greet.py": textwrap.dedent("""
        def greet(name: str = "world") -> None:
            print(name)
    """),
}


@pytest.fixture
def project(project_tree):
    return project_tree(jobs=_JOBS, convention_dirs=True)


class TestPrint:
    def test_it_prints_a_script_for_each_shell(self, cli_run, project) -> None:
        for shell in ("bash", "zsh", "fish"):
            result = cli_run(["builtin", "shell-init", shell], cwd=project)
            assert result.exit_code == 0, result.stderr
            assert "greet" in result.stdout
            assert "_func_complete" in result.stdout or "complete -c func" in (
                result.stdout
            )

    def test_the_printed_script_has_no_python_callback(self, cli_run, project) -> None:
        """The greppable rule, on the real command output."""
        out = cli_run(["builtin", "shell-init", "bash"], cwd=project).stdout

        for line in out.splitlines():
            code = line.split("#", 1)[0]
            assert "__complete" not in code
            assert "$(func" not in code

    def test_an_unknown_shell_is_rejected(self, cli_run, project) -> None:
        result = cli_run(["builtin", "shell-init", "tcsh"], cwd=project)

        assert result.exit_code != 0


class TestInstall:
    def test_it_writes_beside_the_cache(self, cli_run, project) -> None:
        """The install path is `resolve_cache_path().parent / completions` — the
        same directory the discovery cache lives in, so there is one path rule,
        not two."""
        from functualize.app.utils import resolve_cache_path

        result = cli_run(["builtin", "shell-init", "bash", "--install"], cwd=project)

        assert result.exit_code == 0, result.stderr
        expected = resolve_cache_path(project).parent / "completions" / "init.bash"
        assert expected.exists()
        assert "greet" in expected.read_text()

    def test_install_reports_the_path_and_source_hint_on_stderr(
        self, cli_run, project
    ) -> None:
        """Path + source line go to stderr so a redirect of stdout still yields a
        clean file; the hint is advice, not data."""
        result = cli_run(["builtin", "shell-init", "zsh", "--install"], cwd=project)

        assert "completions/init.zsh" in result.stderr
        assert "source " in result.stderr
        assert result.stdout.strip() == ""

    def test_each_shell_installs_to_its_own_file(self, cli_run, project) -> None:
        from functualize.app.utils import resolve_cache_path

        for shell in ("bash", "zsh", "fish"):
            cli_run(["builtin", "shell-init", shell, "--install"], cwd=project)

        comp_dir = resolve_cache_path(project).parent / "completions"
        assert {p.name for p in comp_dir.iterdir()} == {
            "init.bash",
            "init.zsh",
            "init.fish",
        }
