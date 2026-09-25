"""The emit surface is offered at the keyboard, and a bad value says so.

A first-user rehearsal on the 0.4.0 wheel found the emit surface working and
documented, and invisible from the CLI:

    $ func --help                      -> no --emit-format, no --force, no --prompt-gates
    $ func --emit-format bogus greet   -> Error: Unknown command 'bogus'.
    $ func greet                       -> (nothing on stdout, exit 0)

A job that returns a value prints nothing, by design (`_types/stdout.py`), so an
author who has never been told about `out.emit()` writes the silent version and
cannot tell success from a no-op. The run-scoped globals are parsed pre-boot and
deliberately not declared on the `cli_app` group (it also serves `func builtin`,
which rejects them — ADR-020), so help never listed them. And because
`--emit-format` takes an *optional* value, the lookahead left `bogus` standing
as the command name.
"""

from __future__ import annotations

import textwrap

from tests.conftest import surfaces

_JOB = textwrap.dedent(
    '''
    from functualize.job import job


    @job
    def greet() -> str:
        """Returns a greeting and prints nothing."""
        return "hi"
    '''
)


def _tree(project_tree):
    return project_tree(jobs={"j.py": _JOB}, convention_dirs=True)


class TestHelpOffersTheEmitSurface:
    @surfaces("func")
    def test_run_options_are_listed_with_the_valid_set(
        self, cli_run, project_tree
    ) -> None:
        """AC1 — rendered from the flag grammar, with where they go."""
        result = cli_run(["--help"], cwd=_tree(project_tree))

        assert result.exit_code == 0
        out = result.stdout
        assert "--emit-format [auto|json|ndjson|none|raw]" in out
        assert "--force" in out
        assert "--prompt-gates" in out
        assert "before the job name" in out

    def test_help_says_how_output_reaches_stdout(self, cli_run, project_tree) -> None:
        """AC2 — on both doors: `func --help` and an app's own `--help`."""
        result = cli_run(["--help"], cwd=_tree(project_tree))

        assert result.exit_code == 0
        out = " ".join(result.stdout.split())  # undo click's wrapping
        assert "return value is never printed" in out
        assert "out.emit()" in out
        assert "print()" in out


@surfaces("func")
class TestABadValueIsDiagnosedAsAValue:
    def test_bad_value_before_a_job(self, cli_run, project_tree) -> None:
        """AC3 — the `--emit-format=bogus` sentence, not `Unknown command`."""
        result = cli_run(["--emit-format", "bogus", "greet"], cwd=_tree(project_tree))

        assert result.exit_code == 1
        assert "--emit-format must be one of" in result.stderr
        assert "'bogus'" in result.stderr
        assert "Unknown command" not in result.stderr

    def test_bad_value_alone(self, cli_run, project_tree) -> None:
        result = cli_run(["--emit-format", "bogus"], cwd=_tree(project_tree))

        assert result.exit_code == 1
        assert "--emit-format must be one of" in result.stderr
        assert "Unknown command" not in result.stderr

    def test_bad_value_for_the_other_optional_value_flag(
        self, cli_run, project_tree
    ) -> None:
        result = cli_run(["--perf-report", "bogus", "greet"], cwd=_tree(project_tree))

        assert result.exit_code == 1
        assert "--perf-report must be one of" in result.stderr
        assert "Unknown command" not in result.stderr

    def test_both_spellings_get_the_same_sentence(self, cli_run, project_tree) -> None:
        root = _tree(project_tree)
        spaced = cli_run(["--emit-format", "bogus", "greet"], cwd=root)
        joined = cli_run(["--emit-format=bogus", "greet"], cwd=root)

        assert spaced.exit_code == joined.exit_code == 1
        assert spaced.stderr.strip() == joined.stderr.strip()


@surfaces("func")
class TestTheLookaheadIsUnchanged:
    def test_a_bare_flag_before_a_job_still_runs_it(
        self, cli_run, project_tree
    ) -> None:
        """AC4 — `--emit-format greet` is the default format, then `greet`."""
        result = cli_run(["--emit-format", "greet"], cwd=_tree(project_tree))

        assert result.exit_code == 0, result.stderr

    def test_an_unknown_command_is_still_one(self, cli_run, project_tree) -> None:
        result = cli_run(["nosuchjob"], cwd=_tree(project_tree))

        assert result.exit_code == 1
        assert "Unknown command 'nosuchjob'" in result.stderr

    def test_builtin_still_rejects_run_options(self, cli_run, project_tree) -> None:
        """AC5 — listed in help is not accepted by `builtin` (ADR-020)."""
        result = cli_run(
            ["--emit-format", "json", "builtin", "version"], cwd=_tree(project_tree)
        )

        assert result.exit_code != 0
        assert "No such option '--emit-format'" in result.stderr
